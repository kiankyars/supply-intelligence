"""Auditable release bundles for reconciliation revision alerts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .alert_report import render_alert_dashboard
from .alerts import detect_revision_alerts
from .release import _csv, _json, _sha256


def _load_result(path: Path) -> tuple[dict[str, Any], str, int]:
    content = path.read_bytes()
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"result in {path} must be an object")
    return value, hashlib.sha256(content).hexdigest(), len(content)


def _portable_source_path(path: Path, release_directory: Path) -> str:
    return Path(
        os.path.relpath(path.resolve(), start=release_directory.resolve())
    ).as_posix()


def build_alert_release_documents(
    report: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, str]:
    rows = []
    for alert in report["alerts"]:
        details = {
            key: value
            for key, value in alert.items()
            if key not in {"id", "type", "severity", "path"}
        }
        rows.append(
            {
                "id": alert["id"],
                "type": alert["type"],
                "severity": alert["severity"],
                "path": alert["path"],
                "details_json": json.dumps(
                    details,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ),
            }
        )
    documents = {
        "dashboard.html": render_alert_dashboard(report),
        "alerts.json": _json(report),
        "alerts.csv": _csv(
            ["id", "type", "severity", "path", "details_json"],
            rows,
        ),
        "lineage.json": _json(lineage),
        "README.md": (
            f"# Revision alerts for {report['scenario_id']}\n\n"
            f"Compared `{report['previous']['recorded_at']}` with "
            f"`{report['current']['recorded_at']}` and emitted "
            f"`{report['alert_count']}` alerts.\n\n"
            "Open `dashboard.html` first. `alerts.json` is the complete machine-readable "
            "comparison, `alerts.csv` is the flat queue, and `lineage.json` pins both "
            "source result files by byte length and SHA-256.\n"
        ),
    }
    manifest = {
        "format": "ai-supply-revision-alert-release.v1",
        "scenario_id": report["scenario_id"],
        "result_format": report["result_format"],
        "previous_recorded_at": report["previous"]["recorded_at"],
        "current_recorded_at": report["current"]["recorded_at"],
        "alert_count": report["alert_count"],
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_revision_alert_release(
    previous_result: str | Path,
    current_result: str | Path,
    output_dir: str | Path,
    *,
    output_relative_threshold: float = 0.10,
    bottleneck_probability_threshold: float = 0.15,
) -> dict[str, Any]:
    previous_path = Path(previous_result)
    current_path = Path(current_result)
    destination = Path(output_dir)
    previous, previous_hash, previous_bytes = _load_result(previous_path)
    current, current_hash, current_bytes = _load_result(current_path)
    report = detect_revision_alerts(
        previous,
        current,
        output_relative_threshold=output_relative_threshold,
        bottleneck_probability_threshold=bottleneck_probability_threshold,
        previous_sha256=previous_hash,
        current_sha256=current_hash,
    )
    lineage = {
        "format": "ai-supply-revision-lineage.v1",
        "previous": {
            "path": _portable_source_path(previous_path, destination),
            "bytes": previous_bytes,
            "sha256": previous_hash,
        },
        "current": {
            "path": _portable_source_path(current_path, destination),
            "bytes": current_bytes,
            "sha256": current_hash,
        },
    }
    documents = build_alert_release_documents(report, lineage)
    destination.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
