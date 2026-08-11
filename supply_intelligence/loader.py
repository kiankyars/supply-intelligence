"""Strict JSON loading for auditable quarterly scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, TypeVar

from .models import (
    AllocationRule,
    CapacityBasis,
    ConsensusEstimate,
    Constraint,
    CustomerCategory,
    Estimate,
    EstimatePosture,
    Evidence,
    EvidenceKind,
    OpportunityFactors,
    Platform,
    QuarterlyScenario,
    ResourceKind,
    Stage,
    SupplierEconomics,
)


EnumType = TypeVar("EnumType")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    return value


def _value(data: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in data:
        raise ValueError(f"{path}.{key} is required")
    return data[key]


def _text(data: Mapping[str, Any], key: str, path: str, default: str | None = None) -> str:
    if key not in data and default is not None:
        return default
    value = _value(data, key, path)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string")
    return value


def _number(data: Mapping[str, Any], key: str, path: str) -> float:
    value = _value(data, key, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}.{key} must be a number")
    return float(value)


def _integer(data: Mapping[str, Any], key: str, path: str) -> int:
    value = _value(data, key, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}.{key} must be an integer")
    return value


def _boolean(data: Mapping[str, Any], key: str, path: str) -> bool:
    value = _value(data, key, path)
    if not isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be a boolean")
    return value


def _enum(enum_type: type[EnumType], value: Any, path: str) -> EnumType:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)  # type: ignore[attr-defined]
        raise ValueError(f"{path} must be one of: {allowed}") from exc


def _optional_text(data: Mapping[str, Any], key: str, path: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string or null")
    return value


def _estimate(value: Any, path: str) -> Estimate:
    data = _mapping(value, path)
    evidence_ids = _list(_value(data, "evidence_ids", path), f"{path}.evidence_ids")
    if not all(isinstance(item, str) for item in evidence_ids):
        raise ValueError(f"{path}.evidence_ids must contain strings")
    correlation_group = _optional_text(data, "correlation_group", path)
    return Estimate(
        low=_number(data, "low", path),
        base=_number(data, "base", path),
        high=_number(data, "high", path),
        unit=_text(data, "unit", path),
        posture=_enum(
            EstimatePosture, _value(data, "posture", path), f"{path}.posture"
        ),
        methodology=_text(data, "methodology", path),
        confidence=_number(data, "confidence", path),
        last_updated=_text(data, "last_updated", path),
        evidence_ids=tuple(evidence_ids),
        confirming_evidence=_text(data, "confirming_evidence", path),
        falsifying_evidence=_text(data, "falsifying_evidence", path),
        correlation_group=correlation_group,
    )


def _evidence(value: Any, path: str) -> Evidence:
    data = _mapping(value, path)
    return Evidence(
        id=_text(data, "id", path),
        kind=_enum(EvidenceKind, _value(data, "kind", path), f"{path}.kind"),
        title=_text(data, "title", path),
        source_url=_text(data, "source_url", path),
        publisher=_text(data, "publisher", path),
        retrieved_at=_text(data, "retrieved_at", path),
        published_at=_optional_text(data, "published_at", path),
        source_family=_optional_text(data, "source_family", path),
        license=_optional_text(data, "license", path),
        excerpt=_optional_text(data, "excerpt", path),
        content_hash=_optional_text(data, "content_hash", path),
    )


def _platform(value: Any, path: str) -> Platform:
    data = _mapping(value, path)
    return Platform(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        vendor=_text(data, "vendor", path),
        system_unit=_text(data, "system_unit", path),
        accelerator_packages_per_system=_estimate(
            _value(data, "accelerator_packages_per_system", path),
            f"{path}.accelerator_packages_per_system",
        ),
        servers_per_system=_estimate(
            _value(data, "servers_per_system", path), f"{path}.servers_per_system"
        ),
        racks_per_system=_estimate(
            _value(data, "racks_per_system", path), f"{path}.racks_per_system"
        ),
        notes=_text(data, "notes", path, ""),
    )


def _constraint(value: Any, path: str) -> Constraint:
    data = _mapping(value, path)
    return Constraint(
        id=_text(data, "id", path),
        resource_kind=_enum(
            ResourceKind, _value(data, "resource_kind", path), f"{path}.resource_kind"
        ),
        resource_name=_text(data, "resource_name", path),
        stage=_enum(Stage, _value(data, "stage", path), f"{path}.stage"),
        capacity_basis=_enum(
            CapacityBasis,
            _value(data, "capacity_basis", path),
            f"{path}.capacity_basis",
        ),
        capacity=_estimate(_value(data, "capacity", path), f"{path}.capacity"),
        effective_yield=_estimate(
            _value(data, "effective_yield", path), f"{path}.effective_yield"
        ),
        platform_allocation=_estimate(
            _value(data, "platform_allocation", path), f"{path}.platform_allocation"
        ),
        units_per_system=_estimate(
            _value(data, "units_per_system", path), f"{path}.units_per_system"
        ),
        notes=_text(data, "notes", path, ""),
    )


def _allocation(value: Any, path: str) -> AllocationRule:
    data = _mapping(value, path)
    return AllocationRule(
        id=_text(data, "id", path),
        customer=_text(data, "customer", path),
        category=_enum(
            CustomerCategory, _value(data, "category", path), f"{path}.category"
        ),
        share=_estimate(_value(data, "share", path), f"{path}.share"),
        demand_cap=_estimate(_value(data, "demand_cap", path), f"{path}.demand_cap"),
        notes=_text(data, "notes", path, ""),
    )


def _supplier_economics(value: Any, path: str) -> SupplierEconomics:
    data = _mapping(value, path)
    return SupplierEconomics(
        id=_text(data, "id", path),
        supplier=_text(data, "supplier", path),
        ticker=_text(data, "ticker", path),
        revenue_category=_text(data, "revenue_category", path),
        recognition_stage=_enum(
            Stage,
            _value(data, "recognition_stage", path),
            f"{path}.recognition_stage",
        ),
        units_per_system=_estimate(
            _value(data, "units_per_system", path), f"{path}.units_per_system"
        ),
        revenue_per_unit=_estimate(
            _value(data, "revenue_per_unit", path), f"{path}.revenue_per_unit"
        ),
        gross_margin=_estimate(
            _value(data, "gross_margin", path), f"{path}.gross_margin"
        ),
    )


def _consensus(value: Any, path: str) -> ConsensusEstimate:
    data = _mapping(value, path)
    return ConsensusEstimate(
        id=_text(data, "id", path),
        supplier=_text(data, "supplier", path),
        ticker=_text(data, "ticker", path),
        revenue=_estimate(_value(data, "revenue", path), f"{path}.revenue"),
    )


def _opportunity_factors(value: Any, path: str) -> OpportunityFactors:
    data = _mapping(value, path)
    return OpportunityFactors(
        id=_text(data, "id", path),
        supplier=_text(data, "supplier", path),
        ticker=_text(data, "ticker", path),
        confidence=_estimate(_value(data, "confidence", path), f"{path}.confidence"),
        liquidity=_estimate(_value(data, "liquidity", path), f"{path}.liquidity"),
        timing=_estimate(_value(data, "timing", path), f"{path}.timing"),
        catalyst_strength=_estimate(
            _value(data, "catalyst_strength", path), f"{path}.catalyst_strength"
        ),
        actionability=_text(data, "actionability", path),
        variant_wedge=_text(data, "variant_wedge", path),
        what_is_priced_in=_text(data, "what_is_priced_in", path),
        why_now=_text(data, "why_now", path),
        catalyst=_text(data, "catalyst", path),
        first_rejection=_text(data, "first_rejection", path),
        investable_if=_text(data, "investable_if", path),
        thesis_kill=_text(data, "thesis_kill", path),
        next_workflow=_text(data, "next_workflow", path),
    )


def scenario_from_dict(document: Mapping[str, Any]) -> QuarterlyScenario:
    if document.get("format") != "ai-supply-scenario.v1":
        raise ValueError("format must be ai-supply-scenario.v1")
    metadata = _mapping(_value(document, "scenario", "document"), "scenario")
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    constraint_values = _list(_value(document, "constraints", "document"), "constraints")
    allocation_values = _list(document.get("allocations", []), "allocations")
    economics_values = _list(document.get("supplier_economics", []), "supplier_economics")
    consensus_values = _list(document.get("consensus", []), "consensus")
    factor_values = _list(document.get("opportunity_factors", []), "opportunity_factors")
    return QuarterlyScenario(
        id=_text(metadata, "id", "scenario"),
        name=_text(metadata, "name", "scenario"),
        quarter=_text(metadata, "quarter", "scenario"),
        as_of_date=_text(metadata, "as_of_date", "scenario"),
        recorded_at=_text(metadata, "recorded_at", "scenario"),
        synthetic=_boolean(metadata, "synthetic", "scenario"),
        samples=_integer(metadata, "samples", "scenario"),
        seed=_integer(metadata, "seed", "scenario"),
        notes=_text(metadata, "notes", "scenario", ""),
        scope_notes=_text(metadata, "scope_notes", "scenario", ""),
        platform=_platform(_value(document, "platform", "document"), "platform"),
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
        constraints=tuple(
            _constraint(value, f"constraints[{index}]")
            for index, value in enumerate(constraint_values)
        ),
        allocations=tuple(
            _allocation(value, f"allocations[{index}]")
            for index, value in enumerate(allocation_values)
        ),
        supplier_economics=tuple(
            _supplier_economics(value, f"supplier_economics[{index}]")
            for index, value in enumerate(economics_values)
        ),
        consensus=tuple(
            _consensus(value, f"consensus[{index}]")
            for index, value in enumerate(consensus_values)
        ),
        opportunity_factors=tuple(
            _opportunity_factors(value, f"opportunity_factors[{index}]")
            for index, value in enumerate(factor_values)
        ),
    )


def load_scenario(path: str | Path) -> QuarterlyScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return scenario_from_dict(_mapping(document, "document"))
