"""Replay-safe releases for supplier-resolved HBM portfolios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .hbm_supplier_engine import (
    SUPPLIER_OUTPUT_UNITS,
    TOTAL_OUTPUT_UNITS,
    reconcile_hbm_supplier_capacity_draws,
    reconcile_hbm_suppliers,
)
from .hbm_supplier_models import HbmSupplierScenario
from .hbm_supplier_report import render_hbm_supplier_dashboard
from .release import _csv, _json, _sha256


HBM_SUPPLIER_RELEASE_FORMAT = "ai-supply-hbm-supplier-release.v1"
HBM_SUPPLIER_DRAW_RELEASE_FORMAT = "ai-supply-hbm-supplier-release.v2"


def _estimate_groups(
    result: dict[str, Any],
) -> Iterable[tuple[str, str, dict[str, Any]]]:
    platform = result["inputs"]["platform"]
    yield "platform", platform["id"], platform
    for supplier in result["inputs"]["suppliers"]:
        yield "supplier_wafer", supplier["id"], supplier["wafer"]
        yield "supplier_process", supplier["id"], supplier


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


def _distribution_rows(
    values: dict[str, dict[str, float]],
    units: dict[str, str],
) -> list[dict[str, Any]]:
    return [
        {"metric": metric, "unit": units[metric], **distribution}
        for metric, distribution in sorted(values.items())
    ]


def build_hbm_supplier_release_documents(
    scenario: HbmSupplierScenario,
    *,
    source_document: str,
    include_capacity_draws: bool = False,
) -> dict[str, str]:
    capacity_draws: list[dict[str, Any]] = []
    if include_capacity_draws:
        result, capacity_draws = reconcile_hbm_supplier_capacity_draws(scenario)
    else:
        result = reconcile_hbm_suppliers(scenario)
    distribution_fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    supplier_rows = []
    for supplier in result["suppliers"]:
        for metric, distribution in sorted(supplier["outputs"].items()):
            supplier_rows.append(
                {
                    "supplier_id": supplier["id"],
                    "supplier_name": supplier["name"],
                    "capacity_scope_id": supplier["capacity_scope_id"],
                    "metric": metric,
                    "unit": SUPPLIER_OUTPUT_UNITS[metric],
                    **distribution,
                    "criticality_probability": supplier[
                        "criticality_probability"
                    ],
                }
            )
    gap_rows = [
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
        "dashboard.html": render_hbm_supplier_dashboard(result),
        "result.json": _json(result),
        "totals.csv": _csv(
            ["metric", "unit", *distribution_fields],
            _distribution_rows(result["totals"], TOTAL_OUTPUT_UNITS),
        ),
        "supplier_outputs.csv": _csv(
            [
                "supplier_id",
                "supplier_name",
                "capacity_scope_id",
                "metric",
                "unit",
                *distribution_fields,
                "criticality_probability",
            ],
            supplier_rows,
        ),
        "input_estimates.csv": _csv(estimate_fields, _estimate_rows(result)),
        "evidence_gaps.csv": _csv(
            [
                "owner_type",
                "owner_id",
                "parameter",
                "low",
                "base",
                "high",
                "unit",
                "confidence",
                "last_updated",
                "influence_share",
                "research_priority",
                "methodology",
                "evidence_ids",
                "confirming_evidence",
                "falsifying_evidence",
            ],
            gap_rows,
        ),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "scenario.json": source_document.rstrip() + "\n",
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"Suppliers: `{len(scenario.suppliers)}`. Draws: `{scenario.samples:,}`.\n\n"
            + (
                "**This supplier-resolved HBM portfolio remains illustrative. One or "
                "more wafer-start, geometry, yield, qualification, allocation, or "
                "demand inputs are synthetic, so it is not an estimate of actual HBM "
                "supply.**\n\n"
                if scenario.synthetic
                else "Inspect every source and capacity scope before relying on the output.\n\n"
            )
            + "Open `dashboard.html` first. `supplier_outputs.csv` preserves each "
            "non-overlapping declared capacity scope; `totals.csv` aggregates the "
            "customer-qualified stack pool; and `evidence_gaps.csv` ranks the remaining "
            "synthetic inputs.\n"
        ),
    }
    capacity_draw_fields = [
        "draw_index",
        "memory_dies_per_stack",
        "stacks_per_accelerator",
        "accelerator_package_demand",
        "demanded_stacks",
        "good_stacks",
        "platform_qualified_stacks",
        "customer_allocated_stacks",
        "hbm_package_equivalents",
        "packages_supported",
        *[
            f"supplier.{supplier.id}.customer_allocated_stacks"
            for supplier in scenario.suppliers
        ],
    ]
    if include_capacity_draws:
        flattened_draws = []
        for draw in capacity_draws:
            row = {
                key: value
                for key, value in draw.items()
                if key != "supplier_customer_allocated_stacks"
            }
            row.update(
                {
                    f"supplier.{supplier_id}.customer_allocated_stacks": value
                    for supplier_id, value in draw[
                        "supplier_customer_allocated_stacks"
                    ].items()
                }
            )
            flattened_draws.append(row)
        documents["capacity_draws.csv"] = _csv(
            capacity_draw_fields,
            flattened_draws,
        )
        documents["README.md"] += (
            " `capacity_draws.csv` preserves every sampled supplier allocation and "
            "aggregate capacity draw for downstream links without a quantile fit.\n"
        )
    for index, source in enumerate(scenario.source_documents):
        basename = Path(source.path).name
        documents[f"sources/{index:02d}-{basename}"] = source.raw.decode("utf-8")
    manifest = {
        "format": (
            HBM_SUPPLIER_DRAW_RELEASE_FORMAT
            if include_capacity_draws
            else HBM_SUPPLIER_RELEASE_FORMAT
        ),
        "scenario_id": scenario.id,
        "quarter": scenario.quarter,
        "as_of_date": scenario.as_of_date,
        "recorded_at": scenario.recorded_at,
        "synthetic": scenario.synthetic,
        "supplier_count": len(scenario.suppliers),
        "source_document_count": len(scenario.source_documents),
        "capacity_scope_ids": sorted(
            supplier.capacity_scope_id for supplier in scenario.suppliers
        ),
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    if include_capacity_draws:
        manifest["capacity_draw_count"] = len(capacity_draws)
        manifest["capacity_draw_fields"] = capacity_draw_fields
    documents["manifest.json"] = _json(manifest)
    return documents


def write_hbm_supplier_release(
    scenario: HbmSupplierScenario,
    output_dir: str | Path,
    *,
    source_document: str,
    include_capacity_draws: bool = False,
) -> dict[str, Any]:
    documents = build_hbm_supplier_release_documents(
        scenario,
        source_document=source_document,
        include_capacity_draws=include_capacity_draws,
    )
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
