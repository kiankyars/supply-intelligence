"""Replay-safe releases for supplier-HBM manufacturing links."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hbm_manufacturing_link import (
    HbmManufacturingLinkCase,
    reconcile_hbm_manufacturing_link,
    reconcile_hbm_manufacturing_output_draws,
)
from .hbm_manufacturing_report import render_hbm_manufacturing_dashboard
from .manufacturing_engine import OUTPUT_UNITS
from .release import _csv, _json, _sha256


HBM_MANUFACTURING_LINK_RELEASE_FORMAT = "ai-supply-hbm-manufacturing-link-release.v1"
HBM_MANUFACTURING_DRAW_LINK_RELEASE_FORMAT = "ai-supply-hbm-manufacturing-link-release.v2"
HBM_MANUFACTURING_COVERAGE_LINK_RELEASE_FORMAT = "ai-supply-hbm-manufacturing-link-release.v3"
HBM_MANUFACTURING_OUTPUT_DRAW_RELEASE_FORMAT = "ai-supply-hbm-manufacturing-link-release.v4"


def _estimate_rows(value: Any, path: str = "inputs") -> list[dict[str, Any]]:
    rows = []
    if isinstance(value, dict):
        if {"low", "base", "high", "unit", "posture"}.issubset(value):
            rows.append(
                {
                    "path": path,
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
        else:
            for key, child in value.items():
                rows.extend(_estimate_rows(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            rows.extend(_estimate_rows(child, f"{path}[{index}]"))
    return rows


def build_hbm_manufacturing_link_release_documents(
    case: HbmManufacturingLinkCase,
    *,
    include_output_draws: bool = False,
) -> dict[str, str]:
    output_draws: list[dict[str, Any]] = []
    if include_output_draws:
        result, output_draws = reconcile_hbm_manufacturing_output_draws(case)
    else:
        result = reconcile_hbm_manufacturing_link(case)
    fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    output_rows = [
        {
            "metric": metric,
            "unit": OUTPUT_UNITS[metric],
            **distribution,
        }
        for metric, distribution in result["conversion_outputs"].items()
    ]
    gap_rows = [
        {**item, "evidence_ids": "|".join(item["evidence_ids"])}
        for item in result["research_queue"]
    ]
    documents = {
        "dashboard.html": render_hbm_manufacturing_dashboard(result),
        "result.json": _json(result),
        "conversion_outputs.csv": _csv(
            ["metric", "unit", *fields],
            output_rows,
        ),
        "bottlenecks.csv": _csv(
            ["constraint", "probability"],
            result["bottlenecks"],
        ),
        "input_estimates.csv": _csv(
            [
                "path",
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
            ],
            _estimate_rows(result["inputs"]),
        ),
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
            gap_rows,
        ),
        "evidence.csv": _csv(
            [
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
            ],
            result["evidence"],
        ),
        "manufacturing_scenario.json": case.manufacturing_document,
        "hbm_supplier_result.json": case.hbm_result_document,
        "link_recipe.json": case.recipe_document,
        "link_lineage.json": _json(case.lineage),
        "README.md": (
            f"# {result['scenario']['name']}\n\n"
            f"Quarter: `{result['scenario']['quarter']}`. As of: "
            f"`{result['scenario']['as_of_date']}`. Draws: "
            f"`{result['scenario']['samples']:,}`.\n\n"
            "**This linked manufacturing run remains illustrative. Logic, packaging, "
            "supplier HBM capacity, yields, qualification, allocation, and demand contain "
            "synthetic inputs. It is not an estimate of actual Blackwell production.**\n\n"
            "Open `dashboard.html` first. The aggregate HBM wafer branch is removed and "
            "replaced once by customer-allocated stacks from the hash-pinned supplier "
            "result. `link_lineage.json` records the removed flow, source hashes, topology "
            "checks, and lossy P10/P50/P90-to-triangular mapping. Both source documents and "
            "the link recipe are preserved byte for byte.\n"
        ),
    }
    if case.capacity_draws_document is not None:
        documents["hbm_supplier_capacity_draws.csv"] = (
            case.capacity_draws_document
        )
        documents["README.md"] = documents["README.md"].replace(
            "checks, and lossy P10/P50/P90-to-triangular mapping. Both source documents and ",
            "checks, and the deterministic draw permutation. Both source documents, the exact capacity draws, and ",
        )
    if case.package_coverage is not None:
        documents["README.md"] += (
            " Package assembly starts are explicitly declared material-cleared for "
            f"{', '.join(case.package_coverage['absorbed_resource_kinds'])}; this "
            "synthetic scope prevents those pools from being linked a second time.\n"
        )
    output_draw_fields = list(output_draws[0]) if output_draws else []
    if include_output_draws:
        documents["manufacturing_draws.csv"] = _csv(
            output_draw_fields,
            output_draws,
        )
        documents["README.md"] += (
            " `manufacturing_draws.csv` preserves every linked logic, HBM, package, "
            "and complete-system draw for downstream reconciliation without a quantile fit.\n"
        )
    manifest = {
        "format": (
            HBM_MANUFACTURING_OUTPUT_DRAW_RELEASE_FORMAT
            if include_output_draws
            else (
                HBM_MANUFACTURING_COVERAGE_LINK_RELEASE_FORMAT
                if case.package_coverage is not None
                else (
                    HBM_MANUFACTURING_DRAW_LINK_RELEASE_FORMAT
                    if case.capacity_draws
                    else HBM_MANUFACTURING_LINK_RELEASE_FORMAT
                )
            )
        ),
        "scenario_id": result["scenario"]["id"],
        "quarter": result["scenario"]["quarter"],
        "as_of_date": result["scenario"]["as_of_date"],
        "recorded_at": result["scenario"]["recorded_at"],
        "synthetic": result["scenario"]["synthetic"],
        "manufacturing_scenario_sha256": case.manufacturing_sha256,
        "hbm_supplier_result_sha256": case.hbm_result_sha256,
        "removed_aggregate_hbm_wafer_flow_id": case.lineage["replacement"][
            "removed_aggregate_hbm_wafer_flow_id"
        ],
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    if case.capacity_draws:
        manifest["hbm_supplier_capacity_draws_sha256"] = (
            case.capacity_draws_sha256
        )
        manifest["capacity_draw_count"] = len(case.capacity_draws)
    if case.package_coverage is not None:
        manifest["package_assembly_start_basis"] = case.package_coverage[
            "assembly_start_basis"
        ]
        manifest["absorbed_resource_kinds"] = list(
            case.package_coverage["absorbed_resource_kinds"]
        )
    if include_output_draws:
        manifest["manufacturing_draw_count"] = len(output_draws)
        manifest["manufacturing_draw_fields"] = output_draw_fields
    documents["manifest.json"] = _json(manifest)
    return documents


def write_hbm_manufacturing_link_release(
    case: HbmManufacturingLinkCase,
    output_dir: str | Path,
    *,
    include_output_draws: bool = False,
) -> dict[str, Any]:
    documents = build_hbm_manufacturing_link_release_documents(
        case,
        include_output_draws=include_output_draws,
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
