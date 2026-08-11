"""Replay-safe releases for forecast outcome reviews."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .forecast_outcome_review import build_forecast_outcome_review_result
from .forecast_outcome_review_report import render_forecast_outcome_review_dashboard
from .release import _csv, _json


FORECAST_OUTCOME_REVIEW_RELEASE_FORMAT = "ai-supply-forecast-outcome-review-release.v1"


DISPOSITION_FIELDS = [
    "id",
    "forecast_id",
    "metric",
    "metric_class",
    "period",
    "unit",
    "status",
    "calendar_status",
    "reviewer",
    "reviewed_at",
    "rationale",
    "actual_value",
    "posture",
    "observed_at",
    "source_family",
    "evidence_ids",
    "mismatch_dimensions",
    "reason_code",
    "eligible_for_evidence_backed_scoring",
    "eligible_for_model_calibration",
]


SCORE_FIELDS = [
    "forecast_id",
    "metric",
    "unit",
    "forecast_p10",
    "forecast_p50",
    "forecast_p90",
    "actual_value",
    "inside_p10_p90",
    "signed_error",
    "absolute_error",
    "interval_miss",
    "pinball_p10",
    "pinball_p50",
    "pinball_p90",
    "event_operator",
    "event_threshold",
    "event_probability",
    "event_realized",
    "brier_score",
]


def _disposition_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["dispositions"]:
        rows.append(
            {
                **item,
                "evidence_ids": "|".join(item.get("evidence_ids", [])),
                "mismatch_dimensions": "|".join(item.get("mismatch_dimensions", [])),
            }
        )
    return rows


def _score_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["dispositions"]:
        score = item["score"]
        if score is None:
            continue
        event = score["event_score"] or {}
        rows.append(
            {
                "forecast_id": item["forecast_id"],
                "metric": item["metric"],
                "unit": item["unit"],
                **{
                    key: value
                    for key, value in score.items()
                    if key not in {"pinball_loss", "event_score"}
                },
                "pinball_p10": score["pinball_loss"]["p10"],
                "pinball_p50": score["pinball_loss"]["p50"],
                "pinball_p90": score["pinball_loss"]["p90"],
                "event_operator": event.get("operator", ""),
                "event_threshold": event.get("threshold", ""),
                "event_probability": event.get("forecast_probability", ""),
                "event_realized": event.get("realized", ""),
                "brier_score": event.get("brier_score", ""),
            }
        )
    return rows


def build_forecast_outcome_review_release_documents(
    case: Mapping[str, Any],
) -> dict[str, bytes]:
    result = build_forecast_outcome_review_result(case)
    review = case["review"]
    registry = case["registry"]
    replay_review = json.loads(review["raw"])
    replay_review["registry_release"]["path"] = "sources/registry-release"
    for evidence in replay_review["evidence"]:
        evidence["path"] = f"sources/evidence/{evidence['id']}{Path(evidence['path']).suffix}"
    documents = {
        "dashboard.html": render_forecast_outcome_review_dashboard(result).encode("utf-8"),
        "result.json": _json(result).encode("utf-8"),
        "dispositions.csv": _csv(
            DISPOSITION_FIELDS, _disposition_rows(result)
        ).encode("utf-8"),
        "scores.csv": _csv(SCORE_FIELDS, _score_rows(result)).encode("utf-8"),
        "review.json": review["raw"],
        "replay-review.json": _json(replay_review).encode("utf-8"),
        "sources/registry-release/manifest.json": registry["manifest_raw"],
        f"sources/registry-release/{registry['result_file']}": registry["result_raw"],
        f"sources/registry-release/{registry['registry_file']}": registry["registry_raw"],
        "README.md": (
            f"# {review['id']}\n\n"
            f"As of: `{review['as_of_date']}`. Forecast dispositions: "
            f"`{len(case['dispositions'])}`. Scores: `{result['summary']['score_count']}`.\n\n"
            "This review covers every forecast in the pinned registry. Pending, scope-mismatched, "
            "and unobservable rows receive no score. The checked source registry is synthetic, so "
            "the release audits lifecycle discipline rather than model skill. Open `dashboard.html` "
            "first; inspect `dispositions.csv`, `scores.csv`, and `result.json` for the complete "
            "machine-readable state. `replay-review.json` remaps only preserved source paths.\n"
        ).encode("utf-8"),
    }
    for evidence in case["evidence"]:
        suffix = Path(evidence["path"]).suffix
        documents[f"sources/evidence/{evidence['id']}{suffix}"] = evidence["raw"]
    manifest = {
        "format": FORECAST_OUTCOME_REVIEW_RELEASE_FORMAT,
        "review_id": review["id"],
        "as_of_date": review["as_of_date"],
        "recorded_at": review["recorded_at"],
        "review_sha256": review["sha256"],
        "registry_manifest_sha256": registry["manifest_sha256"],
        "registry_result_sha256": registry["result_sha256"],
        "registry_sha256": registry["registry_sha256"],
        "source_synthetic": registry["synthetic"],
        "forecast_count": registry["forecast_count"],
        "disposition_count": len(case["dispositions"]),
        "evidence_count": len(case["evidence"]),
        "score_count": result["summary"]["score_count"],
        "files": {
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest).encode("utf-8")
    return documents


def write_forecast_outcome_review_release(
    case: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    destination = Path(output_dir)
    documents = build_forecast_outcome_review_release_documents(case)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != raw for name, raw in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, raw in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
