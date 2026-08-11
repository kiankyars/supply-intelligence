"""Supplier-resolved HBM wafer, stack, qualification, and allocation inputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from .manufacturing_models import WaferFlow
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


WAFER_START_BASES = {
    "supplier_hbm3e_compatible",
    "platform_allocated",
}


@dataclass(frozen=True, slots=True)
class HbmSourceDocument:
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
            raise ValueError("HBM source document sha256 must be a lowercase digest")
        if hashlib.sha256(self.raw).hexdigest() != self.sha256:
            raise ValueError("HBM source document bytes do not match sha256")
        try:
            self.raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("HBM source documents must be UTF-8 normalized text") from exc


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
class HbmPlatformDemand:
    id: str
    name: str
    customer: str
    hbm_generation: str
    memory_dies_per_stack: Estimate
    stack_capacity_gb: Estimate
    stacks_per_accelerator: Estimate
    accelerator_package_demand: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "customer", "hbm_generation"):
            _required(getattr(self, field_name), field_name)
        _fixed_positive_integer(
            self.memory_dies_per_stack,
            "die/stack",
            "memory_dies_per_stack",
        )
        _unit(self.stack_capacity_gb, "GB/stack", "stack_capacity_gb")
        _positive(self.stack_capacity_gb, "stack_capacity_gb")
        if not (
            self.stack_capacity_gb.low
            == self.stack_capacity_gb.base
            == self.stack_capacity_gb.high
        ):
            raise ValueError("stack_capacity_gb must be a fixed platform topology")
        _fixed_positive_integer(
            self.stacks_per_accelerator,
            "stack/accelerator",
            "stacks_per_accelerator",
        )
        _unit(
            self.accelerator_package_demand,
            "package",
            "accelerator_package_demand",
        )
        _positive(self.accelerator_package_demand, "accelerator_package_demand")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.memory_dies_per_stack
        yield self.stack_capacity_gb
        yield self.stacks_per_accelerator
        yield self.accelerator_package_demand


@dataclass(frozen=True, slots=True)
class HbmSupplierFlow:
    id: str
    name: str
    capacity_scope_id: str
    capacity_scope: str
    geography: str
    product: str
    process_node: str
    wafer_start_basis: str
    wafer: WaferFlow
    known_good_die_yield: Estimate
    stack_assembly_yield: Estimate
    stack_final_test_yield: Estimate
    platform_qualified_share: Estimate
    customer_allocation_share: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "capacity_scope_id",
            "capacity_scope",
            "geography",
            "product",
            "process_node",
        ):
            _required(getattr(self, field_name), field_name)
        if self.wafer_start_basis not in WAFER_START_BASES:
            allowed = ", ".join(sorted(WAFER_START_BASES))
            raise ValueError(f"wafer_start_basis must be one of: {allowed}")
        for field_name in (
            "known_good_die_yield",
            "stack_assembly_yield",
            "stack_final_test_yield",
            "platform_qualified_share",
            "customer_allocation_share",
        ):
            _unit(getattr(self, field_name), "ratio", field_name)
        if self.wafer_start_basis == "platform_allocated":
            _fixed_one(
                self.platform_qualified_share,
                "platform_qualified_share for platform_allocated starts",
            )
            _fixed_one(
                self.customer_allocation_share,
                "customer_allocation_share for platform_allocated starts",
            )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.wafer.iter_estimates()
        yield self.known_good_die_yield
        yield self.stack_assembly_yield
        yield self.stack_final_test_yield
        yield self.platform_qualified_share
        yield self.customer_allocation_share


@dataclass(frozen=True, slots=True)
class HbmSupplierScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    evidence: tuple[Evidence, ...]
    platform: HbmPlatformDemand
    suppliers: tuple[HbmSupplierFlow, ...]
    source_documents: tuple[HbmSourceDocument, ...] = ()
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
        if not self.suppliers:
            raise ValueError("at least one HBM supplier is required")
        supplier_ids = [item.id for item in self.suppliers]
        if len(supplier_ids) != len(set(supplier_ids)):
            raise ValueError("duplicate HBM supplier id")
        capacity_scope_ids = [item.capacity_scope_id for item in self.suppliers]
        if len(capacity_scope_ids) != len(set(capacity_scope_ids)):
            raise ValueError("duplicate HBM capacity_scope_id would double count supply")
        wafer_ids = [item.wafer.id for item in self.suppliers]
        if len(wafer_ids) != len(set(wafer_ids)):
            raise ValueError("duplicate HBM supplier wafer-flow id")
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate HBM supplier evidence id")
        available_evidence = set(evidence_ids)
        source_evidence_ids = [item.evidence_id for item in self.source_documents]
        if len(source_evidence_ids) != len(set(source_evidence_ids)):
            raise ValueError("duplicate HBM source-document evidence_id")
        unexpected_source_ids = set(source_evidence_ids) - available_evidence
        if unexpected_source_ids:
            raise ValueError(
                "HBM source document references unknown evidence: "
                f"{sorted(unexpected_source_ids)}"
            )
        sources_by_evidence = {
            item.evidence_id: item for item in self.source_documents
        }
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available_evidence
            if missing:
                raise ValueError(
                    "HBM supplier estimate references missing evidence: "
                    f"{sorted(missing)}"
                )
            if not self.synthetic and estimate.posture is EstimatePosture.SYNTHETIC:
                raise ValueError(
                    "an evidence-backed HBM supplier scenario cannot contain "
                    "synthetic estimates"
                )
        for item in self.evidence:
            retrieved_at = datetime.fromisoformat(
                item.retrieved_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if retrieved_at > recorded_at:
                raise ValueError("HBM supplier evidence was retrieved after recorded_at")
            if item.published_at and _published_timestamp(item.published_at) > retrieved_at:
                raise ValueError("HBM supplier evidence was retrieved before publication")
            if item.kind is EvidenceKind.SYNTHETIC:
                continue
            if not item.content_hash:
                raise ValueError("non-synthetic HBM evidence requires content_hash")
            source_document = sources_by_evidence.get(item.id)
            if source_document is None:
                raise ValueError(
                    "non-synthetic HBM evidence requires a pinned source document"
                )
            if source_document.sha256 != item.content_hash:
                raise ValueError(
                    "HBM evidence content_hash does not match its source document"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.platform.iter_estimates()
        for supplier in self.suppliers:
            yield from supplier.iter_estimates()
