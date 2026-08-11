"""Evidence-backed scoring of reported guidance against later company results."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping


GUIDANCE_BACKTEST_CASE_FORMAT = "ai-supply-guidance-backtest-case.v1"
GUIDANCE_OBSERVATION_FORMAT = "ai-supply-reported-guidance-observation.v1"
OUTCOME_OBSERVATION_FORMAT = "ai-supply-reported-outcome-observation.v1"
GUIDANCE_BACKTEST_RESULT_FORMAT = "ai-supply-guidance-backtest-result.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RANGE_SEMANTICS = {"management_range", "approximate_point"}


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _optional_text(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, path)


def _identifier(value: Any, path: str) -> str:
    text = _required_text(value, path)
    if ID_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{path} must use lowercase letters, digits, and hyphens")
    return text


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _date(value: Any, path: str) -> date:
    text = _required_text(value, path)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _timestamp(value: Any, path: str) -> datetime:
    text = _required_text(value, path)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if result.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return result.astimezone(timezone.utc)


def _sha256(value: Any, path: str) -> str:
    text = _required_text(value, path)
    if SHA256_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return text


def _resolve_under(root: Path, value: Any, path: str) -> tuple[str, Path]:
    text = _required_text(value, path)
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{path} must be below source_root")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{path} escapes source_root")
    return relative.as_posix(), resolved


def _json_document(raw: bytes, path: str) -> dict[str, Any]:
    try:
        return dict(_mapping(json.loads(raw), path))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def _read_pinned(
    root: Path,
    value: Any,
    path: str,
) -> tuple[str, bytes, dict[str, Any], str]:
    descriptor = _mapping(value, path)
    _only(descriptor, {"path", "sha256"}, path)
    relative, source = _resolve_under(root, descriptor.get("path"), f"{path}.path")
    expected = _sha256(descriptor.get("sha256"), f"{path}.sha256")
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"{path} SHA-256 mismatch: expected {expected}, got {actual}")
    return relative, raw, _json_document(raw, str(source)), expected


def _entity(value: Any, path: str) -> dict[str, str]:
    data = _mapping(value, path)
    _only(data, {"id", "name", "ticker"}, path)
    return {
        "id": _identifier(data.get("id"), f"{path}.id"),
        "name": _required_text(data.get("name"), f"{path}.name"),
        "ticker": _required_text(data.get("ticker"), f"{path}.ticker"),
    }


def _period(value: Any, path: str) -> dict[str, str]:
    data = _mapping(value, path)
    _only(data, {"label", "start", "end"}, path)
    start = _date(data.get("start"), f"{path}.start")
    end = _date(data.get("end"), f"{path}.end")
    if end <= start:
        raise ValueError(f"{path}.end must follow start")
    return {
        "label": _required_text(data.get("label"), f"{path}.label"),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _source(
    value: Any,
    path: str,
    *,
    captured_at: datetime,
    recorded_at: datetime,
) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
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
    published_at = _date(data.get("published_at"), f"{path}.published_at")
    retrieved_at = _timestamp(data.get("retrieved_at"), f"{path}.retrieved_at")
    if retrieved_at.date() < published_at:
        raise ValueError(f"{path} was retrieved before publication")
    if captured_at < retrieved_at:
        raise ValueError(f"{path} cannot be captured before retrieval")
    if captured_at > recorded_at:
        raise ValueError(f"{path} was captured after case.recorded_at")
    return {
        "source_url": _required_text(data.get("source_url"), f"{path}.source_url"),
        "publisher": _required_text(data.get("publisher"), f"{path}.publisher"),
        "published_at": published_at.isoformat(),
        "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
        "source_family": _required_text(
            data.get("source_family"),
            f"{path}.source_family",
        ),
        "license": _optional_text(data.get("license"), f"{path}.license"),
        "excerpt": _required_text(data.get("excerpt"), f"{path}.excerpt"),
    }


def _guidance_metric(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "label",
            "metric_class",
            "basis",
            "low",
            "midpoint",
            "high",
            "unit",
            "range_semantics",
            "methodology",
        },
        path,
    )
    low = _number(data.get("low"), f"{path}.low")
    midpoint = _number(data.get("midpoint"), f"{path}.midpoint")
    high = _number(data.get("high"), f"{path}.high")
    if low < 0 or not low <= midpoint <= high:
        raise ValueError(f"{path} must satisfy 0 <= low <= midpoint <= high")
    semantics = _required_text(data.get("range_semantics"), f"{path}.range_semantics")
    if semantics not in RANGE_SEMANTICS:
        raise ValueError(f"{path}.range_semantics is unsupported")
    if semantics == "approximate_point" and not low == midpoint == high:
        raise ValueError(f"{path} approximate_point must have identical values")
    return {
        "id": _identifier(data.get("id"), f"{path}.id"),
        "label": _required_text(data.get("label"), f"{path}.label"),
        "metric_class": _required_text(
            data.get("metric_class"),
            f"{path}.metric_class",
        ),
        "basis": _required_text(data.get("basis"), f"{path}.basis"),
        "low": low,
        "midpoint": midpoint,
        "high": high,
        "unit": _required_text(data.get("unit"), f"{path}.unit"),
        "range_semantics": semantics,
        "methodology": _required_text(
            data.get("methodology"),
            f"{path}.methodology",
        ),
    }


def _outcome_metric(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "label",
            "metric_class",
            "basis",
            "value",
            "unit",
            "methodology",
            "revision_risk",
        },
        path,
    )
    actual = _number(data.get("value"), f"{path}.value")
    if actual < 0:
        raise ValueError(f"{path}.value cannot be negative")
    return {
        "id": _identifier(data.get("id"), f"{path}.id"),
        "label": _required_text(data.get("label"), f"{path}.label"),
        "metric_class": _required_text(
            data.get("metric_class"),
            f"{path}.metric_class",
        ),
        "basis": _required_text(data.get("basis"), f"{path}.basis"),
        "value": actual,
        "unit": _required_text(data.get("unit"), f"{path}.unit"),
        "methodology": _required_text(
            data.get("methodology"),
            f"{path}.methodology",
        ),
        "revision_risk": _required_text(
            data.get("revision_risk"),
            f"{path}.revision_risk",
        ),
    }


def _observation(
    document: Mapping[str, Any],
    *,
    expected_format: str,
    recorded_at: datetime,
    path: str,
) -> dict[str, Any]:
    if document.get("format") != expected_format:
        raise ValueError(f"{path} format must be {expected_format}")
    _only(
        document,
        {
            "format",
            "observation_id",
            "captured_at",
            "entity",
            "period",
            "source",
            "metrics",
            "limitations",
        },
        path,
    )
    captured_at = _timestamp(document.get("captured_at"), f"{path}.captured_at")
    source = _source(
        document.get("source"),
        f"{path}.source",
        captured_at=captured_at,
        recorded_at=recorded_at,
    )
    metric_values = document.get("metrics")
    if not isinstance(metric_values, list) or not metric_values:
        raise ValueError(f"{path}.metrics requires at least one metric")
    loader = (
        _guidance_metric
        if expected_format == GUIDANCE_OBSERVATION_FORMAT
        else _outcome_metric
    )
    metrics = [loader(value, f"{path}.metrics[{index}]") for index, value in enumerate(metric_values)]
    metric_ids = [item["id"] for item in metrics]
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError(f"{path}.metrics contains duplicate IDs")
    limitations = document.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(
        isinstance(item, str) and item.strip() for item in limitations
    ):
        raise ValueError(f"{path}.limitations requires nonempty text entries")
    return {
        "format": expected_format,
        "observation_id": _identifier(
            document.get("observation_id"),
            f"{path}.observation_id",
        ),
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "entity": _entity(document.get("entity"), f"{path}.entity"),
        "period": _period(document.get("period"), f"{path}.period"),
        "source": source,
        "metrics": {item["id"]: item for item in metrics},
        "limitations": list(limitations),
    }


def load_guidance_backtest(
    case_path: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ValueError("source_root must be an existing directory")
    source = Path(case_path).resolve()
    if source != root and root not in source.parents:
        raise ValueError("case must be below source_root")
    raw = source.read_bytes()
    document = _json_document(raw, str(source))
    if document.get("format") != GUIDANCE_BACKTEST_CASE_FORMAT:
        raise ValueError(f"case format must be {GUIDANCE_BACKTEST_CASE_FORMAT}")
    _only(
        document,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "entity",
            "period",
            "guidance_observation",
            "outcome_observation",
            "metric_ids",
            "notes",
        },
        "case",
    )
    case_id = _identifier(document.get("id"), "case.id")
    as_of_date = _date(document.get("as_of_date"), "case.as_of_date")
    recorded_at = _timestamp(document.get("recorded_at"), "case.recorded_at")
    if as_of_date > recorded_at.date():
        raise ValueError("case.as_of_date cannot follow recorded_at")
    entity = _entity(document.get("entity"), "case.entity")
    period = _period(document.get("period"), "case.period")
    period_end = date.fromisoformat(period["end"])

    guidance_path, guidance_raw, guidance_document, guidance_sha = _read_pinned(
        root,
        document.get("guidance_observation"),
        "case.guidance_observation",
    )
    outcome_path, outcome_raw, outcome_document, outcome_sha = _read_pinned(
        root,
        document.get("outcome_observation"),
        "case.outcome_observation",
    )
    guidance = _observation(
        guidance_document,
        expected_format=GUIDANCE_OBSERVATION_FORMAT,
        recorded_at=recorded_at,
        path="guidance observation",
    )
    outcome = _observation(
        outcome_document,
        expected_format=OUTCOME_OBSERVATION_FORMAT,
        recorded_at=recorded_at,
        path="outcome observation",
    )
    for label, observation in (("guidance", guidance), ("outcome", outcome)):
        if observation["entity"] != entity:
            raise ValueError(f"{label} observation entity does not match case")
        if observation["period"] != period:
            raise ValueError(f"{label} observation period does not match case")
    guidance_published = date.fromisoformat(guidance["source"]["published_at"])
    outcome_published = date.fromisoformat(outcome["source"]["published_at"])
    if guidance_published >= period_end:
        raise ValueError("guidance must be published before the period ends")
    if outcome_published <= period_end:
        raise ValueError("outcome must be published after the period ends")
    if outcome_published <= guidance_published:
        raise ValueError("outcome publication must follow guidance publication")
    if outcome_published > as_of_date:
        raise ValueError("outcome was not published by case.as_of_date")

    metric_ids = document.get("metric_ids")
    if not isinstance(metric_ids, list) or not metric_ids or not all(
        isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in metric_ids
    ):
        raise ValueError("case.metric_ids requires lowercase identifier entries")
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError("case.metric_ids contains duplicates")
    pairs = []
    for metric_id in metric_ids:
        forecast_metric = guidance["metrics"].get(metric_id)
        actual_metric = outcome["metrics"].get(metric_id)
        if forecast_metric is None or actual_metric is None:
            raise ValueError(f"selected metric is absent from an observation: {metric_id}")
        for field in ("label", "metric_class", "basis", "unit"):
            if forecast_metric[field] != actual_metric[field]:
                raise ValueError(f"metric {metric_id} {field} does not match")
        pairs.append({"guidance": forecast_metric, "outcome": actual_metric})
    return {
        "case": {
            "format": GUIDANCE_BACKTEST_CASE_FORMAT,
            "id": case_id,
            "as_of_date": as_of_date.isoformat(),
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "entity": entity,
            "period": period,
            "metric_ids": list(metric_ids),
            "notes": _required_text(document.get("notes"), "case.notes"),
            "path": source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
        },
        "guidance": {
            **guidance,
            "path": guidance_path,
            "sha256": guidance_sha,
            "raw": guidance_raw,
        },
        "outcome": {
            **outcome,
            "path": outcome_path,
            "sha256": outcome_sha,
            "raw": outcome_raw,
        },
        "metric_pairs": pairs,
    }


def score_guidance_backtest(case: Mapping[str, Any]) -> dict[str, Any]:
    scores = []
    for pair in case["metric_pairs"]:
        guidance = pair["guidance"]
        outcome = pair["outcome"]
        actual = outcome["value"]
        midpoint = guidance["midpoint"]
        signed_error = midpoint - actual
        absolute_error = abs(signed_error)
        half_width = (guidance["high"] - guidance["low"]) / 2
        normalization_scale = max(half_width, abs(midpoint) * 0.01, 1e-12)
        inside = guidance["low"] <= actual <= guidance["high"]
        if inside:
            surprise_direction = "inside_range"
        elif actual > guidance["high"]:
            surprise_direction = "above_range"
        else:
            surprise_direction = "below_range"
        scores.append(
            {
                "id": guidance["id"],
                "label": guidance["label"],
                "metric_class": guidance["metric_class"],
                "basis": guidance["basis"],
                "unit": guidance["unit"],
                "range_semantics": guidance["range_semantics"],
                "guidance_low": guidance["low"],
                "guidance_midpoint": midpoint,
                "guidance_high": guidance["high"],
                "actual_value": actual,
                "inside_guidance_range": inside,
                "surprise_direction": surprise_direction,
                "signed_error": signed_error,
                "absolute_error": absolute_error,
                "signed_error_ratio": None if actual == 0 else signed_error / actual,
                "actual_to_guidance_midpoint_ratio": (
                    None if midpoint == 0 else actual / midpoint
                ),
                "interval_miss": max(guidance["low"] - actual, actual - guidance["high"], 0.0),
                "guidance_half_width": half_width,
                "normalization_scale": normalization_scale,
                "normalized_absolute_error": absolute_error / normalization_scale,
                "guidance_methodology": guidance["methodology"],
                "outcome_methodology": outcome["methodology"],
                "revision_risk": outcome["revision_risk"],
            }
        )
    relative_errors = [
        abs(item["signed_error_ratio"])
        for item in scores
        if item["signed_error_ratio"] is not None
    ]
    case_metadata = {key: value for key, value in case["case"].items() if key != "raw"}
    evidence = []
    for role in ("guidance", "outcome"):
        observation = case[role]
        source = observation["source"]
        evidence.append(
            {
                "id": f"{role}:{observation['observation_id']}",
                "role": role,
                "kind": "company_disclosure",
                "title": f"{case['case']['entity']['name']} {case['case']['period']['label']} {role}",
                "source_url": source["source_url"],
                "publisher": source["publisher"],
                "published_at": source["published_at"],
                "retrieved_at": source["retrieved_at"],
                "source_family": source["source_family"],
                "license": source["license"],
                "excerpt": source["excerpt"],
                "content_hash": observation["sha256"],
            }
        )
    return {
        "format": GUIDANCE_BACKTEST_RESULT_FORMAT,
        "case": case_metadata,
        "benchmark": {
            "type": "reconstructed_external_company_guidance",
            "native_model_forecast": False,
            "eligible_for_model_calibration": False,
            "guidance_published_at": case["guidance"]["source"]["published_at"],
            "outcome_published_at": case["outcome"]["source"]["published_at"],
            "guidance_captured_at": case["guidance"]["captured_at"],
            "outcome_captured_at": case["outcome"]["captured_at"],
        },
        "scores": scores,
        "summary": {
            "metric_count": len(scores),
            "inside_guidance_range_count": sum(
                item["inside_guidance_range"] for item in scores
            ),
            "inside_guidance_range_rate": fmean(
                float(item["inside_guidance_range"]) for item in scores
            ),
            "above_range_count": sum(
                item["surprise_direction"] == "above_range" for item in scores
            ),
            "below_range_count": sum(
                item["surprise_direction"] == "below_range" for item in scores
            ),
            "mean_absolute_percentage_error": (
                fmean(relative_errors) if relative_errors else None
            ),
            "mean_normalized_absolute_error": fmean(
                item["normalized_absolute_error"] for item in scores
            ),
        },
        "evidence": evidence,
        "methodology": {
            "range_coverage": "Whether the reported outcome falls inside management's stated guidance range; approximate point guidance has zero width.",
            "signed_error": "Guidance midpoint minus reported actual; negative values mean actual exceeded the midpoint.",
            "normalization": "Absolute midpoint error divided by max(guidance half-width, 1% of absolute midpoint, epsilon).",
            "transaction_boundary": "The official guidance predates period end, but this normalized benchmark was reconstructed after the outcome and cannot calibrate native model forecasts.",
        },
        "warnings": [
            "Management guidance ranges are not P10/P90 quantiles, so this benchmark does not compute pinball or Brier scores.",
            "Guidance and outcome come from the same company source family and are not independent evidence.",
            "One company-quarter cannot establish forecast skill or justify a calibration parameter.",
            "The normalized guidance artifact was captured after the outcome; only the underlying company disclosure was public beforehand.",
        ],
    }
