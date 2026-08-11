"""Shared-resource scenario inputs for multiple accelerator platforms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .models import (
    CapacityBasis,
    Estimate,
    Evidence,
    Platform,
    QUARTER_PATTERN,
    ResourceKind,
    Stage,
    _iso_date,
    _iso_timestamp,
    _required,
)


@dataclass(frozen=True, slots=True)
class PlatformDemand:
    platform: Platform
    demand: Estimate
    priority_weight: Estimate

    def __post_init__(self) -> None:
        if self.demand.unit != "system":
            raise ValueError("platform demand must use system units")
        if self.priority_weight.unit != "weight":
            raise ValueError("platform priority_weight must use weight units")
        if self.priority_weight.base <= 0:
            raise ValueError("platform priority_weight base must be greater than zero")


@dataclass(frozen=True, slots=True)
class SharedResourcePool:
    id: str
    resource_kind: ResourceKind
    resource_name: str
    stage: Stage
    capacity_basis: CapacityBasis
    capacity: Estimate
    effective_yield: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "resource_name"):
            _required(getattr(self, field_name), field_name)
        if self.effective_yield.unit != "ratio":
            raise ValueError("resource effective_yield must use ratio units")


@dataclass(frozen=True, slots=True)
class PlatformRequirement:
    id: str
    platform_id: str
    resource_pool_id: str
    units_per_system: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "platform_id", "resource_pool_id"):
            _required(getattr(self, field_name), field_name)
        if self.units_per_system.low <= 0:
            raise ValueError("portfolio units_per_system must be greater than zero")


@dataclass(frozen=True, slots=True)
class PortfolioScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    evidence: tuple[Evidence, ...]
    platforms: tuple[PlatformDemand, ...]
    resource_pools: tuple[SharedResourcePool, ...]
    requirements: tuple[PlatformRequirement, ...]
    notes: str = ""
    allocation_policy: str = field(default="weighted_progressive_filling", init=False)

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "quarter", "as_of_date", "recorded_at"):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.quarter):
            raise ValueError("quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        if self.samples < 100:
            raise ValueError("samples must be at least 100")
        if len(self.platforms) < 2:
            raise ValueError("portfolio scenario requires at least two platforms")
        if not self.resource_pools:
            raise ValueError("portfolio scenario requires resource pools")
        if not self.requirements:
            raise ValueError("portfolio scenario requires platform requirements")
        self._validate_unique_ids()
        self._validate_relationships()
        self._validate_evidence_references()

    def _validate_unique_ids(self) -> None:
        collections = (
            ("evidence", [item.id for item in self.evidence]),
            ("platform", [item.platform.id for item in self.platforms]),
            ("resource pool", [item.id for item in self.resource_pools]),
            ("requirement", [item.id for item in self.requirements]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} id")
        pairs = [
            (item.platform_id, item.resource_pool_id) for item in self.requirements
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate platform and resource-pool requirement")

    def _validate_relationships(self) -> None:
        platform_ids = {item.platform.id for item in self.platforms}
        resources = {item.id: item for item in self.resource_pools}
        resource_ids = set(resources)
        for requirement in self.requirements:
            if requirement.platform_id not in platform_ids:
                raise ValueError(
                    f"requirement references missing platform: {requirement.platform_id}"
                )
            if requirement.resource_pool_id not in resource_ids:
                raise ValueError(
                    f"requirement references missing resource pool: {requirement.resource_pool_id}"
                )
            resource = resources[requirement.resource_pool_id]
            if requirement.units_per_system.unit != resource.capacity.unit:
                raise ValueError(
                    f"requirement {requirement.id} unit must match resource capacity unit"
                )
        referenced_resources = {item.resource_pool_id for item in self.requirements}
        missing_requirements = resource_ids - referenced_resources
        if missing_requirements:
            raise ValueError(
                f"resource pools have no platform requirements: {sorted(missing_requirements)}"
            )
        package_resources = {
            item.id for item in self.resource_pools if item.stage is Stage.ACCELERATOR_PACKAGE
        }
        for platform_id in platform_ids:
            if not any(
                item.platform_id == platform_id
                and item.resource_pool_id in package_resources
                for item in self.requirements
            ):
                raise ValueError(
                    f"platform {platform_id} requires an accelerator_package resource"
                )

    def _validate_evidence_references(self) -> None:
        available = {item.id for item in self.evidence}
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available
            if missing:
                raise ValueError(
                    f"portfolio estimate references missing evidence: {sorted(missing)}"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        for platform in self.platforms:
            yield platform.platform.accelerator_packages_per_system
            yield platform.platform.servers_per_system
            yield platform.platform.racks_per_system
            yield platform.demand
            yield platform.priority_weight
        for resource in self.resource_pools:
            yield resource.capacity
            yield resource.effective_yield
        for requirement in self.requirements:
            yield requirement.units_per_system
