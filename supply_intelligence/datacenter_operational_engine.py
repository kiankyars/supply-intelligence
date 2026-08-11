"""Monte Carlo conversion from gross site power to operational rack throughput."""

from __future__ import annotations

from collections import defaultdict
from math import isclose
from random import Random
from typing import Any

from .datacenter_operational_models import DatacenterOperationalCase
from .engine import EstimateSampler, _input_estimate, summarize
from .models import Estimate, EstimatePosture


OUTPUT_UNITS = {
    "gross_critical_it_power": "MW",
    "current_critical_it_load": "MW",
    "contracted_reservations": "MW",
    "other_platform_commitments": "MW",
    "rack_incompatible_capacity": "MW",
    "total_deductions": "MW",
    "net_uncommitted_compatible_power": "MW",
    "other_unallocated_compatible_power": "MW",
    "target_allocatable_power": "MW",
    "power_limited_racks": "rack",
    "commissioning_slots": "rack",
    "commissioning_completed_capacity": "rack",
    "operational_racks": "rack",
    "operational_rack_power": "MW",
    "shadow_allocatable_power": "MW",
    "shadow_commissioning_capacity": "rack",
    "oversubscribed_deductions": "MW",
    "gross_power_utilization": "ratio",
    "target_power_utilization": "ratio",
    "commissioning_utilization": "ratio",
}


def _evidence_payload(case: DatacenterOperationalCase) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "kind": item.kind.value,
            "title": item.title,
            "source_url": item.source_url,
            "publisher": item.publisher,
            "retrieved_at": item.retrieved_at,
            "published_at": item.published_at,
            "source_family": item.source_family,
            "license": item.license,
            "excerpt": item.excerpt,
            "content_hash": item.content_hash,
        }
        for item in case.evidence
    ]


def _input_payload(case: DatacenterOperationalCase) -> dict[str, Any]:
    scenario = case.scenario
    return {
        "gross_power": {
            "estimate": _input_estimate(case.gross_estimate),
            "source_sha256": case.gross_import_sha256,
            "expected_entity_ids": list(
                scenario.gross_power.expected_entity_ids
            ),
            "datacenter_manifest_sha256": (
                scenario.gross_power.expected_datacenter_manifest_sha256
            ),
            "capacity_semantics": "gross_site_critical_it_envelope",
            "availability_status": "not_net_incremental_capacity",
        },
        "deductions": {
            "current_critical_it_load": _input_estimate(
                scenario.deductions.current_critical_it_load
            ),
            "contracted_reservations": _input_estimate(
                scenario.deductions.contracted_reservations
            ),
            "other_platform_commitments": _input_estimate(
                scenario.deductions.other_platform_commitments
            ),
            "rack_incompatible_capacity": _input_estimate(
                scenario.deductions.rack_incompatible_capacity
            ),
            "non_overlap_rationale": scenario.deductions.non_overlap_rationale,
        },
        "target_platform_share": _input_estimate(
            scenario.target_platform_share
        ),
        "rack_it_load": _input_estimate(scenario.rack_it_load),
        "commissioning_slots": _input_estimate(scenario.commissioning_slots),
        "commissioning_completion_ratio": _input_estimate(
            scenario.commissioning_completion_ratio
        ),
    }


def _research_item(
    parameter: str,
    branch: str,
    estimate: Estimate,
    influence_probability: float,
) -> dict[str, Any]:
    return {
        "parameter": parameter,
        "branch": branch,
        "low": estimate.low,
        "base": estimate.base,
        "high": estimate.high,
        "unit": estimate.unit,
        "posture": estimate.posture.value,
        "confidence": estimate.confidence,
        "last_updated": estimate.last_updated,
        "influence_probability": influence_probability,
        "influence_method": (
            "Current-run probability that this input's branch constrains "
            "operational racks; this is a triage heuristic, not causal proof."
        ),
        "research_priority": influence_probability * (1 - estimate.confidence),
        "methodology": estimate.methodology,
        "evidence_ids": list(estimate.evidence_ids),
        "confirming_evidence": estimate.confirming_evidence,
        "falsifying_evidence": estimate.falsifying_evidence,
        "conditional_on_current_scenario": True,
    }


def reconcile_datacenter_operational(
    case: DatacenterOperationalCase,
    *,
    _capacity_draws: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Subtract site commitments, then constrain racks by power and commissioning."""

    scenario = case.scenario
    random = Random(scenario.seed)
    samples: dict[str, list[float]] = defaultdict(list)
    bottleneck_counts: dict[str, float] = defaultdict(float)
    zero_residual_draws = 0

    for draw_index in range(scenario.samples):
        sampler = EstimateSampler(random)
        gross = sampler.estimate(case.gross_estimate)
        current_load = sampler.estimate(
            scenario.deductions.current_critical_it_load
        )
        reservations = sampler.estimate(
            scenario.deductions.contracted_reservations
        )
        other_commitments = sampler.estimate(
            scenario.deductions.other_platform_commitments
        )
        incompatible = sampler.estimate(
            scenario.deductions.rack_incompatible_capacity
        )
        total_deductions = (
            current_load + reservations + other_commitments + incompatible
        )
        residual = max(0.0, gross - total_deductions)
        oversubscribed = max(0.0, total_deductions - gross)
        if residual == 0:
            zero_residual_draws += 1

        target_share = sampler.estimate(scenario.target_platform_share)
        target_power = residual * target_share
        other_unallocated = residual - target_power
        rack_it_load = sampler.estimate(scenario.rack_it_load)
        power_limited_racks = target_power / rack_it_load

        commissioning_slots = sampler.estimate(scenario.commissioning_slots)
        completion_ratio = sampler.estimate(
            scenario.commissioning_completion_ratio
        )
        commissioning_capacity = commissioning_slots * completion_ratio
        candidates = {
            "power": power_limited_racks,
            "commissioning": commissioning_capacity,
        }
        operational_racks = min(candidates.values())
        tied = [
            key
            for key, value in candidates.items()
            if isclose(value, operational_racks, rel_tol=1e-10, abs_tol=1e-8)
        ]
        for key in tied:
            bottleneck_counts[key] += 1 / len(tied)

        operational_power = operational_racks * rack_it_load
        shadow_power = max(0.0, target_power - operational_power)
        shadow_commissioning = max(
            0.0,
            commissioning_capacity - operational_racks,
        )
        values = {
            "gross_critical_it_power": gross,
            "current_critical_it_load": current_load,
            "contracted_reservations": reservations,
            "other_platform_commitments": other_commitments,
            "rack_incompatible_capacity": incompatible,
            "total_deductions": total_deductions,
            "net_uncommitted_compatible_power": residual,
            "other_unallocated_compatible_power": other_unallocated,
            "target_allocatable_power": target_power,
            "power_limited_racks": power_limited_racks,
            "commissioning_slots": commissioning_slots,
            "commissioning_completed_capacity": commissioning_capacity,
            "operational_racks": operational_racks,
            "operational_rack_power": operational_power,
            "shadow_allocatable_power": shadow_power,
            "shadow_commissioning_capacity": shadow_commissioning,
            "oversubscribed_deductions": oversubscribed,
            "gross_power_utilization": (
                0.0 if gross == 0 else operational_power / gross
            ),
            "target_power_utilization": (
                0.0 if target_power == 0 else operational_power / target_power
            ),
            "commissioning_utilization": (
                0.0
                if commissioning_capacity == 0
                else operational_racks / commissioning_capacity
            ),
        }
        for key, value in values.items():
            samples[key].append(value)
        if _capacity_draws is not None:
            _capacity_draws.append({"draw_index": draw_index, **values})

    bottlenecks = [
        {
            "constraint": key,
            "probability": bottleneck_counts[key] / scenario.samples,
        }
        for key in sorted(
            bottleneck_counts,
            key=lambda item: (-bottleneck_counts[item], item),
        )
    ]
    probabilities = {
        item["constraint"]: item["probability"] for item in bottlenecks
    }
    power_probability = probabilities.get("power", 0.0)
    commissioning_probability = probabilities.get("commissioning", 0.0)
    research_inputs = (
        (
            "current_critical_it_load",
            "power",
            scenario.deductions.current_critical_it_load,
            power_probability,
        ),
        (
            "contracted_reservations",
            "power",
            scenario.deductions.contracted_reservations,
            power_probability,
        ),
        (
            "other_platform_commitments",
            "power",
            scenario.deductions.other_platform_commitments,
            power_probability,
        ),
        (
            "rack_incompatible_capacity",
            "power",
            scenario.deductions.rack_incompatible_capacity,
            power_probability,
        ),
        (
            "target_platform_share",
            "power",
            scenario.target_platform_share,
            power_probability,
        ),
        (
            "rack_it_load",
            "power",
            scenario.rack_it_load,
            power_probability,
        ),
        (
            "commissioning_slots",
            "commissioning",
            scenario.commissioning_slots,
            commissioning_probability,
        ),
        (
            "commissioning_completion_ratio",
            "commissioning",
            scenario.commissioning_completion_ratio,
            commissioning_probability,
        ),
    )
    research_queue = sorted(
        (
            _research_item(parameter, branch, estimate, influence)
            for parameter, branch, estimate, influence in research_inputs
            if estimate.posture is EstimatePosture.SYNTHETIC
        ),
        key=lambda item: (-item["research_priority"], item["parameter"]),
    )
    warnings = [
        "The imported MW range is a gross site critical-IT envelope, not vacant or platform-allocated capacity.",
        "Deductions are additive only because the scenario supplies an explicit non-overlap rationale; overlapping categories would double count unavailable power.",
        "Operational racks are the lower of power-supported racks and completed commissioning slots in the target quarter.",
    ]
    if scenario.synthetic:
        warnings.append(
            "Site load, reservations, platform commitments, compatibility, allocation, and commissioning inputs are synthetic; outputs are not an estimate of actual Abilene headroom or deployments."
        )
    return {
        "format": "ai-supply-datacenter-operational-result.v1",
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "quarter": scenario.quarter,
            "as_of_date": scenario.as_of_date,
            "recorded_at": scenario.recorded_at,
            "synthetic": scenario.synthetic,
            "samples": scenario.samples,
            "seed": scenario.seed,
            "scope_description": scenario.scope_description,
            "notes": scenario.notes,
        },
        "usable_as_operational_capacity": (
            not scenario.synthetic
            and case.gross_estimate.posture is not EstimatePosture.SYNTHETIC
            and all(
                estimate.posture is not EstimatePosture.SYNTHETIC
                for estimate in scenario.iter_estimates()
            )
        ),
        "conversion_outputs": {
            key: summarize(values).as_dict()
            for key, values in sorted(samples.items())
        },
        "bottlenecks": bottlenecks,
        "diagnostics": {
            "zero_residual_probability": zero_residual_draws / scenario.samples,
            "deduction_non_overlap_rationale": (
                scenario.deductions.non_overlap_rationale
            ),
        },
        "research_queue": research_queue,
        "inputs": _input_payload(case),
        "sites": [dict(item) for item in case.sites],
        "gross_lineage": dict(case.gross_lineage),
        "evidence": _evidence_payload(case),
        "methodology": {
            "gross_to_net": (
                "For each draw, subtract current critical-IT load, contracted "
                "reservations, other-platform commitments, and rack-incompatible "
                "capacity from gross critical-IT MW, flooring residual power at zero."
            ),
            "platform_allocation": (
                "Apply the target-platform share only to residual compatible MW."
            ),
            "operational_throughput": (
                "Divide target MW by rack critical-IT MW, then take the minimum of "
                "power-supported racks and target-quarter commissioning slots times "
                "their completion ratio."
            ),
            "shadow_capacity": (
                "Shadow power is target-allocated compatible MW left unused when "
                "commissioning binds; shadow commissioning capacity is completed "
                "rack throughput left unused when power binds."
            ),
        },
        "warnings": warnings,
    }


def reconcile_datacenter_operational_capacity_draws(
    case: DatacenterOperationalCase,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draws: list[dict[str, Any]] = []
    result = reconcile_datacenter_operational(case, _capacity_draws=draws)
    return result, draws
