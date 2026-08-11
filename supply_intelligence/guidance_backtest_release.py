"""Replay-safe releases for reported-guidance backtests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .guidance_backtest import score_guidance_backtest
from .guidance_backtest_report import render_guidance_backtest_dashboard
from .release import _csv, _json, _sha256


GUIDANCE_BACKTEST_RELEASE_FORMAT = "ai-supply-guidance-backtest-release.v1"


SCORE_FIELDS = [
    "id",
    "label",
    "metric_class",
    "basis",
    "unit",
    "range_semantics",
    "guidance_low",
    "guidance_midpoint",
    "guidance_high",
    "actual_value",
    "inside_guidance_range",
    "surprise_direction",
    "signed_error",
    "absolute_error",
    "signed_error_ratio",
    "actual_to_guidance_midpoint_ratio",
    "interval_miss",
    "guidance_half_width",
    "normalization_scale",
    "normalized_absolute_error",
    "guidance_methodology",
    "outcome_methodology",
    "revision_risk",
]

EVIDENCE_FIELDS = [
    "id",
    "role",
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


def build_guidance_backtest_release_documents(
    case: Mapping[str, Any],
) -> dict[str, str]:
    result = score_guidance_backtest(case)
    metadata = result["case"]
    documents = {
        "dashboard.html": render_guidance_backtest_dashboard(result),
        "result.json": _json(result),
        "scores.csv": _csv(SCORE_FIELDS, result["scores"]),
        "evidence.csv": _csv(EVIDENCE_FIELDS, result["evidence"]),
        "case.json": case["case"]["raw"].decode("utf-8"),
        "sources/guidance-observation.json": case["guidance"]["raw"].decode(
            "utf-8"
        ),
        "sources/outcome-observation.json": case["outcome"]["raw"].decode(
            "utf-8"
        ),
        "README.md": (
            f"# {metadata['id']}\n\n"
            f"{metadata['entity']['name']} `{metadata['period']['label']}`. "
            f"As of `{metadata['as_of_date']}`. Metrics scored: "
            f"`{result['summary']['metric_count']}`.\n\n"
            "**This is an evidence-backed reconstruction of external company guidance, "
            "not a native AI Supply Intelligence forecast. It is ineligible for model "
            "calibration.**\n\n"
            "Open `dashboard.html` first. `result.json` and `scores.csv` retain the "
            "range-coverage and midpoint-error audit. `case.json` and `sources/` retain "
            "the exact normalized observations and hashes. Management ranges are not "
            "treated as probability quantiles.\n"
        ),
    }
    manifest = {
        "format": GUIDANCE_BACKTEST_RELEASE_FORMAT,
        "case_id": metadata["id"],
        "entity_id": metadata["entity"]["id"],
        "period": metadata["period"]["label"],
        "as_of_date": metadata["as_of_date"],
        "recorded_at": metadata["recorded_at"],
        "native_model_forecast": False,
        "eligible_for_model_calibration": False,
        "guidance_observation_sha256": case["guidance"]["sha256"],
        "outcome_observation_sha256": case["outcome"]["sha256"],
        "metric_count": result["summary"]["metric_count"],
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_guidance_backtest_release(
    case: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_guidance_backtest_release_documents(case)
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
