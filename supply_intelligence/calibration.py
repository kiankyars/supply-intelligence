"""Multi-vintage forecast scoring and conservative calibration diagnostics."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable, Mapping

from .manufacturing_engine import OUTPUT_UNITS


CALIBRATION_DATASET_FORMAT = "ai-supply-calibration-dataset.v1"
CALIBRATION_RESULT_FORMAT = "ai-supply-calibration-result.v1"
MANUFACTURING_RESULT_FORMAT = "ai-supply-manufacturing-result.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
POSTURES = {"reported", "derived", "modeled", "synthetic"}
EVENT_OPERATORS = {"at_least", "at_most"}


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
    if not ID_PATTERN.fullmatch(text):
        raise ValueError(f"{path} must use lowercase letters, digits, and hyphens")
    return text


def _sha256(value: Any, path: str) -> str:
    text = _required_text(value, path)
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return text


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be numeric")
    value = float(value)
    if not isfinite(value):
        raise ValueError(f"{path} must be finite")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be boolean")
    return value


def _date(value: Any, path: str) -> date:
    text = _required_text(value, path)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _timestamp(value: Any, path: str) -> datetime:
    text = _required_text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _resolve_under(root: Path, value: Any, path: str) -> tuple[str, Path]:
    text = _required_text(value, path)
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{path} must be below source_root")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{path} escapes source_root")
    return relative.as_posix(), resolved


def _quarter_end(value: str) -> date:
    if not re.fullmatch(r"\d{4}-Q[1-4]", value):
        raise ValueError("forecast quarter must use YYYY-QN")
    year = int(value[:4])
    quarter = int(value[-1])
    return (
        date(year, 3, 31),
        date(year, 6, 30),
        date(year, 9, 30),
        date(year, 12, 31),
    )[quarter - 1]


def _forecast_metrics(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = _mapping(document.get("conversion_outputs"), "forecast.conversion_outputs")
    metrics = {}
    for name, value in values.items():
        if name not in OUTPUT_UNITS:
            raise ValueError(f"unsupported manufacturing forecast metric: {name}")
        distribution = _mapping(value, f"forecast.conversion_outputs.{name}")
        points = {
            field: _number(
                distribution.get(field),
                f"forecast.conversion_outputs.{name}.{field}",
            )
            for field in ("p10", "p50", "p90")
        }
        if not points["p10"] <= points["p50"] <= points["p90"]:
            raise ValueError(f"forecast metric {name} range is not ordered")
        metrics[name] = {**points, "unit": OUTPUT_UNITS[name]}
    return metrics


def _load_evidence(
    value: Any,
    path: str,
    recorded_at: datetime,
    *,
    synthetic: bool,
) -> dict[str, Any]:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "kind",
            "title",
            "source_url",
            "publisher",
            "published_at",
            "retrieved_at",
            "source_family",
            "license",
            "excerpt",
            "content_hash",
        },
        path,
    )
    retrieved_at = _timestamp(data.get("retrieved_at"), f"{path}.retrieved_at")
    if retrieved_at > recorded_at:
        raise ValueError(f"{path} was retrieved after dataset.recorded_at")
    published_value = data.get("published_at")
    if published_value is None:
        if not synthetic:
            raise ValueError(f"{path}.published_at is required for evidence-backed data")
        published_at = None
    else:
        published_at = _date(published_value, f"{path}.published_at").isoformat()
        if date.fromisoformat(published_at) > retrieved_at.date():
            raise ValueError(f"{path} was retrieved before it was published")
    content_hash_value = data.get("content_hash")
    if content_hash_value is None:
        if not synthetic:
            raise ValueError(f"{path}.content_hash is required for evidence-backed data")
        content_hash = None
    else:
        content_hash = _sha256(content_hash_value, f"{path}.content_hash")
    return {
        "id": _required_text(data.get("id"), f"{path}.id"),
        "kind": _required_text(data.get("kind"), f"{path}.kind"),
        "title": _required_text(data.get("title"), f"{path}.title"),
        "source_url": _required_text(data.get("source_url"), f"{path}.source_url"),
        "publisher": _required_text(data.get("publisher"), f"{path}.publisher"),
        "published_at": published_at,
        "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
        "source_family": _required_text(
            data.get("source_family"),
            f"{path}.source_family",
        ),
        "license": _optional_text(data.get("license"), f"{path}.license"),
        "excerpt": _required_text(data.get("excerpt"), f"{path}.excerpt"),
        "content_hash": content_hash,
    }


def load_calibration_dataset(
    dataset_path: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ValueError("source_root must be an existing directory")
    dataset_source = Path(dataset_path).resolve()
    if dataset_source != root and root not in dataset_source.parents:
        raise ValueError("dataset must be below source_root")
    dataset_raw = dataset_source.read_bytes()
    try:
        document = _mapping(json.loads(dataset_raw), "calibration dataset")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid calibration dataset JSON: {exc}") from exc
    if document.get("format") != CALIBRATION_DATASET_FORMAT:
        raise ValueError(f"dataset format must be {CALIBRATION_DATASET_FORMAT}")
    _only(
        document,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "synthetic",
            "minimum_group_size",
            "forecasts",
            "evidence",
            "outcomes",
            "notes",
        },
        "calibration dataset",
    )
    dataset_id = _identifier(document.get("id"), "dataset.id")
    as_of_date = _date(document.get("as_of_date"), "dataset.as_of_date")
    recorded_at = _timestamp(document.get("recorded_at"), "dataset.recorded_at")
    if as_of_date > recorded_at.date():
        raise ValueError("dataset.as_of_date cannot follow recorded_at")
    synthetic = _boolean(document.get("synthetic"), "dataset.synthetic")
    minimum_group_size = _integer(
        document.get("minimum_group_size"),
        "dataset.minimum_group_size",
    )
    if minimum_group_size < 10:
        raise ValueError("dataset.minimum_group_size must be at least 10")

    evidence_values = document.get("evidence")
    if not isinstance(evidence_values, list) or not evidence_values:
        raise ValueError("dataset.evidence requires at least one record")
    evidence = [
        _load_evidence(
            value,
            f"evidence[{index}]",
            recorded_at,
            synthetic=synthetic,
        )
        for index, value in enumerate(evidence_values)
    ]
    evidence_ids = [item["id"] for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("duplicate calibration evidence id")

    forecast_values = document.get("forecasts")
    if not isinstance(forecast_values, list) or not forecast_values:
        raise ValueError("dataset.forecasts requires at least one forecast")
    forecasts = {}
    for index, value in enumerate(forecast_values):
        selection = _mapping(value, f"forecasts[{index}]")
        _only(
            selection,
            {"id", "path", "sha256", "format", "scenario_id"},
            f"forecasts[{index}]",
        )
        forecast_id = _identifier(selection.get("id"), f"forecasts[{index}].id")
        if forecast_id in forecasts:
            raise ValueError(f"duplicate forecast id: {forecast_id}")
        relative, path = _resolve_under(
            root,
            selection.get("path"),
            f"forecasts[{index}].path",
        )
        expected_sha = _sha256(
            selection.get("sha256"),
            f"forecasts[{index}].sha256",
        )
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            raise ValueError(f"forecast {forecast_id} SHA-256 mismatch")
        try:
            forecast = _mapping(json.loads(raw), f"forecast {forecast_id}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid forecast JSON for {forecast_id}: {exc}") from exc
        expected_format = _required_text(
            selection.get("format"),
            f"forecasts[{index}].format",
        )
        if expected_format != MANUFACTURING_RESULT_FORMAT:
            raise ValueError(
                f"calibration v1 supports only {MANUFACTURING_RESULT_FORMAT}"
            )
        if forecast.get("format") != expected_format:
            raise ValueError(f"forecast {forecast_id} format mismatch")
        scenario = _mapping(forecast.get("scenario"), f"forecast {forecast_id}.scenario")
        expected_scenario = _required_text(
            selection.get("scenario_id"),
            f"forecasts[{index}].scenario_id",
        )
        if scenario.get("id") != expected_scenario:
            raise ValueError(f"forecast {forecast_id} scenario ID mismatch")
        forecast_recorded_at = _timestamp(
            scenario.get("recorded_at"),
            f"forecast {forecast_id}.scenario.recorded_at",
        )
        if forecast_recorded_at >= recorded_at:
            raise ValueError(f"forecast {forecast_id} must predate dataset.recorded_at")
        forecast_as_of_date = _date(
            scenario.get("as_of_date"),
            f"forecast {forecast_id}.scenario.as_of_date",
        )
        if forecast_as_of_date > forecast_recorded_at.date():
            raise ValueError(f"forecast {forecast_id} as-of date follows its recording")
        forecast_synthetic = _boolean(
            scenario.get("synthetic"),
            f"forecast {forecast_id}.scenario.synthetic",
        )
        if forecast_synthetic and not synthetic:
            raise ValueError("a synthetic forecast requires a synthetic calibration dataset")
        quarter = _required_text(
            scenario.get("quarter"),
            f"forecast {forecast_id}.scenario.quarter",
        )
        _quarter_end(quarter)
        forecasts[forecast_id] = {
            "id": forecast_id,
            "path": relative,
            "sha256": expected_sha,
            "format": expected_format,
            "scenario_id": expected_scenario,
            "quarter": quarter,
            "as_of_date": forecast_as_of_date.isoformat(),
            "recorded_at": forecast_recorded_at.isoformat().replace("+00:00", "Z"),
            "synthetic": forecast_synthetic,
            "metrics": _forecast_metrics(forecast),
            "raw": raw,
        }

    outcome_values = document.get("outcomes")
    if not isinstance(outcome_values, list) or not outcome_values:
        raise ValueError("dataset.outcomes requires at least one outcome")
    outcomes = []
    seen_outcomes: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    available_evidence = set(evidence_ids)
    evidence_by_id = {item["id"]: item for item in evidence}
    for index, value in enumerate(outcome_values):
        outcome = _mapping(value, f"outcomes[{index}]")
        _only(
            outcome,
            {
                "id",
                "forecast_id",
                "metric_class",
                "forecast_metric",
                "period",
                "actual_value",
                "unit",
                "posture",
                "observed_at",
                "source_family",
                "evidence_ids",
                "methodology",
                "revision_risk",
                "event",
            },
            f"outcomes[{index}]",
        )
        outcome_id = _identifier(outcome.get("id"), f"outcomes[{index}].id")
        if outcome_id in seen_outcomes:
            raise ValueError(f"duplicate outcome id: {outcome_id}")
        seen_outcomes.add(outcome_id)
        forecast_id = _identifier(
            outcome.get("forecast_id"),
            f"outcomes[{index}].forecast_id",
        )
        forecast = forecasts.get(forecast_id)
        if forecast is None:
            raise ValueError(f"outcome {outcome_id} references missing forecast")
        metric = _required_text(
            outcome.get("forecast_metric"),
            f"outcomes[{index}].forecast_metric",
        )
        distribution = forecast["metrics"].get(metric)
        if distribution is None:
            raise ValueError(f"outcome {outcome_id} references missing forecast metric")
        target = (forecast_id, metric)
        if target in seen_targets:
            raise ValueError(f"duplicate outcome target: {forecast_id} {metric}")
        seen_targets.add(target)
        period = _required_text(outcome.get("period"), f"outcomes[{index}].period")
        if period != forecast["quarter"]:
            raise ValueError(f"outcome {outcome_id} period does not match forecast")
        unit = _required_text(outcome.get("unit"), f"outcomes[{index}].unit")
        if unit != distribution["unit"]:
            raise ValueError(f"outcome {outcome_id} unit does not match forecast")
        actual = _number(
            outcome.get("actual_value"),
            f"outcomes[{index}].actual_value",
        )
        if actual < 0:
            raise ValueError(f"outcome {outcome_id} actual_value cannot be negative")
        posture = _required_text(
            outcome.get("posture"),
            f"outcomes[{index}].posture",
        )
        if posture not in POSTURES:
            raise ValueError(f"outcome {outcome_id} has unsupported posture")
        if not synthetic and posture not in {"reported", "derived"}:
            raise ValueError(
                "an evidence-backed calibration dataset requires reported or derived outcomes"
            )
        observed_at = _date(
            outcome.get("observed_at"),
            f"outcomes[{index}].observed_at",
        )
        if observed_at > as_of_date:
            raise ValueError(f"outcome {outcome_id} was not observed by dataset.as_of_date")
        if _timestamp(
            forecast["recorded_at"],
            f"forecast {forecast_id}.recorded_at",
        ).date() >= observed_at:
            raise ValueError(
                f"forecast {forecast_id} was not frozen before outcome {outcome_id}"
            )
        if not synthetic and observed_at <= _quarter_end(period):
            raise ValueError(f"outcome {outcome_id} predates quarter completion")
        ids = outcome.get("evidence_ids")
        if not isinstance(ids, list) or not ids or not all(
            isinstance(item, str) and item for item in ids
        ):
            raise ValueError(f"outcome {outcome_id} requires evidence_ids")
        missing = set(ids) - available_evidence
        if missing:
            raise ValueError(
                f"outcome {outcome_id} references missing evidence: {sorted(missing)}"
            )
        source_family = _required_text(
            outcome.get("source_family"),
            f"outcomes[{index}].source_family",
        )
        evidence_families = {evidence_by_id[item]["source_family"] for item in ids}
        if evidence_families != {source_family}:
            raise ValueError(
                f"outcome {outcome_id} source_family does not match its evidence"
            )
        if not synthetic:
            published_dates = [
                _date(
                    evidence_by_id[item]["published_at"],
                    f"evidence {item}.published_at",
                )
                for item in ids
            ]
            if any(published > observed_at for published in published_dates):
                raise ValueError(
                    f"outcome {outcome_id} predates publication of its evidence"
                )
        event_value = outcome.get("event")
        event = None
        if event_value is not None:
            event_mapping = _mapping(event_value, f"outcomes[{index}].event")
            _only(
                event_mapping,
                {"operator", "threshold", "unit"},
                f"outcomes[{index}].event",
            )
            operator = _required_text(
                event_mapping.get("operator"),
                f"outcomes[{index}].event.operator",
            )
            if operator not in EVENT_OPERATORS:
                raise ValueError(f"outcome {outcome_id} has unsupported event operator")
            event_unit = _required_text(
                event_mapping.get("unit"),
                f"outcomes[{index}].event.unit",
            )
            if event_unit != unit:
                raise ValueError(f"outcome {outcome_id} event unit mismatch")
            threshold = _number(
                event_mapping.get("threshold"),
                f"outcomes[{index}].event.threshold",
            )
            if threshold < 0:
                raise ValueError(f"outcome {outcome_id} event threshold cannot be negative")
            event = {"operator": operator, "threshold": threshold, "unit": event_unit}
        outcomes.append(
            {
                "id": outcome_id,
                "forecast_id": forecast_id,
                "metric_class": _required_text(
                    outcome.get("metric_class"),
                    f"outcomes[{index}].metric_class",
                ),
                "forecast_metric": metric,
                "period": period,
                "actual_value": actual,
                "unit": unit,
                "posture": posture,
                "observed_at": observed_at.isoformat(),
                "source_family": source_family,
                "evidence_ids": list(ids),
                "methodology": _required_text(
                    outcome.get("methodology"),
                    f"outcomes[{index}].methodology",
                ),
                "revision_risk": _required_text(
                    outcome.get("revision_risk"),
                    f"outcomes[{index}].revision_risk",
                ),
                "event": event,
                "forecast_distribution": distribution,
            }
        )
    return {
        "dataset": {
            "format": CALIBRATION_DATASET_FORMAT,
            "id": dataset_id,
            "as_of_date": as_of_date.isoformat(),
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "synthetic": synthetic,
            "minimum_group_size": minimum_group_size,
            "notes": document.get("notes", ""),
            "path": dataset_source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(dataset_raw).hexdigest(),
            "raw": dataset_raw,
        },
        "forecasts": forecasts,
        "evidence": evidence,
        "outcomes": outcomes,
    }


def _triangular_cdf(low: float, mode: float, high: float, value: float) -> float:
    if low == high:
        return 0.0 if value < low else 1.0
    if value <= low:
        return 0.0
    if value >= high:
        return 1.0
    if value <= mode:
        if mode == low:
            return 0.0
        return ((value - low) ** 2) / ((high - low) * (mode - low))
    if mode == high:
        return 1.0
    return 1 - ((high - value) ** 2) / ((high - low) * (high - mode))


def _event_score(
    distribution: Mapping[str, float],
    actual: float,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    if distribution["p10"] == distribution["p90"]:
        if event["operator"] == "at_least":
            probability = float(distribution["p50"] >= event["threshold"])
            realized = actual >= event["threshold"]
        else:
            probability = float(distribution["p50"] <= event["threshold"])
            realized = actual <= event["threshold"]
    else:
        cdf = _triangular_cdf(
            distribution["p10"],
            distribution["p50"],
            distribution["p90"],
            event["threshold"],
        )
        if event["operator"] == "at_least":
            probability = 1 - cdf
            realized = actual >= event["threshold"]
        else:
            probability = cdf
            realized = actual <= event["threshold"]
    return {
        "operator": event["operator"],
        "threshold": event["threshold"],
        "unit": event["unit"],
        "forecast_probability": probability,
        "realized": realized,
        "brier_score": (probability - float(realized)) ** 2,
    }


def _pinball(prediction: float, actual: float, quantile: float) -> float:
    error = actual - prediction
    return quantile * error if error >= 0 else (1 - quantile) * -error


def _quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute a quantile of no values")
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _group_summary(
    rows: list[dict[str, Any]],
    minimum_group_size: int,
    *,
    allow_proposal: bool,
) -> dict[str, Any]:
    units = sorted({item["unit"] for item in rows})
    relative_errors = [
        item["signed_error_ratio"]
        for item in rows
        if item["signed_error_ratio"] is not None
    ]
    brier_scores = [
        item["event_score"]["brier_score"]
        for item in rows
        if item["event_score"] is not None
    ]
    ratios = [
        item["actual_to_forecast_p50_ratio"]
        for item in rows
        if item["actual_to_forecast_p50_ratio"] is not None
    ]
    normalized_errors = [item["normalized_absolute_error"] for item in rows]
    if not allow_proposal:
        proposal = {
            "status": "diagnostic_only",
            "eligible_for_application": False,
            "minimum_group_size": minimum_group_size,
            "additional_outcomes_needed": None,
            "p50_multiplier": None,
            "half_width_multiplier": None,
        }
    elif len(rows) < minimum_group_size:
        proposal = {
            "status": "insufficient_history",
            "eligible_for_application": False,
            "minimum_group_size": minimum_group_size,
            "additional_outcomes_needed": minimum_group_size - len(rows),
            "p50_multiplier": None,
            "half_width_multiplier": None,
        }
    elif len(ratios) != len(rows):
        proposal = {
            "status": "not_estimable_zero_p50",
            "eligible_for_application": False,
            "minimum_group_size": minimum_group_size,
            "additional_outcomes_needed": 0,
            "p50_multiplier": None,
            "half_width_multiplier": None,
        }
    else:
        proposal = {
            "status": "holdout_validation_required",
            "eligible_for_application": False,
            "minimum_group_size": minimum_group_size,
            "additional_outcomes_needed": 0,
            "p50_multiplier": median(ratios),
            "half_width_multiplier": max(1.0, _quantile(normalized_errors, 0.80)),
        }
    return {
        "count": len(rows),
        "units": units,
        "p10_p90_coverage_rate": fmean(
            float(item["inside_p10_p90"]) for item in rows
        ),
        "mean_signed_error": (
            fmean(item["signed_error"] for item in rows) if len(units) == 1 else None
        ),
        "mean_absolute_error": (
            fmean(item["absolute_error"] for item in rows) if len(units) == 1 else None
        ),
        "mean_signed_error_ratio": fmean(relative_errors) if relative_errors else None,
        "mean_absolute_percentage_error": (
            fmean(abs(value) for value in relative_errors) if relative_errors else None
        ),
        "mean_normalized_pinball_loss": fmean(
            item["normalized_mean_pinball_loss"] for item in rows
        ),
        "mean_brier_score": fmean(brier_scores) if brier_scores else None,
        "brier_event_count": len(brier_scores),
        "calibration_proposal": proposal,
    }


def score_calibration_dataset(case: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for outcome in case["outcomes"]:
        distribution = outcome["forecast_distribution"]
        actual = outcome["actual_value"]
        p10 = distribution["p10"]
        p50 = distribution["p50"]
        p90 = distribution["p90"]
        signed_error = p50 - actual
        absolute_error = abs(signed_error)
        half_width = max((p90 - p10) / 2, abs(p50) * 0.01, 1e-12)
        pinball = {
            "p10": _pinball(p10, actual, 0.10),
            "p50": _pinball(p50, actual, 0.50),
            "p90": _pinball(p90, actual, 0.90),
        }
        mean_pinball = fmean(pinball.values())
        event_score = (
            _event_score(distribution, actual, outcome["event"])
            if outcome["event"] is not None
            else None
        )
        rows.append(
            {
                "id": outcome["id"],
                "forecast_id": outcome["forecast_id"],
                "forecast_scenario_id": case["forecasts"][outcome["forecast_id"]][
                    "scenario_id"
                ],
                "forecast_metric": outcome["forecast_metric"],
                "metric_class": outcome["metric_class"],
                "period": outcome["period"],
                "unit": outcome["unit"],
                "forecast_p10": p10,
                "forecast_p50": p50,
                "forecast_p90": p90,
                "actual_value": actual,
                "actual_posture": outcome["posture"],
                "observed_at": outcome["observed_at"],
                "source_family": outcome["source_family"],
                "evidence_ids": outcome["evidence_ids"],
                "methodology": outcome["methodology"],
                "revision_risk": outcome["revision_risk"],
                "inside_p10_p90": p10 <= actual <= p90,
                "signed_error": signed_error,
                "absolute_error": absolute_error,
                "signed_error_ratio": None if actual == 0 else signed_error / actual,
                "actual_to_forecast_p50_ratio": None if p50 == 0 else actual / p50,
                "interval_miss": max(p10 - actual, actual - p90, 0.0),
                "normalization_half_width": half_width,
                "normalized_absolute_error": absolute_error / half_width,
                "pinball_loss": pinball,
                "mean_pinball_loss": mean_pinball,
                "normalized_mean_pinball_loss": mean_pinball / max(abs(actual), 1e-12),
                "event_score": event_score,
            }
        )
    minimum = case["dataset"]["minimum_group_size"]
    by_metric_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_source_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_metric_class[row["metric_class"]].append(row)
        by_source_family[row["source_family"]].append(row)
    return {
        "format": CALIBRATION_RESULT_FORMAT,
        "dataset": {
            key: value
            for key, value in case["dataset"].items()
            if key != "raw"
        },
        "forecast_lineage": [
            {
                key: value
                for key, value in forecast.items()
                if key not in {"raw", "metrics"}
            }
            for forecast in case["forecasts"].values()
        ],
        "scores": rows,
        "summary": _group_summary(rows, minimum, allow_proposal=False),
        "by_metric_class": {
            key: _group_summary(value, minimum, allow_proposal=True)
            for key, value in sorted(by_metric_class.items())
        },
        "by_source_family": {
            key: _group_summary(value, minimum, allow_proposal=False)
            for key, value in sorted(by_source_family.items())
        },
        "evidence": case["evidence"],
        "methodology": {
            "transaction_time": "Every forecast must be hash-pinned and frozen on an earlier date than its outcome; evidence must be retrieved by the dataset recording time.",
            "outcome_provenance": "Evidence-backed outcomes accept reported or derived posture only and require publication-dated, content-hashed evidence from the declared source family.",
            "coverage": "Whether the realized outcome falls inside the frozen forecast P10-to-P90 interval.",
            "bias": "Signed error is forecast P50 minus actual; positive values are overforecasts.",
            "unit_aggregation": "Raw signed and absolute errors are aggregated only when every outcome in a group shares one unit; normalized metrics remain comparable across units.",
            "normalization": "Absolute error is normalized by max(P10-to-P90 half-width, 1% of absolute P50, epsilon); mean pinball loss is normalized by max(absolute actual, epsilon).",
            "pinball": "Quantile loss is scored at P10, P50, and P90.",
            "brier": "Event probabilities use a triangular approximation with forecast P10/P50/P90 as low/mode/high.",
            "proposal": "Metric classes meeting the minimum expose a median actual/P50 multiplier and a non-narrowing P80 normalized-error width multiplier; overall and source-family aggregates are diagnostic only, and no proposal is eligible before holdout validation.",
        },
        "warnings": [
            "P10 and P90 are treated as triangular support endpoints for event scoring, so tail probability and cross-metric dependence are not preserved.",
            "Calibration proposals are diagnostics only and never mutate a forecast or narrow an interval automatically.",
            "Overall and source-family aggregates never emit shared recalibration parameters; only explicit metric classes can do so.",
        ]
        + (
            [
                "This checked dataset and its outcomes are synthetic fixtures, not historical realized production."
            ]
            if case["dataset"]["synthetic"]
            else []
        ),
    }
