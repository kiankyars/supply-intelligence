"""Link frozen manufacturing and deployment results into one scoped chain scenario."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from pathlib import Path
from random import Random
from typing import Any, Mapping

from .datacenter_operational_engine import OUTPUT_UNITS as OPERATIONAL_OUTPUT_UNITS
from .engine import _input_estimate, summarize
from .loader import (
    _boolean,
    _estimate,
    _evidence,
    _integer,
    _list,
    _mapping,
    _number,
    _text,
    _value,
    scenario_from_dict,
)
from .manufacturing_engine import OUTPUT_UNITS as MANUFACTURING_OUTPUT_UNITS
from .models import QuarterlyScenario
from .system_assembly_engine import OUTPUT_UNITS as SYSTEM_ASSEMBLY_OUTPUT_UNITS


CHAIN_LINK_FORMAT = "ai-supply-chain-link.v1"
CHAIN_LINK_DRAW_FORMAT = "ai-supply-chain-link.v2"
SOURCE_CONTRACTS = {
    "manufacturing": (
        "ai-supply-manufacturing-result.v1",
        MANUFACTURING_OUTPUT_UNITS,
    ),
    "datacenter_operational": (
        "ai-supply-datacenter-operational-result.v1",
        OPERATIONAL_OUTPUT_UNITS,
    ),
    "system_assembly": (
        "ai-supply-system-assembly-result.v1",
        SYSTEM_ASSEMBLY_OUTPUT_UNITS,
    ),
}
REQUIRED_SOURCE_KEYS = {"manufacturing", "datacenter_operational"}
LINKABLE_METRICS = {
    "manufacturing": {
        "complete_system_equivalents",
        "finished_accelerator_packages",
    },
    "datacenter_operational": {"operational_racks"},
    "system_assembly": {"complete_racks"},
}


def _only(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unexpected = set(data) - allowed
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _capacity_draw_columns(
    raw: bytes,
    *,
    source_key: str,
    expected_count: int,
) -> dict[str, tuple[float, ...]]:
    try:
        document = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_key} capacity draws must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(document))
    if not reader.fieldnames or reader.fieldnames[0] != "draw_index":
        raise ValueError(
            f"{source_key} capacity draws must start with draw_index"
        )
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError(f"{source_key} capacity draw fields must be unique")
    columns: dict[str, list[float]] = {
        field: [] for field in reader.fieldnames if field != "draw_index"
    }
    for expected_index, row in enumerate(reader):
        try:
            draw_index = int(row["draw_index"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{source_key} capacity draw_index must be an integer"
            ) from exc
        if draw_index != expected_index:
            raise ValueError(
                f"{source_key} capacity draw_index must be contiguous from zero"
            )
        for field in columns:
            try:
                value = float(row[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{source_key} capacity draw {field} must be numeric"
                ) from exc
            if not isfinite(value) or value < 0:
                raise ValueError(
                    f"{source_key} capacity draw {field} must be finite and nonnegative"
                )
            columns[field].append(value)
    if any(len(values) != expected_count for values in columns.values()):
        raise ValueError(
            f"{source_key} capacity draws must contain {expected_count} rows"
        )
    if not columns and expected_count:
        raise ValueError(f"{source_key} capacity draws contain no metric fields")
    return {key: tuple(values) for key, values in columns.items()}


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
    scenario = _mapping(_value(document, "scenario", path), f"{path}.scenario")
    for key in ("id", "quarter", "as_of_date", "recorded_at", "synthetic"):
        _value(scenario, key, f"{path}.scenario")
    return scenario


def _minimum_input_confidence(result: Mapping[str, Any], source_key: str) -> float:
    values: list[float] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if {"low", "base", "high", "confidence"}.issubset(value):
                confidence = value["confidence"]
                if isinstance(confidence, bool) or not isinstance(
                    confidence,
                    (int, float),
                ):
                    raise ValueError(
                        f"{source_key} result contains invalid input confidence"
                    )
                values.append(float(confidence))
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result.get("inputs", {}))
    if not values:
        raise ValueError(f"{source_key} result contains no auditable input estimates")
    return min(values)


def _fixed_estimate_value(value: Any, path: str) -> float:
    estimate = _mapping(value, path)
    values = []
    for key in ("low", "base", "high"):
        item = estimate.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{path}.{key} must be numeric")
        values.append(float(item))
    if values[0] != values[1] or values[1] != values[2]:
        raise ValueError(f"{path} must be fixed for linked topology conversion")
    return values[1]


def _source_evidence(
    source_key: str,
    digest: str,
    result: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    metadata = _scenario_metadata(result, source_key)
    synthetic = metadata["synthetic"]
    return {
        "id": f"linked-result:{source_key}:{digest[:12]}",
        "kind": "synthetic" if synthetic else "other",
        "title": f"Frozen {source_key.replace('_', ' ')} reconciliation result",
        "source_url": f"urn:sha256:{digest}",
        "publisher": "AI Supply Intelligence",
        "retrieved_at": recorded_at,
        "published_at": metadata["recorded_at"],
        "source_family": "ai-supply-frozen-result",
        "license": None,
        "excerpt": (
            f"Hash-pinned {metadata['quarter']} result for {metadata['id']}; "
            f"source scenario synthetic={str(synthetic).lower()}."
        ),
        "content_hash": digest,
    }


def _identity_estimate(
    *,
    unit: str,
    evidence_id: str,
    last_updated: str,
    confidence: float,
    methodology: str,
) -> dict[str, Any]:
    return {
        "low": 1.0,
        "base": 1.0,
        "high": 1.0,
        "unit": unit,
        "posture": "derived",
        "methodology": methodology,
        "confidence": confidence,
        "last_updated": last_updated,
        "evidence_ids": [evidence_id],
        "confirming_evidence": "The frozen source metric remains on the stated post-conversion basis.",
        "falsifying_evidence": "The source metric is redefined to require another yield or allocation conversion.",
        "correlation_group": None,
    }


def _capacity_estimate(
    *,
    distribution: Mapping[str, Any],
    unit: str,
    source_key: str,
    metric: str,
    source: Mapping[str, Any],
    digest: str,
    evidence_id: str,
    confidence: float,
    confirming_evidence: str,
    falsifying_evidence: str,
    draw_link: bool = False,
) -> dict[str, Any]:
    values = []
    for key in ("p10", "p50", "p90"):
        value = distribution.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{source_key}.{metric}.{key} must be numeric")
        numeric = float(value)
        if not isfinite(numeric) or numeric < 0:
            raise ValueError(f"{source_key}.{metric}.{key} must be finite and nonnegative")
        values.append(numeric)
    if values != sorted(values):
        raise ValueError(f"{source_key}.{metric} quantiles must be ordered")
    metadata = _scenario_metadata(source, source_key)
    return {
        "low": values[0],
        "base": values[1],
        "high": values[2],
        "unit": unit,
        "posture": "synthetic" if metadata["synthetic"] else "modeled",
        "methodology": (
            f"Import {source_key} {metric} from frozen result {digest}. "
            + (
                "The displayed P10, P50, and P90 retain the source audit range, while "
                "the linked engine consumes every exact hash-pinned source draw after "
                "a deterministic cross-source permutation."
                if draw_link
                else (
                    "The source P10, P50, and P90 are used as triangular low, mode, and high "
                    "parameters in the linked engine. This preserves the central range but "
                    "does not preserve source tails, point masses, or joint dependence."
                )
            )
        ),
        "confidence": confidence,
        "last_updated": metadata["as_of_date"],
        "evidence_ids": [evidence_id],
        "confirming_evidence": confirming_evidence,
        "falsifying_evidence": falsifying_evidence,
        "correlation_group": f"linked:{source_key}:{digest[:12]}:{metric}",
    }


@dataclass(frozen=True, slots=True)
class LinkedChainCase:
    scenario: QuarterlyScenario
    scenario_document: str
    lineage: Mapping[str, Any]
    base_document: str
    recipe_document: str
    source_documents: Mapping[str, str]
    source_draw_documents: Mapping[str, str]
    constraint_capacity_draws: Mapping[str, tuple[float, ...]]


def load_linked_chain_case(
    base_scenario_path: str | Path,
    recipe_path: str | Path,
    manufacturing_result_path: str | Path,
    operational_result_path: str | Path,
    assembly_result_path: str | Path | None = None,
    manufacturing_draws_path: str | Path | None = None,
    operational_draws_path: str | Path | None = None,
    assembly_draws_path: str | Path | None = None,
) -> LinkedChainCase:
    base_path = Path(base_scenario_path)
    recipe_source = Path(recipe_path)
    source_paths = {
        "manufacturing": Path(manufacturing_result_path),
        "datacenter_operational": Path(operational_result_path),
    }
    if assembly_result_path is not None:
        source_paths["system_assembly"] = Path(assembly_result_path)
    source_draw_paths = {
        key: Path(path)
        for key, path in (
            ("manufacturing", manufacturing_draws_path),
            ("datacenter_operational", operational_draws_path),
            ("system_assembly", assembly_draws_path),
        )
        if path is not None
    }
    base_raw = base_path.read_bytes()
    recipe_raw = recipe_source.read_bytes()
    source_raw = {key: path.read_bytes() for key, path in source_paths.items()}
    source_draw_raw = {
        key: path.read_bytes() for key, path in source_draw_paths.items()
    }
    try:
        base = _mapping(json.loads(base_raw), "base_scenario")
        recipe = _mapping(json.loads(recipe_raw), "link_recipe")
        sources = {
            key: _mapping(json.loads(raw), f"source.{key}")
            for key, raw in source_raw.items()
        }
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid linked-chain JSON: {exc}") from exc

    recipe_format = recipe.get("format")
    if recipe_format not in {CHAIN_LINK_FORMAT, CHAIN_LINK_DRAW_FORMAT}:
        raise ValueError(
            f"link recipe format must be {CHAIN_LINK_FORMAT} or {CHAIN_LINK_DRAW_FORMAT}"
        )
    draw_link = recipe_format == CHAIN_LINK_DRAW_FORMAT
    if draw_link and set(source_draw_paths) != set(source_paths):
        raise ValueError(
            "draw-linked recipes require one capacity-draw path for every source"
        )
    if not draw_link and source_draw_paths:
        raise ValueError("capacity-draw paths require an ai-supply-chain-link.v2 recipe")
    _only(
        recipe,
        {
            "format",
            "scenario",
            "base_scenario",
            "sources",
            "links",
            "evidence",
            "preserve_market_views",
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
            "scope_notes",
            "notes",
        },
        "scenario",
    )
    base_spec = _mapping(
        _value(recipe, "base_scenario", "link_recipe"),
        "base_scenario",
    )
    _only(base_spec, {"sha256", "expected_scenario_id"}, "base_scenario")
    if _sha256(base_raw) != _text(base_spec, "sha256", "base_scenario"):
        raise ValueError("base scenario SHA-256 does not match the link recipe")
    if base.get("format") != "ai-supply-scenario.v1":
        raise ValueError("base scenario format must be ai-supply-scenario.v1")
    base_metadata = _scenario_metadata(base, "base_scenario")
    if base_metadata["id"] != _text(
        base_spec,
        "expected_scenario_id",
        "base_scenario",
    ):
        raise ValueError("base scenario ID does not match the link recipe")

    source_specs = _mapping(_value(recipe, "sources", "link_recipe"), "sources")
    if not REQUIRED_SOURCE_KEYS.issubset(source_specs):
        raise ValueError(
            "sources must contain manufacturing and datacenter_operational"
        )
    if unexpected_sources := set(source_specs) - set(SOURCE_CONTRACTS):
        raise ValueError(f"unsupported linked sources: {sorted(unexpected_sources)}")
    if set(source_specs) != set(source_paths):
        raise ValueError(
            "source result paths must exactly match the sources declared in the recipe"
        )
    source_digests: dict[str, str] = {}
    source_draw_digests: dict[str, str] = {}
    source_draw_columns: dict[str, dict[str, tuple[float, ...]]] = {}
    source_confidences: dict[str, float] = {}
    source_evidence: dict[str, dict[str, Any]] = {}
    linked_recorded_at = _text(metadata, "recorded_at", "scenario")
    linked_timestamp = _timestamp(linked_recorded_at, "scenario.recorded_at")
    linked_quarter = _text(metadata, "quarter", "scenario")
    linked_samples = _integer(metadata, "samples", "scenario")
    linked_as_of = _date(_text(metadata, "as_of_date", "scenario"), "scenario.as_of_date")
    if base_metadata["quarter"] != linked_quarter:
        raise ValueError("base scenario quarter does not match linked scenario")
    if _date(base_metadata["as_of_date"], "base_scenario.as_of_date") > linked_as_of:
        raise ValueError("base scenario as_of_date cannot follow linked scenario")
    if _timestamp(base_metadata["recorded_at"], "base_scenario.recorded_at") >= linked_timestamp:
        raise ValueError("linked recorded_at must follow the base scenario")

    for source_key in source_paths:
        expected_format = SOURCE_CONTRACTS[source_key][0]
        spec = _mapping(source_specs[source_key], f"sources.{source_key}")
        _only(
            spec,
            {
                "sha256",
                "expected_scenario_id",
                "scope",
                *(
                    {"capacity_draws_sha256", "expected_draw_count"}
                    if draw_link
                    else set()
                ),
            },
            f"sources.{source_key}",
        )
        digest = _sha256(source_raw[source_key])
        if digest != _text(spec, "sha256", f"sources.{source_key}"):
            raise ValueError(f"{source_key} result SHA-256 does not match the link recipe")
        source = sources[source_key]
        if source.get("format") != expected_format:
            raise ValueError(f"{source_key} result format must be {expected_format}")
        source_metadata = _scenario_metadata(source, f"sources.{source_key}")
        if source_metadata["id"] != _text(
            spec,
            "expected_scenario_id",
            f"sources.{source_key}",
        ):
            raise ValueError(f"{source_key} scenario ID does not match the link recipe")
        if source_metadata["quarter"] != linked_quarter:
            raise ValueError(f"{source_key} quarter does not match linked scenario")
        if _date(
            source_metadata["as_of_date"],
            f"sources.{source_key}.as_of_date",
        ) > linked_as_of:
            raise ValueError(f"{source_key} as_of_date cannot follow linked scenario")
        if _timestamp(
            source_metadata["recorded_at"],
            f"sources.{source_key}.recorded_at",
        ) >= linked_timestamp:
            raise ValueError(f"linked recorded_at must follow {source_key} result")
        _text(spec, "scope", f"sources.{source_key}")
        source_digests[source_key] = digest
        source_confidences[source_key] = _minimum_input_confidence(
            source,
            source_key,
        )
        source_evidence[source_key] = _source_evidence(
            source_key,
            digest,
            source,
            linked_recorded_at,
        )
        if draw_link:
            draw_digest = _sha256(source_draw_raw[source_key])
            if draw_digest != _text(
                spec,
                "capacity_draws_sha256",
                f"sources.{source_key}",
            ):
                raise ValueError(
                    f"{source_key} capacity-draw SHA-256 does not match the link recipe"
                )
            expected_draw_count = _integer(
                spec,
                "expected_draw_count",
                f"sources.{source_key}",
            )
            if expected_draw_count != linked_samples:
                raise ValueError(
                    f"{source_key} expected draw count must match linked samples"
                )
            source_draw_digests[source_key] = draw_digest
            source_draw_columns[source_key] = _capacity_draw_columns(
                source_draw_raw[source_key],
                source_key=source_key,
                expected_count=expected_draw_count,
            )
        if (
            source_key == "datacenter_operational"
            and not source_metadata["synthetic"]
            and source.get("usable_as_operational_capacity") is not True
        ):
            raise ValueError(
                "an evidence-backed operational result must be marked usable before linking"
            )

    recipe_evidence_values = _list(
        _value(recipe, "evidence", "link_recipe"),
        "evidence",
    )
    recipe_evidence = [
        _evidence(value, f"evidence[{index}]")
        for index, value in enumerate(recipe_evidence_values)
    ]
    generated = json.loads(json.dumps(base))
    generated_metadata = generated["scenario"]
    generated_metadata.update(
        {
            "id": _text(metadata, "id", "scenario"),
            "name": _text(metadata, "name", "scenario"),
            "quarter": linked_quarter,
            "as_of_date": linked_as_of.isoformat(),
            "recorded_at": linked_recorded_at,
            "samples": _integer(metadata, "samples", "scenario"),
            "seed": _integer(metadata, "seed", "scenario"),
            "scope_notes": _text(metadata, "scope_notes", "scenario"),
            "notes": _text(metadata, "notes", "scenario"),
        }
    )
    generated["evidence"] = [
        *generated.get("evidence", []),
        *[
            {
                "id": item.id,
                "kind": item.kind.value,
                "title": item.title,
                "source_url": item.source_url,
                "publisher": item.publisher,
                "retrieved_at": item.retrieved_at,
                "published_at": item.published_at,
                "source_family": item.source_family,
                "license": item.license,
                "excerpt": item.excerpt,
                "content_hash": item.content_hash,
            }
            for item in recipe_evidence
        ],
        *source_evidence.values(),
    ]

    links = _list(_value(recipe, "links", "link_recipe"), "links")
    if not links:
        raise ValueError("link recipe requires at least one capacity link")
    constraints = list(generated["constraints"])
    available_constraint_ids = {item.get("id") for item in constraints}
    replaced_ids: set[str] = set()
    link_lineage = []
    constraint_capacity_draws: dict[str, tuple[float, ...]] = {}
    source_draw_orders: dict[str, list[int]] = {}
    if draw_link:
        for source_key, digest in source_draw_digests.items():
            order = list(range(linked_samples))
            draw_random = Random(
                f"{metadata['seed']}:{source_key}:{digest}:linked-permutation"
            )
            draw_random.shuffle(order)
            source_draw_orders[source_key] = order
    for index, value in enumerate(links):
        path = f"links[{index}]"
        link = _mapping(value, path)
        _only(
            link,
            {
                "id",
                "source",
                "metric",
                "resource_kind",
                "resource_name",
                "stage",
                "capacity_basis",
                "units_per_system",
                "platform_allocation",
                "replace_constraint_ids",
                "require_source_coverage",
                "require_source_coverage_selectors",
                "confirming_evidence",
                "falsifying_evidence",
                "notes",
            },
            path,
        )
        source_key = _text(link, "source", path)
        if source_key not in sources:
            raise ValueError(f"{path}.source must name a configured source")
        metric = _text(link, "metric", path)
        units = SOURCE_CONTRACTS[source_key][1]
        if metric not in LINKABLE_METRICS[source_key] or metric not in units:
            raise ValueError(f"{path}.metric is not supported for {source_key}")
        outputs = _mapping(
            _value(sources[source_key], "conversion_outputs", source_key),
            f"{source_key}.conversion_outputs",
        )
        distribution = _mapping(
            _value(outputs, metric, f"{source_key}.conversion_outputs"),
            f"{source_key}.conversion_outputs.{metric}",
        )
        evidence_id = source_evidence[source_key]["id"]
        confidence = source_confidences[source_key]
        unit = units[metric]
        capacity = _capacity_estimate(
            distribution=distribution,
            unit=unit,
            source_key=source_key,
            metric=metric,
            source=sources[source_key],
            digest=source_digests[source_key],
            evidence_id=evidence_id,
            confidence=confidence,
            confirming_evidence=_text(link, "confirming_evidence", path),
            falsifying_evidence=_text(link, "falsifying_evidence", path),
            draw_link=draw_link,
        )
        linked_constraint_id = _text(link, "id", path)
        if draw_link:
            columns = source_draw_columns[source_key]
            if metric not in columns:
                raise ValueError(
                    f"{source_key} capacity draws do not contain linked metric {metric}"
                )
            source_values = columns[metric]
            reproduced = summarize(source_values).as_dict()
            for field in ("p10", "p50", "p90", "mean", "minimum", "maximum"):
                expected = distribution.get(field)
                if isinstance(expected, bool) or not isinstance(
                    expected, (int, float)
                ):
                    raise ValueError(
                        f"{source_key}.{metric}.{field} must be numeric"
                    )
                if not isclose(
                    reproduced[field],
                    float(expected),
                    rel_tol=1e-12,
                    abs_tol=1e-8,
                ):
                    raise ValueError(
                        f"{source_key} capacity draws do not reproduce {metric}.{field}"
                    )
            constraint_capacity_draws[linked_constraint_id] = tuple(
                source_values[position]
                for position in source_draw_orders[source_key]
            )
        units_per_system = _number(link, "units_per_system", path)
        if units_per_system <= 0:
            raise ValueError(f"{path}.units_per_system must be positive")
        if source_key == "manufacturing":
            base_packages = _fixed_estimate_value(
                generated["platform"]["accelerator_packages_per_system"],
                "base_scenario.platform.accelerator_packages_per_system",
            )
            if metric == "complete_system_equivalents":
                source_accelerators = _fixed_estimate_value(
                    sources[source_key]["topology"]["accelerators_per_system"],
                    "manufacturing.topology.accelerators_per_system",
                )
                if source_accelerators != base_packages:
                    raise ValueError(
                        "manufacturing system topology does not match the base platform"
                    )
                if units_per_system != 1:
                    raise ValueError(
                        "complete_system_equivalents requires one source system per scenario system"
                    )
            elif units_per_system != base_packages:
                raise ValueError(
                    "finished accelerator packages must use the base platform package count"
                )
        elif source_key == "system_assembly":
            topology = _mapping(
                sources[source_key].get("topology"),
                "system_assembly.topology",
            )
            source_packages_per_rack = _number(
                topology,
                "accelerator_packages_per_rack",
                "system_assembly.topology",
            )
            base_packages = _fixed_estimate_value(
                generated["platform"]["accelerator_packages_per_system"],
                "base_scenario.platform.accelerator_packages_per_system",
            )
            base_racks = _fixed_estimate_value(
                generated["platform"]["racks_per_system"],
                "base_scenario.platform.racks_per_system",
            )
            if source_packages_per_rack * base_racks != base_packages:
                raise ValueError(
                    "system assembly topology does not match the base platform"
                )
            if units_per_system != base_racks:
                raise ValueError(
                    "complete racks must use the base platform rack count"
                )
        elif source_key == "datacenter_operational":
            base_racks = _fixed_estimate_value(
                generated["platform"]["racks_per_system"],
                "base_scenario.platform.racks_per_system",
            )
            if units_per_system != base_racks:
                raise ValueError(
                    "operational racks must use the base platform rack count"
                )
        unit_requirement = {
            **_identity_estimate(
                unit=unit,
                evidence_id=evidence_id,
                last_updated=_scenario_metadata(
                    sources[source_key],
                    source_key,
                )["as_of_date"],
                confidence=confidence,
                methodology=(
                    "Convert the frozen source metric into scenario-system equivalents "
                    f"using {units_per_system:g} {unit} per system."
                ),
            ),
            "low": units_per_system,
            "base": units_per_system,
            "high": units_per_system,
        }
        allocation_value = link.get("platform_allocation")
        if allocation_value is None:
            platform_allocation = _identity_estimate(
                unit="ratio",
                evidence_id=evidence_id,
                last_updated=_scenario_metadata(
                    sources[source_key],
                    source_key,
                )["as_of_date"],
                confidence=confidence,
                methodology=(
                    "The frozen source output is already scoped to this linked constraint."
                ),
            )
        else:
            allocation_estimate = _estimate(
                allocation_value,
                f"{path}.platform_allocation",
            )
            if allocation_estimate.unit != "ratio":
                raise ValueError(f"{path}.platform_allocation must use ratio")
            platform_allocation = _input_estimate(allocation_estimate)
        replace_values = _list(
            _value(link, "replace_constraint_ids", path),
            f"{path}.replace_constraint_ids",
        )
        if not all(isinstance(item, str) and item for item in replace_values):
            raise ValueError(f"{path}.replace_constraint_ids must contain IDs")
        replace_ids = tuple(replace_values)
        if len(set(replace_ids)) != len(replace_ids):
            raise ValueError(f"{path}.replace_constraint_ids must be unique")
        overlap = replaced_ids.intersection(replace_ids)
        if overlap:
            raise ValueError(f"constraints replaced more than once: {sorted(overlap)}")
        missing = set(replace_ids) - available_constraint_ids
        if missing:
            raise ValueError(f"replacement constraints are missing: {sorted(missing)}")
        required_coverage_values = _list(
            link.get("require_source_coverage", []),
            f"{path}.require_source_coverage",
        )
        if not all(
            isinstance(item, str) and item for item in required_coverage_values
        ):
            raise ValueError(f"{path}.require_source_coverage must contain names")
        required_coverage = tuple(required_coverage_values)
        if len(set(required_coverage)) != len(required_coverage):
            raise ValueError(f"{path}.require_source_coverage must be unique")
        if required_coverage:
            if source_key != "manufacturing":
                raise ValueError(
                    f"{path}.require_source_coverage is supported only for manufacturing"
                )
            coverage = _mapping(
                sources[source_key].get("coverage"),
                "manufacturing.coverage",
            )
            package_coverage = _mapping(
                coverage.get("package_assembly_starts"),
                "manufacturing.coverage.package_assembly_starts",
            )
            absorbed_values = _list(
                package_coverage.get("absorbed_resource_kinds"),
                "manufacturing.coverage.package_assembly_starts.absorbed_resource_kinds",
            )
            absorbed = {
                item for item in absorbed_values if isinstance(item, str) and item
            }
            uncovered = set(required_coverage) - absorbed
            if uncovered:
                raise ValueError(
                    "manufacturing source does not cover required resource kinds: "
                    f"{sorted(uncovered)}"
                )
            covered_constraint_ids = {
                item.get("id")
                for item in constraints
                if item.get("resource_kind") in required_coverage
            }
            omitted = covered_constraint_ids - set(replace_ids)
            if omitted:
                raise ValueError(
                    "covered constraints must be replaced to prevent double counting: "
                    f"{sorted(omitted)}"
                )
        selector_values = _list(
            link.get("require_source_coverage_selectors", []),
            f"{path}.require_source_coverage_selectors",
        )
        required_selectors = []
        for selector_index, value in enumerate(selector_values):
            selector_path = (
                f"{path}.require_source_coverage_selectors[{selector_index}]"
            )
            selector = _mapping(value, selector_path)
            _only(selector, {"stage", "resource_kind"}, selector_path)
            required_selectors.append(
                (
                    _text(selector, "stage", selector_path),
                    _text(selector, "resource_kind", selector_path),
                )
            )
        if len(set(required_selectors)) != len(required_selectors):
            raise ValueError(
                f"{path}.require_source_coverage_selectors must be unique"
            )
        if required_coverage and required_selectors:
            raise ValueError(
                f"{path} cannot mix resource-kind and stage-scoped coverage requirements"
            )
        if required_selectors:
            if source_key != "system_assembly":
                raise ValueError(
                    f"{path}.require_source_coverage_selectors is supported only for system_assembly"
                )
            coverage = _mapping(
                sources[source_key].get("coverage"),
                "system_assembly.coverage",
            )
            complete_rack_coverage = _mapping(
                coverage.get("complete_rack_output"),
                "system_assembly.coverage.complete_rack_output",
            )
            absorbed_values = _list(
                complete_rack_coverage.get("absorbed_constraints"),
                "system_assembly.coverage.complete_rack_output.absorbed_constraints",
            )
            absorbed_selectors = []
            for absorbed_index, value in enumerate(absorbed_values):
                absorbed_path = (
                    "system_assembly.coverage.complete_rack_output."
                    f"absorbed_constraints[{absorbed_index}]"
                )
                selector = _mapping(value, absorbed_path)
                _only(selector, {"stage", "resource_kind"}, absorbed_path)
                absorbed_selectors.append(
                    (
                        _text(selector, "stage", absorbed_path),
                        _text(selector, "resource_kind", absorbed_path),
                    )
                )
            if len(set(absorbed_selectors)) != len(absorbed_selectors):
                raise ValueError(
                    "system assembly source contains duplicate coverage selectors"
                )
            if set(required_selectors) != set(absorbed_selectors):
                raise ValueError(
                    "system assembly source coverage does not exactly match the required selectors"
                )
            covered_constraint_ids = {
                item.get("id")
                for item in constraints
                if (item.get("stage"), item.get("resource_kind"))
                in set(required_selectors)
            }
            omitted = covered_constraint_ids - set(replace_ids)
            if omitted:
                raise ValueError(
                    "covered constraints must be replaced to prevent double counting: "
                    f"{sorted(omitted)}"
                )
        linked_constraint = {
            "id": linked_constraint_id,
            "resource_kind": _text(link, "resource_kind", path),
            "resource_name": _text(link, "resource_name", path),
            "stage": _text(link, "stage", path),
            "capacity_basis": _text(link, "capacity_basis", path),
            "capacity": capacity,
            "effective_yield": _identity_estimate(
                unit="ratio",
                evidence_id=evidence_id,
                last_updated=_scenario_metadata(
                    sources[source_key],
                    source_key,
                )["as_of_date"],
                confidence=confidence,
                methodology="The frozen source output is already post-yield.",
            ),
            "platform_allocation": platform_allocation,
            "units_per_system": unit_requirement,
            "notes": _text(link, "notes", path),
        }
        if replace_ids:
            insertion = min(
                position
                for position, item in enumerate(constraints)
                if item.get("id") in replace_ids
            )
            constraints = [
                item for item in constraints if item.get("id") not in replace_ids
            ]
            constraints.insert(insertion, linked_constraint)
        else:
            constraints.append(linked_constraint)
        available_constraint_ids.difference_update(replace_ids)
        available_constraint_ids.add(linked_constraint["id"])
        replaced_ids.update(replace_ids)
        lineage_item = {
            "constraint_id": linked_constraint["id"],
            "source": source_key,
            "source_sha256": source_digests[source_key],
            "metric": metric,
            "source_unit": unit,
            "replace_constraint_ids": list(replace_ids),
            "distribution_mapping": (
                "source_capacity_draws_deterministic_cross_source_permutation"
                if draw_link
                else "source_p10_p50_p90_to_triangular_low_mode_high"
            ),
        }
        if required_coverage:
            lineage_item["required_source_coverage"] = list(required_coverage)
        if required_selectors:
            lineage_item["required_source_coverage_selectors"] = [
                {"stage": stage, "resource_kind": resource_kind}
                for stage, resource_kind in required_selectors
            ]
        link_lineage.append(lineage_item)

    if "system_assembly" in sources and not any(
        item.get("required_source_coverage_selectors") for item in link_lineage
    ):
        raise ValueError(
            "a system_assembly source requires one exact stage-scoped coverage handoff"
        )
    generated["constraints"] = constraints
    preserve_market_views = _boolean(
        recipe,
        "preserve_market_views",
        "link_recipe",
    )
    if not preserve_market_views:
        for key in (
            "allocations",
            "supplier_economics",
            "consensus",
            "opportunity_factors",
        ):
            generated[key] = []
    source_synthetic = any(
        bool(_scenario_metadata(source, key)["synthetic"])
        for key, source in sources.items()
    )
    recipe_synthetic = any(
        estimate.posture.value == "synthetic"
        for link in links
        if link.get("platform_allocation") is not None
        for estimate in (_estimate(link["platform_allocation"], "platform_allocation"),)
    )
    generated_metadata["synthetic"] = bool(
        base_metadata["synthetic"] or source_synthetic or recipe_synthetic
    )
    scenario_document = json.dumps(
        generated,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    scenario = scenario_from_dict(generated)
    lineage = {
        "format": (
            "ai-supply-chain-lineage.v2"
            if draw_link
            else "ai-supply-chain-lineage.v1"
        ),
        "scenario_id": scenario.id,
        "base_scenario": {
            "scenario_id": base_metadata["id"],
            "sha256": _sha256(base_raw),
        },
        "sources": {
            key: {
                "scenario_id": _scenario_metadata(source, key)["id"],
                "format": source["format"],
                "sha256": source_digests[key],
                "scope": source_specs[key]["scope"],
                "minimum_input_confidence": source_confidences[key],
                "synthetic": _scenario_metadata(source, key)["synthetic"],
                **(
                    {
                        "capacity_draws_sha256": source_draw_digests[key],
                        "capacity_draw_count": linked_samples,
                        "draw_permutation": (
                            "deterministic_independent_cross_source_permutation"
                        ),
                    }
                    if draw_link
                    else {}
                ),
            }
            for key, source in sources.items()
        },
        "links": link_lineage,
        "preserve_market_views": preserve_market_views,
        "scope_notes": scenario.scope_notes,
    }
    return LinkedChainCase(
        scenario=scenario,
        scenario_document=scenario_document,
        lineage=lineage,
        base_document=base_raw.decode("utf-8"),
        recipe_document=recipe_raw.decode("utf-8"),
        source_documents={
            key: raw.decode("utf-8") for key, raw in source_raw.items()
        },
        source_draw_documents={
            key: raw.decode("utf-8")
            for key, raw in source_draw_raw.items()
        },
        constraint_capacity_draws=constraint_capacity_draws,
    )
