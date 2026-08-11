"""Canonical scenario inputs and auditable estimate contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from math import isfinite
from typing import Iterable


QUARTER_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")


class EvidenceKind(StrEnum):
    COMPANY_DISCLOSURE = "company_disclosure"
    COMPANY_TECHNICAL_DOCUMENT = "company_technical_document"
    GOVERNMENT_RECORD = "government_record"
    UTILITY_RECORD = "utility_record"
    CUSTOMS_RECORD = "customs_record"
    SATELLITE_IMAGERY = "satellite_imagery"
    JOB_POSTING = "job_posting"
    DISTRIBUTOR_OBSERVATION = "distributor_observation"
    MARKET_DATA = "market_data"
    THIRD_PARTY_RESEARCH = "third_party_research"
    SYNTHETIC = "synthetic"
    OTHER = "other"


class EstimatePosture(StrEnum):
    REPORTED = "reported"
    DERIVED = "derived"
    MODELED = "modeled"
    SYNTHETIC = "synthetic"


class Stage(StrEnum):
    ACCELERATOR_PACKAGE = "accelerator_package"
    SERVER_ASSEMBLY = "server_assembly"
    RACK_INTEGRATION = "rack_integration"
    SHIPPED = "shipped"
    INSTALLED = "installed"
    OPERATIONAL = "operational"


STAGE_ORDER = {
    Stage.ACCELERATOR_PACKAGE: 0,
    Stage.SERVER_ASSEMBLY: 1,
    Stage.RACK_INTEGRATION: 2,
    Stage.SHIPPED: 3,
    Stage.INSTALLED: 4,
    Stage.OPERATIONAL: 5,
}


class ResourceKind(StrEnum):
    LEADING_EDGE_WAFER = "leading_edge_wafer"
    ACCELERATOR_DIE = "accelerator_die"
    ACCELERATOR_PACKAGE = "accelerator_package"
    HBM_WAFER = "hbm_wafer"
    HBM_KNOWN_GOOD_DIE = "hbm_known_good_die"
    HBM_STACK = "hbm_stack"
    HBM_CAPACITY = "hbm_capacity"
    ADVANCED_PACKAGING = "advanced_packaging"
    SILICON_INTERPOSER = "silicon_interposer"
    ABF_SUBSTRATE = "abf_substrate"
    THERMAL_MATERIAL = "thermal_material"
    CONNECTOR = "connector"
    POWER_DELIVERY = "power_delivery"
    RETIMER = "retimer"
    OPTICAL_TRANSCEIVER = "optical_transceiver"
    NETWORK_SWITCH = "network_switch"
    CABLE = "cable"
    COOLING = "cooling"
    SERVER_ASSEMBLY = "server_assembly"
    RACK_INTEGRATION = "rack_integration"
    QUALIFICATION = "qualification"
    LOGISTICS = "logistics"
    DATACENTER_POWER = "datacenter_power"
    DATACENTER_COMMISSIONING = "datacenter_commissioning"
    OTHER = "other"


class CapacityBasis(StrEnum):
    NAMEPLATE_INPUT = "nameplate_input"
    TOOL_THROUGHPUT = "tool_throughput"
    KNOWN_GOOD_OUTPUT = "known_good_output"
    SELLABLE_OUTPUT = "sellable_output"
    ALLOCATED_OUTPUT = "allocated_output"
    INSTALLED_RESOURCE = "installed_resource"
    ENERGIZED_RESOURCE = "energized_resource"


class CustomerCategory(StrEnum):
    HYPERSCALER = "hyperscaler"
    SOVEREIGN = "sovereign"
    MODEL_LAB = "model_lab"
    ENTERPRISE = "enterprise"
    CHINA = "china"
    NEOCLOUD = "neocloud"
    OTHER = "other"


def _required(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")


def _iso_date(value: str, field_name: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _iso_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    kind: EvidenceKind
    title: str
    source_url: str
    publisher: str
    retrieved_at: str
    published_at: str | None = None
    source_family: str | None = None
    license: str | None = None
    excerpt: str | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "title", "source_url", "publisher", "retrieved_at"):
            _required(getattr(self, field_name), field_name)
        _iso_timestamp(self.retrieved_at, "retrieved_at")
        if self.published_at:
            try:
                datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("published_at must be an ISO date or timestamp") from exc


@dataclass(frozen=True, slots=True)
class Estimate:
    low: float
    base: float
    high: float
    unit: str
    posture: EstimatePosture
    methodology: str
    confidence: float
    last_updated: str
    evidence_ids: tuple[str, ...]
    confirming_evidence: str
    falsifying_evidence: str
    correlation_group: str | None = None

    def __post_init__(self) -> None:
        if not all(isfinite(value) for value in (self.low, self.base, self.high)):
            raise ValueError("estimate bounds must be finite")
        if self.low < 0 or not self.low <= self.base <= self.high:
            raise ValueError("estimate must satisfy 0 <= low <= base <= high")
        for field_name in (
            "unit",
            "methodology",
            "last_updated",
            "confirming_evidence",
            "falsifying_evidence",
        ):
            _required(getattr(self, field_name), field_name)
        if not 0 <= self.confidence <= 1:
            raise ValueError("estimate confidence must be between 0 and 1")
        _iso_date(self.last_updated, "last_updated")
        if not self.evidence_ids:
            raise ValueError("estimate requires at least one evidence id")
        if any(not item.strip() for item in self.evidence_ids):
            raise ValueError("estimate evidence ids cannot be blank")
        if self.unit == "ratio" and self.high > 1:
            raise ValueError("ratio estimates cannot exceed 1")


@dataclass(frozen=True, slots=True)
class Platform:
    id: str
    name: str
    vendor: str
    system_unit: str
    accelerator_packages_per_system: Estimate
    servers_per_system: Estimate
    racks_per_system: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "vendor", "system_unit"):
            _required(getattr(self, field_name), field_name)
        for estimate, expected_unit in (
            (self.accelerator_packages_per_system, "package/system"),
            (self.servers_per_system, "server/system"),
            (self.racks_per_system, "rack/system"),
        ):
            if estimate.unit != expected_unit:
                raise ValueError(f"platform estimate must use {expected_unit}")


@dataclass(frozen=True, slots=True)
class Constraint:
    id: str
    resource_kind: ResourceKind
    resource_name: str
    stage: Stage
    capacity_basis: CapacityBasis
    capacity: Estimate
    effective_yield: Estimate
    platform_allocation: Estimate
    units_per_system: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "resource_name"):
            _required(getattr(self, field_name), field_name)
        if self.capacity.unit != self.units_per_system.unit:
            raise ValueError("constraint capacity and units_per_system must share a unit")
        if self.effective_yield.unit != "ratio":
            raise ValueError("effective_yield must use ratio units")
        if self.platform_allocation.unit != "ratio":
            raise ValueError("platform_allocation must use ratio units")
        if self.units_per_system.low <= 0:
            raise ValueError("units_per_system must be greater than zero")


@dataclass(frozen=True, slots=True)
class AllocationRule:
    id: str
    customer: str
    category: CustomerCategory
    share: Estimate
    demand_cap: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "customer"):
            _required(getattr(self, field_name), field_name)
        if self.share.unit != "ratio":
            raise ValueError("allocation share must use ratio units")
        if self.demand_cap.unit != "system":
            raise ValueError("allocation demand_cap must use system units")


@dataclass(frozen=True, slots=True)
class SupplierEconomics:
    id: str
    supplier: str
    ticker: str
    revenue_category: str
    recognition_stage: Stage
    units_per_system: Estimate
    revenue_per_unit: Estimate
    gross_margin: Estimate

    def __post_init__(self) -> None:
        for field_name in ("id", "supplier", "ticker", "revenue_category"):
            _required(getattr(self, field_name), field_name)
        if self.revenue_per_unit.unit != "USD/unit":
            raise ValueError("revenue_per_unit must use USD/unit")
        if self.gross_margin.unit != "ratio":
            raise ValueError("gross_margin must use ratio units")


@dataclass(frozen=True, slots=True)
class ConsensusEstimate:
    id: str
    supplier: str
    ticker: str
    revenue: Estimate

    def __post_init__(self) -> None:
        for field_name in ("id", "supplier", "ticker"):
            _required(getattr(self, field_name), field_name)
        if self.revenue.unit != "USD":
            raise ValueError("consensus revenue must use USD")


@dataclass(frozen=True, slots=True)
class OpportunityFactors:
    id: str
    supplier: str
    ticker: str
    confidence: Estimate
    liquidity: Estimate
    timing: Estimate
    catalyst_strength: Estimate
    actionability: str
    variant_wedge: str
    what_is_priced_in: str
    why_now: str
    catalyst: str
    first_rejection: str
    investable_if: str
    thesis_kill: str
    next_workflow: str

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "supplier",
            "ticker",
            "actionability",
            "variant_wedge",
            "what_is_priced_in",
            "why_now",
            "catalyst",
            "first_rejection",
            "investable_if",
            "thesis_kill",
            "next_workflow",
        ):
            _required(getattr(self, field_name), field_name)
        for estimate in (
            self.confidence,
            self.liquidity,
            self.timing,
            self.catalyst_strength,
        ):
            if estimate.unit != "ratio":
                raise ValueError("opportunity factors must use ratio units")


@dataclass(frozen=True, slots=True)
class QuarterlyScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    platform: Platform
    evidence: tuple[Evidence, ...]
    constraints: tuple[Constraint, ...]
    allocations: tuple[AllocationRule, ...] = field(default_factory=tuple)
    supplier_economics: tuple[SupplierEconomics, ...] = field(default_factory=tuple)
    consensus: tuple[ConsensusEstimate, ...] = field(default_factory=tuple)
    opportunity_factors: tuple[OpportunityFactors, ...] = field(default_factory=tuple)
    notes: str = ""
    scope_notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "quarter", "as_of_date", "recorded_at"):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.quarter):
            raise ValueError("quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        if self.samples < 100:
            raise ValueError("samples must be at least 100")
        if not self.constraints:
            raise ValueError("scenario requires at least one constraint")
        if not any(item.stage is Stage.ACCELERATOR_PACKAGE for item in self.constraints):
            raise ValueError("scenario requires an accelerator_package constraint")
        self._validate_unique_ids()
        self._validate_evidence_references()
        self._validate_tickers()

    def _validate_unique_ids(self) -> None:
        collections: tuple[tuple[str, Iterable[object]], ...] = (
            ("evidence", self.evidence),
            ("constraint", self.constraints),
            ("allocation", self.allocations),
            ("supplier economics", self.supplier_economics),
            ("consensus", self.consensus),
            ("opportunity factors", self.opportunity_factors),
        )
        for label, items in collections:
            ids = [getattr(item, "id") for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {label} id")

    def _validate_evidence_references(self) -> None:
        available = {item.id for item in self.evidence}
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available
            if missing:
                raise ValueError(f"estimate references missing evidence: {sorted(missing)}")

    def _validate_tickers(self) -> None:
        economics = {(item.supplier, item.ticker) for item in self.supplier_economics}
        for item in (*self.consensus, *self.opportunity_factors):
            if (item.supplier, item.ticker) not in economics:
                raise ValueError(
                    f"{item.id} references supplier without economics: {item.supplier} {item.ticker}"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.platform.accelerator_packages_per_system
        yield self.platform.servers_per_system
        yield self.platform.racks_per_system
        for constraint in self.constraints:
            yield constraint.capacity
            yield constraint.effective_yield
            yield constraint.platform_allocation
            yield constraint.units_per_system
        for allocation in self.allocations:
            yield allocation.share
            yield allocation.demand_cap
        for economics in self.supplier_economics:
            yield economics.units_per_system
            yield economics.revenue_per_unit
            yield economics.gross_margin
        for consensus in self.consensus:
            yield consensus.revenue
        for factors in self.opportunity_factors:
            yield factors.confidence
            yield factors.liquidity
            yield factors.timing
            yield factors.catalyst_strength
