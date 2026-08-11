"""Replay-safe releases for supplier-resolved system assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .release import _csv, _json, _sha256
from .system_assembly_engine import (
    ODM_OUTPUT_UNITS,
    OUTPUT_UNITS,
    reconcile_system_assembly_capacity_draws,
)
from .system_assembly_models import SystemAssemblyScenario
from .system_assembly_report import render_system_assembly_dashboard


SYSTEM_ASSEMBLY_RELEASE_FORMAT = "ai-supply-system-assembly-release.v1"


def _estimate_groups(
    result: dict[str, Any],
) -> Iterable[tuple[str, str, dict[str, Any]]]:
    yield "platform", result["inputs"]["platform"]["id"], result["inputs"]["platform"]
    for odm in result["inputs"]["odms"]:
        yield "odm", odm["id"], odm
    for component in result["inputs"]["components"]:
        yield "component", component["id"], component


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


def build_system_assembly_release_documents(
    scenario: SystemAssemblyScenario,
    *,
    source_document: str,
) -> dict[str, str]:
    result, capacity_draws = reconcile_system_assembly_capacity_draws(scenario)
    distribution_fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    odm_rows = []
    for odm in result["odms"]:
        for metric, distribution in sorted(odm["outputs"].items()):
            odm_rows.append(
                {
                    "odm_id": odm["id"],
                    "odm_name": odm["name"],
                    "tray_capacity_scope_id": odm["tray_capacity_scope_id"],
                    "rack_capacity_scope_id": odm["rack_capacity_scope_id"],
                    "metric": metric,
                    "unit": ODM_OUTPUT_UNITS[metric],
                    **distribution,
                    "compute_tray_bottleneck_probability": odm[
                        "stage_bottleneck_probabilities"
                    ].get("compute_trays", 0.0),
                    "rack_integration_bottleneck_probability": odm[
                        "stage_bottleneck_probabilities"
                    ].get("rack_integration", 0.0),
                }
            )
    component_rows = []
    for component in result["components"]:
        for metric, distribution in sorted(component["outputs"].items()):
            unit = (
                "rack"
                if metric == "rack_equivalents"
                else "ratio"
                if metric == "customer_allocated_utilization"
                else component["unit"]
            )
            component_rows.append(
                {
                    "component_id": component["id"],
                    "component_name": component["name"],
                    "stage": component["stage"],
                    "resource_kind": component["resource_kind"],
                    "capacity_scope_id": component["capacity_scope_id"],
                    "metric": metric,
                    "unit": unit,
                    **distribution,
                    "bottleneck_probability": component[
                        "bottleneck_probability"
                    ],
                }
            )
    gap_rows = [
        {**item, "evidence_ids": "|".join(item["evidence_ids"])}
        for item in result["research_queue"]
    ]
    flattened_draws = []
    for draw in capacity_draws:
        row = {
            key: value
            for key, value in draw.items()
            if key not in {"odms", "components"}
        }
        for odm_id, values in draw["odms"].items():
            for metric, value in values.items():
                row[f"odm.{odm_id}.{metric}"] = value
        for component_id, values in draw["components"].items():
            for metric, value in values.items():
                row[f"component.{component_id}.{metric}"] = value
        flattened_draws.append(row)
    draw_fields = list(flattened_draws[0])
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
        "dashboard.html": render_system_assembly_dashboard(result),
        "result.json": _json(result),
        "conversion_outputs.csv": _csv(
            ["metric", "unit", *distribution_fields],
            [
                {"metric": metric, "unit": OUTPUT_UNITS[metric], **distribution}
                for metric, distribution in sorted(
                    result["conversion_outputs"].items()
                )
            ],
        ),
        "odm_outputs.csv": _csv(
            [
                "odm_id",
                "odm_name",
                "tray_capacity_scope_id",
                "rack_capacity_scope_id",
                "metric",
                "unit",
                *distribution_fields,
                "compute_tray_bottleneck_probability",
                "rack_integration_bottleneck_probability",
            ],
            odm_rows,
        ),
        "component_outputs.csv": _csv(
            [
                "component_id",
                "component_name",
                "stage",
                "resource_kind",
                "capacity_scope_id",
                "metric",
                "unit",
                *distribution_fields,
                "bottleneck_probability",
            ],
            component_rows,
        ),
        "bottlenecks.csv": _csv(
            ["constraint", "probability"],
            result["bottlenecks"],
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
                "influence_probability",
                "research_priority",
                "methodology",
                "evidence_ids",
                "confirming_evidence",
                "falsifying_evidence",
            ],
            gap_rows,
        ),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "capacity_draws.csv": _csv(draw_fields, flattened_draws),
        "scenario.json": source_document.rstrip() + "\n",
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"ODMs: `{len(scenario.odms)}`. Component pools: "
            f"`{len(scenario.components)}`. Draws: `{scenario.samples:,}`.\n\n"
            "**This supplier-resolved assembly run is illustrative. ODM and component "
            "capacity, yield, qualification, allocation, and demand inputs are synthetic. "
            "It is not an estimate of actual GB200 rack output.**\n\n"
            "Open `dashboard.html` first. `capacity_draws.csv` preserves every sampled "
            "ODM and component handoff. The complete-rack output is component-cleared only "
            "for the exact coverage selectors in `result.json`; factory qualification, "
            "logistics, site installation, and deployment infrastructure remain separate.\n"
        ),
    }
    for index, source in enumerate(scenario.source_documents):
        documents[f"sources/{index:02d}-{Path(source.path).name}"] = source.raw.decode(
            "utf-8"
        )
    manifest = {
        "format": SYSTEM_ASSEMBLY_RELEASE_FORMAT,
        "scenario_id": scenario.id,
        "quarter": scenario.quarter,
        "as_of_date": scenario.as_of_date,
        "recorded_at": scenario.recorded_at,
        "synthetic": scenario.synthetic,
        "odm_count": len(scenario.odms),
        "component_pool_count": len(scenario.components),
        "capacity_scope_ids": sorted(
            [
                scope
                for odm in scenario.odms
                for scope in (
                    odm.tray_capacity_scope_id,
                    odm.rack_capacity_scope_id,
                )
            ]
            + [component.capacity_scope_id for component in scenario.components]
        ),
        "capacity_draw_count": len(capacity_draws),
        "capacity_draw_fields": draw_fields,
        "complete_rack_output_basis": scenario.coverage.output_basis,
        "absorbed_constraints": [
            {
                "stage": selector.stage,
                "resource_kind": selector.resource_kind,
            }
            for selector in scenario.coverage.absorbed_constraints
        ],
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_system_assembly_release(
    scenario: SystemAssemblyScenario,
    output_dir: str | Path,
    *,
    source_document: str,
) -> dict[str, Any]:
    documents = build_system_assembly_release_documents(
        scenario,
        source_document=source_document,
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
    return {"output_dir": str(destination.resolve()), **json.loads(documents["manifest.json"])}
