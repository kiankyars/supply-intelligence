"""Strict loading for wafer-to-package manufacturing scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

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
from .manufacturing_models import (
    HbmStackFlow,
    LogicDieFlow,
    ManufacturingReference,
    ManufacturingScenario,
    PackageAssemblyFlow,
    WaferFlow,
)


def _reference(value: Any, path: str) -> ManufacturingReference:
    data = _mapping(value, path)
    return ManufacturingReference(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        period=_text(data, "period", path),
        comparison_target=_text(data, "comparison_target", path),
        estimate=_estimate(_value(data, "estimate", path), f"{path}.estimate"),
        usable_as_product_capacity=_boolean(
            data,
            "usable_as_product_capacity",
            path,
        ),
        notes=_text(data, "notes", path),
    )


def _wafer(value: Any, path: str) -> WaferFlow:
    data = _mapping(value, path)
    return WaferFlow(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        wafer_starts=_estimate(_value(data, "wafer_starts", path), f"{path}.wafer_starts"),
        wafer_diameter_mm=_estimate(
            _value(data, "wafer_diameter_mm", path),
            f"{path}.wafer_diameter_mm",
        ),
        edge_exclusion_mm=_estimate(
            _value(data, "edge_exclusion_mm", path),
            f"{path}.edge_exclusion_mm",
        ),
        die_width_mm=_estimate(
            _value(data, "die_width_mm", path), f"{path}.die_width_mm"
        ),
        die_height_mm=_estimate(
            _value(data, "die_height_mm", path), f"{path}.die_height_mm"
        ),
        scribe_width_mm=_estimate(
            _value(data, "scribe_width_mm", path), f"{path}.scribe_width_mm"
        ),
        notes=_text(data, "notes", path, ""),
    )


def _logic(value: Any, path: str) -> LogicDieFlow:
    data = _mapping(value, path)
    return LogicDieFlow(
        wafer=_wafer(_value(data, "wafer", path), f"{path}.wafer"),
        defect_density_per_cm2=_estimate(
            _value(data, "defect_density_per_cm2", path),
            f"{path}.defect_density_per_cm2",
        ),
        clustering_alpha=_estimate(
            _value(data, "clustering_alpha", path),
            f"{path}.clustering_alpha",
        ),
        wafer_sort_yield=_estimate(
            _value(data, "wafer_sort_yield", path),
            f"{path}.wafer_sort_yield",
        ),
        performance_bin_share=_estimate(
            _value(data, "performance_bin_share", path),
            f"{path}.performance_bin_share",
        ),
    )


def _hbm(value: Any, path: str) -> HbmStackFlow:
    data = _mapping(value, path)
    return HbmStackFlow(
        wafer=_wafer(_value(data, "wafer", path), f"{path}.wafer"),
        known_good_die_yield=_estimate(
            _value(data, "known_good_die_yield", path),
            f"{path}.known_good_die_yield",
        ),
        memory_dies_per_stack=_estimate(
            _value(data, "memory_dies_per_stack", path),
            f"{path}.memory_dies_per_stack",
        ),
        stack_assembly_yield=_estimate(
            _value(data, "stack_assembly_yield", path),
            f"{path}.stack_assembly_yield",
        ),
        stack_final_test_yield=_estimate(
            _value(data, "stack_final_test_yield", path),
            f"{path}.stack_final_test_yield",
        ),
        stack_capacity_gb=_estimate(
            _value(data, "stack_capacity_gb", path),
            f"{path}.stack_capacity_gb",
        ),
        stacks_per_accelerator=_estimate(
            _value(data, "stacks_per_accelerator", path),
            f"{path}.stacks_per_accelerator",
        ),
    )


def _package(value: Any, path: str) -> PackageAssemblyFlow:
    data = _mapping(value, path)
    return PackageAssemblyFlow(
        assembly_starts=_estimate(
            _value(data, "assembly_starts", path),
            f"{path}.assembly_starts",
        ),
        assembly_yield=_estimate(
            _value(data, "assembly_yield", path),
            f"{path}.assembly_yield",
        ),
        logic_dies_per_accelerator=_estimate(
            _value(data, "logic_dies_per_accelerator", path),
            f"{path}.logic_dies_per_accelerator",
        ),
        accelerators_per_system=_estimate(
            _value(data, "accelerators_per_system", path),
            f"{path}.accelerators_per_system",
        ),
    )


def manufacturing_from_dict(document: Mapping[str, Any]) -> ManufacturingScenario:
    if document.get("format") != "ai-supply-manufacturing.v1":
        raise ValueError("format must be ai-supply-manufacturing.v1")
    metadata = _mapping(_value(document, "scenario", "document"), "scenario")
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    reference_values = _list(document.get("references", []), "references")
    return ManufacturingScenario(
        id=_text(metadata, "id", "scenario"),
        name=_text(metadata, "name", "scenario"),
        quarter=_text(metadata, "quarter", "scenario"),
        as_of_date=_text(metadata, "as_of_date", "scenario"),
        recorded_at=_text(metadata, "recorded_at", "scenario"),
        synthetic=_boolean(metadata, "synthetic", "scenario"),
        samples=_integer(metadata, "samples", "scenario"),
        seed=_integer(metadata, "seed", "scenario"),
        notes=_text(metadata, "notes", "scenario", ""),
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
        logic=_logic(_value(document, "logic", "document"), "logic"),
        hbm=_hbm(_value(document, "hbm", "document"), "hbm"),
        package=_package(_value(document, "package", "document"), "package"),
        references=tuple(
            _reference(value, f"references[{index}]")
            for index, value in enumerate(reference_values)
        ),
    )


def load_manufacturing(path: str | Path) -> ManufacturingScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return manufacturing_from_dict(_mapping(document, "document"))
