"""Replace one aggregate manufacturing HBM branch with a frozen supplier result."""

from __future__ import annotations

import hashlib
import json
import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from pathlib import Path
from random import Random
from typing import Any, Mapping

from .engine import EstimateSampler, _input_estimate, summarize
from .loader import _integer, _list, _mapping, _text, _value
from .manufacturing_engine import (
    _evidence_payload as _manufacturing_evidence_payload,
    _inputs as _manufacturing_inputs,
    gross_dies_per_wafer,
    negative_binomial_die_yield,
)
from .manufacturing_loader import manufacturing_from_dict
from .manufacturing_models import ManufacturingScenario


HBM_MANUFACTURING_LINK_FORMAT = "ai-supply-hbm-manufacturing-link.v1"
HBM_MANUFACTURING_DRAW_LINK_FORMAT = "ai-supply-hbm-manufacturing-link.v2"
HBM_MANUFACTURING_COVERAGE_LINK_FORMAT = "ai-supply-hbm-manufacturing-link.v3"
HBM_MANUFACTURING_LINEAGE_FORMAT = "ai-supply-hbm-manufacturing-lineage.v1"
HBM_SUPPLIER_RESULT_FORMAT = "ai-supply-hbm-supplier-result.v1"
MANUFACTURING_RESULT_FORMAT = "ai-supply-manufacturing-result.v1"
TRIANGULAR_MAPPING = "source_p10_p50_p90_to_triangular_low_mode_high"
DRAW_MAPPING = "source_capacity_draws_deterministic_permutation"
IMPORTED_METRIC = "customer_allocated_stacks"


def _only(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unexpected = set(data) - allowed
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed


def _date(value: str, path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _scenario_metadata(document: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    metadata = _mapping(_value(document, "scenario", path), f"{path}.scenario")
    for key in ("id", "quarter", "as_of_date", "recorded_at"):
        _text(metadata, key, f"{path}.scenario")
    if not isinstance(metadata.get("synthetic"), bool):
        raise ValueError(f"{path}.scenario.synthetic must be boolean")
    return metadata


def _minimum_input_confidence(result: Mapping[str, Any]) -> float:
    values: list[float] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if {"low", "base", "high", "confidence"}.issubset(value):
                confidence = value["confidence"]
                if isinstance(confidence, bool) or not isinstance(
                    confidence,
                    (int, float),
                ):
                    raise ValueError("HBM supplier result contains invalid confidence")
                numeric = float(confidence)
                if not isfinite(numeric) or not 0 <= numeric <= 1:
                    raise ValueError("HBM supplier result confidence must be in [0, 1]")
                values.append(numeric)
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result.get("inputs", {}))
    if not values:
        raise ValueError("HBM supplier result contains no auditable input estimates")
    return min(values)


def _distribution(value: Any, path: str) -> dict[str, float]:
    source = _mapping(value, path)
    parsed = {}
    for field in ("p10", "p50", "p90", "mean", "minimum", "maximum"):
        item = source.get(field)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{path}.{field} must be numeric")
        numeric = float(item)
        if not isfinite(numeric) or numeric < 0:
            raise ValueError(f"{path}.{field} must be finite and nonnegative")
        parsed[field] = numeric
    if not parsed["p10"] <= parsed["p50"] <= parsed["p90"]:
        raise ValueError(f"{path} quantiles must be ordered")
    if not parsed["minimum"] <= parsed["maximum"]:
        raise ValueError(f"{path} minimum cannot exceed maximum")
    return parsed


def _estimate_signature(value: Mapping[str, Any], path: str) -> tuple[Any, ...]:
    signature: list[Any] = []
    for field in ("low", "base", "high"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{path}.{field} must be numeric")
        signature.append(float(item))
    unit = value.get("unit")
    if not isinstance(unit, str) or not unit:
        raise ValueError(f"{path}.unit must be text")
    signature.append(unit)
    return tuple(signature)


def _topology_checks(
    manufacturing: ManufacturingScenario,
    hbm_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    source_platform = _mapping(hbm_result.get("platform"), "hbm_result.platform")
    pairs = (
        (
            "memory_dies_per_stack",
            _input_estimate(manufacturing.hbm.memory_dies_per_stack),
            source_platform.get("memory_dies_per_stack"),
        ),
        (
            "stack_capacity_gb",
            _input_estimate(manufacturing.hbm.stack_capacity_gb),
            source_platform.get("stack_capacity_gb"),
        ),
        (
            "stacks_per_accelerator",
            _input_estimate(manufacturing.hbm.stacks_per_accelerator),
            source_platform.get("stacks_per_accelerator"),
        ),
    )
    checks = []
    for name, manufacturing_value, source_value in pairs:
        source_estimate = _mapping(
            source_value,
            f"hbm_result.platform.{name}",
        )
        left = _estimate_signature(
            manufacturing_value,
            f"manufacturing.hbm.{name}",
        )
        right = _estimate_signature(
            source_estimate,
            f"hbm_result.platform.{name}",
        )
        if left != right:
            raise ValueError(f"HBM topology mismatch for {name}")
        checks.append(
            {
                "field": name,
                "manufacturing": list(left),
                "hbm_supplier_result": list(right),
                "match": True,
            }
        )
    return checks


def _package_coverage(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
            "assembly_start_basis",
            "absorbed_resource_kinds",
            "posture",
            "methodology",
            "confirming_evidence",
            "falsifying_evidence",
            "notes",
        },
        path,
    )
    basis = _text(data, "assembly_start_basis", path)
    if basis != "material_cleared_starts":
        raise ValueError(f"{path}.assembly_start_basis must be material_cleared_starts")
    resource_values = _list(
        _value(data, "absorbed_resource_kinds", path),
        f"{path}.absorbed_resource_kinds",
    )
    if not resource_values or not all(
        isinstance(item, str) and item for item in resource_values
    ):
        raise ValueError(f"{path}.absorbed_resource_kinds must contain resource names")
    if len(set(resource_values)) != len(resource_values):
        raise ValueError(f"{path}.absorbed_resource_kinds must be unique")
    posture = _text(data, "posture", path)
    if posture not in {"synthetic", "modeled", "derived", "reported"}:
        raise ValueError(f"{path}.posture is invalid")
    return {
        "assembly_start_basis": basis,
        "absorbed_resource_kinds": list(resource_values),
        "posture": posture,
        "methodology": _text(data, "methodology", path),
        "confirming_evidence": _text(data, "confirming_evidence", path),
        "falsifying_evidence": _text(data, "falsifying_evidence", path),
        "notes": _text(data, "notes", path),
    }


def _capacity_draws(
    raw: bytes,
    *,
    hbm_result: Mapping[str, Any],
    supplier_ids: list[str],
) -> tuple[dict[str, float], ...]:
    try:
        document = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("HBM capacity draws must be UTF-8") from exc
    expected_fields = [
        "draw_index",
        "memory_dies_per_stack",
        "stacks_per_accelerator",
        "accelerator_package_demand",
        "demanded_stacks",
        "good_stacks",
        "platform_qualified_stacks",
        "customer_allocated_stacks",
        "hbm_package_equivalents",
        "packages_supported",
        *[
            f"supplier.{supplier_id}.customer_allocated_stacks"
            for supplier_id in supplier_ids
        ],
    ]
    reader = csv.DictReader(io.StringIO(document))
    if reader.fieldnames != expected_fields:
        raise ValueError("HBM capacity draw fields do not match the supplier result")
    rows = []
    numeric_fields = expected_fields[1:]
    for expected_index, source in enumerate(reader):
        try:
            draw_index = int(source["draw_index"])
        except (TypeError, ValueError) as exc:
            raise ValueError("HBM capacity draw_index must be an integer") from exc
        if draw_index != expected_index:
            raise ValueError("HBM capacity draw_index must be contiguous from zero")
        row: dict[str, float] = {"draw_index": float(draw_index)}
        for field in numeric_fields:
            try:
                value = float(source[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"HBM capacity draw {field} must be numeric") from exc
            if not isfinite(value) or value < 0:
                raise ValueError(
                    f"HBM capacity draw {field} must be finite and nonnegative"
                )
            row[field] = value
        if row["memory_dies_per_stack"] <= 0 or row["stacks_per_accelerator"] <= 0:
            raise ValueError("HBM capacity draw topology must be positive")
        supplier_total = sum(
            row[f"supplier.{supplier_id}.customer_allocated_stacks"]
            for supplier_id in supplier_ids
        )
        if not isclose(
            supplier_total,
            row["customer_allocated_stacks"],
            rel_tol=1e-12,
            abs_tol=1e-8,
        ):
            raise ValueError("HBM capacity draw supplier allocations do not sum")
        if not isclose(
            row["accelerator_package_demand"] * row["stacks_per_accelerator"],
            row["demanded_stacks"],
            rel_tol=1e-12,
            abs_tol=1e-8,
        ):
            raise ValueError("HBM capacity draw demanded stacks do not conserve demand")
        if not isclose(
            row["customer_allocated_stacks"] / row["stacks_per_accelerator"],
            row["hbm_package_equivalents"],
            rel_tol=1e-12,
            abs_tol=1e-8,
        ):
            raise ValueError("HBM capacity draw package equivalents do not conserve stacks")
        if not isclose(
            min(
                row["hbm_package_equivalents"],
                row["accelerator_package_demand"],
            ),
            row["packages_supported"],
            rel_tol=1e-12,
            abs_tol=1e-8,
        ):
            raise ValueError("HBM capacity draw supported packages are inconsistent")
        rows.append(row)
    if not rows:
        raise ValueError("HBM capacity draws cannot be empty")

    platform = _mapping(hbm_result.get("platform"), "hbm_result.platform")
    topology_values = {
        "memory_dies_per_stack": _estimate_signature(
            _mapping(
                platform.get("memory_dies_per_stack"),
                "hbm_result.platform.memory_dies_per_stack",
            ),
            "hbm_result.platform.memory_dies_per_stack",
        )[1],
        "stacks_per_accelerator": _estimate_signature(
            _mapping(
                platform.get("stacks_per_accelerator"),
                "hbm_result.platform.stacks_per_accelerator",
            ),
            "hbm_result.platform.stacks_per_accelerator",
        )[1],
    }
    for row in rows:
        for field, expected in topology_values.items():
            if not isclose(row[field], expected, rel_tol=0, abs_tol=1e-12):
                raise ValueError(
                    f"HBM capacity draw {field} does not match source topology"
                )

    totals = _mapping(hbm_result.get("totals"), "hbm_result.totals")
    checks: list[tuple[str, list[float], Mapping[str, Any]]] = [
        (
            IMPORTED_METRIC,
            [row[IMPORTED_METRIC] for row in rows],
            _mapping(totals.get(IMPORTED_METRIC), f"hbm_result.totals.{IMPORTED_METRIC}"),
        )
    ]
    suppliers = {
        _text(item, "id", "hbm_result.supplier"): item
        for item in (
            _mapping(value, "hbm_result.supplier")
            for value in hbm_result.get("suppliers", [])
        )
    }
    for supplier_id in supplier_ids:
        supplier = suppliers[supplier_id]
        outputs = _mapping(supplier.get("outputs"), f"supplier.{supplier_id}.outputs")
        checks.append(
            (
                f"supplier.{supplier_id}.customer_allocated_stacks",
                [
                    row[f"supplier.{supplier_id}.customer_allocated_stacks"]
                    for row in rows
                ],
                _mapping(
                    outputs.get("customer_allocated_stacks"),
                    f"supplier.{supplier_id}.customer_allocated_stacks",
                ),
            )
        )
    for name, values, expected in checks:
        observed = summarize(values).as_dict()
        for field in ("p10", "p50", "p90", "mean", "minimum", "maximum"):
            target = expected.get(field)
            if isinstance(target, bool) or not isinstance(target, (int, float)):
                raise ValueError(f"{name}.{field} must be numeric")
            if not isclose(
                observed[field],
                float(target),
                rel_tol=1e-12,
                abs_tol=1e-8,
            ):
                raise ValueError(
                    f"HBM capacity draws do not reproduce {name}.{field}"
                )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class HbmManufacturingLinkCase:
    manufacturing: ManufacturingScenario
    metadata: Mapping[str, Any]
    manufacturing_document: str
    hbm_result: Mapping[str, Any]
    hbm_result_document: str
    recipe_document: str
    manufacturing_sha256: str
    hbm_result_sha256: str
    imported_distribution: Mapping[str, float]
    source_minimum_confidence: float
    lineage: Mapping[str, Any]
    capacity_draws_document: str | None
    capacity_draws_sha256: str | None
    capacity_draws: tuple[dict[str, float], ...]
    package_coverage: Mapping[str, Any] | None


def load_hbm_manufacturing_link_case(
    manufacturing_scenario_path: str | Path,
    hbm_result_path: str | Path,
    recipe_path: str | Path,
    capacity_draws_path: str | Path | None = None,
) -> HbmManufacturingLinkCase:
    manufacturing_raw = Path(manufacturing_scenario_path).read_bytes()
    hbm_raw = Path(hbm_result_path).read_bytes()
    recipe_raw = Path(recipe_path).read_bytes()
    capacity_draws_raw = (
        Path(capacity_draws_path).read_bytes()
        if capacity_draws_path is not None
        else None
    )
    try:
        manufacturing_document = manufacturing_raw.decode("utf-8")
        hbm_document = hbm_raw.decode("utf-8")
        recipe_document = recipe_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("link inputs must be UTF-8") from exc
    try:
        manufacturing_data = _mapping(
            json.loads(manufacturing_document),
            "manufacturing_scenario",
        )
        hbm_result = _mapping(json.loads(hbm_document), "hbm_result")
        recipe = _mapping(json.loads(recipe_document), "link_recipe")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid HBM manufacturing link JSON: {exc}") from exc

    recipe_format = recipe.get("format")
    if recipe_format not in {
        HBM_MANUFACTURING_LINK_FORMAT,
        HBM_MANUFACTURING_DRAW_LINK_FORMAT,
        HBM_MANUFACTURING_COVERAGE_LINK_FORMAT,
    }:
        raise ValueError(
            "link recipe format must be "
            f"{HBM_MANUFACTURING_LINK_FORMAT}, {HBM_MANUFACTURING_DRAW_LINK_FORMAT}, "
            f"or {HBM_MANUFACTURING_COVERAGE_LINK_FORMAT}"
        )
    coverage_link = recipe_format == HBM_MANUFACTURING_COVERAGE_LINK_FORMAT
    draw_link = recipe_format in {
        HBM_MANUFACTURING_DRAW_LINK_FORMAT,
        HBM_MANUFACTURING_COVERAGE_LINK_FORMAT,
    }
    if draw_link and capacity_draws_raw is None:
        raise ValueError("capacity_draws_path is required for a draw-level link")
    if not draw_link and capacity_draws_raw is not None:
        raise ValueError("capacity_draws_path requires a draw-level link recipe")
    _only(
        recipe,
        {
            "format",
            "scenario",
            "manufacturing_scenario",
            "hbm_supplier_result",
            "mapping",
            *({"package_coverage"} if coverage_link else set()),
        },
        "link_recipe",
    )
    metadata = _mapping(_value(recipe, "scenario", "link_recipe"), "scenario")
    _only(
        metadata,
        {
            "id",
            "name",
            "quarter",
            "as_of_date",
            "recorded_at",
            "samples",
            "seed",
            "notes",
        },
        "scenario",
    )
    for field in ("id", "name", "quarter", "as_of_date", "recorded_at", "notes"):
        _text(metadata, field, "scenario")
    if _integer(metadata, "samples", "scenario") < 100:
        raise ValueError("scenario.samples must be at least 100")
    _integer(metadata, "seed", "scenario")
    linked_as_of = _date(_text(metadata, "as_of_date", "scenario"), "scenario.as_of_date")
    linked_recorded_at = _timestamp(
        _text(metadata, "recorded_at", "scenario"),
        "scenario.recorded_at",
    )

    manufacturing_digest = _sha256(manufacturing_raw)
    manufacturing_spec = _mapping(
        _value(recipe, "manufacturing_scenario", "link_recipe"),
        "manufacturing_scenario",
    )
    _only(
        manufacturing_spec,
        {"sha256", "expected_scenario_id", "replace_hbm_wafer_flow_id", "scope"},
        "manufacturing_scenario",
    )
    if manufacturing_digest != _text(
        manufacturing_spec,
        "sha256",
        "manufacturing_scenario",
    ):
        raise ValueError("manufacturing scenario SHA-256 does not match the link recipe")
    manufacturing = manufacturing_from_dict(manufacturing_data)
    if manufacturing.id != _text(
        manufacturing_spec,
        "expected_scenario_id",
        "manufacturing_scenario",
    ):
        raise ValueError("manufacturing scenario ID does not match the link recipe")
    removed_flow = _text(
        manufacturing_spec,
        "replace_hbm_wafer_flow_id",
        "manufacturing_scenario",
    )
    if removed_flow != manufacturing.hbm.wafer.id:
        raise ValueError("replace_hbm_wafer_flow_id does not match the aggregate HBM flow")
    _text(manufacturing_spec, "scope", "manufacturing_scenario")

    if hbm_result.get("format") != HBM_SUPPLIER_RESULT_FORMAT:
        raise ValueError(f"HBM result format must be {HBM_SUPPLIER_RESULT_FORMAT}")
    hbm_digest = _sha256(hbm_raw)
    hbm_spec = _mapping(
        _value(recipe, "hbm_supplier_result", "link_recipe"),
        "hbm_supplier_result",
    )
    _only(
        hbm_spec,
        {
            "sha256",
            "expected_scenario_id",
            "capacity_metric",
            "scope",
            *(
                {"capacity_draws_sha256", "expected_draw_count"}
                if draw_link
                else set()
            ),
        },
        "hbm_supplier_result",
    )
    if hbm_digest != _text(hbm_spec, "sha256", "hbm_supplier_result"):
        raise ValueError("HBM supplier result SHA-256 does not match the link recipe")
    hbm_metadata = _scenario_metadata(hbm_result, "hbm_result")
    if hbm_metadata["id"] != _text(
        hbm_spec,
        "expected_scenario_id",
        "hbm_supplier_result",
    ):
        raise ValueError("HBM supplier scenario ID does not match the link recipe")
    if _text(hbm_spec, "capacity_metric", "hbm_supplier_result") != IMPORTED_METRIC:
        raise ValueError(f"capacity_metric must be {IMPORTED_METRIC}")
    _text(hbm_spec, "scope", "hbm_supplier_result")

    quarter = _text(metadata, "quarter", "scenario")
    if manufacturing.quarter != quarter or hbm_metadata["quarter"] != quarter:
        raise ValueError("linked, manufacturing, and HBM supplier quarters must match")
    for source_name, source_as_of, source_recorded in (
        ("manufacturing", manufacturing.as_of_date, manufacturing.recorded_at),
        ("HBM supplier", hbm_metadata["as_of_date"], hbm_metadata["recorded_at"]),
    ):
        if _date(source_as_of, f"{source_name}.as_of_date") > linked_as_of:
            raise ValueError(f"{source_name} as_of_date cannot follow linked as_of_date")
        if _timestamp(source_recorded, f"{source_name}.recorded_at") >= linked_recorded_at:
            raise ValueError(f"linked recorded_at must follow {source_name} recorded_at")

    mapping = _mapping(_value(recipe, "mapping", "link_recipe"), "mapping")
    _only(
        mapping,
        {
            "distribution_mapping",
            "confirming_evidence",
            "falsifying_evidence",
            "notes",
        },
        "mapping",
    )
    expected_mapping = DRAW_MAPPING if draw_link else TRIANGULAR_MAPPING
    if _text(mapping, "distribution_mapping", "mapping") != expected_mapping:
        raise ValueError(f"distribution_mapping must be {expected_mapping}")
    for field in ("confirming_evidence", "falsifying_evidence", "notes"):
        _text(mapping, field, "mapping")
    package_coverage = None
    if coverage_link:
        package_coverage = _package_coverage(
            _value(recipe, "package_coverage", "link_recipe"),
            "package_coverage",
        )
        assembly_posture = manufacturing.package.assembly_starts.posture.value
        if package_coverage["posture"] != assembly_posture:
            raise ValueError(
                "package coverage posture must match package assembly starts posture"
            )

    totals = _mapping(hbm_result.get("totals"), "hbm_result.totals")
    imported = _distribution(
        totals.get(IMPORTED_METRIC),
        f"hbm_result.totals.{IMPORTED_METRIC}",
    )
    topology_checks = _topology_checks(manufacturing, hbm_result)
    supplier_values = hbm_result.get("suppliers")
    if not isinstance(supplier_values, list) or not supplier_values:
        raise ValueError("HBM supplier result must contain suppliers")
    capacity_scope_ids = []
    supplier_ids = []
    supplier_names = []
    for index, value in enumerate(supplier_values):
        supplier = _mapping(value, f"hbm_result.suppliers[{index}]")
        supplier_ids.append(_text(supplier, "id", f"hbm_result.suppliers[{index}]"))
        supplier_names.append(
            _text(supplier, "name", f"hbm_result.suppliers[{index}]")
        )
        capacity_scope_ids.append(
            _text(
                supplier,
                "capacity_scope_id",
                f"hbm_result.suppliers[{index}]",
            )
        )
    if len(set(supplier_ids)) != len(supplier_ids):
        raise ValueError("HBM supplier result contains duplicate supplier IDs")
    if len(set(capacity_scope_ids)) != len(capacity_scope_ids):
        raise ValueError("HBM supplier result contains overlapping capacity scopes")
    parsed_capacity_draws: tuple[dict[str, float], ...] = ()
    capacity_draws_digest = None
    capacity_draws_document = None
    if draw_link:
        assert capacity_draws_raw is not None
        capacity_draws_digest = _sha256(capacity_draws_raw)
        if capacity_draws_digest != _text(
            hbm_spec,
            "capacity_draws_sha256",
            "hbm_supplier_result",
        ):
            raise ValueError(
                "HBM supplier capacity draws SHA-256 does not match the link recipe"
            )
        parsed_capacity_draws = _capacity_draws(
            capacity_draws_raw,
            hbm_result=hbm_result,
            supplier_ids=supplier_ids,
        )
        expected_draw_count = _integer(
            hbm_spec,
            "expected_draw_count",
            "hbm_supplier_result",
        )
        if expected_draw_count != len(parsed_capacity_draws):
            raise ValueError("HBM supplier capacity draw count does not match the recipe")
        source_samples = hbm_metadata.get("samples")
        if isinstance(source_samples, bool) or not isinstance(source_samples, int):
            raise ValueError("HBM supplier result scenario.samples must be an integer")
        if source_samples != expected_draw_count:
            raise ValueError("HBM supplier capacity draws do not match source samples")
        if _integer(metadata, "samples", "scenario") != expected_draw_count:
            raise ValueError("draw-level linked samples must equal the source draw count")
        capacity_draws_document = capacity_draws_raw.decode("utf-8")
    if any(item.comparison_target == "hbm_wafer_starts" for item in manufacturing.references):
        raise ValueError("aggregate HBM wafer-start references cannot survive the replacement")

    minimum_confidence = _minimum_input_confidence(hbm_result)
    linked_synthetic = bool(manufacturing.synthetic or hbm_metadata["synthetic"])
    lineage = {
        "format": HBM_MANUFACTURING_LINEAGE_FORMAT,
        "scenario_id": _text(metadata, "id", "scenario"),
        "quarter": quarter,
        "synthetic": linked_synthetic,
        "sources": {
            "manufacturing_scenario": {
                "scenario_id": manufacturing.id,
                "format": manufacturing_data.get("format"),
                "sha256": manufacturing_digest,
                "scope": manufacturing_spec["scope"],
                "synthetic": manufacturing.synthetic,
            },
            "hbm_supplier_result": {
                "scenario_id": hbm_metadata["id"],
                "format": hbm_result["format"],
                "sha256": hbm_digest,
                "scope": hbm_spec["scope"],
                "synthetic": hbm_metadata["synthetic"],
                "minimum_input_confidence": minimum_confidence,
                "supplier_ids": supplier_ids,
                "supplier_names": supplier_names,
                "capacity_scope_ids": capacity_scope_ids,
                **(
                    {
                        "capacity_draws_sha256": capacity_draws_digest,
                        "capacity_draw_count": len(parsed_capacity_draws),
                    }
                    if draw_link
                    else {}
                ),
            },
        },
        "replacement": {
            "removed_aggregate_hbm_wafer_flow_id": removed_flow,
            "imported_metric": IMPORTED_METRIC,
            "source_distribution": imported,
            "source_unit": "stack",
            "distribution_mapping": expected_mapping,
            "topology_checks": topology_checks,
            "double_count_guard": (
                "The aggregate HBM wafer flow is not sampled or emitted; only the "
                "supplier result's customer-allocated stack pool enters package attempts."
            ),
            "confirming_evidence": mapping["confirming_evidence"],
            "falsifying_evidence": mapping["falsifying_evidence"],
            "notes": mapping["notes"],
        },
    }
    if package_coverage is not None:
        lineage["package_coverage"] = package_coverage
    return HbmManufacturingLinkCase(
        manufacturing=manufacturing,
        metadata=dict(metadata),
        manufacturing_document=manufacturing_document,
        hbm_result=dict(hbm_result),
        hbm_result_document=hbm_document,
        recipe_document=recipe_document,
        manufacturing_sha256=manufacturing_digest,
        hbm_result_sha256=hbm_digest,
        imported_distribution=imported,
        source_minimum_confidence=minimum_confidence,
        lineage=lineage,
        capacity_draws_document=capacity_draws_document,
        capacity_draws_sha256=capacity_draws_digest,
        capacity_draws=parsed_capacity_draws,
        package_coverage=package_coverage,
    )


def _linked_capacity_estimate(case: HbmManufacturingLinkCase) -> dict[str, Any]:
    source_metadata = _scenario_metadata(case.hbm_result, "hbm_result")
    evidence_id = f"linked-result:hbm-suppliers:{case.hbm_result_sha256[:12]}"
    distribution = case.imported_distribution
    if case.capacity_draws:
        methodology = (
            f"Import every {IMPORTED_METRIC} draw from frozen HBM supplier result "
            f"{case.hbm_result_sha256} and capacity-draw artifact "
            f"{case.capacity_draws_sha256}. A deterministic permutation preserves the "
            "source marginal distribution and within-draw supplier allocation while "
            "avoiding an unsupported draw-index relationship with manufacturing."
        )
    else:
        methodology = (
            f"Import {IMPORTED_METRIC} from frozen HBM supplier result "
            f"{case.hbm_result_sha256}. Source P10, P50, and P90 become the "
            "triangular low, mode, and high; source tails and joint dependence are not preserved."
        )
    return {
        "low": distribution["p10"],
        "base": distribution["p50"],
        "high": distribution["p90"],
        "unit": "stack",
        "posture": "synthetic" if source_metadata["synthetic"] else "modeled",
        "methodology": methodology,
        "confidence": case.source_minimum_confidence,
        "last_updated": source_metadata["as_of_date"],
        "evidence_ids": [evidence_id],
        "confirming_evidence": case.lineage["replacement"]["confirming_evidence"],
        "falsifying_evidence": case.lineage["replacement"]["falsifying_evidence"],
        "correlation_group": f"linked:hbm-suppliers:{case.hbm_result_sha256[:12]}",
    }


def _linked_inputs(case: HbmManufacturingLinkCase) -> dict[str, Any]:
    inputs = _manufacturing_inputs(case.manufacturing)
    removed = inputs["hbm"]
    inputs["hbm"] = {
        "replacement_basis": IMPORTED_METRIC,
        "source_scenario_id": case.hbm_result["scenario"]["id"],
        "source_result_sha256": case.hbm_result_sha256,
        "removed_aggregate_hbm_wafer_flow_id": removed["wafer"]["id"],
        "customer_allocated_stacks": _linked_capacity_estimate(case),
        "memory_dies_per_stack": removed["memory_dies_per_stack"],
        "stack_capacity_gb": removed["stack_capacity_gb"],
        "stacks_per_accelerator": removed["stacks_per_accelerator"],
    }
    if case.package_coverage is not None:
        inputs["package"]["assembly_start_basis"] = case.package_coverage[
            "assembly_start_basis"
        ]
        inputs["package"]["absorbed_resource_kinds"] = list(
            case.package_coverage["absorbed_resource_kinds"]
        )
    return inputs


def _research_queue(
    case: HbmManufacturingLinkCase,
    inputs: dict[str, Any],
    bottlenecks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    binding = {item["constraint"]: item["probability"] for item in bottlenecks}
    rows = []
    groups = (
        ("logic_wafer", inputs["logic"]["wafer"]["id"], "logic_binned_dies", inputs["logic"]["wafer"]),
        ("logic_process", "logic-yield-and-binning", "logic_binned_dies", inputs["logic"]),
        ("package", "advanced-package-assembly", "package_assembly_starts", inputs["package"]),
    )
    for owner_type, owner_id, branch, values in groups:
        for parameter, estimate in values.items():
            if not isinstance(estimate, dict) or estimate.get("posture") != "synthetic":
                continue
            influence = binding.get(branch, 0.0)
            influence_method = "Current linked branch binding probability"
            if owner_type == "package" and parameter == "assembly_yield":
                influence = 1.0
                influence_method = "Applied to every attempted package"
            rows.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "parameter": parameter,
                    "branch": branch,
                    "low": estimate["low"],
                    "base": estimate["base"],
                    "high": estimate["high"],
                    "unit": estimate["unit"],
                    "confidence": estimate["confidence"],
                    "last_updated": estimate["last_updated"],
                    "influence_probability": influence,
                    "influence_method": influence_method,
                    "research_priority": influence * (1 - estimate["confidence"]),
                    "methodology": estimate["methodology"],
                    "evidence_ids": list(estimate["evidence_ids"]),
                    "confirming_evidence": estimate["confirming_evidence"],
                    "falsifying_evidence": estimate["falsifying_evidence"],
                    "conditional_on_current_scenario": True,
                }
            )

    hbm_binding = binding.get("hbm_good_stacks", 0.0)
    for source_gap in case.hbm_result.get("research_queue", []):
        if (
            source_gap.get("owner_type") == "platform"
            and source_gap.get("parameter") == "accelerator_package_demand"
        ):
            continue
        source_influence = float(source_gap.get("influence_share", 1.0))
        influence = hbm_binding * source_influence
        rows.append(
            {
                "owner_type": f"hbm_{source_gap['owner_type']}",
                "owner_id": source_gap["owner_id"],
                "parameter": source_gap["parameter"],
                "branch": "hbm_good_stacks",
                "low": source_gap["low"],
                "base": source_gap["base"],
                "high": source_gap["high"],
                "unit": source_gap["unit"],
                "confidence": source_gap["confidence"],
                "last_updated": source_gap["last_updated"],
                "influence_probability": influence,
                "influence_method": (
                    "Linked HBM binding probability multiplied by upstream supplier share"
                ),
                "research_priority": influence * (1 - source_gap["confidence"]),
                "methodology": source_gap["methodology"],
                "evidence_ids": list(source_gap["evidence_ids"]),
                "confirming_evidence": source_gap["confirming_evidence"],
                "falsifying_evidence": source_gap["falsifying_evidence"],
                "conditional_on_current_scenario": True,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            -item["research_priority"],
            item["owner_type"],
            item["owner_id"],
            item["parameter"],
        ),
    )


def reconcile_hbm_manufacturing_link(
    case: HbmManufacturingLinkCase,
    *,
    _output_draws: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run logic and package conversion with only the linked supplier HBM pool."""

    scenario = case.manufacturing
    random = Random(_integer(case.metadata, "seed", "scenario"))
    sample_count = _integer(case.metadata, "samples", "scenario")
    samples: dict[str, list[float]] = defaultdict(list)
    bottleneck_counts: dict[str, float] = defaultdict(float)
    comparison_target_samples: dict[str, list[float]] = defaultdict(list)
    low = case.imported_distribution["p10"]
    mode = case.imported_distribution["p50"]
    high = case.imported_distribution["p90"]
    capacity_draw_order = list(range(len(case.capacity_draws)))
    if capacity_draw_order:
        draw_random = Random(
            f"{case.metadata['seed']}:{case.capacity_draws_sha256}:permutation"
        )
        draw_random.shuffle(capacity_draw_order)

    for draw_index in range(sample_count):
        sampler = EstimateSampler(random)
        logic_wafer_starts = sampler.estimate(scenario.logic.wafer.wafer_starts)
        logic_width = sampler.estimate(scenario.logic.wafer.die_width_mm)
        logic_height = sampler.estimate(scenario.logic.wafer.die_height_mm)
        logic_gross_per_wafer = gross_dies_per_wafer(
            wafer_diameter_mm=sampler.estimate(scenario.logic.wafer.wafer_diameter_mm),
            edge_exclusion_mm=sampler.estimate(scenario.logic.wafer.edge_exclusion_mm),
            die_width_mm=logic_width,
            die_height_mm=logic_height,
            scribe_width_mm=sampler.estimate(scenario.logic.wafer.scribe_width_mm),
        )
        defect_yield = negative_binomial_die_yield(
            defect_density_per_cm2=sampler.estimate(
                scenario.logic.defect_density_per_cm2
            ),
            die_area_mm2=logic_width * logic_height,
            clustering_alpha=sampler.estimate(scenario.logic.clustering_alpha),
        )
        sort_yield = sampler.estimate(scenario.logic.wafer_sort_yield)
        bin_share = sampler.estimate(scenario.logic.performance_bin_share)
        logic_gross_dies = logic_wafer_starts * logic_gross_per_wafer
        logic_known_good_dies = logic_gross_dies * defect_yield * sort_yield
        logic_binned_dies = logic_known_good_dies * bin_share
        logic_dies_per_accelerator = sampler.estimate(
            scenario.package.logic_dies_per_accelerator
        )
        logic_package_equivalents = logic_binned_dies / logic_dies_per_accelerator

        if capacity_draw_order:
            sampled_stacks_per_accelerator = sampler.estimate(
                scenario.hbm.stacks_per_accelerator
            )
            capacity_draw = case.capacity_draws[capacity_draw_order[draw_index]]
            customer_allocated_stacks = capacity_draw[
                "customer_allocated_stacks"
            ]
            stacks_per_accelerator = capacity_draw["stacks_per_accelerator"]
            if not isclose(
                sampled_stacks_per_accelerator,
                stacks_per_accelerator,
                rel_tol=0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "source capacity draw topology changed after link validation"
                )
        else:
            customer_allocated_stacks = random.triangular(low, high, mode)
            stacks_per_accelerator = sampler.estimate(
                scenario.hbm.stacks_per_accelerator
            )
        hbm_package_equivalents = customer_allocated_stacks / stacks_per_accelerator
        assembly_starts = sampler.estimate(scenario.package.assembly_starts)
        candidates = {
            "logic_binned_dies": logic_package_equivalents,
            "hbm_good_stacks": hbm_package_equivalents,
            "package_assembly_starts": assembly_starts,
        }
        attempted_packages = min(candidates.values())
        tied = [
            key
            for key, value in candidates.items()
            if isclose(value, attempted_packages, rel_tol=1e-10, abs_tol=1e-8)
        ]
        for key in tied:
            bottleneck_counts[key] += 1 / len(tied)
        assembly_yield = sampler.estimate(scenario.package.assembly_yield)
        finished_packages = attempted_packages * assembly_yield
        accelerators_per_system = sampler.estimate(
            scenario.package.accelerators_per_system
        )
        complete_systems = finished_packages / accelerators_per_system
        stack_capacity_gb = sampler.estimate(scenario.hbm.stack_capacity_gb)
        memory_dies_per_stack = sampler.estimate(scenario.hbm.memory_dies_per_stack)

        comparison_target_samples["logic_wafer_starts"].append(logic_wafer_starts)
        comparison_target_samples["package_assembly_starts"].append(assembly_starts)
        values = {
            "logic_gross_dies_per_wafer": logic_gross_per_wafer,
            "logic_defect_yield": defect_yield,
            "logic_effective_known_good_yield": defect_yield * sort_yield,
            "logic_binned_yield": defect_yield * sort_yield * bin_share,
            "logic_gross_dies": logic_gross_dies,
            "logic_known_good_dies": logic_known_good_dies,
            "logic_binned_dies": logic_binned_dies,
            "logic_package_equivalents": logic_package_equivalents,
            "hbm_good_stacks": customer_allocated_stacks,
            "hbm_package_equivalents": hbm_package_equivalents,
            "hbm_gb_per_accelerator": stack_capacity_gb * stacks_per_accelerator,
            "hbm_memory_dies_per_accelerator": (
                memory_dies_per_stack * stacks_per_accelerator
            ),
            "package_assembly_start_capacity": assembly_starts,
            "package_attempts": attempted_packages,
            "package_assembly_yield": assembly_yield,
            "finished_accelerator_packages": finished_packages,
            "complete_system_equivalents": complete_systems,
            "surplus_binned_logic_dies": max(
                0.0,
                logic_binned_dies - attempted_packages * logic_dies_per_accelerator,
            ),
            "surplus_good_hbm_stacks": max(
                0.0,
                customer_allocated_stacks - attempted_packages * stacks_per_accelerator,
            ),
            "logic_die_utilization": (
                0.0
                if logic_binned_dies == 0
                else attempted_packages * logic_dies_per_accelerator / logic_binned_dies
            ),
            "hbm_stack_utilization": (
                0.0
                if customer_allocated_stacks == 0
                else attempted_packages * stacks_per_accelerator / customer_allocated_stacks
            ),
            "assembly_start_utilization": (
                0.0 if assembly_starts == 0 else attempted_packages / assembly_starts
            ),
        }
        for key, value in values.items():
            samples[key].append(value)
        if _output_draws is not None:
            _output_draws.append(
                {
                    "draw_index": draw_index,
                    "source_hbm_draw_index": (
                        capacity_draw_order[draw_index]
                        if capacity_draw_order
                        else -1
                    ),
                    "logic_package_equivalents": logic_package_equivalents,
                    "customer_allocated_hbm_stacks": customer_allocated_stacks,
                    "hbm_package_equivalents": hbm_package_equivalents,
                    "package_assembly_start_capacity": assembly_starts,
                    "package_attempts": attempted_packages,
                    "package_assembly_yield": assembly_yield,
                    "finished_accelerator_packages": finished_packages,
                    "complete_system_equivalents": complete_systems,
                }
            )

    bottlenecks = [
        {
            "constraint": key,
            "probability": bottleneck_counts[key] / sample_count,
        }
        for key in sorted(
            bottleneck_counts,
            key=lambda item: (-bottleneck_counts[item], item),
        )
    ]
    reference_comparisons = []
    for reference in scenario.references:
        reference_random = Random(
            f"{_integer(case.metadata, 'seed', 'scenario')}:{reference.id}"
        )
        reference_values = []
        modeled_values = comparison_target_samples[reference.comparison_target]
        shares = []
        for modeled in modeled_values:
            value = EstimateSampler(reference_random).estimate(reference.estimate)
            reference_values.append(value)
            shares.append(modeled / value)
        reference_comparisons.append(
            {
                "id": reference.id,
                "name": reference.name,
                "period": reference.period,
                "comparison_target": reference.comparison_target,
                "reference_value": summarize(reference_values).as_dict(),
                "modeled_target": summarize(modeled_values).as_dict(),
                "target_share": summarize(shares).as_dict(),
                "unit": reference.estimate.unit,
                "usable_as_product_capacity": reference.usable_as_product_capacity,
                "notes": reference.notes,
            }
        )

    inputs = _linked_inputs(case)
    source_metadata = _scenario_metadata(case.hbm_result, "hbm_result")
    evidence_id = f"linked-result:hbm-suppliers:{case.hbm_result_sha256[:12]}"
    evidence = _manufacturing_evidence_payload(scenario)
    evidence.append(
        {
            "id": evidence_id,
            "kind": "synthetic" if source_metadata["synthetic"] else "other",
            "title": "Frozen supplier-resolved HBM reconciliation result",
            "source_url": f"urn:sha256:{case.hbm_result_sha256}",
            "publisher": "AI Supply Intelligence",
            "retrieved_at": case.metadata["recorded_at"],
            "published_at": source_metadata["recorded_at"],
            "source_family": "ai-supply-frozen-hbm-supplier-result",
            "license": None,
            "excerpt": (
                f"Hash-pinned {source_metadata['quarter']} customer-allocated HBM "
                f"stack result for {source_metadata['id']}; synthetic="
                f"{str(source_metadata['synthetic']).lower()}."
            ),
            "content_hash": case.hbm_result_sha256,
        }
    )
    synthetic = bool(scenario.synthetic or source_metadata["synthetic"])
    warnings = [
        (
            f"Aggregate HBM wafer flow {scenario.hbm.wafer.id} is removed. Only the "
            "frozen supplier result's customer-allocated stacks enter package attempts."
        )
    ]
    if case.capacity_draws:
        warnings.append(
            "The draw-level link preserves the source HBM marginal tails and within-draw supplier allocation. Its deterministic permutation does not assert or preserve dependence with logic or packaging inputs."
        )
    else:
        warnings.append(
            "The source P10, P50, and P90 are triangular endpoints and mode. This truncates source tails and does not preserve supplier or cross-branch dependence."
        )
    warnings.append(
        "Pre-allocation HBM gross-die, known-good-die, and raw-stack outputs are not re-emitted as aggregate manufacturing outputs; they remain in the source result."
    )
    if synthetic:
        warnings.append(
            "The linked manufacturing and supplier-capacity inputs are synthetic; this is not an estimate of actual Blackwell output."
        )
    if case.package_coverage is not None:
        warnings.append(
            "Package assembly starts are declared material-cleared and absorb the listed interposer and substrate resource kinds. This scope declaration is synthetic and is not supplier evidence."
        )
    result = {
        "format": MANUFACTURING_RESULT_FORMAT,
        "scenario": {
            "id": case.metadata["id"],
            "name": case.metadata["name"],
            "quarter": case.metadata["quarter"],
            "as_of_date": case.metadata["as_of_date"],
            "recorded_at": case.metadata["recorded_at"],
            "synthetic": synthetic,
            "samples": sample_count,
            "seed": case.metadata["seed"],
            "notes": case.metadata["notes"],
        },
        "topology": {
            "logic_dies_per_accelerator": _input_estimate(
                scenario.package.logic_dies_per_accelerator
            ),
            "hbm_memory_dies_per_stack": _input_estimate(
                scenario.hbm.memory_dies_per_stack
            ),
            "hbm_stacks_per_accelerator": _input_estimate(
                scenario.hbm.stacks_per_accelerator
            ),
            "hbm_stack_capacity_gb": _input_estimate(scenario.hbm.stack_capacity_gb),
            "accelerators_per_system": _input_estimate(
                scenario.package.accelerators_per_system
            ),
        },
        "conversion_outputs": {
            key: summarize(values).as_dict() for key, values in sorted(samples.items())
        },
        "bottlenecks": bottlenecks,
        "reference_comparisons": reference_comparisons,
        "methodology": {
            "gross_dies_per_wafer": (
                "Circular wafer area divided by effective die and scribe area, less an analytical edge-loss term."
            ),
            "logic_yield": (
                "Negative-binomial random-defect yield multiplied by wafer-sort yield and performance-bin share."
            ),
            "hbm_replacement": (
                "Remove the aggregate HBM wafer path and import customer-allocated stacks from one hash-pinned supplier result."
            ),
            "distribution_mapping": case.lineage["replacement"][
                "distribution_mapping"
            ],
            "package_output": (
                "The minimum of logic-die, imported allocated-HBM-stack, and assembly-start package equivalents, multiplied by final assembly yield."
            ),
        },
        "inputs": inputs,
        "research_queue": _research_queue(case, inputs, bottlenecks),
        "evidence": evidence,
        "lineage": case.lineage,
        "warnings": warnings,
    }
    if case.package_coverage is not None:
        result["coverage"] = {
            "package_assembly_starts": dict(case.package_coverage)
        }
    return result


def reconcile_hbm_manufacturing_output_draws(
    case: HbmManufacturingLinkCase,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draws: list[dict[str, Any]] = []
    result = reconcile_hbm_manufacturing_link(case, _output_draws=draws)
    return result, draws
