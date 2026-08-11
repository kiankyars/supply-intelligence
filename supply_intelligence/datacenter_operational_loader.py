"""Strict loading for gross-to-net data-center operational scenarios."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .datacenter_adapter import DATACENTER_IMPORT_FORMAT
from .datacenter_operational_models import (
    DatacenterOperationalCase,
    DatacenterOperationalScenario,
    GrossPowerReference,
    PowerDeductions,
)
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


OPERATIONAL_SCENARIO_FORMAT = "ai-supply-datacenter-operational.v1"


def _only(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unexpected = set(data) - allowed
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _string_tuple(data: Mapping[str, Any], key: str, path: str) -> tuple[str, ...]:
    values = _list(_value(data, key, path), f"{path}.{key}")
    if not all(isinstance(item, str) for item in values):
        raise ValueError(f"{path}.{key} must contain strings")
    return tuple(values)


def operational_scenario_from_dict(
    document: Mapping[str, Any],
) -> DatacenterOperationalScenario:
    if document.get("format") != OPERATIONAL_SCENARIO_FORMAT:
        raise ValueError(f"format must be {OPERATIONAL_SCENARIO_FORMAT}")
    _only(
        document,
        {
            "format",
            "scenario",
            "gross_power",
            "deductions",
            "target_platform_share",
            "rack_it_load",
            "commissioning_slots",
            "commissioning_completion_ratio",
            "evidence",
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
            "scope_description",
            "notes",
        },
        "scenario",
    )
    gross = _mapping(_value(document, "gross_power", "document"), "gross_power")
    _only(
        gross,
        {
            "sha256",
            "expected_entity_ids",
            "expected_datacenter_manifest_sha256",
        },
        "gross_power",
    )
    deductions = _mapping(
        _value(document, "deductions", "document"),
        "deductions",
    )
    _only(
        deductions,
        {
            "current_critical_it_load",
            "contracted_reservations",
            "other_platform_commitments",
            "rack_incompatible_capacity",
            "non_overlap_rationale",
        },
        "deductions",
    )
    evidence_values = _list(_value(document, "evidence", "document"), "evidence")
    return DatacenterOperationalScenario(
        id=_text(metadata, "id", "scenario"),
        name=_text(metadata, "name", "scenario"),
        quarter=_text(metadata, "quarter", "scenario"),
        as_of_date=_text(metadata, "as_of_date", "scenario"),
        recorded_at=_text(metadata, "recorded_at", "scenario"),
        synthetic=_boolean(metadata, "synthetic", "scenario"),
        samples=_integer(metadata, "samples", "scenario"),
        seed=_integer(metadata, "seed", "scenario"),
        scope_description=_text(metadata, "scope_description", "scenario"),
        notes=_text(metadata, "notes", "scenario", ""),
        gross_power=GrossPowerReference(
            sha256=_text(gross, "sha256", "gross_power"),
            expected_entity_ids=_string_tuple(
                gross,
                "expected_entity_ids",
                "gross_power",
            ),
            expected_datacenter_manifest_sha256=_text(
                gross,
                "expected_datacenter_manifest_sha256",
                "gross_power",
            ),
        ),
        deductions=PowerDeductions(
            current_critical_it_load=_estimate(
                _value(deductions, "current_critical_it_load", "deductions"),
                "deductions.current_critical_it_load",
            ),
            contracted_reservations=_estimate(
                _value(deductions, "contracted_reservations", "deductions"),
                "deductions.contracted_reservations",
            ),
            other_platform_commitments=_estimate(
                _value(deductions, "other_platform_commitments", "deductions"),
                "deductions.other_platform_commitments",
            ),
            rack_incompatible_capacity=_estimate(
                _value(deductions, "rack_incompatible_capacity", "deductions"),
                "deductions.rack_incompatible_capacity",
            ),
            non_overlap_rationale=_text(
                deductions,
                "non_overlap_rationale",
                "deductions",
            ),
        ),
        target_platform_share=_estimate(
            _value(document, "target_platform_share", "document"),
            "target_platform_share",
        ),
        rack_it_load=_estimate(
            _value(document, "rack_it_load", "document"),
            "rack_it_load",
        ),
        commissioning_slots=_estimate(
            _value(document, "commissioning_slots", "document"),
            "commissioning_slots",
        ),
        commissioning_completion_ratio=_estimate(
            _value(document, "commissioning_completion_ratio", "document"),
            "commissioning_completion_ratio",
        ),
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
    )


def load_operational_scenario(path: str | Path) -> DatacenterOperationalScenario:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    return operational_scenario_from_dict(_mapping(document, "document"))


def _load_gross_import(
    path: str | Path,
    scenario: DatacenterOperationalScenario,
) -> tuple[Any, ...]:
    source = Path(path)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != scenario.gross_power.sha256:
        raise ValueError("gross import SHA-256 does not match the scenario pin")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    data = _mapping(document, "gross_import")
    if data.get("format") != DATACENTER_IMPORT_FORMAT:
        raise ValueError(f"gross import format must be {DATACENTER_IMPORT_FORMAT}")
    if data.get("usable_as_incremental_power_pool") is not False:
        raise ValueError(
            "gross import must remain blocked from direct incremental-capacity use"
        )
    estimate = _estimate(_value(data, "estimate", "gross_import"), "gross_import.estimate")
    if estimate.unit != "MW":
        raise ValueError("gross import estimate must use MW")
    evidence_values = _list(
        _value(data, "evidence", "gross_import"),
        "gross_import.evidence",
    )
    evidence = tuple(
        _evidence(value, f"gross_import.evidence[{index}]")
        for index, value in enumerate(evidence_values)
    )
    if len({item.id for item in evidence}) != len(evidence):
        raise ValueError("gross import contains duplicate evidence ids")
    sites_values = _list(_value(data, "sites", "gross_import"), "gross_import.sites")
    sites = tuple(
        _mapping(value, f"gross_import.sites[{index}]")
        for index, value in enumerate(sites_values)
    )
    entity_ids = tuple(sorted(str(site.get("entity_id", "")) for site in sites))
    if entity_ids != scenario.gross_power.expected_entity_ids:
        raise ValueError("gross import site ids do not match the scenario pin")
    lineage = _mapping(_value(data, "lineage", "gross_import"), "gross_import.lineage")
    if lineage.get("capacity_semantics") != "gross_site_critical_it_envelope":
        raise ValueError("gross import must retain gross critical-IT semantics")
    if lineage.get("availability_status") != "not_net_incremental_capacity":
        raise ValueError("gross import must retain blocked availability status")
    datacenter_release = _mapping(
        _value(lineage, "datacenter_release", "gross_import.lineage"),
        "gross_import.lineage.datacenter_release",
    )
    if (
        datacenter_release.get("manifest_sha256")
        != scenario.gross_power.expected_datacenter_manifest_sha256
    ):
        raise ValueError("data-center manifest SHA-256 does not match the scenario pin")
    release_as_of = datacenter_release.get("as_of")
    release_recorded_at = datacenter_release.get("recorded_at")
    if not isinstance(release_as_of, str) or not isinstance(release_recorded_at, str):
        raise ValueError("gross import lineage requires release freeze timestamps")
    try:
        release_as_of_date = date.fromisoformat(release_as_of)
        scenario_as_of_date = date.fromisoformat(scenario.as_of_date)
        source_recorded = datetime.fromisoformat(
            release_recorded_at.replace("Z", "+00:00")
        )
        scenario_recorded = datetime.fromisoformat(
            scenario.recorded_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("gross import lineage contains an invalid freeze timestamp") from exc
    if release_as_of_date > scenario_as_of_date:
        raise ValueError("gross import as_of cannot follow scenario as_of_date")
    if source_recorded.tzinfo is None:
        raise ValueError("gross import recorded_at must include a timezone")
    if scenario_recorded < source_recorded:
        raise ValueError("gross import recorded_at cannot follow scenario recorded_at")
    return estimate, evidence, sites, lineage, digest


def load_datacenter_operational_case(
    scenario_path: str | Path,
    gross_import_path: str | Path,
) -> DatacenterOperationalCase:
    scenario = load_operational_scenario(scenario_path)
    estimate, evidence, sites, lineage, digest = _load_gross_import(
        gross_import_path,
        scenario,
    )
    return DatacenterOperationalCase(
        scenario=scenario,
        gross_estimate=estimate,
        gross_evidence=evidence,
        sites=sites,
        gross_lineage=lineage,
        gross_import_sha256=digest,
    )
