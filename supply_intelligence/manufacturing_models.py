"""Inputs for wafer-to-accelerator manufacturing conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Evidence, Estimate, QUARTER_PATTERN, _iso_date, _iso_timestamp, _required


REFERENCE_TARGET_UNITS = {
    "logic_wafer_starts": "wafer",
    "hbm_wafer_starts": "wafer",
    "package_assembly_starts": "package",
}


def _unit(estimate: Estimate, expected: str, field_name: str) -> None:
    if estimate.unit != expected:
        raise ValueError(f"{field_name} must use {expected}")


def _positive(estimate: Estimate, field_name: str) -> None:
    if estimate.low <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


def _fixed_integer(estimate: Estimate, expected_unit: str, field_name: str) -> None:
    _unit(estimate, expected_unit, field_name)
    _positive(estimate, field_name)
    if not (
        estimate.low == estimate.base == estimate.high
        and float(estimate.base).is_integer()
    ):
        raise ValueError(f"{field_name} must be a fixed positive integer")


@dataclass(frozen=True, slots=True)
class WaferFlow:
    id: str
    name: str
    wafer_starts: Estimate
    wafer_diameter_mm: Estimate
    edge_exclusion_mm: Estimate
    die_width_mm: Estimate
    die_height_mm: Estimate
    scribe_width_mm: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name"):
            _required(getattr(self, field_name), field_name)
        _unit(self.wafer_starts, "wafer", "wafer_starts")
        for field_name in (
            "wafer_diameter_mm",
            "edge_exclusion_mm",
            "die_width_mm",
            "die_height_mm",
            "scribe_width_mm",
        ):
            estimate = getattr(self, field_name)
            _unit(estimate, "mm", field_name)
        for field_name in ("wafer_diameter_mm", "die_width_mm", "die_height_mm"):
            _positive(getattr(self, field_name), field_name)
        if self.edge_exclusion_mm.low < 0 or self.scribe_width_mm.low < 0:
            raise ValueError("edge exclusion and scribe width must be nonnegative")
        if self.edge_exclusion_mm.high * 2 >= self.wafer_diameter_mm.low:
            raise ValueError("edge exclusion must leave a positive usable wafer diameter")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.wafer_starts
        yield self.wafer_diameter_mm
        yield self.edge_exclusion_mm
        yield self.die_width_mm
        yield self.die_height_mm
        yield self.scribe_width_mm


@dataclass(frozen=True, slots=True)
class LogicDieFlow:
    wafer: WaferFlow
    defect_density_per_cm2: Estimate
    clustering_alpha: Estimate
    wafer_sort_yield: Estimate
    performance_bin_share: Estimate

    def __post_init__(self) -> None:
        _unit(
            self.defect_density_per_cm2,
            "defects/cm2",
            "defect_density_per_cm2",
        )
        _unit(self.clustering_alpha, "alpha", "clustering_alpha")
        _positive(self.clustering_alpha, "clustering_alpha")
        _unit(self.wafer_sort_yield, "ratio", "wafer_sort_yield")
        _unit(self.performance_bin_share, "ratio", "performance_bin_share")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.wafer.iter_estimates()
        yield self.defect_density_per_cm2
        yield self.clustering_alpha
        yield self.wafer_sort_yield
        yield self.performance_bin_share


@dataclass(frozen=True, slots=True)
class HbmStackFlow:
    wafer: WaferFlow
    known_good_die_yield: Estimate
    memory_dies_per_stack: Estimate
    stack_assembly_yield: Estimate
    stack_final_test_yield: Estimate
    stack_capacity_gb: Estimate
    stacks_per_accelerator: Estimate

    def __post_init__(self) -> None:
        _unit(self.known_good_die_yield, "ratio", "known_good_die_yield")
        _fixed_integer(
            self.memory_dies_per_stack,
            "die/stack",
            "memory_dies_per_stack",
        )
        _unit(self.stack_assembly_yield, "ratio", "stack_assembly_yield")
        _unit(self.stack_final_test_yield, "ratio", "stack_final_test_yield")
        _unit(self.stack_capacity_gb, "GB/stack", "stack_capacity_gb")
        _positive(self.stack_capacity_gb, "stack_capacity_gb")
        _fixed_integer(
            self.stacks_per_accelerator,
            "stack/accelerator",
            "stacks_per_accelerator",
        )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.wafer.iter_estimates()
        yield self.known_good_die_yield
        yield self.memory_dies_per_stack
        yield self.stack_assembly_yield
        yield self.stack_final_test_yield
        yield self.stack_capacity_gb
        yield self.stacks_per_accelerator


@dataclass(frozen=True, slots=True)
class PackageAssemblyFlow:
    assembly_starts: Estimate
    assembly_yield: Estimate
    logic_dies_per_accelerator: Estimate
    accelerators_per_system: Estimate

    def __post_init__(self) -> None:
        _unit(self.assembly_starts, "package", "assembly_starts")
        _unit(self.assembly_yield, "ratio", "assembly_yield")
        _fixed_integer(
            self.logic_dies_per_accelerator,
            "die/accelerator",
            "logic_dies_per_accelerator",
        )
        _fixed_integer(
            self.accelerators_per_system,
            "accelerator/system",
            "accelerators_per_system",
        )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.assembly_starts
        yield self.assembly_yield
        yield self.logic_dies_per_accelerator
        yield self.accelerators_per_system


@dataclass(frozen=True, slots=True)
class ManufacturingReference:
    id: str
    name: str
    period: str
    comparison_target: str
    estimate: Estimate
    usable_as_product_capacity: bool
    notes: str

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "period", "comparison_target", "notes"):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.period):
            raise ValueError("manufacturing reference period must use YYYY-QN form")
        expected_unit = REFERENCE_TARGET_UNITS.get(self.comparison_target)
        if expected_unit is None:
            allowed = ", ".join(sorted(REFERENCE_TARGET_UNITS))
            raise ValueError(f"manufacturing reference target must be one of: {allowed}")
        _unit(self.estimate, expected_unit, "manufacturing reference estimate")
        _positive(self.estimate, "manufacturing reference estimate")


@dataclass(frozen=True, slots=True)
class ManufacturingScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    evidence: tuple[Evidence, ...]
    logic: LogicDieFlow
    hbm: HbmStackFlow
    package: PackageAssemblyFlow
    references: tuple[ManufacturingReference, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "quarter", "as_of_date", "recorded_at"):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.quarter):
            raise ValueError("quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        if self.samples < 100:
            raise ValueError("samples must be at least 100")
        if self.logic.wafer.id == self.hbm.wafer.id:
            raise ValueError("logic and HBM wafer flows must have distinct IDs")
        reference_ids = [item.id for item in self.references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("duplicate manufacturing reference id")
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate manufacturing evidence id")
        available = set(evidence_ids)
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available
            if missing:
                raise ValueError(
                    f"manufacturing estimate references missing evidence: {sorted(missing)}"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.logic.iter_estimates()
        yield from self.hbm.iter_estimates()
        yield from self.package.iter_estimates()
        for reference in self.references:
            yield reference.estimate
