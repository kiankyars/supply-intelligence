"""Release bundles for shared-resource portfolio reconciliations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .portfolio_engine import reconcile_portfolio
from .portfolio_models import PortfolioScenario
from .portfolio_report import render_portfolio_dashboard
from .release import _csv, _json, _sha256


def _estimate_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for owner_type, owners, estimate_keys in (
        (
            "platform",
            result["inputs"]["platforms"],
            (
                "accelerator_packages_per_system",
                "servers_per_system",
                "racks_per_system",
                "demand",
                "priority_weight",
            ),
        ),
        (
            "resource_pool",
            result["inputs"]["resource_pools"],
            ("capacity", "effective_yield"),
        ),
        (
            "requirement",
            result["inputs"]["requirements"],
            ("units_per_system",),
        ),
    ):
        for owner in owners:
            for key in estimate_keys:
                estimate = owner[key]
                rows.append(
                    {
                        "owner_type": owner_type,
                        "owner_id": owner["id"],
                        "parameter": key,
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


def build_portfolio_release_documents(
    scenario: PortfolioScenario,
    *,
    source_document: str | None = None,
) -> dict[str, str]:
    result = reconcile_portfolio(scenario)
    stage_rows = [
        {
            "platform_id": platform["id"],
            "platform_name": platform["name"],
            "stage": stage["stage"],
            **stage["system_equivalents"],
        }
        for platform in result["platforms"]
        for stage in platform["stage_outputs"]
    ]
    resource_rows = [
        {
            "id": item["id"],
            "resource_kind": item["resource_kind"],
            "resource_name": item["resource_name"],
            "stage": item["stage"],
            "unit": item["unit"],
            "capacity_p10": item["effective_capacity"]["p10"],
            "capacity_p50": item["effective_capacity"]["p50"],
            "capacity_p90": item["effective_capacity"]["p90"],
            "consumption_p10": item["consumption"]["p10"],
            "consumption_p50": item["consumption"]["p50"],
            "consumption_p90": item["consumption"]["p90"],
            "utilization_p50": item["utilization"]["p50"],
            "binding_probability": item["binding_probability"],
        }
        for item in result["resource_pools"]
    ]
    inventory_rows = [
        {
            "platform_id": item["platform_id"],
            "platform_name": item["platform_name"],
            "from_stage": item["from_stage"],
            "to_stage": item["to_stage"],
            **item["systems_held_back"],
        }
        for item in result["inventory"]
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
    distribution_fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    documents = {
        "dashboard.html": render_portfolio_dashboard(result),
        "result.json": _json(result),
        "platform_stage_outputs.csv": _csv(
            ["platform_id", "platform_name", "stage", *distribution_fields], stage_rows
        ),
        "resource_pools.csv": _csv(
            [
                "id",
                "resource_kind",
                "resource_name",
                "stage",
                "unit",
                "capacity_p10",
                "capacity_p50",
                "capacity_p90",
                "consumption_p10",
                "consumption_p50",
                "consumption_p90",
                "utilization_p50",
                "binding_probability",
            ],
            resource_rows,
        ),
        "inventory.csv": _csv(
            [
                "platform_id",
                "platform_name",
                "from_stage",
                "to_stage",
                *distribution_fields,
            ],
            inventory_rows,
        ),
        "input_estimates.csv": _csv(estimate_fields, _estimate_rows(result)),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"Monte Carlo draws: `{scenario.samples:,}`.\n\n"
            + (
                "**This is an illustrative portfolio. Synthetic capacity, demand, yield, and "
                "priority inputs are not market estimates.**\n\n"
                if scenario.synthetic
                else "Inspect each source and input before relying on the portfolio output.\n\n"
            )
            + "Open `dashboard.html` first. `result.json` contains the full shared-resource "
            "allocation and audit payload.\n"
        ),
    }
    if source_document is not None:
        documents["portfolio.json"] = source_document.rstrip() + "\n"
    manifest = {
        "format": "ai-supply-portfolio-release.v1",
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


def write_portfolio_release(
    scenario: PortfolioScenario,
    output_dir: str | Path,
    *,
    source_document: str | None = None,
) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    documents = build_portfolio_release_documents(
        scenario, source_document=source_document
    )
    for name, text in documents.items():
        (destination / name).write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
