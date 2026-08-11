"""Release bundles for wafer-to-package manufacturing reconciliations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .manufacturing_engine import OUTPUT_UNITS, reconcile_manufacturing
from .manufacturing_models import ManufacturingScenario
from .manufacturing_report import OUTPUT_LABELS, render_manufacturing_dashboard
from .release import _csv, _json, _sha256


def _estimate_groups(
    result: dict[str, Any],
) -> Iterable[tuple[str, str, dict[str, Any]]]:
    inputs = result["inputs"]
    yield "logic_wafer", inputs["logic"]["wafer"]["id"], inputs["logic"]["wafer"]
    yield "logic_process", "logic-yield-and-binning", inputs["logic"]
    yield "hbm_wafer", inputs["hbm"]["wafer"]["id"], inputs["hbm"]["wafer"]
    yield "hbm_process", "hbm-die-and-stack", inputs["hbm"]
    yield "package", "advanced-package-assembly", inputs["package"]
    yield "reference", "external-scale-controls", {
        item["id"]: item["estimate"] for item in inputs["references"]
    }


def _estimate_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for owner_type, owner_id, values in _estimate_groups(result):
        for parameter, estimate in values.items():
            if not isinstance(estimate, dict) or "low" not in estimate:
                continue
            rows.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "parameter": parameter,
                    "low": estimate["low"],
                    "base": estimate["base"],
                    "high": estimate["high"],
                    "unit": estimate["unit"],
                    "posture": estimate["posture"],
                    "confidence": estimate["confidence"],
                    "last_updated": estimate["last_updated"],
                    "methodology": estimate["methodology"],
                    "evidence_ids": "|".join(estimate["evidence_ids"]),
                    "confirming_evidence": estimate["confirming_evidence"],
                    "falsifying_evidence": estimate["falsifying_evidence"],
                    "correlation_group": estimate["correlation_group"] or "",
                }
            )
    return rows


def build_manufacturing_release_documents(
    scenario: ManufacturingScenario,
    *,
    source_document: str | None = None,
) -> dict[str, str]:
    result = reconcile_manufacturing(scenario)
    distribution_fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    output_rows = [
        {
            "metric": key,
            "label": OUTPUT_LABELS[key],
            "unit": OUTPUT_UNITS[key],
            **distribution,
        }
        for key, distribution in result["conversion_outputs"].items()
    ]
    reference_rows = [
        {
            "id": item["id"],
            "name": item["name"],
            "period": item["period"],
            "comparison_target": item["comparison_target"],
            "unit": item["unit"],
            "usable_as_product_capacity": item["usable_as_product_capacity"],
            **{
                f"reference_{key}": item["reference_value"][key]
                for key in ("p10", "p50", "p90")
            },
            **{
                f"modeled_{key}": item["modeled_target"][key]
                for key in ("p10", "p50", "p90")
            },
            **{
                f"share_{key}": item["target_share"][key]
                for key in ("p10", "p50", "p90")
            },
            "notes": item["notes"],
        }
        for item in result["reference_comparisons"]
    ]
    research_rows = [
        {**item, "evidence_ids": "|".join(item["evidence_ids"])}
        for item in result["research_queue"]
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
    documents = {
        "dashboard.html": render_manufacturing_dashboard(result),
        "result.json": _json(result),
        "conversion_outputs.csv": _csv(
            ["metric", "label", "unit", *distribution_fields], output_rows
        ),
        "bottlenecks.csv": _csv(
            ["constraint", "probability"], result["bottlenecks"]
        ),
        "reference_comparisons.csv": _csv(
            [
                "id",
                "name",
                "period",
                "comparison_target",
                "unit",
                "usable_as_product_capacity",
                "reference_p10",
                "reference_p50",
                "reference_p90",
                "modeled_p10",
                "modeled_p50",
                "modeled_p90",
                "share_p10",
                "share_p50",
                "share_p90",
                "notes",
            ],
            reference_rows,
        ),
        "input_estimates.csv": _csv(estimate_fields, _estimate_rows(result)),
        "evidence_gaps.csv": _csv(
            [
                "owner_type",
                "owner_id",
                "parameter",
                "branch",
                "low",
                "base",
                "high",
                "unit",
                "confidence",
                "last_updated",
                "influence_probability",
                "influence_method",
                "research_priority",
                "methodology",
                "evidence_ids",
                "confirming_evidence",
                "falsifying_evidence",
                "conditional_on_current_scenario",
            ],
            research_rows,
        ),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"Monte Carlo draws: `{scenario.samples:,}`.\n\n"
            + (
                "**This is an illustrative manufacturing run. One or more wafer, die "
                "geometry, yield, binning, supplier-allocation, or package-capacity "
                "inputs remain synthetic. Inspect `input_estimates.csv`; the output is "
                "not an estimate of actual Blackwell production.**\n\n"
                if scenario.synthetic
                else "Inspect every source and input before relying on the output.\n\n"
            )
            + "Open `dashboard.html` first. `result.json` contains the complete "
            "conversion and audit payload. `conversion_outputs.csv` separates physical "
            "outputs from `input_estimates.csv`; `evidence_gaps.csv` ranks synthetic "
            "inputs for replacement; and `evidence.csv` preserves source lineage.\n"
        ),
    }
    if source_document is not None:
        documents["scenario.json"] = source_document.rstrip() + "\n"
    manifest = {
        "format": "ai-supply-manufacturing-release.v1",
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


def write_manufacturing_release(
    scenario: ManufacturingScenario,
    output_dir: str | Path,
    *,
    source_document: str | None = None,
) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    documents = build_manufacturing_release_documents(
        scenario,
        source_document=source_document,
    )
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
