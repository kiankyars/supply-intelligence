"""Release bundles for gross-to-net data-center operational reconciliations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .datacenter_operational_engine import (
    OUTPUT_UNITS,
    reconcile_datacenter_operational,
    reconcile_datacenter_operational_capacity_draws,
)
from .datacenter_operational_models import DatacenterOperationalCase
from .datacenter_operational_report import (
    OUTPUT_LABELS,
    render_datacenter_operational_dashboard,
)
from .release import _csv, _json, _sha256


DATACENTER_OPERATIONAL_RELEASE_FORMAT = "ai-supply-datacenter-operational-release.v1"
DATACENTER_OPERATIONAL_DRAW_RELEASE_FORMAT = "ai-supply-datacenter-operational-release.v2"


ESTIMATE_FIELDS = [
    "owner_type",
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


def _estimates(result: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    inputs = result["inputs"]
    yield "gross_power", "gross_critical_it_power", inputs["gross_power"]["estimate"]
    for parameter, estimate in inputs["deductions"].items():
        if isinstance(estimate, dict) and "low" in estimate:
            yield "deduction", parameter, estimate
    for parameter in (
        "target_platform_share",
        "rack_it_load",
        "commissioning_slots",
        "commissioning_completion_ratio",
    ):
        yield "operational_conversion", parameter, inputs[parameter]


def _estimate_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "owner_type": owner_type,
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
        for owner_type, parameter, estimate in _estimates(result)
    ]


def _site_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for site in result["sites"]:
        capacity = site.get("capacity", {})
        rows.append(
            {
                "entity_id": site.get("entity_id", ""),
                "name": site.get("name", ""),
                "country": site.get("country", ""),
                "owner": site.get("owner", ""),
                "operator": site.get("operator", ""),
                "users": site.get("users", ""),
                "status": site.get("status", ""),
                "status_as_of": site.get("status_as_of", ""),
                "gross_low_mw": capacity.get("low", ""),
                "gross_base_mw": capacity.get("base", ""),
                "gross_high_mw": capacity.get("high", ""),
                "capacity_evidence_id": capacity.get("evidence_id", ""),
            }
        )
    return rows


def build_datacenter_operational_release_documents(
    case: DatacenterOperationalCase,
    *,
    scenario_document: str | None = None,
    gross_import_document: str | None = None,
    include_capacity_draws: bool = False,
) -> dict[str, str]:
    capacity_draws: list[dict[str, Any]] = []
    if include_capacity_draws:
        result, capacity_draws = reconcile_datacenter_operational_capacity_draws(
            case
        )
    else:
        result = reconcile_datacenter_operational(case)
    distribution_fields = ["p10", "p50", "p90", "mean", "minimum", "maximum"]
    output_rows = [
        {
            "metric": metric,
            "label": OUTPUT_LABELS[metric],
            "unit": OUTPUT_UNITS[metric],
            **distribution,
        }
        for metric, distribution in result["conversion_outputs"].items()
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
    research_rows = [
        {**item, "evidence_ids": "|".join(item["evidence_ids"])}
        for item in result["research_queue"]
    ]
    scenario = case.scenario
    documents = {
        "dashboard.html": render_datacenter_operational_dashboard(result),
        "result.json": _json(result),
        "operational_outputs.csv": _csv(
            ["metric", "label", "unit", *distribution_fields],
            output_rows,
        ),
        "bottlenecks.csv": _csv(
            ["constraint", "probability"],
            result["bottlenecks"],
        ),
        "input_estimates.csv": _csv(ESTIMATE_FIELDS, _estimate_rows(result)),
        "evidence_gaps.csv": _csv(
            [
                "parameter",
                "branch",
                "low",
                "base",
                "high",
                "unit",
                "posture",
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
        "selected_sites.csv": _csv(
            [
                "entity_id",
                "name",
                "country",
                "owner",
                "operator",
                "users",
                "status",
                "status_as_of",
                "gross_low_mw",
                "gross_base_mw",
                "gross_high_mw",
                "capacity_evidence_id",
            ],
            _site_rows(result),
        ),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "README.md": (
            f"# {scenario.name}\n\n"
            f"Quarter: `{scenario.quarter}`. As of: `{scenario.as_of_date}`. "
            f"Monte Carlo draws: `{scenario.samples:,}`.\n\n"
            + (
                "**This is an illustrative operational run. Site load, reservations, "
                "other-platform commitments, rack compatibility, target allocation, "
                "and commissioning inputs are synthetic. The output is not an estimate "
                "of actual Abilene headroom or rack deployments.**\n\n"
                if scenario.synthetic
                else "Inspect every source and input before relying on the output.\n\n"
            )
            + "Open `dashboard.html` first. `result.json` contains the complete model "
            "and lineage payload. `operational_outputs.csv` separates physical outputs "
            "from `input_estimates.csv`; `evidence_gaps.csv` ranks synthetic assumptions "
            "for replacement; and the two source JSON files preserve the hash-pinned "
            "scenario and gross-envelope inputs.\n"
        ),
    }
    if scenario_document is not None:
        documents["scenario.json"] = scenario_document.rstrip() + "\n"
    if gross_import_document is not None:
        documents["gross_import.json"] = gross_import_document
    capacity_draw_fields = list(capacity_draws[0]) if capacity_draws else []
    if include_capacity_draws:
        documents["capacity_draws.csv"] = _csv(
            capacity_draw_fields,
            capacity_draws,
        )
        documents["README.md"] += (
            " `capacity_draws.csv` preserves every gross-to-net power and commissioning "
            "draw for downstream reconciliation without a quantile fit.\n"
        )
    manifest = {
        "format": (
            DATACENTER_OPERATIONAL_DRAW_RELEASE_FORMAT
            if include_capacity_draws
            else DATACENTER_OPERATIONAL_RELEASE_FORMAT
        ),
        "scenario_id": scenario.id,
        "quarter": scenario.quarter,
        "as_of_date": scenario.as_of_date,
        "recorded_at": scenario.recorded_at,
        "synthetic": scenario.synthetic,
        "usable_as_operational_capacity": result["usable_as_operational_capacity"],
        "gross_import_sha256": case.gross_import_sha256,
        "files": {
            name: {
                "bytes": len(text.encode("utf-8")),
                "sha256": _sha256(text),
            }
            for name, text in sorted(documents.items())
        },
    }
    if include_capacity_draws:
        manifest["capacity_draw_count"] = len(capacity_draws)
        manifest["capacity_draw_fields"] = capacity_draw_fields
    documents["manifest.json"] = _json(manifest)
    return documents


def write_datacenter_operational_release(
    case: DatacenterOperationalCase,
    output_dir: str | Path,
    *,
    scenario_document: str | None = None,
    gross_import_document: str | None = None,
    include_capacity_draws: bool = False,
) -> dict[str, Any]:
    destination = Path(output_dir)
    documents = build_datacenter_operational_release_documents(
        case,
        scenario_document=scenario_document,
        gross_import_document=gross_import_document,
        include_capacity_draws=include_capacity_draws,
    )
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
