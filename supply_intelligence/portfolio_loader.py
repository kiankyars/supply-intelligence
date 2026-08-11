"""Strict loading for multi-platform shared-resource scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .loader import (
    _boolean,
    _enum,
    _estimate,
    _evidence,
    _integer,
    _list,
    _mapping,
    _platform,
    _text,
    _value,
)
from .models import CapacityBasis, ResourceKind, Stage
from .portfolio_models import (
    PlatformDemand,
    PlatformRequirement,
    PortfolioScenario,
    SharedResourcePool,
)


def _platform_demand(value: Any, path: str) -> PlatformDemand:
    data = _mapping(value, path)
    return PlatformDemand(
        platform=_platform(_value(data, "platform", path), f"{path}.platform"),
        demand=_estimate(_value(data, "demand", path), f"{path}.demand"),
        priority_weight=_estimate(
            _value(data, "priority_weight", path), f"{path}.priority_weight"
        ),
    )


def _resource_pool(value: Any, path: str) -> SharedResourcePool:
    data = _mapping(value, path)
    return SharedResourcePool(
        id=_text(data, "id", path),
        resource_kind=_enum(
            ResourceKind,
            _value(data, "resource_kind", path),
            f"{path}.resource_kind",
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
        notes=_text(data, "notes", path, ""),
    )


def _requirement(value: Any, path: str) -> PlatformRequirement:
    data = _mapping(value, path)
    return PlatformRequirement(
        id=_text(data, "id", path),
        platform_id=_text(data, "platform_id", path),
        resource_pool_id=_text(data, "resource_pool_id", path),
        units_per_system=_estimate(
            _value(data, "units_per_system", path), f"{path}.units_per_system"
        ),
        notes=_text(data, "notes", path, ""),
    )


def portfolio_from_dict(document: Mapping[str, Any]) -> PortfolioScenario:
    if document.get("format") != "ai-supply-portfolio.v1":
        raise ValueError("format must be ai-supply-portfolio.v1")
    metadata = _mapping(_value(document, "scenario", "document"), "scenario")
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    platform_values = _list(_value(document, "platforms", "document"), "platforms")
    resource_values = _list(
        _value(document, "resource_pools", "document"), "resource_pools"
    )
    requirement_values = _list(
        _value(document, "requirements", "document"), "requirements"
    )
    return PortfolioScenario(
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
        platforms=tuple(
            _platform_demand(value, f"platforms[{index}]")
            for index, value in enumerate(platform_values)
        ),
        resource_pools=tuple(
            _resource_pool(value, f"resource_pools[{index}]")
            for index, value in enumerate(resource_values)
        ),
        requirements=tuple(
            _requirement(value, f"requirements[{index}]")
            for index, value in enumerate(requirement_values)
        ),
    )


def load_portfolio(path: str | Path) -> PortfolioScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return portfolio_from_dict(_mapping(document, "document"))
