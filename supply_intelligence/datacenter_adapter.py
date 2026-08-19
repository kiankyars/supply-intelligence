"""Strict Data Center Atlas imports for site-level critical IT power envelopes."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from .models import Evidence, EvidenceKind, Estimate, EstimatePosture, QUARTER_PATTERN


DATACENTER_RELEASE_FORMAT = "datacenter-atlas-release-v1"
DATACENTER_FIXTURE_FORMAT = "ai-supply-datacenter-adapter-fixture.v1"
DATACENTER_SELECTION_FORMAT = "ai-supply-datacenter-selection.v1"
DATACENTER_IMPORT_FORMAT = "ai-supply-datacenter-power-import.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class DatacenterCapacityStage(StrEnum):
    OPERATIONAL = "operational"
    FORECAST = "forecast"


class DatacenterAggregationPolicy(StrEnum):
    SINGLE_SITE = "single_site"
    SUM_EXPLICIT_NONOVERLAPPING_SITES = "sum_explicit_nonoverlapping_sites"


def _required(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _iso_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _quarter_end(quarter: str) -> date:
    year = int(quarter[:4])
    number = int(quarter[-1])
    if number == 4:
        return date(year + 1, 1, 1)
    return date(year, number * 3 + 1, 1)


@dataclass(frozen=True, slots=True)
class DatacenterPowerSelection:
    target_quarter: str
    stage: DatacenterCapacityStage
    entity_ids: tuple[str, ...]
    aggregation_policy: DatacenterAggregationPolicy
    aggregation_rationale: str
    scope_name: str
    scope_description: str
    expected_release_as_of: str
    expected_release_recorded_at: str
    minimum_capacity_as_of: str
    confirming_evidence: str
    falsifying_evidence: str
    required_user_labels: tuple[str, ...] = ()
    required_countries: tuple[str, ...] = ()
    correlation_group: str | None = None
    metric: str = "critical_it_mw"
    unit: str = "MW"
    capacity_semantics: str = "gross_site_critical_it_envelope"
    availability_status: str = "not_net_incremental_capacity"

    def __post_init__(self) -> None:
        if not QUARTER_PATTERN.match(self.target_quarter):
            raise ValueError("target_quarter must use YYYY-QN form")
        for field_name in (
            "aggregation_rationale",
            "scope_name",
            "scope_description",
            "expected_release_as_of",
            "expected_release_recorded_at",
            "minimum_capacity_as_of",
            "confirming_evidence",
            "falsifying_evidence",
            "metric",
            "unit",
            "capacity_semantics",
            "availability_status",
        ):
            _required(getattr(self, field_name), field_name)
        _iso_date(self.expected_release_as_of, "expected_release_as_of")
        _iso_timestamp(
            self.expected_release_recorded_at,
            "expected_release_recorded_at",
        )
        minimum = _iso_date(self.minimum_capacity_as_of, "minimum_capacity_as_of")
        if minimum > _quarter_end(self.target_quarter):
            raise ValueError("minimum_capacity_as_of must precede the target quarter end")
        if self.metric != "critical_it_mw" or self.unit != "MW":
            raise ValueError("the v1 data-center bridge accepts only critical_it_mw in MW")
        if self.capacity_semantics != "gross_site_critical_it_envelope":
            raise ValueError(
                "capacity_semantics must be gross_site_critical_it_envelope"
            )
        if self.availability_status != "not_net_incremental_capacity":
            raise ValueError(
                "availability_status must be not_net_incremental_capacity"
            )
        if not self.entity_ids:
            raise ValueError("entity_ids must explicitly select at least one site")
        if tuple(sorted(set(self.entity_ids))) != self.entity_ids:
            raise ValueError("entity_ids must be unique and sorted")
        if self.aggregation_policy is DatacenterAggregationPolicy.SINGLE_SITE:
            if len(self.entity_ids) != 1:
                raise ValueError("single_site aggregation requires exactly one entity")
        elif len(self.entity_ids) < 2:
            raise ValueError(
                "sum_explicit_nonoverlapping_sites requires at least two entities"
            )
        for field_name in ("required_user_labels", "required_countries"):
            values = getattr(self, field_name)
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{field_name} must be unique and sorted")
            if any(not item.strip() for item in values):
                raise ValueError(f"{field_name} cannot contain blanks")
        if self.correlation_group is not None:
            _required(self.correlation_group, "correlation_group")

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": DATACENTER_SELECTION_FORMAT,
            "target_quarter": self.target_quarter,
            "stage": self.stage.value,
            "entity_ids": list(self.entity_ids),
            "aggregation_policy": self.aggregation_policy.value,
            "aggregation_rationale": self.aggregation_rationale,
            "scope_name": self.scope_name,
            "scope_description": self.scope_description,
            "expected_release_as_of": self.expected_release_as_of,
            "expected_release_recorded_at": self.expected_release_recorded_at,
            "minimum_capacity_as_of": self.minimum_capacity_as_of,
            "confirming_evidence": self.confirming_evidence,
            "falsifying_evidence": self.falsifying_evidence,
            "required_user_labels": list(self.required_user_labels),
            "required_countries": list(self.required_countries),
            "correlation_group": self.correlation_group,
            "metric": self.metric,
            "unit": self.unit,
            "capacity_semantics": self.capacity_semantics,
            "availability_status": self.availability_status,
        }


@dataclass(frozen=True, slots=True)
class DatacenterPowerImport:
    estimate: Estimate
    evidence: tuple[Evidence, ...]
    sites: tuple[Mapping[str, Any], ...]
    lineage: Mapping[str, Any]
    usable_as_incremental_power_pool: bool = False

    def as_dict(self) -> dict[str, Any]:
        estimate = self.estimate
        return {
            "format": DATACENTER_IMPORT_FORMAT,
            "usable_as_incremental_power_pool": self.usable_as_incremental_power_pool,
            "blocking_inputs": [
                "current critical IT load",
                "contracted and reserved capacity",
                "platform-specific allocation",
                "rack-compatible cooling and power-density headroom",
            ],
            "estimate": {
                "low": estimate.low,
                "base": estimate.base,
                "high": estimate.high,
                "unit": estimate.unit,
                "posture": estimate.posture.value,
                "methodology": estimate.methodology,
                "confidence": estimate.confidence,
                "last_updated": estimate.last_updated,
                "evidence_ids": list(estimate.evidence_ids),
                "confirming_evidence": estimate.confirming_evidence,
                "falsifying_evidence": estimate.falsifying_evidence,
                "correlation_group": estimate.correlation_group,
            },
            "evidence": [
                {
                    "id": item.id,
                    "kind": item.kind.value,
                    "title": item.title,
                    "source_url": item.source_url,
                    "publisher": item.publisher,
                    "retrieved_at": item.retrieved_at,
                    "published_at": item.published_at,
                    "source_family": item.source_family,
                    "license": item.license,
                    "excerpt": item.excerpt,
                    "content_hash": item.content_hash,
                }
                for item in self.evidence
            ],
            "sites": [dict(item) for item in self.sites],
            "lineage": dict(self.lineage),
        }


def datacenter_selection_from_dict(
    document: Mapping[str, Any],
) -> DatacenterPowerSelection:
    if document.get("format") != DATACENTER_SELECTION_FORMAT:
        raise ValueError(f"format must be {DATACENTER_SELECTION_FORMAT}")
    allowed = {
        "format",
        "target_quarter",
        "stage",
        "entity_ids",
        "aggregation_policy",
        "aggregation_rationale",
        "scope_name",
        "scope_description",
        "expected_release_as_of",
        "expected_release_recorded_at",
        "minimum_capacity_as_of",
        "confirming_evidence",
        "falsifying_evidence",
        "required_user_labels",
        "required_countries",
        "correlation_group",
        "metric",
        "unit",
        "capacity_semantics",
        "availability_status",
    }
    unexpected = set(document) - allowed
    if unexpected:
        raise ValueError(f"unexpected data-center selection fields: {sorted(unexpected)}")

    def text_field(key: str) -> str:
        value = document.get(key)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        return value

    def string_tuple(key: str) -> tuple[str, ...]:
        value = document.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"{key} must be a list of strings")
        return tuple(value)

    correlation_group = document.get("correlation_group")
    if correlation_group is not None and not isinstance(correlation_group, str):
        raise ValueError("correlation_group must be text or null")
    try:
        stage = DatacenterCapacityStage(text_field("stage"))
        aggregation = DatacenterAggregationPolicy(
            text_field("aggregation_policy")
        )
    except ValueError as exc:
        raise ValueError(f"invalid data-center selection enum: {exc}") from exc
    return DatacenterPowerSelection(
        target_quarter=text_field("target_quarter"),
        stage=stage,
        entity_ids=string_tuple("entity_ids"),
        aggregation_policy=aggregation,
        aggregation_rationale=text_field("aggregation_rationale"),
        scope_name=text_field("scope_name"),
        scope_description=text_field("scope_description"),
        expected_release_as_of=text_field("expected_release_as_of"),
        expected_release_recorded_at=text_field("expected_release_recorded_at"),
        minimum_capacity_as_of=text_field("minimum_capacity_as_of"),
        confirming_evidence=text_field("confirming_evidence"),
        falsifying_evidence=text_field("falsifying_evidence"),
        required_user_labels=string_tuple("required_user_labels"),
        required_countries=string_tuple("required_countries"),
        correlation_group=correlation_group,
        metric=text_field("metric"),
        unit=text_field("unit"),
        capacity_semantics=text_field("capacity_semantics"),
        availability_status=text_field("availability_status"),
    )


def load_datacenter_selection(path: str | Path) -> DatacenterPowerSelection:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("data-center selection document must be an object")
    return datacenter_selection_from_dict(document)


def _verified_file(
    release_dir: Path,
    manifest: Mapping[str, Any],
    name: str,
) -> bytes:
    files = manifest.get("files")
    if not isinstance(files, dict) or name not in files:
        raise ValueError(f"data-center manifest does not pin required file: {name}")
    metadata = files[name]
    if not isinstance(metadata, dict):
        raise ValueError(f"data-center manifest metadata is invalid for {name}")
    raw = (release_dir / name).read_bytes()
    if metadata.get("bytes") != len(raw):
        raise ValueError(f"data-center release byte count mismatch: {name}")
    digest = hashlib.sha256(raw).hexdigest()
    if metadata.get("sha256") != digest:
        raise ValueError(f"data-center release hash mismatch: {name}")
    return raw


def _source_release_contract(
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
) -> tuple[Mapping[str, Any], str]:
    manifest_format = manifest.get("format")
    if manifest_format == DATACENTER_RELEASE_FORMAT:
        return manifest, manifest_sha256
    if manifest_format != DATACENTER_FIXTURE_FORMAT:
        raise ValueError(
            "data-center format must be "
            f"{DATACENTER_RELEASE_FORMAT} or {DATACENTER_FIXTURE_FORMAT}"
        )
    if set(manifest) != {"files", "format", "scope", "source_release"}:
        raise ValueError("data-center adapter fixture manifest fields are invalid")
    if manifest.get("scope") != "selected_rows_only":
        raise ValueError(
            "data-center adapter fixture must declare selected_rows_only scope"
        )
    source_release = manifest.get("source_release")
    if not isinstance(source_release, dict) or set(source_release) != {
        "as_of",
        "format",
        "manifest_sha256",
        "recorded_at",
    }:
        raise ValueError("data-center adapter fixture source_release is invalid")
    if source_release.get("format") != DATACENTER_RELEASE_FORMAT:
        raise ValueError(
            f"data-center fixture source format must be {DATACENTER_RELEASE_FORMAT}"
        )
    source_manifest_sha256 = source_release.get("manifest_sha256")
    if not isinstance(source_manifest_sha256, str) or not SHA256_PATTERN.fullmatch(
        source_manifest_sha256
    ):
        raise ValueError("data-center fixture source manifest hash is invalid")
    as_of = source_release.get("as_of")
    recorded_at = source_release.get("recorded_at")
    if not isinstance(as_of, str) or not isinstance(recorded_at, str):
        raise ValueError("data-center fixture source timestamps are invalid")
    _iso_date(as_of, "source_release.as_of")
    _iso_timestamp(recorded_at, "source_release.recorded_at")
    return source_release, source_manifest_sha256


def _csv_rows(raw: bytes, name: str) -> list[dict[str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} must use UTF-8") from exc
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _float(row: Mapping[str, str], key: str, context: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{context}.{key} must be numeric") from exc
    if value < 0:
        raise ValueError(f"{context}.{key} must be nonnegative")
    return value


def _tokens(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _evidence_kind(kind: str) -> EvidenceKind:
    mapping = {
        "company_disclosure": EvidenceKind.COMPANY_DISCLOSURE,
        "government_record": EvidenceKind.GOVERNMENT_RECORD,
        "satellite_imagery": EvidenceKind.SATELLITE_IMAGERY,
        "utility_record": EvidenceKind.UTILITY_RECORD,
        "third_party_research": EvidenceKind.THIRD_PARTY_RESEARCH,
        "third_party_dataset": EvidenceKind.THIRD_PARTY_RESEARCH,
    }
    return mapping.get(kind, EvidenceKind.OTHER)


def load_datacenter_power(
    release_dir: str | Path,
    selection: DatacenterPowerSelection,
) -> DatacenterPowerImport:
    root = Path(release_dir)
    manifest_raw = (root / "manifest.json").read_bytes()
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("data-center manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("data-center manifest must be an object")
    manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
    source_release, source_manifest_digest = _source_release_contract(
        manifest,
        manifest_sha256=manifest_digest,
    )
    if source_release.get("as_of") != selection.expected_release_as_of:
        raise ValueError("data-center release as_of does not match the pinned selection")
    if source_release.get("recorded_at") != selection.expected_release_recorded_at:
        raise ValueError(
            "data-center release recorded_at does not match the pinned selection"
        )
    capacity_rows = _csv_rows(
        _verified_file(root, manifest, "capacity_estimates.csv"),
        "capacity_estimates.csv",
    )
    entity_rows = _csv_rows(
        _verified_file(root, manifest, "entities.csv"),
        "entities.csv",
    )
    evidence_rows = _csv_rows(
        _verified_file(root, manifest, "evidence.csv"),
        "evidence.csv",
    )
    entities = {row.get("entity_id", ""): row for row in entity_rows}
    if len(entities) != len(entity_rows) or "" in entities:
        raise ValueError("entities.csv contains blank or duplicate entity IDs")
    evidence_by_id = {row.get("evidence_id", ""): row for row in evidence_rows}
    if len(evidence_by_id) != len(evidence_rows) or "" in evidence_by_id:
        raise ValueError("evidence.csv contains blank or duplicate evidence IDs")

    minimum_as_of = _iso_date(
        selection.minimum_capacity_as_of,
        "minimum_capacity_as_of",
    )
    target_end = _quarter_end(selection.target_quarter)
    selected_capacity = []
    selected_sites = []
    capacity_evidence_ids = set()
    all_evidence_ids = set()
    for entity_id in selection.entity_ids:
        entity = entities.get(entity_id)
        if entity is None:
            raise ValueError(f"selected data-center entity is missing: {entity_id}")
        country = entity.get("country", "")
        if selection.required_countries and country not in selection.required_countries:
            raise ValueError(f"country mismatch for selected entity {entity_id}")
        users = _tokens(entity.get("users", ""))
        missing_users = set(selection.required_user_labels) - users
        if missing_users:
            raise ValueError(
                f"user-label mismatch for entity {entity_id}: {sorted(missing_users)}"
            )
        matches = [
            row
            for row in capacity_rows
            if row.get("entity_id") == entity_id
            and row.get("metric") == selection.metric
            and row.get("unit") == selection.unit
            and row.get("stage") == selection.stage.value
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one selected capacity row for entity {entity_id}; found {len(matches)}"
            )
        row = matches[0]
        as_of_date = _iso_date(
            row.get("as_of_date", ""),
            f"capacity[{entity_id}].as_of_date",
        )
        if as_of_date < minimum_as_of or as_of_date >= target_end:
            raise ValueError(f"capacity observation is outside the selected window: {entity_id}")
        target_date = row.get("target_date", "")
        if selection.stage is DatacenterCapacityStage.OPERATIONAL:
            if target_date:
                raise ValueError(
                    f"operational capacity cannot carry a future target date: {entity_id}"
                )
        else:
            if not target_date:
                raise ValueError(f"forecast capacity requires a target date: {entity_id}")
            if _iso_date(target_date, f"capacity[{entity_id}].target_date") >= target_end:
                raise ValueError(
                    f"forecast capacity is not available by target quarter end: {entity_id}"
                )
        low = _float(row, "low", f"capacity[{entity_id}]")
        base = _float(row, "base", f"capacity[{entity_id}]")
        high = _float(row, "high", f"capacity[{entity_id}]")
        if not low <= base <= high:
            raise ValueError(f"capacity range is unordered for entity {entity_id}")
        evidence_id = row.get("evidence_id", "")
        if evidence_id not in evidence_by_id:
            raise ValueError(f"capacity evidence is missing for entity {entity_id}")
        capacity_evidence_ids.add(evidence_id)
        all_evidence_ids.add(evidence_id)
        status_evidence_id = entity.get("status_evidence_id", "")
        if selection.stage is DatacenterCapacityStage.OPERATIONAL:
            if status_evidence_id not in evidence_by_id:
                raise ValueError(f"status evidence is missing for entity {entity_id}")
            all_evidence_ids.add(status_evidence_id)
        selected_capacity.append({**row, "low": low, "base": base, "high": high})
        selected_sites.append(
            {
                "entity_id": entity_id,
                "name": entity.get("name"),
                "country": country,
                "owner": entity.get("owner"),
                "operator": entity.get("operator"),
                "users": entity.get("users"),
                "status": entity.get("status"),
                "status_as_of": entity.get("status_as_of"),
                "status_confidence": entity.get("status_confidence"),
                "status_method": entity.get("status_method"),
                "status_evidence_id": status_evidence_id or None,
                "capacity": {**row, "low": low, "base": base, "high": high},
            }
        )

    evidence = []
    evidence_id_map = {}
    for evidence_id in sorted(all_evidence_ids):
        row = evidence_by_id[evidence_id]
        imported_id = f"datacenter:{source_manifest_digest[:12]}:{evidence_id}"
        evidence_id_map[evidence_id] = imported_id
        evidence.append(
            Evidence(
                id=imported_id,
                kind=_evidence_kind(row.get("kind", "")),
                title=row.get("title", ""),
                source_url=row.get("source_url", ""),
                publisher=row.get("publisher", ""),
                retrieved_at=row.get("retrieved_at", ""),
                published_at=row.get("published_at") or None,
                source_family=row.get("source_family") or None,
                license=row.get("license") or None,
                excerpt=(
                    f"Attribution: {row['attribution']}"
                    if row.get("attribution")
                    else None
                ),
                content_hash=row.get("content_hash") or None,
            )
        )

    low = sum(row["low"] for row in selected_capacity)
    base = sum(row["base"] for row in selected_capacity)
    high = sum(row["high"] for row in selected_capacity)
    confidence = min(_float(row, "confidence", "capacity") for row in selected_capacity)
    posture = (
        EstimatePosture.REPORTED
        if all(row.get("method") == "reported" for row in selected_capacity)
        else EstimatePosture.MODELED
    )
    method = (
        f"Summed {selection.metric} across {len(selected_capacity)} explicitly selected "
        f"Data Center Atlas site(s) for {selection.scope_name}. This is a gross site "
        "critical IT power envelope, not vacant or platform-allocated MW. Existing load, "
        "reservations, and rack-compatible headroom must be removed before use as an "
        f"incremental power pool. Aggregation: {selection.aggregation_policy.value}. "
        f"Rationale: {selection.aggregation_rationale}"
    )
    estimate = Estimate(
        low=low,
        base=base,
        high=high,
        unit=selection.unit,
        posture=posture,
        methodology=method,
        confidence=confidence,
        last_updated=selection.expected_release_as_of,
        evidence_ids=tuple(
            evidence_id_map[item] for item in sorted(capacity_evidence_ids)
        ),
        confirming_evidence=selection.confirming_evidence,
        falsifying_evidence=selection.falsifying_evidence,
        correlation_group=selection.correlation_group,
    )
    lineage = {
        "datacenter_release": {
            "format": DATACENTER_RELEASE_FORMAT,
            "manifest_sha256": source_manifest_digest,
            "as_of": source_release["as_of"],
            "recorded_at": source_release["recorded_at"],
        },
        "selection": selection.as_dict(),
        "selected_capacity_rows": selected_capacity,
        "capacity_semantics": selection.capacity_semantics,
        "availability_status": selection.availability_status,
    }
    return DatacenterPowerImport(
        estimate=estimate,
        evidence=tuple(evidence),
        sites=tuple(selected_sites),
        lineage=lineage,
    )
