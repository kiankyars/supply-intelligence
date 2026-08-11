"""Strict JSON loading for supplier-resolved system assembly scenarios."""

from __future__ import annotations

import hashlib
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
from .system_assembly_models import (
    AssemblyComponentPool,
    AssemblyCoverage,
    AssemblyCoverageSelector,
    AssemblyPlatform,
    AssemblySourceDocument,
    OdmAssemblyFlow,
    SystemAssemblyScenario,
)


SYSTEM_ASSEMBLY_SCENARIO_FORMAT = "ai-supply-system-assembly.v1"


def _only(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    if unexpected := set(data) - allowed:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _platform(value: Any, path: str) -> AssemblyPlatform:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "customer",
            "accelerator_packages_per_compute_tray",
            "compute_trays_per_rack",
            "rack_demand",
            "notes",
        },
        path,
    )
    return AssemblyPlatform(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        customer=_text(data, "customer", path),
        accelerator_packages_per_compute_tray=_estimate(
            _value(data, "accelerator_packages_per_compute_tray", path),
            f"{path}.accelerator_packages_per_compute_tray",
        ),
        compute_trays_per_rack=_estimate(
            _value(data, "compute_trays_per_rack", path),
            f"{path}.compute_trays_per_rack",
        ),
        rack_demand=_estimate(
            _value(data, "rack_demand", path),
            f"{path}.rack_demand",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _odm(value: Any, path: str) -> OdmAssemblyFlow:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "geography",
            "tray_capacity_scope_id",
            "tray_capacity_scope",
            "tray_capacity_basis",
            "compute_tray_capacity",
            "compute_tray_effective_yield",
            "compute_tray_platform_qualified_share",
            "compute_tray_customer_allocation_share",
            "rack_capacity_scope_id",
            "rack_capacity_scope",
            "rack_capacity_basis",
            "rack_integration_capacity",
            "rack_integration_effective_yield",
            "rack_platform_qualified_share",
            "rack_customer_allocation_share",
            "notes",
        },
        path,
    )
    return OdmAssemblyFlow(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        geography=_text(data, "geography", path),
        tray_capacity_scope_id=_text(data, "tray_capacity_scope_id", path),
        tray_capacity_scope=_text(data, "tray_capacity_scope", path),
        tray_capacity_basis=_text(data, "tray_capacity_basis", path),
        compute_tray_capacity=_estimate(
            _value(data, "compute_tray_capacity", path),
            f"{path}.compute_tray_capacity",
        ),
        compute_tray_effective_yield=_estimate(
            _value(data, "compute_tray_effective_yield", path),
            f"{path}.compute_tray_effective_yield",
        ),
        compute_tray_platform_qualified_share=_estimate(
            _value(data, "compute_tray_platform_qualified_share", path),
            f"{path}.compute_tray_platform_qualified_share",
        ),
        compute_tray_customer_allocation_share=_estimate(
            _value(data, "compute_tray_customer_allocation_share", path),
            f"{path}.compute_tray_customer_allocation_share",
        ),
        rack_capacity_scope_id=_text(data, "rack_capacity_scope_id", path),
        rack_capacity_scope=_text(data, "rack_capacity_scope", path),
        rack_capacity_basis=_text(data, "rack_capacity_basis", path),
        rack_integration_capacity=_estimate(
            _value(data, "rack_integration_capacity", path),
            f"{path}.rack_integration_capacity",
        ),
        rack_integration_effective_yield=_estimate(
            _value(data, "rack_integration_effective_yield", path),
            f"{path}.rack_integration_effective_yield",
        ),
        rack_platform_qualified_share=_estimate(
            _value(data, "rack_platform_qualified_share", path),
            f"{path}.rack_platform_qualified_share",
        ),
        rack_customer_allocation_share=_estimate(
            _value(data, "rack_customer_allocation_share", path),
            f"{path}.rack_customer_allocation_share",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _component(value: Any, path: str) -> AssemblyComponentPool:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "stage",
            "resource_kind",
            "capacity_scope_id",
            "capacity_scope",
            "capacity_basis",
            "capacity",
            "effective_yield",
            "platform_qualified_share",
            "customer_allocation_share",
            "units_per_rack",
            "notes",
        },
        path,
    )
    return AssemblyComponentPool(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        stage=_text(data, "stage", path),
        resource_kind=_text(data, "resource_kind", path),
        capacity_scope_id=_text(data, "capacity_scope_id", path),
        capacity_scope=_text(data, "capacity_scope", path),
        capacity_basis=_text(data, "capacity_basis", path),
        capacity=_estimate(_value(data, "capacity", path), f"{path}.capacity"),
        effective_yield=_estimate(
            _value(data, "effective_yield", path),
            f"{path}.effective_yield",
        ),
        platform_qualified_share=_estimate(
            _value(data, "platform_qualified_share", path),
            f"{path}.platform_qualified_share",
        ),
        customer_allocation_share=_estimate(
            _value(data, "customer_allocation_share", path),
            f"{path}.customer_allocation_share",
        ),
        units_per_rack=_estimate(
            _value(data, "units_per_rack", path),
            f"{path}.units_per_rack",
        ),
        notes=_text(data, "notes", path, ""),
    )


def _coverage(value: Any, path: str) -> AssemblyCoverage:
    data = _mapping(value, path)
    _only(
        data,
        {
            "output_basis",
            "absorbed_constraints",
            "posture",
            "methodology",
            "confirming_evidence",
            "falsifying_evidence",
            "notes",
        },
        path,
    )
    selectors = _list(
        _value(data, "absorbed_constraints", path),
        f"{path}.absorbed_constraints",
    )
    parsed = []
    for index, value in enumerate(selectors):
        selector_path = f"{path}.absorbed_constraints[{index}]"
        selector = _mapping(value, selector_path)
        _only(selector, {"stage", "resource_kind"}, selector_path)
        parsed.append(
            AssemblyCoverageSelector(
                stage=_text(selector, "stage", selector_path),
                resource_kind=_text(selector, "resource_kind", selector_path),
            )
        )
    return AssemblyCoverage(
        output_basis=_text(data, "output_basis", path),
        absorbed_constraints=tuple(parsed),
        posture=_text(data, "posture", path),
        methodology=_text(data, "methodology", path),
        confirming_evidence=_text(data, "confirming_evidence", path),
        falsifying_evidence=_text(data, "falsifying_evidence", path),
        notes=_text(data, "notes", path, ""),
    )


def _source_document(
    value: Any,
    path: str,
    *,
    source_root: Path | None,
) -> AssemblySourceDocument:
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
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"{path} SHA-256 mismatch")
    return AssemblySourceDocument(
        evidence_id=_text(data, "evidence_id", path),
        path=relative.as_posix(),
        sha256=expected,
        raw=raw,
    )


def system_assembly_scenario_from_dict(
    document: Mapping[str, Any],
    *,
    source_root: str | Path | None = None,
) -> SystemAssemblyScenario:
    if document.get("format") != SYSTEM_ASSEMBLY_SCENARIO_FORMAT:
        raise ValueError(f"format must be {SYSTEM_ASSEMBLY_SCENARIO_FORMAT}")
    _only(
        document,
        {
            "format",
            "scenario",
            "platform",
            "odms",
            "components",
            "coverage",
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
    odm_values = _list(_value(document, "odms", "document"), "odms")
    component_values = _list(
        _value(document, "components", "document"),
        "components",
    )
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    source_values = _list(document.get("source_files", []), "source_files")
    root = Path(source_root).resolve() if source_root is not None else None
    return SystemAssemblyScenario(
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
        odms=tuple(_odm(value, f"odms[{index}]") for index, value in enumerate(odm_values)),
        components=tuple(
            _component(value, f"components[{index}]")
            for index, value in enumerate(component_values)
        ),
        coverage=_coverage(_value(document, "coverage", "document"), "coverage"),
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
        source_documents=tuple(
            _source_document(value, f"source_files[{index}]", source_root=root)
            for index, value in enumerate(source_values)
        ),
    )


def load_system_assembly_scenario(
    path: str | Path,
    *,
    source_root: str | Path | None = None,
) -> SystemAssemblyScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return system_assembly_scenario_from_dict(
        _mapping(document, "document"),
        source_root=source_root,
    )
