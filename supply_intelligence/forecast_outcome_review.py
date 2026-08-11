"""Outcome attachment and explicit-unobservability review for frozen forecasts."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .forecast_registry import (
    FORECAST_REGISTRY_RESULT_FORMAT,
    _date,
    _identifier,
    _mapping,
    _number,
    _only,
    _required_text,
    _resolve_under,
    _sha256,
    _timestamp,
)


FORECAST_OUTCOME_REVIEW_FORMAT = "ai-supply-forecast-outcome-review.v1"
FORECAST_OUTCOME_REVIEW_RESULT_FORMAT = "ai-supply-forecast-outcome-review-result.v1"
FORECAST_REGISTRY_RELEASE_FORMAT = "ai-supply-forecast-registry-release.v1"
DISPOSITION_STATUSES = {"pending", "observed", "not_comparable", "unobservable"}
OUTCOME_POSTURES = {"reported", "derived"}
MISMATCH_DIMENSIONS = {
    "entity",
    "product",
    "geography",
    "period",
    "stage",
    "quantity_semantics",
    "aggregation",
    "unit",
    "cutoff",
}
UNOBSERVABLE_REASONS = {
    "no_public_disclosure",
    "scope_not_disclosed",
    "source_access_unavailable",
    "evidence_conflict_unresolved",
}


def _release_file(
    release_dir: Path,
    manifest: Mapping[str, Any],
    filename: Any,
    expected_sha: Any,
    path: str,
) -> tuple[str, bytes, str]:
    relative, source = _resolve_under(release_dir, filename, f"{path}.file")
    if source == release_dir or not source.is_file():
        raise ValueError(f"{path}.file must identify an existing release file")
    expected = _sha256(expected_sha, f"{path}.sha256")
    files = _mapping(manifest.get("files"), "registry release manifest.files")
    entry = _mapping(files.get(relative), f"registry release manifest.files.{relative}")
    manifest_sha = _sha256(
        entry.get("sha256"), f"registry release manifest.files.{relative}.sha256"
    )
    manifest_bytes = entry.get("bytes")
    if isinstance(manifest_bytes, bool) or not isinstance(manifest_bytes, int):
        raise ValueError(f"registry release manifest.files.{relative}.bytes must be an integer")
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected or actual != manifest_sha:
        raise ValueError(f"{path} SHA-256 mismatch")
    if len(raw) != manifest_bytes:
        raise ValueError(f"{path} byte count mismatch")
    return relative, raw, actual


def _load_evidence(
    value: Any,
    path: str,
    *,
    root: Path,
    recorded_at,
) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "path",
            "sha256",
            "kind",
            "title",
            "source_url",
            "publisher",
            "published_at",
            "retrieved_at",
            "source_family",
            "license",
            "excerpt",
        },
        path,
    )
    evidence_id = _identifier(data.get("id"), f"{path}.id")
    relative, source = _resolve_under(root, data.get("path"), f"{path}.path")
    if source == root or not source.is_file():
        raise ValueError(f"{path}.path must identify an existing source file")
    raw = source.read_bytes()
    expected_sha = _sha256(data.get("sha256"), f"{path}.sha256")
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError(f"{path} SHA-256 mismatch")
    published = _date(data.get("published_at"), f"{path}.published_at")
    retrieved = _timestamp(data.get("retrieved_at"), f"{path}.retrieved_at")
    if published > retrieved.date():
        raise ValueError(f"{path} was retrieved before publication")
    if retrieved > recorded_at:
        raise ValueError(f"{path} was retrieved after review.recorded_at")
    license_value = data.get("license")
    if license_value is not None:
        license_value = _required_text(license_value, f"{path}.license")
    return {
        "id": evidence_id,
        "path": relative,
        "sha256": expected_sha,
        "raw": raw,
        "kind": _required_text(data.get("kind"), f"{path}.kind"),
        "title": _required_text(data.get("title"), f"{path}.title"),
        "source_url": _required_text(data.get("source_url"), f"{path}.source_url"),
        "publisher": _required_text(data.get("publisher"), f"{path}.publisher"),
        "published_at": published.isoformat(),
        "retrieved_at": retrieved.isoformat().replace("+00:00", "Z"),
        "source_family": _required_text(
            data.get("source_family"), f"{path}.source_family"
        ),
        "license": license_value,
        "excerpt": _required_text(data.get("excerpt"), f"{path}.excerpt"),
    }


def _pinball(prediction: float, actual: float, probability: float) -> float:
    error = actual - prediction
    return probability * error if error >= 0 else (1 - probability) * -error


def _score(forecast: Mapping[str, Any], actual: float) -> dict[str, Any]:
    distribution = forecast["distribution"]
    p10 = distribution["p10"]
    p50 = distribution["p50"]
    p90 = distribution["p90"]
    pinball = {
        "p10": _pinball(p10, actual, 0.10),
        "p50": _pinball(p50, actual, 0.50),
        "p90": _pinball(p90, actual, 0.90),
    }
    event_score = None
    if forecast.get("event") is not None:
        event = forecast["event"]
        probability = event["forecast_probability"]
        realized = (
            actual >= event["threshold"]
            if event["operator"] == "at_least"
            else actual <= event["threshold"]
        )
        event_score = {
            "operator": event["operator"],
            "threshold": event["threshold"],
            "unit": event["unit"],
            "forecast_probability": probability,
            "probability_method": event["probability_method"],
            "realized": realized,
            "brier_score": (probability - float(realized)) ** 2,
        }
    return {
        "forecast_p10": p10,
        "forecast_p50": p50,
        "forecast_p90": p90,
        "actual_value": actual,
        "inside_p10_p90": p10 <= actual <= p90,
        "signed_error": p50 - actual,
        "absolute_error": abs(p50 - actual),
        "interval_miss": max(p10 - actual, actual - p90, 0.0),
        "pinball_loss": pinball,
        "event_score": event_score,
    }


def load_forecast_outcome_review(
    review_path: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ValueError("source_root must be an existing directory")
    source = Path(review_path).resolve()
    if source != root and root not in source.parents:
        raise ValueError("review must be below source_root")
    raw = source.read_bytes()
    try:
        document = _mapping(json.loads(raw), "forecast outcome review")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid forecast outcome review JSON: {exc}") from exc
    if document.get("format") != FORECAST_OUTCOME_REVIEW_FORMAT:
        raise ValueError(f"review format must be {FORECAST_OUTCOME_REVIEW_FORMAT}")
    _only(
        document,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "registry_release",
            "evidence",
            "dispositions",
            "notes",
        },
        "forecast outcome review",
    )
    review_id = _identifier(document.get("id"), "review.id")
    as_of = _date(document.get("as_of_date"), "review.as_of_date")
    recorded = _timestamp(document.get("recorded_at"), "review.recorded_at")
    if as_of > recorded.date():
        raise ValueError("review.as_of_date cannot follow review.recorded_at")

    registry_selection = _mapping(document.get("registry_release"), "registry_release")
    _only(
        registry_selection,
        {
            "path",
            "manifest_sha256",
            "manifest_format",
            "result_file",
            "result_sha256",
            "result_format",
            "registry_file",
            "registry_sha256",
            "registry_id",
        },
        "registry_release",
    )
    registry_relative, registry_dir = _resolve_under(
        root, registry_selection.get("path"), "registry_release.path"
    )
    if not registry_dir.is_dir():
        raise ValueError("registry_release.path must identify an existing directory")
    manifest_raw = (registry_dir / "manifest.json").read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_sha != _sha256(
        registry_selection.get("manifest_sha256"),
        "registry_release.manifest_sha256",
    ):
        raise ValueError("registry release manifest SHA-256 mismatch")
    try:
        manifest = _mapping(json.loads(manifest_raw), "registry release manifest")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid registry release manifest JSON: {exc}") from exc
    expected_manifest_format = _required_text(
        registry_selection.get("manifest_format"),
        "registry_release.manifest_format",
    )
    if expected_manifest_format != FORECAST_REGISTRY_RELEASE_FORMAT:
        raise ValueError(
            f"outcome review v1 supports only {FORECAST_REGISTRY_RELEASE_FORMAT}"
        )
    if manifest.get("format") != expected_manifest_format:
        raise ValueError("registry release manifest format mismatch")
    result_relative, result_raw, result_sha = _release_file(
        registry_dir,
        manifest,
        registry_selection.get("result_file"),
        registry_selection.get("result_sha256"),
        "registry_release.result",
    )
    source_registry_relative, source_registry_raw, source_registry_sha = _release_file(
        registry_dir,
        manifest,
        registry_selection.get("registry_file"),
        registry_selection.get("registry_sha256"),
        "registry_release.registry",
    )
    try:
        registry_result = _mapping(json.loads(result_raw), "registry result")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid registry result JSON: {exc}") from exc
    expected_result_format = _required_text(
        registry_selection.get("result_format"), "registry_release.result_format"
    )
    if expected_result_format != FORECAST_REGISTRY_RESULT_FORMAT:
        raise ValueError(
            f"outcome review v1 supports only {FORECAST_REGISTRY_RESULT_FORMAT}"
        )
    if registry_result.get("format") != expected_result_format:
        raise ValueError("registry result format mismatch")
    registry_metadata = _mapping(registry_result.get("registry"), "registry result.registry")
    registry_id = _required_text(
        registry_selection.get("registry_id"), "registry_release.registry_id"
    )
    if registry_metadata.get("id") != registry_id or manifest.get("registry_id") != registry_id:
        raise ValueError("registry ID mismatch")
    registry_recorded = _timestamp(
        registry_metadata.get("recorded_at"), "registry result.registry.recorded_at"
    )
    if registry_recorded >= recorded:
        raise ValueError("registry release must predate review.recorded_at")
    registry_as_of = _date(
        registry_metadata.get("as_of_date"), "registry result.registry.as_of_date"
    )
    if as_of < registry_as_of:
        raise ValueError("review.as_of_date predates the frozen registry")
    source_metadata = _mapping(registry_result.get("source"), "registry result.source")
    source_synthetic = source_metadata.get("synthetic")
    if not isinstance(source_synthetic, bool):
        raise ValueError("registry result.source.synthetic must be boolean")

    evidence_values = document.get("evidence")
    if not isinstance(evidence_values, list):
        raise ValueError("review.evidence must be an array")
    evidence = [
        _load_evidence(
            value,
            f"evidence[{index}]",
            root=root,
            recorded_at=recorded,
        )
        for index, value in enumerate(evidence_values)
    ]
    evidence_ids = [item["id"] for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate review evidence id")
    evidence_by_id = {item["id"]: item for item in evidence}
    if any(date.fromisoformat(item["published_at"]) > as_of for item in evidence):
        raise ValueError("review evidence was published after review.as_of_date")

    forecast_values = registry_result.get("forecasts")
    if not isinstance(forecast_values, list) or not forecast_values:
        raise ValueError("registry result requires forecasts")
    forecasts = {}
    for index, value in enumerate(forecast_values):
        forecast = _mapping(value, f"registry forecasts[{index}]")
        forecast_id = _identifier(forecast.get("id"), f"registry forecasts[{index}].id")
        if forecast_id in forecasts:
            raise ValueError(f"duplicate registry forecast id: {forecast_id}")
        forecasts[forecast_id] = forecast

    disposition_values = document.get("dispositions")
    if not isinstance(disposition_values, list) or not disposition_values:
        raise ValueError("review.dispositions requires one row per forecast")
    dispositions = []
    seen: set[str] = set()
    for index, value in enumerate(disposition_values):
        path = f"dispositions[{index}]"
        disposition = _mapping(value, path)
        common = {
            "id",
            "forecast_id",
            "status",
            "reviewer",
            "reviewed_at",
            "rationale",
        }
        status = _required_text(disposition.get("status"), f"{path}.status")
        if status not in DISPOSITION_STATUSES:
            raise ValueError(f"{path}.status is unsupported")
        extras = {
            "observed": {
                "actual_value",
                "unit",
                "posture",
                "observed_at",
                "source_family",
                "evidence_ids",
                "methodology",
                "revision_risk",
            },
            "not_comparable": {
                "evidence_ids",
                "candidate_description",
                "mismatch_dimensions",
            },
            "unobservable": {"reason_code", "search_summary"},
            "pending": set(),
        }[status]
        _only(disposition, common | extras, path)
        disposition_id = _identifier(disposition.get("id"), f"{path}.id")
        forecast_id = _identifier(disposition.get("forecast_id"), f"{path}.forecast_id")
        forecast = forecasts.get(forecast_id)
        if forecast is None:
            raise ValueError(f"{path} references a missing forecast")
        if forecast_id in seen:
            raise ValueError(f"duplicate disposition forecast: {forecast_id}")
        seen.add(forecast_id)
        reviewed_at = _timestamp(disposition.get("reviewed_at"), f"{path}.reviewed_at")
        if reviewed_at < registry_recorded or reviewed_at > recorded:
            raise ValueError(f"{path}.reviewed_at must fall between registry and review recording")
        contract = _mapping(forecast.get("outcome_contract"), f"forecast {forecast_id}.outcome_contract")
        target = _mapping(forecast.get("target"), f"forecast {forecast_id}.target")
        earliest = _date(contract.get("earliest_observed_at"), "outcome earliest_observed_at")
        expected = _date(contract.get("expected_evidence_by"), "outcome expected_evidence_by")
        cutoff = _date(target.get("cutoff_date"), "forecast target.cutoff_date")
        base = {
            "id": disposition_id,
            "forecast_id": forecast_id,
            "metric": _required_text(forecast.get("metric"), f"forecast {forecast_id}.metric"),
            "metric_class": _required_text(
                forecast.get("metric_class"), f"forecast {forecast_id}.metric_class"
            ),
            "period": _required_text(forecast.get("period"), f"forecast {forecast_id}.period"),
            "unit": _required_text(forecast.get("unit"), f"forecast {forecast_id}.unit"),
            "status": status,
            "reviewer": _required_text(disposition.get("reviewer"), f"{path}.reviewer"),
            "reviewed_at": reviewed_at.isoformat().replace("+00:00", "Z"),
            "rationale": _required_text(disposition.get("rationale"), f"{path}.rationale"),
            "score": None,
            "eligible_for_model_calibration": False,
        }
        if status == "pending":
            if as_of > expected:
                raise ValueError(f"overdue forecast requires explicit disposition: {forecast_id}")
            base["calendar_status"] = (
                "pending_period_end"
                if as_of <= cutoff
                else "awaiting_outcome"
            )
        elif status == "unobservable":
            if as_of <= expected:
                raise ValueError(f"{path} cannot declare unobservable before expected evidence date")
            reason = _required_text(disposition.get("reason_code"), f"{path}.reason_code")
            if reason not in UNOBSERVABLE_REASONS:
                raise ValueError(f"{path}.reason_code is unsupported")
            base.update(
                {
                    "calendar_status": "closed_unobservable",
                    "reason_code": reason,
                    "search_summary": _required_text(
                        disposition.get("search_summary"), f"{path}.search_summary"
                    ),
                }
            )
        elif status == "not_comparable":
            if as_of < earliest:
                raise ValueError(f"{path} cannot review outcome evidence before the observation window")
            ids = disposition.get("evidence_ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
                raise ValueError(f"{path}.evidence_ids requires at least one evidence record")
            if len(ids) != len(set(ids)):
                raise ValueError(f"{path}.evidence_ids contains duplicates")
            missing = set(ids) - set(evidence_by_id)
            if missing:
                raise ValueError(f"{path} references missing evidence: {sorted(missing)}")
            dimensions = disposition.get("mismatch_dimensions")
            if not isinstance(dimensions, list) or not dimensions or not all(
                isinstance(item, str) and item in MISMATCH_DIMENSIONS for item in dimensions
            ):
                raise ValueError(f"{path}.mismatch_dimensions is invalid")
            if len(dimensions) != len(set(dimensions)):
                raise ValueError(f"{path}.mismatch_dimensions contains duplicates")
            if any(
                _timestamp(evidence_by_id[item]["retrieved_at"], "evidence retrieved_at")
                > reviewed_at
                for item in ids
            ):
                raise ValueError(f"{path}.reviewed_at predates evidence retrieval")
            base.update(
                {
                    "calendar_status": "closed_not_comparable",
                    "evidence_ids": list(ids),
                    "candidate_description": _required_text(
                        disposition.get("candidate_description"),
                        f"{path}.candidate_description",
                    ),
                    "mismatch_dimensions": list(dimensions),
                }
            )
        else:
            if as_of < earliest:
                raise ValueError(f"{path} cannot attach an outcome before the observation window")
            unit = _required_text(disposition.get("unit"), f"{path}.unit")
            if unit != base["unit"]:
                raise ValueError(f"{path}.unit does not match the frozen forecast")
            actual = _number(disposition.get("actual_value"), f"{path}.actual_value")
            if actual < 0:
                raise ValueError(f"{path}.actual_value cannot be negative")
            posture = _required_text(disposition.get("posture"), f"{path}.posture")
            if posture not in OUTCOME_POSTURES:
                raise ValueError(f"{path}.posture must be reported or derived")
            observed = _date(disposition.get("observed_at"), f"{path}.observed_at")
            if observed < earliest or observed > as_of:
                raise ValueError(f"{path}.observed_at falls outside the review window")
            ids = disposition.get("evidence_ids")
            if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
                raise ValueError(f"{path}.evidence_ids requires at least one evidence record")
            if len(ids) != len(set(ids)):
                raise ValueError(f"{path}.evidence_ids contains duplicates")
            missing = set(ids) - set(evidence_by_id)
            if missing:
                raise ValueError(f"{path} references missing evidence: {sorted(missing)}")
            family = _required_text(
                disposition.get("source_family"), f"{path}.source_family"
            )
            if {evidence_by_id[item]["source_family"] for item in ids} != {family}:
                raise ValueError(f"{path}.source_family does not match its evidence")
            if any(
                date.fromisoformat(evidence_by_id[item]["published_at"]) > observed
                for item in ids
            ):
                raise ValueError(f"{path}.observed_at predates its evidence publication")
            if any(
                _timestamp(evidence_by_id[item]["retrieved_at"], "evidence retrieved_at")
                > reviewed_at
                for item in ids
            ):
                raise ValueError(f"{path}.reviewed_at predates evidence retrieval")
            base.update(
                {
                    "calendar_status": "observed_and_scored",
                    "actual_value": actual,
                    "posture": posture,
                    "observed_at": observed.isoformat(),
                    "source_family": family,
                    "evidence_ids": list(ids),
                    "methodology": _required_text(
                        disposition.get("methodology"), f"{path}.methodology"
                    ),
                    "revision_risk": _required_text(
                        disposition.get("revision_risk"), f"{path}.revision_risk"
                    ),
                    "score": _score(forecast, actual),
                    "eligible_for_evidence_backed_scoring": not source_synthetic,
                }
            )
        dispositions.append(base)

    missing_dispositions = set(forecasts) - seen
    if missing_dispositions:
        raise ValueError(
            f"review lacks dispositions for forecasts: {sorted(missing_dispositions)}"
        )
    return {
        "review": {
            "format": FORECAST_OUTCOME_REVIEW_FORMAT,
            "id": review_id,
            "as_of_date": as_of.isoformat(),
            "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
            "notes": _required_text(document.get("notes"), "review.notes"),
            "path": source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
        },
        "registry": {
            "path": registry_relative,
            "manifest_format": expected_manifest_format,
            "manifest_sha256": manifest_sha,
            "manifest_raw": manifest_raw,
            "result_file": result_relative,
            "result_format": expected_result_format,
            "result_sha256": result_sha,
            "result_raw": result_raw,
            "registry_file": source_registry_relative,
            "registry_sha256": source_registry_sha,
            "registry_raw": source_registry_raw,
            "registry_id": registry_id,
            "recorded_at": registry_recorded.isoformat().replace("+00:00", "Z"),
            "synthetic": source_synthetic,
            "forecast_count": len(forecasts),
        },
        "evidence": evidence,
        "dispositions": dispositions,
    }


def build_forecast_outcome_review_result(case: Mapping[str, Any]) -> dict[str, Any]:
    review = case["review"]
    registry = case["registry"]
    dispositions = case["dispositions"]
    status_counts: dict[str, int] = {}
    for item in dispositions:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    scores = [item for item in dispositions if item["score"] is not None]
    return {
        "format": FORECAST_OUTCOME_REVIEW_RESULT_FORMAT,
        "review": {
            key: value for key, value in review.items() if key not in {"raw", "path"}
        },
        "registry": {
            key: value
            for key, value in registry.items()
            if key not in {"manifest_raw", "result_raw", "registry_raw"}
        },
        "summary": {
            "forecast_count": registry["forecast_count"],
            "disposition_count": len(dispositions),
            "disposition_status_counts": status_counts,
            "score_count": len(scores),
            "interval_coverage_rate": (
                sum(item["score"]["inside_p10_p90"] for item in scores) / len(scores)
                if scores
                else None
            ),
            "source_synthetic": registry["synthetic"],
            "eligible_for_model_calibration": False,
        },
        "dispositions": dispositions,
        "evidence": [
            {key: value for key, value in item.items() if key != "raw"}
            for item in case["evidence"]
        ],
        "methodology": {
            "complete_coverage": "Every frozen forecast requires exactly one disposition, preventing selective scoring of convenient outcomes.",
            "pending": "A pending row becomes invalid after its expected evidence date; it must then be observed, scope-mismatched, or explicitly unobservable.",
            "observed": "Only reported or derived, scope-reviewed outcomes with hash-pinned evidence receive interval, pinball, and exact-draw event scores.",
            "not_comparable": "Candidate evidence is retained with explicit mismatch dimensions and receives no numeric score.",
            "unobservable": "Unobservability can be closed only after the frozen expected evidence date and receives no numeric score.",
            "calibration": "No review automatically calibrates a model. Synthetic source forecasts remain ineligible even when descriptively scored.",
        },
        "warnings": [
            "The frozen registry source is synthetic; any observed score is diagnostic, not evidence of an investable or production-grade forecast."
            if registry["synthetic"]
            else "Observed scores still require calibration minimum history and holdout review.",
            "Capacity announcements, construction progress, and directional statements must be marked not comparable unless they satisfy the frozen quantity scope.",
        ],
    }
