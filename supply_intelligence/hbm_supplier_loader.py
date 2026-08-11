"""Strict JSON loading for supplier-resolved HBM scenarios."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .hbm_supplier_models import (
    HbmPlatformDemand,
    HbmSourceDocument,
    HbmSupplierFlow,
    HbmSupplierScenario,
)
from .loader import (
    _boolean,
    _estimate,
    _evidence,
    _integer,
    _list,
    _mapping,
    _text,
    _value,
)
from .manufacturing_models import WaferFlow


HBM_SUPPLIER_SCENARIO_FORMAT = "ai-supply-hbm-supplier-portfolio.v1"


def _only(data: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(data) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _wafer(value: Any, path: str) -> WaferFlow:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "wafer_starts",
            "wafer_diameter_mm",
            "edge_exclusion_mm",
            "die_width_mm",
            "die_height_mm",
            "scribe_width_mm",
            "notes",
        },
        path,
    )
    return WaferFlow(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        wafer_starts=_estimate(
            _value(data, "wafer_starts", path),
            f"{path}.wafer_starts",
        ),
        wafer_diameter_mm=_estimate(
            _value(data, "wafer_diameter_mm", path),
            f"{path}.wafer_diameter_mm",
        ),
        edge_exclusion_mm=_estimate(
            _value(data, "edge_exclusion_mm", path),
            f"{path}.edge_exclusion_mm",
        ),
        die_width_mm=_estimate(
            _value(data, "die_width_mm", path),
            f"{path}.die_width_mm",
        ),
        die_height_mm=_estimate(
            _value(data, "die_height_mm", path),
            f"{path}.die_height_mm",
        ),
        scribe_width_mm=_estimate(
            _value(data, "scribe_width_mm", path),
            f"{path}.scribe_width_mm",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _platform(value: Any, path: str) -> HbmPlatformDemand:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "customer",
            "hbm_generation",
            "memory_dies_per_stack",
            "stack_capacity_gb",
            "stacks_per_accelerator",
            "accelerator_package_demand",
            "notes",
        },
        path,
    )
    return HbmPlatformDemand(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        customer=_text(data, "customer", path),
        hbm_generation=_text(data, "hbm_generation", path),
        memory_dies_per_stack=_estimate(
            _value(data, "memory_dies_per_stack", path),
            f"{path}.memory_dies_per_stack",
        ),
        stack_capacity_gb=_estimate(
            _value(data, "stack_capacity_gb", path),
            f"{path}.stack_capacity_gb",
        ),
        stacks_per_accelerator=_estimate(
            _value(data, "stacks_per_accelerator", path),
            f"{path}.stacks_per_accelerator",
        ),
        accelerator_package_demand=_estimate(
            _value(data, "accelerator_package_demand", path),
            f"{path}.accelerator_package_demand",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _supplier(value: Any, path: str) -> HbmSupplierFlow:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "capacity_scope_id",
            "capacity_scope",
            "geography",
            "product",
            "process_node",
            "wafer_start_basis",
            "wafer",
            "known_good_die_yield",
            "stack_assembly_yield",
            "stack_final_test_yield",
            "platform_qualified_share",
            "customer_allocation_share",
            "notes",
        },
        path,
    )
    return HbmSupplierFlow(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        capacity_scope_id=_text(data, "capacity_scope_id", path),
        capacity_scope=_text(data, "capacity_scope", path),
        geography=_text(data, "geography", path),
        product=_text(data, "product", path),
        process_node=_text(data, "process_node", path),
        wafer_start_basis=_text(data, "wafer_start_basis", path),
        wafer=_wafer(_value(data, "wafer", path), f"{path}.wafer"),
        known_good_die_yield=_estimate(
            _value(data, "known_good_die_yield", path),
            f"{path}.known_good_die_yield",
        ),
        stack_assembly_yield=_estimate(
            _value(data, "stack_assembly_yield", path),
            f"{path}.stack_assembly_yield",
        ),
        stack_final_test_yield=_estimate(
            _value(data, "stack_final_test_yield", path),
            f"{path}.stack_final_test_yield",
        ),
        platform_qualified_share=_estimate(
            _value(data, "platform_qualified_share", path),
            f"{path}.platform_qualified_share",
        ),
        customer_allocation_share=_estimate(
            _value(data, "customer_allocation_share", path),
            f"{path}.customer_allocation_share",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _source_document(
    value: Any,
    path: str,
    *,
    source_root: Path | None,
) -> HbmSourceDocument:
    if source_root is None:
        raise ValueError("source_root is required when source_files are present")
    data = _mapping(value, path)
    _only(data, {"evidence_id", "path", "sha256"}, path)
    relative = Path(_text(data, "path", path))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{path}.path must be below source_root")
    root = source_root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{path}.path escapes source_root")
    raw = resolved.read_bytes()
    expected = _text(data, "sha256", path)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(
            f"{path} SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return HbmSourceDocument(
        evidence_id=_text(data, "evidence_id", path),
        path=relative.as_posix(),
        sha256=expected,
        raw=raw,
    )


def hbm_supplier_scenario_from_dict(
    document: Mapping[str, Any],
    *,
    source_root: str | Path | None = None,
) -> HbmSupplierScenario:
    if document.get("format") != HBM_SUPPLIER_SCENARIO_FORMAT:
        raise ValueError(f"format must be {HBM_SUPPLIER_SCENARIO_FORMAT}")
    _only(
        document,
        {
            "format",
            "scenario",
            "platform",
            "suppliers",
            "evidence",
            "source_files",
        },
        "document",
    )
    metadata = _mapping(_value(document, "scenario", "document"), "scenario")
    _only(
        metadata,
        {
            "id",
            "name",
            "quarter",
            "as_of_date",
            "recorded_at",
            "synthetic",
            "samples",
            "seed",
            "notes",
        },
        "scenario",
    )
    supplier_values = _list(_value(document, "suppliers", "document"), "suppliers")
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    source_values = _list(document.get("source_files", []), "source_files")
    root = Path(source_root).resolve() if source_root is not None else None
    return HbmSupplierScenario(
        id=_text(metadata, "id", "scenario"),
        name=_text(metadata, "name", "scenario"),
        quarter=_text(metadata, "quarter", "scenario"),
        as_of_date=_text(metadata, "as_of_date", "scenario"),
        recorded_at=_text(metadata, "recorded_at", "scenario"),
        synthetic=_boolean(metadata, "synthetic", "scenario"),
        samples=_integer(metadata, "samples", "scenario"),
        seed=_integer(metadata, "seed", "scenario"),
        notes=_text(metadata, "notes", "scenario", ""),
        platform=_platform(_value(document, "platform", "document"), "platform"),
        suppliers=tuple(
            _supplier(value, f"suppliers[{index}]")
            for index, value in enumerate(supplier_values)
        ),
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
        source_documents=tuple(
            _source_document(
                value,
                f"source_files[{index}]",
                source_root=root,
            )
            for index, value in enumerate(source_values)
        ),
    )


def load_hbm_supplier_scenario(
    path: str | Path,
    *,
    source_root: str | Path | None = None,
) -> HbmSupplierScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return hbm_supplier_scenario_from_dict(
        _mapping(document, "document"),
        source_root=source_root,
    )
