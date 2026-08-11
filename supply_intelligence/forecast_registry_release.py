"""Hash-complete, replay-safe native forecast registry releases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .forecast_registry import build_forecast_registry_result
from .forecast_registry_report import render_forecast_registry_dashboard
from .release import _csv, _json


FORECAST_REGISTRY_RELEASE_FORMAT = "ai-supply-forecast-registry-release.v1"


FORECAST_FIELDS = [
    "id",
    "metric",
    "metric_class",
    "period",
    "unit",
    "draw_column",
    "p10",
    "p50",
    "p90",
    "mean",
    "minimum",
    "maximum",
    "event_operator",
    "event_threshold",
    "event_probability",
    "maturity_status",
    "calendar_eligible_to_attach_outcome",
    "outcome_attached",
    "eligible_to_score",
    "eligible_for_model_calibration",
    "blockers",
]


CONTRACT_FIELDS = [
    "id",
    "metric",
    "entity",
    "product",
    "geography",
    "quantity_semantics",
    "aggregation",
    "cutoff_date",
    "scope_definition",
    "earliest_observed_at",
    "expected_evidence_by",
    "revision_window_end",
    "acceptable_postures",
    "required_evidence",
    "measurement_method",
    "confirming_evidence",
    "falsifying_evidence",
    "known_observability_gap",
]


def _forecast_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["forecasts"]:
        event = item["event"] or {}
        maturity = item["maturity"]
        rows.append(
            {
                **{key: item[key] for key in ("id", "metric", "metric_class", "period", "unit", "draw_column")},
                **item["distribution"],
                "event_operator": event.get("operator", ""),
                "event_threshold": event.get("threshold", ""),
                "event_probability": event.get("forecast_probability", ""),
                "maturity_status": maturity["status"],
                "calendar_eligible_to_attach_outcome": maturity[
                    "calendar_eligible_to_attach_outcome"
                ],
                "outcome_attached": maturity["outcome_attached"],
                "eligible_to_score": maturity["eligible_to_score"],
                "eligible_for_model_calibration": maturity[
                    "eligible_for_model_calibration"
                ],
                "blockers": "|".join(maturity["blockers"]),
            }
        )
    return rows


def _contract_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["forecasts"]:
        rows.append(
            {
                "id": item["id"],
                "metric": item["metric"],
                **item["target"],
                **{
                    key: value
                    for key, value in item["outcome_contract"].items()
                    if key != "acceptable_postures"
                },
                "acceptable_postures": "|".join(
                    item["outcome_contract"]["acceptable_postures"]
                ),
            }
        )
    return rows


def build_forecast_registry_release_documents(
    case: Mapping[str, Any],
) -> dict[str, bytes]:
    result = build_forecast_registry_result(case)
    registry = case["registry"]
    source = case["source"]
    replay_registry = json.loads(registry["raw"])
    replay_registry["source_release"]["path"] = "sources/source-release"
    documents = {
        "dashboard.html": render_forecast_registry_dashboard(result).encode("utf-8"),
        "result.json": _json(result).encode("utf-8"),
        "forecasts.csv": _csv(FORECAST_FIELDS, _forecast_rows(result)).encode("utf-8"),
        "outcome_contracts.csv": _csv(
            CONTRACT_FIELDS, _contract_rows(result)
        ).encode("utf-8"),
        "registry.json": registry["raw"],
        "replay-registry.json": _json(replay_registry).encode("utf-8"),
        "sources/source-release/manifest.json": source["manifest_raw"],
        f"sources/source-release/{source['result_file']}": source["result_raw"],
        f"sources/source-release/{source['draws_file']}": source["draws_raw"],
        "README.md": (
            f"# {registry['id']}\n\n"
            f"As of: `{registry['as_of_date']}`. Recorded: `{registry['recorded_at']}`. "
            f"Forecasts: `{len(case['forecasts'])}`. Raw draws: `{source['draw_count']:,}`.\n\n"
            "**This is a genuine pre-outcome native-model vintage, but its checked source "
            "scenario is synthetic and illustrative. It is not an estimate of actual production, "
            "shipments, installation, or operation and is ineligible for evidence-backed model "
            "calibration.**\n\n"
            "Open `dashboard.html` first. `registry.json` preserves the exact original recipe; "
            "`sources/source-release/` preserves the source manifest, result, and complete raw "
            "draw ledger byte for byte. `replay-registry.json` changes only the source-release "
            "path so this release can validate and rebuild in isolation. No outcome or score is "
            "present. A later outcome must pass the frozen scope and evidence contract.\n"
        ).encode("utf-8"),
    }
    manifest = {
        "format": FORECAST_REGISTRY_RELEASE_FORMAT,
        "registry_id": registry["id"],
        "as_of_date": registry["as_of_date"],
        "recorded_at": registry["recorded_at"],
        "native_model_forecast": True,
        "source_synthetic": source["synthetic"],
        "registry_sha256": registry["sha256"],
        "source_manifest_sha256": source["manifest_sha256"],
        "source_result_sha256": source["result_sha256"],
        "source_draws_sha256": source["draws_sha256"],
        "forecast_count": len(case["forecasts"]),
        "draw_count": source["draw_count"],
        "outcome_count": 0,
        "score_count": 0,
        "files": {
            name: {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            for name, raw in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest).encode("utf-8")
    return documents


def write_forecast_registry_release(
    case: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    destination = Path(output_dir)
    documents = build_forecast_registry_release_documents(case)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != raw
            for name, raw in documents.items()
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
