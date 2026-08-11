"""Auditable reconciliation release bundles."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .engine import reconcile
from .models import QuarterlyScenario
from .report import render_dashboard


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _csv(fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _distribution_rows(items: list[dict[str, Any]], key: str, identity: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        distribution = item[key]
        rows.append(
            {
                **{column: item[value] for column, value in identity.items()},
                "p10": distribution["p10"],
                "p50": distribution["p50"],
                "p90": distribution["p90"],
                "mean": distribution["mean"],
                "minimum": distribution["minimum"],
                "maximum": distribution["maximum"],
            }
        )
    return rows


def _estimate_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for owner_type, owners in (
        ("constraint", result["inputs"]["constraints"]),
        ("allocation", result["inputs"]["allocations"]),
        ("supplier_economics", result["inputs"]["supplier_economics"]),
        ("consensus", result["inputs"]["consensus"]),
        ("opportunity_factors", result["inputs"]["opportunity_factors"]),
    ):
        for owner in owners:
            owner_id = owner["id"]
            for parameter, value in owner.items():
                if not isinstance(value, dict) or "low" not in value:
                    continue
                rows.append(
                    {
                        "owner_type": owner_type,
                        "owner_id": owner_id,
                        "parameter": parameter,
                        "low": value["low"],
                        "base": value["base"],
                        "high": value["high"],
                        "unit": value["unit"],
                        "posture": value["posture"],
                        "confidence": value["confidence"],
                        "last_updated": value["last_updated"],
                        "methodology": value["methodology"],
                        "evidence_ids": "|".join(value["evidence_ids"]),
                        "confirming_evidence": value["confirming_evidence"],
                        "falsifying_evidence": value["falsifying_evidence"],
                        "correlation_group": value["correlation_group"] or "",
                    }
                )
    platform = result["inputs"]["platform"]
    for parameter in (
        "accelerator_packages_per_system",
        "servers_per_system",
        "racks_per_system",
    ):
        value = platform[parameter]
        rows.append(
            {
                "owner_type": "platform",
                "owner_id": platform["id"],
                "parameter": parameter,
                "low": value["low"],
                "base": value["base"],
                "high": value["high"],
                "unit": value["unit"],
                "posture": value["posture"],
                "confidence": value["confidence"],
                "last_updated": value["last_updated"],
                "methodology": value["methodology"],
                "evidence_ids": "|".join(value["evidence_ids"]),
                "confirming_evidence": value["confirming_evidence"],
                "falsifying_evidence": value["falsifying_evidence"],
                "correlation_group": value["correlation_group"] or "",
            }
        )
    return rows


def build_release_documents(
    scenario: QuarterlyScenario,
    *,
    source_document: str | None = None,
    constraint_capacity_draws: Mapping[str, Sequence[float]] | None = None,
    output_draws: list[dict[str, float]] | None = None,
) -> dict[str, str]:
    result = reconcile(
        scenario,
        constraint_capacity_draws=constraint_capacity_draws,
        output_draws=output_draws,
    )
    stage_rows = _distribution_rows(
        result["stage_outputs"], "system_equivalents", {"stage": "stage", "unit": "unit"}
    )
    bottleneck_rows = [
        {
            "stage": stage["stage"],
            "constraint_id": item["constraint_id"],
            "resource_name": item["resource_name"],
            "probability": item["probability"],
        }
        for stage in result["bottlenecks"]
        for item in stage["constraints"]
    ]
    allocation_rows = _distribution_rows(
        result["customer_allocations"],
        "systems_shipped",
        {"id": "id", "customer": "customer", "category": "category"},
    )
    evidence_fields = [
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
    estimate_fields = [
        "owner_type",
        "owner_id",
        "parameter",
        "low",
        "base",
        "high",
        "unit",
        "posture",
        "confidence",
        "last_updated",
        "methodology",
        "evidence_ids",
        "confirming_evidence",
        "falsifying_evidence",
        "correlation_group",
    ]
    documents = {
        "dashboard.html": render_dashboard(result),
        "result.json": _json(result),
        "stage_outputs.csv": _csv(
            ["stage", "unit", "p10", "p50", "p90", "mean", "minimum", "maximum"],
            stage_rows,
        ),
        "bottlenecks.csv": _csv(
            ["stage", "constraint_id", "resource_name", "probability"], bottleneck_rows
        ),
        "customer_allocations.csv": _csv(
            ["id", "customer", "category", "p10", "p50", "p90", "mean", "minimum", "maximum"],
            allocation_rows,
        ),
        "input_estimates.csv": _csv(estimate_fields, _estimate_rows(result)),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"Monte Carlo draws: `{scenario.samples:,}`.\n\n"
            + (
                "**This is an illustrative scenario. Synthetic capacity, yield, allocation, "
                "economics, and consensus inputs are not market estimates.**\n\n"
                if scenario.synthetic
                else "This scenario is marked evidence-backed; inspect every input and source before reliance.\n\n"
            )
            + "Open `dashboard.html` first. `result.json` is the complete machine-readable output; "
            "`input_estimates.csv` and `evidence.csv` provide the audit trail.\n"
        ),
    }
    if source_document is not None:
        documents["scenario.json"] = source_document.rstrip() + "\n"
    manifest = {
        "format": "ai-supply-release.v1",
        "scenario_id": scenario.id,
        "quarter": scenario.quarter,
        "as_of_date": scenario.as_of_date,
        "recorded_at": scenario.recorded_at,
        "synthetic": scenario.synthetic,
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_release(
    scenario: QuarterlyScenario,
    output_dir: str | Path,
    *,
    source_document: str | None = None,
) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    documents = build_release_documents(scenario, source_document=source_document)
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
