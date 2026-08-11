"""Contracts for converting gross site power into operational rack throughput."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models import (
    Evidence,
    Estimate,
    EstimatePosture,
    QUARTER_PATTERN,
    _iso_date,
    _iso_timestamp,
    _required,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _unit(estimate: Estimate, expected: str, field_name: str) -> None:
    if estimate.unit != expected:
        raise ValueError(f"{field_name} must use {expected}")


def _positive(estimate: Estimate, field_name: str) -> None:
    if estimate.low <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class GrossPowerReference:
    sha256: str
    expected_entity_ids: tuple[str, ...]
    expected_datacenter_manifest_sha256: str

    def __post_init__(self) -> None:
        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("gross import sha256 must be a lowercase SHA-256 digest")
        if not SHA256_PATTERN.fullmatch(self.expected_datacenter_manifest_sha256):
            raise ValueError(
                "expected data-center manifest sha256 must be a lowercase SHA-256 digest"
            )
        if not self.expected_entity_ids:
            raise ValueError("gross import must pin at least one entity id")
        if tuple(sorted(set(self.expected_entity_ids))) != self.expected_entity_ids:
            raise ValueError("gross import entity ids must be unique and sorted")


@dataclass(frozen=True, slots=True)
class PowerDeductions:
    current_critical_it_load: Estimate
    contracted_reservations: Estimate
    other_platform_commitments: Estimate
    rack_incompatible_capacity: Estimate
    non_overlap_rationale: str

    def __post_init__(self) -> None:
        _required(self.non_overlap_rationale, "non_overlap_rationale")
        for field_name in (
            "current_critical_it_load",
            "contracted_reservations",
            "other_platform_commitments",
            "rack_incompatible_capacity",
        ):
            _unit(getattr(self, field_name), "MW", field_name)

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.current_critical_it_load
        yield self.contracted_reservations
        yield self.other_platform_commitments
        yield self.rack_incompatible_capacity


@dataclass(frozen=True, slots=True)
class DatacenterOperationalScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    scope_description: str
    gross_power: GrossPowerReference
    deductions: PowerDeductions
    target_platform_share: Estimate
    rack_it_load: Estimate
    commissioning_slots: Estimate
    commissioning_completion_ratio: Estimate
    evidence: tuple[Evidence, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "quarter",
            "as_of_date",
            "recorded_at",
            "scope_description",
        ):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.match(self.quarter):
            raise ValueError("quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        if self.samples < 100:
            raise ValueError("samples must be at least 100")
        _unit(self.target_platform_share, "ratio", "target_platform_share")
        _unit(self.rack_it_load, "MW/rack", "rack_it_load")
        _positive(self.rack_it_load, "rack_it_load")
        _unit(self.commissioning_slots, "rack", "commissioning_slots")
        _unit(
            self.commissioning_completion_ratio,
            "ratio",
            "commissioning_completion_ratio",
        )
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate operational evidence id")
        available = set(evidence_ids)
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available
            if missing:
                raise ValueError(
                    "operational estimate references missing evidence: "
                    f"{sorted(missing)}"
                )
        if not self.synthetic and any(
            item.posture is EstimatePosture.SYNTHETIC
            for item in self.iter_estimates()
        ):
            raise ValueError(
                "an evidence-backed operational scenario cannot contain synthetic estimates"
            )

    def iter_estimates(self) -> Iterable[Estimate]:
        yield from self.deductions.iter_estimates()
        yield self.target_platform_share
        yield self.rack_it_load
        yield self.commissioning_slots
        yield self.commissioning_completion_ratio


@dataclass(frozen=True, slots=True)
class DatacenterOperationalCase:
    scenario: DatacenterOperationalScenario
    gross_estimate: Estimate
    gross_evidence: tuple[Evidence, ...]
    sites: tuple[Mapping[str, Any], ...]
    gross_lineage: Mapping[str, Any]
    gross_import_sha256: str

    def __post_init__(self) -> None:
        _unit(self.gross_estimate, "MW", "gross_estimate")
        if self.gross_import_sha256 != self.scenario.gross_power.sha256:
            raise ValueError("loaded gross import does not match the pinned SHA-256")
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("gross and operational evidence ids must be unique")
        missing = set(self.gross_estimate.evidence_ids) - set(evidence_ids)
        if missing:
            raise ValueError(
                f"gross estimate references missing evidence: {sorted(missing)}"
            )

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return self.gross_evidence + self.scenario.evidence
