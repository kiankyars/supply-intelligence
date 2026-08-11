"""Strict Semiconductor Atlas release imports for quarterly resource capacity."""

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


ATLAS_RELEASE_FORMAT = "semiconductor-atlas-release-v1"
SELECTION_FORMAT = "ai-supply-atlas-selection.v1"
IMPORT_FORMAT = "ai-supply-atlas-capacity-import.v1"
QUARTERLY_FORECAST_FILE = "quarterly_output_forecast.csv"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AtlasSourceMode(StrEnum):
    CANONICAL_CAPACITY = "canonical_capacity"
    QUARTERLY_OUTPUT_FORECAST = "quarterly_output_forecast"


class AtlasCapacityBasis(StrEnum):
    ANNOUNCED = "announced"
    PHYSICAL_CONSTRUCTION = "physical_construction"
    TOOL_INSTALLED = "tool_installed"
    QUALIFIED = "qualified"
    ECONOMICALLY_USABLE = "economically_usable"


class AtlasAggregationPolicy(StrEnum):
    SINGLE_CLAIM = "single_claim"
    SUM_EXPLICIT_NONOVERLAPPING_CLAIMS = "sum_explicit_nonoverlapping_claims"


def _required(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
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
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _quarter_bounds(quarter: str) -> tuple[date, date]:
    year = int(quarter[:4])
    number = int(quarter[-1])
    start = date(year, 3 * (number - 1) + 1, 1)
    if number == 4:
        return start, date(year + 1, 1, 1)
    return start, date(year, 3 * number + 1, 1)


@dataclass(frozen=True, slots=True)
class AtlasCapacitySelection:
    target_quarter: str
    source_mode: AtlasSourceMode
    input_capacity_basis: AtlasCapacityBasis
    metric: str
    unit: str
    quantity_semantics: str
    claim_ids: tuple[str, ...]
    aggregation_policy: AtlasAggregationPolicy
    aggregation_rationale: str
    attribution_basis: str
    expected_release_as_of: str
    expected_release_recorded_at: str
    confirming_evidence: str
    falsifying_evidence: str
    correlation_group: str | None = None
    forecast_vintage: str | None = None
    parameter_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not QUARTER_PATTERN.match(self.target_quarter):
            raise ValueError("target_quarter must use YYYY-QN form")
        for field_name in (
            "metric",
            "unit",
            "quantity_semantics",
            "aggregation_rationale",
            "attribution_basis",
            "expected_release_as_of",
            "expected_release_recorded_at",
            "confirming_evidence",
            "falsifying_evidence",
        ):
            _required(getattr(self, field_name), field_name)
        _iso_date(self.expected_release_as_of, "expected_release_as_of")
        _iso_timestamp(
            self.expected_release_recorded_at,
            "expected_release_recorded_at",
        )
        if self.quantity_semantics != "quarter_total":
            raise ValueError("quantity_semantics must be quarter_total")
        if not self.claim_ids:
            raise ValueError("claim_ids must explicitly select at least one claim")
        if tuple(sorted(set(self.claim_ids))) != self.claim_ids:
            raise ValueError("claim_ids must be unique and sorted")
        if any(not item.strip() for item in self.claim_ids):
            raise ValueError("claim_ids cannot contain blanks")
        if self.aggregation_policy is AtlasAggregationPolicy.SINGLE_CLAIM:
            if len(self.claim_ids) != 1:
                raise ValueError("single_claim aggregation requires exactly one claim")
        elif len(self.claim_ids) < 2:
            raise ValueError(
                "sum_explicit_nonoverlapping_claims requires at least two claims"
            )
        if self.correlation_group is not None:
            _required(self.correlation_group, "correlation_group")

        if self.source_mode is AtlasSourceMode.CANONICAL_CAPACITY:
            if self.forecast_vintage is not None or self.parameter_fingerprint is not None:
                raise ValueError(
                    "canonical capacity selection cannot set forecast metadata"
                )
        else:
            if self.forecast_vintage is None:
                raise ValueError("forecast_vintage is required for forecast selection")
            _required(self.forecast_vintage, "forecast_vintage")
            _iso_timestamp(self.forecast_vintage, "forecast_vintage")
            if self.parameter_fingerprint is None or not SHA256_PATTERN.match(
                self.parameter_fingerprint
            ):
                raise ValueError(
                    "parameter_fingerprint must be a lowercase SHA-256 for forecast selection"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": SELECTION_FORMAT,
            "target_quarter": self.target_quarter,
            "source_mode": self.source_mode.value,
            "input_capacity_basis": self.input_capacity_basis.value,
            "metric": self.metric,
            "unit": self.unit,
            "quantity_semantics": self.quantity_semantics,
            "claim_ids": list(self.claim_ids),
            "aggregation_policy": self.aggregation_policy.value,
            "aggregation_rationale": self.aggregation_rationale,
            "attribution_basis": self.attribution_basis,
            "expected_release_as_of": self.expected_release_as_of,
            "expected_release_recorded_at": self.expected_release_recorded_at,
            "confirming_evidence": self.confirming_evidence,
            "falsifying_evidence": self.falsifying_evidence,
            "correlation_group": self.correlation_group,
            "forecast_vintage": self.forecast_vintage,
            "parameter_fingerprint": self.parameter_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class AtlasCapacityImport:
    estimate: Estimate
    evidence: tuple[Evidence, ...]
    lineage: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        estimate = self.estimate
        return {
            "format": IMPORT_FORMAT,
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
            "lineage": dict(self.lineage),
        }


def selection_from_dict(document: Mapping[str, Any]) -> AtlasCapacitySelection:
    if document.get("format") != SELECTION_FORMAT:
        raise ValueError(f"format must be {SELECTION_FORMAT}")
    allowed = {
        "format",
        "target_quarter",
        "source_mode",
        "input_capacity_basis",
        "metric",
        "unit",
        "quantity_semantics",
        "claim_ids",
        "aggregation_policy",
        "aggregation_rationale",
        "attribution_basis",
        "expected_release_as_of",
        "expected_release_recorded_at",
        "confirming_evidence",
        "falsifying_evidence",
        "correlation_group",
        "forecast_vintage",
        "parameter_fingerprint",
    }
    unexpected = set(document) - allowed
    if unexpected:
        raise ValueError(f"unexpected selection fields: {sorted(unexpected)}")

    def text_field(key: str) -> str:
        value = document.get(key)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        return value

    claim_ids = document.get("claim_ids")
    if not isinstance(claim_ids, list) or not all(
        isinstance(item, str) for item in claim_ids
    ):
        raise ValueError("claim_ids must be a list of strings")
    correlation_group = document.get("correlation_group")
    forecast_vintage = document.get("forecast_vintage")
    parameter_fingerprint = document.get("parameter_fingerprint")
    for key, value in (
        ("correlation_group", correlation_group),
        ("forecast_vintage", forecast_vintage),
        ("parameter_fingerprint", parameter_fingerprint),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be text or null")
    try:
        source_mode = AtlasSourceMode(text_field("source_mode"))
        input_basis = AtlasCapacityBasis(text_field("input_capacity_basis"))
        aggregation = AtlasAggregationPolicy(text_field("aggregation_policy"))
    except ValueError as exc:
        raise ValueError(f"invalid atlas selection enum: {exc}") from exc
    return AtlasCapacitySelection(
        target_quarter=text_field("target_quarter"),
        source_mode=source_mode,
        input_capacity_basis=input_basis,
        metric=text_field("metric"),
        unit=text_field("unit"),
        quantity_semantics=text_field("quantity_semantics"),
        claim_ids=tuple(claim_ids),
        aggregation_policy=aggregation,
        aggregation_rationale=text_field("aggregation_rationale"),
        attribution_basis=text_field("attribution_basis"),
        expected_release_as_of=text_field("expected_release_as_of"),
        expected_release_recorded_at=text_field("expected_release_recorded_at"),
        confirming_evidence=text_field("confirming_evidence"),
        falsifying_evidence=text_field("falsifying_evidence"),
        correlation_group=correlation_group,
        forecast_vintage=forecast_vintage,
        parameter_fingerprint=parameter_fingerprint,
    )


def load_atlas_selection(path: str | Path) -> AtlasCapacitySelection:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("atlas selection document must be an object")
    return selection_from_dict(document)


def _verified_file(
    release_dir: Path,
    manifest: Mapping[str, Any],
    name: str,
) -> bytes:
    files = manifest.get("files")
    if not isinstance(files, dict) or name not in files:
        raise ValueError(f"atlas manifest does not pin required file: {name}")
    metadata = files[name]
    if not isinstance(metadata, dict):
        raise ValueError(f"atlas manifest metadata is invalid for {name}")
    raw = (release_dir / name).read_bytes()
    if metadata.get("bytes") != len(raw):
        raise ValueError(f"atlas release byte count mismatch: {name}")
    digest = hashlib.sha256(raw).hexdigest()
    if metadata.get("sha256") != digest:
        raise ValueError(f"atlas release hash mismatch: {name}")
    return raw


def _csv_rows(raw: bytes, name: str) -> list[dict[str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} must use UTF-8") from exc
    return list(csv.DictReader(io.StringIO(text, newline="")))


def _jsonl_rows(raw: bytes, name: str) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {name}:{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{name}:{line_number} must contain an object")
        rows.append(value)
    return rows


def _float(row: Mapping[str, str], key: str, context: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{context}.{key} must be numeric") from exc
    if value < 0:
        raise ValueError(f"{context}.{key} must be nonnegative")
    return value


def _claim_closure(
    claims: Mapping[str, Mapping[str, Any]],
    selected_ids: tuple[str, ...],
) -> tuple[str, ...]:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visited:
            return
        if claim_id in active:
            raise ValueError(f"atlas claim dependency cycle includes {claim_id}")
        claim = claims.get(claim_id)
        if claim is None:
            raise ValueError(f"atlas release is missing selected or dependent claim: {claim_id}")
        active.add(claim_id)
        dependencies = claim.get("dependencies") or []
        if not isinstance(dependencies, list):
            raise ValueError(f"atlas claim dependencies must be a list: {claim_id}")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise ValueError(f"atlas claim dependency is invalid: {claim_id}")
            parent = dependency.get("depends_on_claim_version_id")
            if not isinstance(parent, str) or not parent:
                raise ValueError(f"atlas claim dependency lacks an ID: {claim_id}")
            visit(parent)
        active.remove(claim_id)
        visited.add(claim_id)

    for selected_id in selected_ids:
        visit(selected_id)
    return tuple(sorted(visited))


def _evidence_kind(row: Mapping[str, str]) -> EvidenceKind:
    value = " ".join(
        (row.get("source_family", ""), row.get("publisher", ""), row.get("document_url", ""))
    ).lower()
    if "nist" in value or ".gov" in value or "government" in value:
        return EvidenceKind.GOVERNMENT_RECORD
    return EvidenceKind.OTHER


def _supporting_evidence(
    *,
    evidence_rows: list[dict[str, str]],
    source_inputs: list[dict[str, Any]],
    claim_closure: tuple[str, ...],
    release_digest: str,
) -> tuple[Evidence, ...]:
    documents = {}
    for item in source_inputs:
        document_id = item.get("id")
        if not isinstance(document_id, str) or not document_id:
            raise ValueError("atlas source_inputs.json contains a document without an ID")
        if document_id in documents:
            raise ValueError(f"duplicate atlas source document ID: {document_id}")
        documents[document_id] = item

    closure = set(claim_closure)
    selected_rows = [
        row
        for row in evidence_rows
        if row.get("claim_id") in closure and row.get("role") == "support"
    ]
    evidence = []
    seen_ids = set()
    for row in sorted(
        selected_rows,
        key=lambda item: (item.get("claim_id", ""), item.get("evidence_link_id", "")),
    ):
        link_id = row.get("evidence_link_id", "")
        _required(link_id, "evidence_link_id")
        evidence_id = f"atlas:{release_digest[:12]}:{link_id}"
        if evidence_id in seen_ids:
            raise ValueError(f"duplicate atlas evidence link ID: {link_id}")
        seen_ids.add(evidence_id)
        document_id = row.get("source_document_id", "")
        document = documents.get(document_id)
        if document is None:
            raise ValueError(f"atlas evidence references missing source document: {document_id}")
        source_url = row.get("document_url", "")
        publisher = row.get("publisher", "")
        retrieved_at = row.get("retrieved_at", "")
        for value, field_name in (
            (source_url, "document_url"),
            (publisher, "publisher"),
            (retrieved_at, "retrieved_at"),
        ):
            _required(value, field_name)
        title = document.get("title")
        if not isinstance(title, str) or not title.strip():
            title = source_url
        evidence.append(
            Evidence(
                id=evidence_id,
                kind=_evidence_kind(row),
                title=title,
                source_url=source_url,
                publisher=publisher,
                retrieved_at=retrieved_at,
                published_at=row.get("published_at") or None,
                source_family=row.get("source_family") or None,
                license=row.get("license") or None,
                excerpt=row.get("excerpt") or None,
                content_hash=row.get("content_sha256") or None,
            )
        )
    if not evidence:
        raise ValueError("selected atlas claims do not resolve to supporting evidence")
    return tuple(evidence)


def _capacity_metadata(
    rows: list[dict[str, str]],
    selection: AtlasCapacitySelection,
) -> tuple[list[dict[str, str]], float, EstimatePosture]:
    by_claim: dict[str, dict[str, str]] = {}
    for row in rows:
        claim_id = row.get("claim_id", "")
        if claim_id in by_claim:
            raise ValueError(f"duplicate atlas capacity claim row: {claim_id}")
        by_claim[claim_id] = row
    selected = []
    confidences = []
    claim_kinds = []
    for claim_id in selection.claim_ids:
        row = by_claim.get(claim_id)
        if row is None:
            raise ValueError(f"selected claim is absent from capacity.csv: {claim_id}")
        if row.get("metric") != selection.metric:
            raise ValueError(f"atlas metric mismatch for claim {claim_id}")
        if row.get("unit") != selection.unit:
            raise ValueError(f"atlas unit mismatch for claim {claim_id}")
        if row.get("basis") != selection.input_capacity_basis.value:
            raise ValueError(f"atlas capacity-basis mismatch for claim {claim_id}")
        confidence = _float(row, "confidence", f"capacity[{claim_id}]")
        if confidence > 1:
            raise ValueError(f"atlas confidence exceeds one for claim {claim_id}")
        confidences.append(confidence)
        claim_kinds.append(row.get("claim_kind", ""))
        selected.append(row)
    posture = (
        EstimatePosture.REPORTED
        if all(
            item in {"source_statement", "direct_observation"}
            for item in claim_kinds
        )
        else EstimatePosture.DERIVED
    )
    return selected, min(confidences), posture


def _canonical_values(
    rows: list[dict[str, str]],
    selection: AtlasCapacitySelection,
) -> tuple[float, float, float, list[dict[str, str]]]:
    quarter_start, quarter_end = _quarter_bounds(selection.target_quarter)
    values = []
    for row in rows:
        claim_id = row["claim_id"]
        try:
            period_start = date.fromisoformat(row.get("period_start", ""))
            period_end = date.fromisoformat(row.get("period_end", ""))
        except ValueError as exc:
            raise ValueError(
                f"canonical capacity claim must have an exact period: {claim_id}"
            ) from exc
        if period_start != quarter_start or period_end != quarter_end:
            raise ValueError(
                f"canonical capacity claim does not exactly cover {selection.target_quarter}: "
                f"{claim_id}"
            )
        values.append(
            (
                _float(row, "low", f"capacity[{claim_id}]"),
                _float(row, "base", f"capacity[{claim_id}]"),
                _float(row, "high", f"capacity[{claim_id}]"),
            )
        )
        if not values[-1][0] <= values[-1][1] <= values[-1][2]:
            raise ValueError(f"atlas capacity range is unordered for claim {claim_id}")
    return (
        sum(item[0] for item in values),
        sum(item[1] for item in values),
        sum(item[2] for item in values),
        rows,
    )


def _forecast_values(
    rows: list[dict[str, str]],
    selection: AtlasCapacitySelection,
) -> tuple[float, float, float, list[dict[str, str]]]:
    selected = []
    for claim_id in selection.claim_ids:
        matches = [
            row
            for row in rows
            if row.get("capacity_claim_id") == claim_id
            and row.get("quarter") == selection.target_quarter
        ]
        if len(matches) != 1:
            raise ValueError(
                f"forecast must have exactly one target-quarter row for claim {claim_id}"
            )
        row = matches[0]
        expected = {
            "forecast_vintage": selection.forecast_vintage,
            "parameter_fingerprint": selection.parameter_fingerprint,
            "input_basis": selection.input_capacity_basis.value,
            "output_basis": AtlasCapacityBasis.ECONOMICALLY_USABLE.value,
            "quantity_semantics": "quarter_total",
            "metric": selection.metric,
            "unit": selection.unit,
        }
        for key, value in expected.items():
            if row.get(key) != value:
                raise ValueError(f"forecast {key} mismatch for claim {claim_id}")
        selected.append(row)
    values = []
    for row in selected:
        claim_id = row["capacity_claim_id"]
        value = (
            _float(row, "p10", f"forecast[{claim_id}]"),
            _float(row, "p50", f"forecast[{claim_id}]"),
            _float(row, "p90", f"forecast[{claim_id}]"),
        )
        if not value[0] <= value[1] <= value[2]:
            raise ValueError(f"atlas forecast range is unordered for claim {claim_id}")
        values.append(value)
    return (
        sum(item[0] for item in values),
        sum(item[1] for item in values),
        sum(item[2] for item in values),
        selected,
    )


def load_atlas_capacity(
    release_dir: str | Path,
    selection: AtlasCapacitySelection,
) -> AtlasCapacityImport:
    root = Path(release_dir)
    manifest_raw = (root / "manifest.json").read_bytes()
    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("atlas manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("atlas manifest must be an object")
    if manifest.get("format") != ATLAS_RELEASE_FORMAT:
        raise ValueError(f"atlas format must be {ATLAS_RELEASE_FORMAT}")
    if manifest.get("as_of") != selection.expected_release_as_of:
        raise ValueError("atlas release as_of does not match the pinned selection")
    if manifest.get("recorded_at") != selection.expected_release_recorded_at:
        raise ValueError("atlas release recorded_at does not match the pinned selection")
    manifest_digest = hashlib.sha256(manifest_raw).hexdigest()

    capacity_rows = _csv_rows(
        _verified_file(root, manifest, "capacity.csv"), "capacity.csv"
    )
    evidence_rows = _csv_rows(
        _verified_file(root, manifest, "evidence.csv"), "evidence.csv"
    )
    claims_rows = _jsonl_rows(
        _verified_file(root, manifest, "claims.jsonl"), "claims.jsonl"
    )
    source_inputs_raw = _verified_file(root, manifest, "source_inputs.json")
    try:
        source_inputs = json.loads(source_inputs_raw)
    except json.JSONDecodeError as exc:
        raise ValueError("source_inputs.json is invalid JSON") from exc
    if not isinstance(source_inputs, list) or not all(
        isinstance(item, dict) for item in source_inputs
    ):
        raise ValueError("source_inputs.json must contain a list of objects")

    claims: dict[str, Mapping[str, Any]] = {}
    for row in claims_rows:
        claim_id = row.get("id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("claims.jsonl contains a claim without an ID")
        if claim_id in claims:
            raise ValueError(f"duplicate atlas claim ID: {claim_id}")
        claims[claim_id] = row
    closure = _claim_closure(claims, selection.claim_ids)
    selected_capacity_rows, confidence, direct_posture = _capacity_metadata(
        capacity_rows,
        selection,
    )

    if selection.source_mode is AtlasSourceMode.CANONICAL_CAPACITY:
        low, base, high, selected_rows = _canonical_values(
            selected_capacity_rows,
            selection,
        )
        posture = direct_posture
        source_description = (
            "exact-quarter canonical capacity rows; low/base/high were summed without "
            "capacity-basis conversion"
        )
    else:
        forecast_rows = _csv_rows(
            _verified_file(root, manifest, QUARTERLY_FORECAST_FILE),
            QUARTERLY_FORECAST_FILE,
        )
        low, base, high, selected_rows = _forecast_values(forecast_rows, selection)
        posture = EstimatePosture.MODELED
        source_description = (
            "quarter-total forecast rows; P10/P50/P90 were mapped to low/base/high and "
            "summed without a diversification adjustment"
        )

    if not low <= base <= high:
        raise ValueError("aggregated atlas capacity must satisfy low <= base <= high")
    evidence = _supporting_evidence(
        evidence_rows=evidence_rows,
        source_inputs=source_inputs,
        claim_closure=closure,
        release_digest=manifest_digest,
    )
    method = (
        f"Imported {selection.target_quarter} {selection.metric} from a pinned Semiconductor "
        f"Atlas release using {source_description}. Aggregation policy: "
        f"{selection.aggregation_policy.value}. Attribution basis: "
        f"{selection.attribution_basis}. Rationale: {selection.aggregation_rationale}"
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
        evidence_ids=tuple(item.id for item in evidence),
        confirming_evidence=selection.confirming_evidence,
        falsifying_evidence=selection.falsifying_evidence,
        correlation_group=selection.correlation_group,
    )
    lineage = {
        "atlas_release": {
            "format": ATLAS_RELEASE_FORMAT,
            "manifest_sha256": manifest_digest,
            "as_of": manifest["as_of"],
            "recorded_at": manifest["recorded_at"],
        },
        "selection": selection.as_dict(),
        "selected_claim_ids": list(selection.claim_ids),
        "claim_dependency_closure": list(closure),
        "selected_source_rows": selected_rows,
        "quantity_semantics": "quarter_total",
    }
    return AtlasCapacityImport(estimate=estimate, evidence=evidence, lineage=lineage)
