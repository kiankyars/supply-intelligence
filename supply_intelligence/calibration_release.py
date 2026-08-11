"""Hash-complete, replay-safe releases for forecast calibration scorecards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .calibration import score_calibration_dataset
from .calibration_report import render_calibration_dashboard
from .release import _csv, _json, _sha256


CALIBRATION_RELEASE_FORMAT = "ai-supply-calibration-release.v1"


def _score_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["scores"]:
        event = item["event_score"] or {}
        rows.append(
            {
                **{key: value for key, value in item.items() if key not in {"pinball_loss", "event_score", "evidence_ids"}},
                "evidence_ids": "|".join(item["evidence_ids"]),
                "pinball_p10": item["pinball_loss"]["p10"],
                "pinball_p50": item["pinball_loss"]["p50"],
                "pinball_p90": item["pinball_loss"]["p90"],
                "event_operator": event.get("operator", ""),
                "event_threshold": event.get("threshold", ""),
                "event_unit": event.get("unit", ""),
                "event_forecast_probability": event.get("forecast_probability", ""),
                "event_realized": event.get("realized", ""),
                "brier_score": event.get("brier_score", ""),
            }
        )
    return rows


def _group_rows(groups: Mapping[str, Mapping[str, Any]], key_name: str) -> list[dict[str, Any]]:
    rows = []
    for name, item in groups.items():
        proposal = item["calibration_proposal"]
        rows.append(
            {
                key_name: name,
                "count": item["count"],
                "units": "|".join(item["units"]),
                "p10_p90_coverage_rate": item["p10_p90_coverage_rate"],
                "mean_signed_error": item["mean_signed_error"],
                "mean_absolute_error": item["mean_absolute_error"],
                "mean_signed_error_ratio": item["mean_signed_error_ratio"],
                "mean_absolute_percentage_error": item["mean_absolute_percentage_error"],
                "mean_normalized_pinball_loss": item["mean_normalized_pinball_loss"],
                "mean_brier_score": item["mean_brier_score"],
                "brier_event_count": item["brier_event_count"],
                "proposal_status": proposal["status"],
                "eligible_for_application": proposal["eligible_for_application"],
                "minimum_group_size": proposal["minimum_group_size"],
                "additional_outcomes_needed": proposal["additional_outcomes_needed"],
                "p50_multiplier": proposal["p50_multiplier"],
                "half_width_multiplier": proposal["half_width_multiplier"],
            }
        )
    return rows


SCORE_FIELDS = [
    "id",
    "forecast_id",
    "forecast_scenario_id",
    "forecast_metric",
    "metric_class",
    "period",
    "unit",
    "forecast_p10",
    "forecast_p50",
    "forecast_p90",
    "actual_value",
    "actual_posture",
    "observed_at",
    "source_family",
    "evidence_ids",
    "methodology",
    "revision_risk",
    "inside_p10_p90",
    "signed_error",
    "absolute_error",
    "signed_error_ratio",
    "actual_to_forecast_p50_ratio",
    "interval_miss",
    "normalization_half_width",
    "normalized_absolute_error",
    "pinball_p10",
    "pinball_p50",
    "pinball_p90",
    "mean_pinball_loss",
    "normalized_mean_pinball_loss",
    "event_operator",
    "event_threshold",
    "event_unit",
    "event_forecast_probability",
    "event_realized",
    "brier_score",
]

GROUP_FIELDS = [
    "count",
    "units",
    "p10_p90_coverage_rate",
    "mean_signed_error",
    "mean_absolute_error",
    "mean_signed_error_ratio",
    "mean_absolute_percentage_error",
    "mean_normalized_pinball_loss",
    "mean_brier_score",
    "brier_event_count",
    "proposal_status",
    "eligible_for_application",
    "minimum_group_size",
    "additional_outcomes_needed",
    "p50_multiplier",
    "half_width_multiplier",
]

EVIDENCE_FIELDS = [
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
]


def build_calibration_release_documents(case: Mapping[str, Any]) -> dict[str, str]:
    result = score_calibration_dataset(case)
    dataset = case["dataset"]
    replay_dataset = json.loads(dataset["raw"])
    for selection in replay_dataset["forecasts"]:
        selection["path"] = f"sources/forecasts/{selection['id']}.json"
    documents = {
        "dashboard.html": render_calibration_dashboard(result),
        "result.json": _json(result),
        "scores.csv": _csv(SCORE_FIELDS, _score_rows(result)),
        "metric_class_summary.csv": _csv(
            ["metric_class", *GROUP_FIELDS],
            _group_rows(result["by_metric_class"], "metric_class"),
        ),
        "source_family_summary.csv": _csv(
            ["source_family", *GROUP_FIELDS],
            _group_rows(result["by_source_family"], "source_family"),
        ),
        "evidence.csv": _csv(EVIDENCE_FIELDS, result["evidence"]),
        "dataset.json": dataset["raw"].decode("utf-8"),
        "replay-dataset.json": _json(replay_dataset),
        "README.md": (
            f"# {dataset['id']}\n\n"
            f"As of: `{dataset['as_of_date']}`. Scored outcomes: `{len(result['scores'])}`. "
            f"Frozen forecast vintages: `{len(result['forecast_lineage'])}`.\n\n"
            + (
                "**This checked scorecard uses synthetic outcomes. It validates the calibration "
                "contract and is not evidence of historical forecast accuracy.**\n\n"
                if dataset["synthetic"]
                else "This scorecard uses evidence-backed outcomes; inspect revisions and source dependence before reliance.\n\n"
            )
            + "Open `dashboard.html` first. `result.json` preserves every score, grouping, "
            "proposal, warning, and evidence record. `dataset.json` and `sources/forecasts/` "
            "retain exact inputs; `replay-dataset.json` changes only their relative paths so the "
            "scorecard can be recomputed with this release as `source_root`. Calibration "
            "proposals are never auto-applied.\n"
        ),
    }
    for forecast in case["forecasts"].values():
        documents[f"sources/forecasts/{forecast['id']}.json"] = forecast["raw"].decode(
            "utf-8"
        )
    manifest = {
        "format": CALIBRATION_RELEASE_FORMAT,
        "dataset_id": dataset["id"],
        "as_of_date": dataset["as_of_date"],
        "recorded_at": dataset["recorded_at"],
        "synthetic": dataset["synthetic"],
        "dataset_sha256": dataset["sha256"],
        "outcome_count": len(result["scores"]),
        "forecast_count": len(result["forecast_lineage"]),
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_calibration_release(
    case: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_calibration_release_documents(case)
    destination = Path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != text.encode("utf-8")
            for name, text in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, text in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
