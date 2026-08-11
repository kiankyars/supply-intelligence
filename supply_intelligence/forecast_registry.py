"""Pre-outcome native forecast vintages with explicit maturity contracts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .engine import summarize


FORECAST_REGISTRY_FORMAT = "ai-supply-forecast-registry.v1"
FORECAST_REGISTRY_RESULT_FORMAT = "ai-supply-forecast-registry-result.v1"
LINKED_CHAIN_RELEASE_FORMAT = "ai-supply-linked-chain-release.v2"
RECONCILIATION_RESULT_FORMAT = "ai-supply-reconciliation.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EVENT_OPERATORS = {"at_least", "at_most"}
OUTCOME_POSTURES = {"reported", "derived"}
PHYSICAL_OUTPUT_UNITS = {
    "accelerator_packages_produced": "package",
    "complete_servers": "server",
    "integrated_racks": "rack-scale system",
    "systems_shipped": "rack-scale system",
    "systems_installed": "rack-scale system",
    "systems_operational": "rack-scale system",
}


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


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path} must be an integer")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be numeric")
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"{path} must be finite")
    return parsed


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


def _quarter_end(value: str) -> date:
    if not re.fullmatch(r"\d{4}-Q[1-4]", value):
        raise ValueError("forecast period must use YYYY-QN")
    year = int(value[:4])
    quarter = int(value[-1])
    return (
        date(year, 3, 31),
        date(year, 6, 30),
        date(year, 9, 30),
        date(year, 12, 31),
    )[quarter - 1]


def _resolve_under(root: Path, value: Any, path: str) -> tuple[str, Path]:
    text = _required_text(value, path)
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{path} must be below source_root")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{path} escapes source_root")
    return relative.as_posix(), resolved


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
    files = _mapping(manifest.get("files"), "source release manifest.files")
    entry = _mapping(files.get(relative), f"source release manifest.files.{relative}")
    manifest_sha = _sha256(
        entry.get("sha256"), f"source release manifest.files.{relative}.sha256"
    )
    manifest_bytes = _integer(
        entry.get("bytes"), f"source release manifest.files.{relative}.bytes"
    )
    raw = source.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected or actual != manifest_sha:
        raise ValueError(f"{path} SHA-256 mismatch")
    if len(raw) != manifest_bytes:
        raise ValueError(f"{path} byte count mismatch")
    return relative, raw, actual


def _distribution(value: Any, path: str) -> dict[str, float]:
    data = _mapping(value, path)
    required = {"p10", "p50", "p90", "mean", "minimum", "maximum"}
    if not required.issubset(data):
        raise ValueError(f"{path} lacks distribution fields")
    result = {field: _number(data.get(field), f"{path}.{field}") for field in required}
    if not result["minimum"] <= result["p10"] <= result["p50"] <= result["p90"] <= result["maximum"]:
        raise ValueError(f"{path} distribution is not ordered")
    if result["minimum"] < 0:
        raise ValueError(f"{path} cannot contain negative physical output")
    return result


def _target(value: Any, path: str, *, period: str) -> dict[str, str]:
    data = _mapping(value, path)
    fields = {
        "entity",
        "product",
        "geography",
        "quantity_semantics",
        "aggregation",
        "cutoff_date",
        "scope_definition",
    }
    _only(data, fields, path)
    result = {field: _required_text(data.get(field), f"{path}.{field}") for field in fields}
    cutoff = _date(result["cutoff_date"], f"{path}.cutoff_date")
    if cutoff != _quarter_end(period):
        raise ValueError(f"{path}.cutoff_date must equal the forecast quarter end")
    return result


def _outcome_contract(
    value: Any,
    path: str,
    *,
    cutoff: date,
) -> dict[str, Any]:
    data = _mapping(value, path)
    fields = {
        "earliest_observed_at",
        "expected_evidence_by",
        "revision_window_end",
        "acceptable_postures",
        "required_evidence",
        "measurement_method",
        "confirming_evidence",
        "falsifying_evidence",
        "known_observability_gap",
    }
    _only(data, fields, path)
    earliest = _date(data.get("earliest_observed_at"), f"{path}.earliest_observed_at")
    expected = _date(data.get("expected_evidence_by"), f"{path}.expected_evidence_by")
    revision = _date(data.get("revision_window_end"), f"{path}.revision_window_end")
    if earliest <= cutoff:
        raise ValueError(f"{path}.earliest_observed_at must follow the quarter end")
    if expected < earliest:
        raise ValueError(f"{path}.expected_evidence_by precedes earliest_observed_at")
    if revision < expected:
        raise ValueError(f"{path}.revision_window_end precedes expected_evidence_by")
    postures = data.get("acceptable_postures")
    if not isinstance(postures, list) or not postures or not all(
        isinstance(item, str) and item in OUTCOME_POSTURES for item in postures
    ):
        raise ValueError(f"{path}.acceptable_postures must contain reported or derived")
    if len(postures) != len(set(postures)):
        raise ValueError(f"{path}.acceptable_postures contains duplicates")
    return {
        "earliest_observed_at": earliest.isoformat(),
        "expected_evidence_by": expected.isoformat(),
        "revision_window_end": revision.isoformat(),
        "acceptable_postures": list(postures),
        **{
            field: _required_text(data.get(field), f"{path}.{field}")
            for field in (
                "required_evidence",
                "measurement_method",
                "confirming_evidence",
                "falsifying_evidence",
                "known_observability_gap",
            )
        },
    }


def _event(value: Any, path: str, *, unit: str) -> dict[str, Any] | None:
    if value is None:
        return None
    data = _mapping(value, path)
    _only(data, {"operator", "threshold", "unit", "rationale"}, path)
    operator = _required_text(data.get("operator"), f"{path}.operator")
    if operator not in EVENT_OPERATORS:
        raise ValueError(f"{path}.operator must be at_least or at_most")
    event_unit = _required_text(data.get("unit"), f"{path}.unit")
    if event_unit != unit:
        raise ValueError(f"{path}.unit must match the forecast unit")
    threshold = _number(data.get("threshold"), f"{path}.threshold")
    if threshold < 0:
        raise ValueError(f"{path}.threshold cannot be negative")
    return {
        "operator": operator,
        "threshold": threshold,
        "unit": event_unit,
        "rationale": _required_text(data.get("rationale"), f"{path}.rationale"),
    }


def _maturity_status(
    as_of_date: date,
    cutoff: date,
    earliest: date,
    expected: date,
) -> str:
    if as_of_date <= cutoff:
        return "pending_period_end"
    if as_of_date < earliest:
        return "pending_observation_window"
    if as_of_date <= expected:
        return "awaiting_outcome"
    return "outcome_overdue"


def load_forecast_registry(
    registry_path: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    """Validate a registry and its complete native forecast source release."""

    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ValueError("source_root must be an existing directory")
    source = Path(registry_path).resolve()
    if source != root and root not in source.parents:
        raise ValueError("registry must be below source_root")
    raw = source.read_bytes()
    try:
        document = _mapping(json.loads(raw), "forecast registry")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid forecast registry JSON: {exc}") from exc
    if document.get("format") != FORECAST_REGISTRY_FORMAT:
        raise ValueError(f"registry format must be {FORECAST_REGISTRY_FORMAT}")
    _only(
        document,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "forecast_kind",
            "source_release",
            "forecasts",
            "notes",
        },
        "forecast registry",
    )
    registry_id = _identifier(document.get("id"), "registry.id")
    as_of = _date(document.get("as_of_date"), "registry.as_of_date")
    recorded = _timestamp(document.get("recorded_at"), "registry.recorded_at")
    if as_of > recorded.date():
        raise ValueError("registry.as_of_date cannot follow registry.recorded_at")
    if document.get("forecast_kind") != "native_model":
        raise ValueError("registry.forecast_kind must be native_model")

    source_selection = _mapping(document.get("source_release"), "source_release")
    _only(
        source_selection,
        {
            "path",
            "manifest_sha256",
            "manifest_format",
            "result_file",
            "result_sha256",
            "result_format",
            "draws_file",
            "draws_sha256",
            "scenario_id",
        },
        "source_release",
    )
    source_relative, source_dir = _resolve_under(
        root, source_selection.get("path"), "source_release.path"
    )
    if not source_dir.is_dir():
        raise ValueError("source_release.path must identify an existing directory")
    manifest_path = source_dir / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_sha != _sha256(
        source_selection.get("manifest_sha256"), "source_release.manifest_sha256"
    ):
        raise ValueError("source release manifest SHA-256 mismatch")
    try:
        manifest = _mapping(json.loads(manifest_raw), "source release manifest")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid source release manifest JSON: {exc}") from exc
    expected_manifest_format = _required_text(
        source_selection.get("manifest_format"), "source_release.manifest_format"
    )
    if expected_manifest_format != LINKED_CHAIN_RELEASE_FORMAT:
        raise ValueError(
            f"forecast registry v1 supports only {LINKED_CHAIN_RELEASE_FORMAT}"
        )
    if manifest.get("format") != expected_manifest_format:
        raise ValueError("source release manifest format mismatch")
    result_relative, result_raw, result_sha = _release_file(
        source_dir,
        manifest,
        source_selection.get("result_file"),
        source_selection.get("result_sha256"),
        "source_release.result",
    )
    draws_relative, draws_raw, draws_sha = _release_file(
        source_dir,
        manifest,
        source_selection.get("draws_file"),
        source_selection.get("draws_sha256"),
        "source_release.draws",
    )
    try:
        result_document = _mapping(json.loads(result_raw), "source result")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid source result JSON: {exc}") from exc
    expected_result_format = _required_text(
        source_selection.get("result_format"), "source_release.result_format"
    )
    if expected_result_format != RECONCILIATION_RESULT_FORMAT:
        raise ValueError(
            f"forecast registry v1 supports only {RECONCILIATION_RESULT_FORMAT}"
        )
    if result_document.get("format") != expected_result_format:
        raise ValueError("source result format mismatch")
    scenario = _mapping(result_document.get("scenario"), "source result.scenario")
    scenario_id = _required_text(
        source_selection.get("scenario_id"), "source_release.scenario_id"
    )
    if scenario.get("id") != scenario_id or manifest.get("scenario_id") != scenario_id:
        raise ValueError("source scenario ID mismatch")
    quarter = _required_text(scenario.get("quarter"), "source result.scenario.quarter")
    _quarter_end(quarter)
    if manifest.get("quarter") != quarter:
        raise ValueError("source release quarter mismatch")
    source_as_of = _date(scenario.get("as_of_date"), "source result.scenario.as_of_date")
    source_recorded = _timestamp(
        scenario.get("recorded_at"), "source result.scenario.recorded_at"
    )
    if source_as_of > source_recorded.date():
        raise ValueError("source result as-of date follows its recording")
    if source_recorded >= recorded:
        raise ValueError("source forecast must be frozen before registry.recorded_at")
    if source_as_of > as_of:
        raise ValueError("registry.as_of_date predates the source forecast")
    if manifest.get("as_of_date") != source_as_of.isoformat():
        raise ValueError("source release as-of date mismatch")
    if _timestamp(manifest.get("recorded_at"), "source release manifest.recorded_at") != source_recorded:
        raise ValueError("source release recorded_at mismatch")
    source_synthetic = scenario.get("synthetic")
    if not isinstance(source_synthetic, bool):
        raise ValueError("source result.scenario.synthetic must be boolean")
    if manifest.get("synthetic") is not source_synthetic:
        raise ValueError("source release synthetic flag mismatch")

    physical_outputs = _mapping(
        result_document.get("physical_outputs"), "source result.physical_outputs"
    )
    forecast_values = document.get("forecasts")
    if not isinstance(forecast_values, list) or not forecast_values:
        raise ValueError("registry.forecasts requires at least one forecast")
    forecasts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_metrics: set[str] = set()
    selected_columns: dict[str, list[float]] = {}
    for index, value in enumerate(forecast_values):
        path = f"forecasts[{index}]"
        selection = _mapping(value, path)
        _only(
            selection,
            {
                "id",
                "metric",
                "metric_class",
                "draw_column",
                "period",
                "unit",
                "target",
                "outcome_contract",
                "event",
            },
            path,
        )
        forecast_id = _identifier(selection.get("id"), f"{path}.id")
        if forecast_id in seen_ids:
            raise ValueError(f"duplicate forecast id: {forecast_id}")
        seen_ids.add(forecast_id)
        metric = _required_text(selection.get("metric"), f"{path}.metric")
        if metric not in PHYSICAL_OUTPUT_UNITS:
            raise ValueError(f"unsupported physical forecast metric: {metric}")
        if metric in seen_metrics:
            raise ValueError(f"duplicate forecast metric: {metric}")
        seen_metrics.add(metric)
        unit = _required_text(selection.get("unit"), f"{path}.unit")
        if unit != PHYSICAL_OUTPUT_UNITS[metric]:
            raise ValueError(f"{path}.unit does not match the physical metric")
        period = _required_text(selection.get("period"), f"{path}.period")
        if period != quarter:
            raise ValueError(f"{path}.period does not match the source forecast")
        cutoff = _quarter_end(period)
        if recorded.date() > cutoff:
            raise ValueError("registry was recorded after the forecast quarter ended")
        target = _target(selection.get("target"), f"{path}.target", period=period)
        contract = _outcome_contract(
            selection.get("outcome_contract"),
            f"{path}.outcome_contract",
            cutoff=cutoff,
        )
        if recorded.date() >= date.fromisoformat(contract["earliest_observed_at"]):
            raise ValueError(f"{path} was not registered before outcomes could be observed")
        draw_column = _required_text(
            selection.get("draw_column"), f"{path}.draw_column"
        )
        expected_column = f"physical.{metric}"
        if draw_column != expected_column:
            raise ValueError(f"{path}.draw_column must be {expected_column}")
        distribution = _distribution(
            physical_outputs.get(metric), f"source result.physical_outputs.{metric}"
        )
        selected_columns[draw_column] = []
        forecasts.append(
            {
                "id": forecast_id,
                "metric": metric,
                "metric_class": _identifier(
                    selection.get("metric_class"), f"{path}.metric_class"
                ),
                "draw_column": draw_column,
                "period": period,
                "unit": unit,
                "target": target,
                "outcome_contract": contract,
                "event": _event(selection.get("event"), f"{path}.event", unit=unit),
                "distribution": distribution,
            }
        )

    try:
        draws_text = draws_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source draw ledger must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(draws_text, newline=""))
    if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("source draw ledger requires unique CSV headers")
    manifest_fields = manifest.get("chain_draw_fields")
    if manifest_fields != reader.fieldnames:
        raise ValueError("source draw headers do not match the release manifest")
    missing_columns = set(selected_columns) - set(reader.fieldnames)
    if missing_columns:
        raise ValueError(f"source draw ledger lacks columns: {sorted(missing_columns)}")
    rows = 0
    for row_index, row in enumerate(reader):
        if row.get("draw_index") != str(row_index):
            raise ValueError("source draw_index must be contiguous from zero")
        for column, values in selected_columns.items():
            try:
                parsed = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"source draw {row_index} {column} must be numeric") from exc
            if not isfinite(parsed) or parsed < 0:
                raise ValueError(f"source draw {row_index} {column} must be finite and nonnegative")
            values.append(parsed)
        rows += 1
    expected_rows = _integer(manifest.get("chain_draw_count"), "source release manifest.chain_draw_count")
    if rows != expected_rows or rows == 0:
        raise ValueError("source draw count does not match the release manifest")

    for forecast in forecasts:
        draws = selected_columns[forecast["draw_column"]]
        recomputed = summarize(draws).as_dict()
        if recomputed != forecast["distribution"]:
            raise ValueError(
                f"source result distribution does not match raw draws for {forecast['metric']}"
            )
        event = forecast["event"]
        if event is not None:
            if event["operator"] == "at_least":
                realized = sum(value >= event["threshold"] for value in draws)
            else:
                realized = sum(value <= event["threshold"] for value in draws)
            event["forecast_probability"] = realized / rows
            event["probability_method"] = "exact_share_of_frozen_source_draws"
        contract = forecast["outcome_contract"]
        status = _maturity_status(
            as_of,
            date.fromisoformat(forecast["target"]["cutoff_date"]),
            date.fromisoformat(contract["earliest_observed_at"]),
            date.fromisoformat(contract["expected_evidence_by"]),
        )
        blockers = ["realized_outcome_not_attached"]
        if status == "pending_period_end":
            blockers.append("forecast_period_not_ended")
        elif status == "pending_observation_window":
            blockers.append("outcome_observation_window_not_open")
        if source_synthetic:
            blockers.append("source_scenario_is_synthetic")
        forecast["maturity"] = {
            "status": status,
            "calendar_eligible_to_attach_outcome": as_of
            >= date.fromisoformat(contract["earliest_observed_at"]),
            "outcome_attached": False,
            "eligible_to_score": False,
            "eligible_for_model_calibration": False,
            "blockers": blockers,
        }

    return {
        "registry": {
            "format": FORECAST_REGISTRY_FORMAT,
            "id": registry_id,
            "as_of_date": as_of.isoformat(),
            "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
            "forecast_kind": "native_model",
            "notes": _required_text(document.get("notes"), "registry.notes"),
            "path": source.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
        },
        "source": {
            "path": source_relative,
            "manifest_format": expected_manifest_format,
            "manifest_sha256": manifest_sha,
            "manifest_raw": manifest_raw,
            "result_file": result_relative,
            "result_format": expected_result_format,
            "result_sha256": result_sha,
            "result_raw": result_raw,
            "draws_file": draws_relative,
            "draws_sha256": draws_sha,
            "draws_raw": draws_raw,
            "draw_count": rows,
            "scenario_id": scenario_id,
            "quarter": quarter,
            "as_of_date": source_as_of.isoformat(),
            "recorded_at": source_recorded.isoformat().replace("+00:00", "Z"),
            "synthetic": source_synthetic,
        },
        "forecasts": forecasts,
    }


def build_forecast_registry_result(case: Mapping[str, Any]) -> dict[str, Any]:
    registry = case["registry"]
    source = case["source"]
    forecasts = case["forecasts"]
    status_counts: dict[str, int] = {}
    for forecast in forecasts:
        status = forecast["maturity"]["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "format": FORECAST_REGISTRY_RESULT_FORMAT,
        "registry": {
            key: value
            for key, value in registry.items()
            if key not in {"raw", "path"}
        },
        "source": {
            key: value
            for key, value in source.items()
            if key not in {"manifest_raw", "result_raw", "draws_raw"}
        },
        "summary": {
            "forecast_count": len(forecasts),
            "raw_draw_count": source["draw_count"],
            "maturity_status_counts": status_counts,
            "native_model_forecast": True,
            "source_synthetic": source["synthetic"],
            "outcomes_attached": 0,
            "scores_emitted": 0,
            "eligible_for_model_calibration": False,
        },
        "forecasts": forecasts,
        "methodology": {
            "transaction_time": "The source result, release manifest, and raw draw ledger are hash-pinned and predate this registry recording.",
            "distribution_integrity": "Every registered P10, P50, P90, mean, minimum, and maximum is recomputed from the selected raw draw column and must match exactly.",
            "maturity": "Status is evaluated at the registry as-of date. A calendar-open observation window does not prove that a comparable outcome exists.",
            "scoring": "This registry contains no realized values and emits no scores. A later evidence-backed outcome artifact must satisfy the frozen scope and observation contract.",
            "calibration": "A synthetic source forecast remains ineligible for evidence-backed model calibration even after the period matures.",
            "event_probability": "Optional threshold probabilities are exact shares of the frozen raw draws, not triangular approximations.",
        },
        "warnings": [
            "This is a native model vintage, but its source scenario is synthetic and illustrative rather than a market estimate."
            if source["synthetic"]
            else "This registry freezes a native model vintage; outcome comparability still requires later review.",
            "No realized outcome is attached, so coverage, bias, pinball, and Brier scores are intentionally absent.",
            "The frozen outcome contracts define what later evidence must measure; they do not guarantee that the required public evidence will become available.",
        ],
    }


def evaluate_forecast_registry_maturity(
    case: Mapping[str, Any],
    *,
    as_of_date: str | date,
) -> dict[str, Any]:
    """Evaluate calendar maturity without mutating the frozen registry or attaching outcomes."""

    evaluated = (
        _date(as_of_date, "status_as_of_date")
        if isinstance(as_of_date, str)
        else as_of_date
    )
    if not isinstance(evaluated, date):
        raise ValueError("status_as_of_date must be an ISO date")
    frozen_as_of = date.fromisoformat(case["registry"]["as_of_date"])
    if evaluated < frozen_as_of:
        raise ValueError("status_as_of_date cannot predate the frozen registry")
    forecasts = []
    counts: dict[str, int] = {}
    for forecast in case["forecasts"]:
        contract = forecast["outcome_contract"]
        status = _maturity_status(
            evaluated,
            date.fromisoformat(forecast["target"]["cutoff_date"]),
            date.fromisoformat(contract["earliest_observed_at"]),
            date.fromisoformat(contract["expected_evidence_by"]),
        )
        counts[status] = counts.get(status, 0) + 1
        blockers = ["realized_outcome_not_attached"]
        if status == "pending_period_end":
            blockers.append("forecast_period_not_ended")
        elif status == "pending_observation_window":
            blockers.append("outcome_observation_window_not_open")
        elif status == "outcome_overdue":
            blockers.append("expected_evidence_date_passed")
        if case["source"]["synthetic"]:
            blockers.append("source_scenario_is_synthetic")
        forecasts.append(
            {
                "id": forecast["id"],
                "metric": forecast["metric"],
                "status": status,
                "calendar_eligible_to_attach_outcome": evaluated
                >= date.fromisoformat(contract["earliest_observed_at"]),
                "outcome_attached": False,
                "eligible_to_score": False,
                "eligible_for_model_calibration": False,
                "blockers": blockers,
            }
        )
    return {
        "registry_id": case["registry"]["id"],
        "frozen_as_of_date": case["registry"]["as_of_date"],
        "status_as_of_date": evaluated.isoformat(),
        "maturity_status_counts": counts,
        "outcomes": 0,
        "scores": 0,
        "forecasts": forecasts,
    }
