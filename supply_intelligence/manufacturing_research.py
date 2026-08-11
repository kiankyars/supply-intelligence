"""Prioritize missing manufacturing evidence from the current scenario."""

from __future__ import annotations

from typing import Any, Iterable


def _estimate_groups(
    inputs: dict[str, Any],
) -> Iterable[tuple[str, str, str, dict[str, Any]]]:
    yield "logic_wafer", inputs["logic"]["wafer"]["id"], "logic_binned_dies", inputs[
        "logic"
    ]["wafer"]
    yield "logic_process", "logic-yield-and-binning", "logic_binned_dies", inputs[
        "logic"
    ]
    yield "hbm_wafer", inputs["hbm"]["wafer"]["id"], "hbm_good_stacks", inputs[
        "hbm"
    ]["wafer"]
    yield "hbm_process", "hbm-die-and-stack", "hbm_good_stacks", inputs["hbm"]
    yield "package", "advanced-package-assembly", "package_assembly_starts", inputs[
        "package"
    ]


def build_manufacturing_research_queue(
    inputs: dict[str, Any],
    bottlenecks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank synthetic inputs by current-run output influence and evidence weakness."""

    binding = {item["constraint"]: item["probability"] for item in bottlenecks}
    rows = []
    for owner_type, owner_id, branch, values in _estimate_groups(inputs):
        for parameter, estimate in values.items():
            if not isinstance(estimate, dict) or estimate.get("posture") != "synthetic":
                continue
            influence = binding.get(branch, 0.0)
            influence_method = "Current branch binding probability"
            if owner_type == "package" and parameter == "assembly_yield":
                influence = 1.0
                influence_method = "Applied to every attempted package"
            rows.append(
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "parameter": parameter,
                    "branch": branch,
                    "low": estimate["low"],
                    "base": estimate["base"],
                    "high": estimate["high"],
                    "unit": estimate["unit"],
                    "confidence": estimate["confidence"],
                    "last_updated": estimate["last_updated"],
                    "influence_probability": influence,
                    "influence_method": influence_method,
                    "research_priority": influence * (1 - estimate["confidence"]),
                    "methodology": estimate["methodology"],
                    "evidence_ids": estimate["evidence_ids"],
                    "confirming_evidence": estimate["confirming_evidence"],
                    "falsifying_evidence": estimate["falsifying_evidence"],
                    "conditional_on_current_scenario": True,
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            -item["research_priority"],
            item["owner_type"],
            item["owner_id"],
            item["parameter"],
        ),
    )
