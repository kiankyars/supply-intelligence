"""Supplier-resolved server and rack assembly capacity contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from .models import (
    Evidence,
    EvidenceKind,
    Estimate,
    EstimatePosture,
    QUARTER_PATTERN,
    _iso_date,
    _iso_timestamp,
    _required,
)


CAPACITY_BASES = {"nameplate_input", "sellable_output", "platform_allocated"}
ASSEMBLY_STAGES = {"server_assembly", "rack_integration"}
COMPLETE_RACK_OUTPUT_BASIS = "component_cleared_complete_racks"


def _unit(estimate: Estimate, expected: str, field_name: str) -> None:
    if estimate.unit != expected:
        raise ValueError(f"{field_name} must use {expected}")


def _positive(estimate: Estimate, field_name: str) -> None:
    if estimate.low <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _fixed_positive_integer(
    estimate: Estimate,
    expected_unit: str,
    field_name: str,
) -> None:
    _unit(estimate, expected_unit, field_name)
    _positive(estimate, field_name)
    if not (
        estimate.low == estimate.base == estimate.high
        and float(estimate.base).is_integer()
    ):
        raise ValueError(f"{field_name} must be a fixed positive integer")


def _fixed_one(estimate: Estimate, field_name: str) -> None:
    if not estimate.low == estimate.base == estimate.high == 1:
        raise ValueError(f"{field_name} must be fixed at one")


def _capacity_semantics(
    *,
    basis: str,
    effective_yield: Estimate,
    platform_qualified_share: Estimate,
    customer_allocation_share: Estimate,
    path: str,
) -> None:
    if basis not in CAPACITY_BASES:
        allowed = ", ".join(sorted(CAPACITY_BASES))
        raise ValueError(f"{path}.capacity_basis must be one of: {allowed}")
    for name, estimate in (
        ("effective_yield", effective_yield),
        ("platform_qualified_share", platform_qualified_share),
        ("customer_allocation_share", customer_allocation_share),
    ):
        _unit(estimate, "ratio", f"{path}.{name}")
    if basis in {"sellable_output", "platform_allocated"}:
        _fixed_one(effective_yield, f"{path}.effective_yield")
    if basis == "platform_allocated":
        _fixed_one(
            platform_qualified_share,
            f"{path}.platform_qualified_share",
        )
        _fixed_one(
            customer_allocation_share,
            f"{path}.customer_allocation_share",
        )


def _published_timestamp(value: str) -> datetime:
    if "T" not in value:
        return datetime.combine(
            date.fromisoformat(value),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class AssemblySourceDocument:
    evidence_id: str
    path: str
    sha256: str
    raw: bytes

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "path", "sha256"):
            _required(getattr(self, field_name), field_name)
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("assembly source sha256 must be a lowercase digest")
        if hashlib.sha256(self.raw).hexdigest() != self.sha256:
            raise ValueError("assembly source bytes do not match sha256")
        try:
            self.raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("assembly source documents must be UTF-8 text") from exc


@dataclass(frozen=True, slots=True)
class AssemblyPlatform:
    id: str
    name: str
    customer: str
    accelerator_packages_per_compute_tray: Estimate
    compute_trays_per_rack: Estimate
    rack_demand: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "customer"):
            _required(getattr(self, field_name), field_name)
        _fixed_positive_integer(
            self.accelerator_packages_per_compute_tray,
            "package/tray",
            "accelerator_packages_per_compute_tray",
        )
        _fixed_positive_integer(
            self.compute_trays_per_rack,
            "tray/rack",
            "compute_trays_per_rack",
        )
        _unit(self.rack_demand, "rack", "rack_demand")
        _positive(self.rack_demand, "rack_demand")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.accelerator_packages_per_compute_tray
        yield self.compute_trays_per_rack
        yield self.rack_demand


@dataclass(frozen=True, slots=True)
class OdmAssemblyFlow:
    id: str
    name: str
    geography: str
    tray_capacity_scope_id: str
    tray_capacity_scope: str
    tray_capacity_basis: str
    compute_tray_capacity: Estimate
    compute_tray_effective_yield: Estimate
    compute_tray_platform_qualified_share: Estimate
    compute_tray_customer_allocation_share: Estimate
    rack_capacity_scope_id: str
    rack_capacity_scope: str
    rack_capacity_basis: str
    rack_integration_capacity: Estimate
    rack_integration_effective_yield: Estimate
    rack_platform_qualified_share: Estimate
    rack_customer_allocation_share: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "geography",
            "tray_capacity_scope_id",
            "tray_capacity_scope",
            "rack_capacity_scope_id",
            "rack_capacity_scope",
        ):
            _required(getattr(self, field_name), field_name)
        _unit(self.compute_tray_capacity, "tray", "compute_tray_capacity")
        _positive(self.compute_tray_capacity, "compute_tray_capacity")
        _capacity_semantics(
            basis=self.tray_capacity_basis,
            effective_yield=self.compute_tray_effective_yield,
            platform_qualified_share=self.compute_tray_platform_qualified_share,
            customer_allocation_share=self.compute_tray_customer_allocation_share,
            path=f"odm.{self.id}.compute_tray",
        )
        _unit(self.rack_integration_capacity, "rack", "rack_integration_capacity")
        _positive(self.rack_integration_capacity, "rack_integration_capacity")
        _capacity_semantics(
            basis=self.rack_capacity_basis,
            effective_yield=self.rack_integration_effective_yield,
            platform_qualified_share=self.rack_platform_qualified_share,
            customer_allocation_share=self.rack_customer_allocation_share,
            path=f"odm.{self.id}.rack_integration",
        )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.compute_tray_capacity
        yield self.compute_tray_effective_yield
        yield self.compute_tray_platform_qualified_share
        yield self.compute_tray_customer_allocation_share
        yield self.rack_integration_capacity
        yield self.rack_integration_effective_yield
        yield self.rack_platform_qualified_share
        yield self.rack_customer_allocation_share


@dataclass(frozen=True, slots=True)
class AssemblyComponentPool:
    id: str
    name: str
    stage: str
    resource_kind: str
    capacity_scope_id: str
    capacity_scope: str
    capacity_basis: str
    capacity: Estimate
    effective_yield: Estimate
    platform_qualified_share: Estimate
    customer_allocation_share: Estimate
    units_per_rack: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "resource_kind",
            "capacity_scope_id",
            "capacity_scope",
        ):
            _required(getattr(self, field_name), field_name)
        if self.stage not in ASSEMBLY_STAGES:
            raise ValueError(
                f"component {self.id} stage must be server_assembly or rack_integration"
            )
        _positive(self.capacity, f"component.{self.id}.capacity")
        _fixed_positive_integer(
            self.units_per_rack,
            f"{self.capacity.unit}/rack",
            f"component.{self.id}.units_per_rack",
        )
        _capacity_semantics(
            basis=self.capacity_basis,
            effective_yield=self.effective_yield,
            platform_qualified_share=self.platform_qualified_share,
            customer_allocation_share=self.customer_allocation_share,
            path=f"component.{self.id}",
        )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.capacity
        yield self.effective_yield
        yield self.platform_qualified_share
        yield self.customer_allocation_share
        yield self.units_per_rack


@dataclass(frozen=True, slots=True, order=True)
class AssemblyCoverageSelector:
    stage: str
    resource_kind: str

    def __post_init__(self) -> None:
        if self.stage not in ASSEMBLY_STAGES:
            raise ValueError("assembly coverage stage is outside the modeled scope")
        _required(self.resource_kind, "coverage.resource_kind")


@dataclass(frozen=True, slots=True)
class AssemblyCoverage:
    output_basis: str
    absorbed_constraints: tuple[AssemblyCoverageSelector, ...]
    posture: str
    methodology: str
    confirming_evidence: str
    falsifying_evidence: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.output_basis != COMPLETE_RACK_OUTPUT_BASIS:
            raise ValueError(
                f"assembly output_basis must be {COMPLETE_RACK_OUTPUT_BASIS}"
            )
        if not self.absorbed_constraints:
            raise ValueError("assembly coverage requires absorbed constraints")
        if self.absorbed_constraints != tuple(
            sorted(set(self.absorbed_constraints))
        ):
            raise ValueError("assembly coverage selectors must be unique and sorted")
        if self.posture not in {item.value for item in EstimatePosture}:
            raise ValueError("assembly coverage posture is invalid")
        for field_name in (
            "methodology",
            "confirming_evidence",
            "falsifying_evidence",
        ):
            _required(getattr(self, field_name), f"coverage.{field_name}")


@dataclass(frozen=True, slots=True)
class SystemAssemblyScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    platform: AssemblyPlatform
    odms: tuple[OdmAssemblyFlow, ...]
    components: tuple[AssemblyComponentPool, ...]
    coverage: AssemblyCoverage
    evidence: tuple[Evidence, ...]
    source_documents: tuple[AssemblySourceDocument, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "quarter", "as_of_date", "recorded_at"):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.quarter):
            raise ValueError("quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        recorded_at = datetime.fromisoformat(
            self.recorded_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if date.fromisoformat(self.as_of_date) > recorded_at.date():
            raise ValueError("as_of_date cannot follow recorded_at")
        if self.samples < 100:
            raise ValueError("samples must be at least 100")
        if not self.odms:
            raise ValueError("at least one ODM assembly flow is required")
        if not self.components:
            raise ValueError("at least one assembly component pool is required")
        odm_ids = [item.id for item in self.odms]
        if len(odm_ids) != len(set(odm_ids)):
            raise ValueError("duplicate ODM assembly id")
        component_ids = [item.id for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("duplicate assembly component id")
        scope_ids = [
            scope
            for odm in self.odms
            for scope in (odm.tray_capacity_scope_id, odm.rack_capacity_scope_id)
        ] + [item.capacity_scope_id for item in self.components]
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("duplicate assembly capacity_scope_id would double count supply")
        expected_coverage = {
            AssemblyCoverageSelector("server_assembly", "server_assembly"),
            AssemblyCoverageSelector("rack_integration", "rack_integration"),
            *{
                AssemblyCoverageSelector(item.stage, item.resource_kind)
                for item in self.components
            },
        }
        if set(self.coverage.absorbed_constraints) != expected_coverage:
            raise ValueError(
                "assembly coverage must exactly match ODM throughput and component pools"
            )
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate assembly evidence id")
        available = set(evidence_ids)
        source_ids = [item.evidence_id for item in self.source_documents]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate assembly source-document evidence_id")
        if unexpected := set(source_ids) - available:
            raise ValueError(
                f"assembly source document references unknown evidence: {sorted(unexpected)}"
            )
        sources_by_evidence = {
            item.evidence_id: item for item in self.source_documents
        }
        for estimate in self.iter_estimates():
            if missing := set(estimate.evidence_ids) - available:
                raise ValueError(
                    f"assembly estimate references missing evidence: {sorted(missing)}"
                )
            if not self.synthetic and estimate.posture is EstimatePosture.SYNTHETIC:
                raise ValueError(
                    "an evidence-backed assembly scenario cannot contain synthetic estimates"
                )
        for item in self.evidence:
            retrieved_at = datetime.fromisoformat(
                item.retrieved_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if retrieved_at > recorded_at:
                raise ValueError("assembly evidence was retrieved after recorded_at")
            if item.published_at and _published_timestamp(item.published_at) > retrieved_at:
                raise ValueError("assembly evidence was retrieved before publication")
            if item.kind is EvidenceKind.SYNTHETIC:
                continue
            if not item.content_hash:
                raise ValueError("non-synthetic assembly evidence requires content_hash")
            source = sources_by_evidence.get(item.id)
            if source is None:
                raise ValueError(
                    f"non-synthetic assembly evidence {item.id} requires source bytes"
                )
            if source.sha256 != item.content_hash:
                raise ValueError(
                    f"assembly evidence {item.id} content hash does not match source"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.platform.iter_estimates()
        for odm in self.odms:
            yield from odm.iter_estimates()
        for component in self.components:
            yield from component.iter_estimates()
