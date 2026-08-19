"""Monte Carlo reconciliation of complete-system supply against every chain constraint."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isclose, isfinite, sqrt
from random import Random
from typing import Any, Iterable, Mapping, Sequence

from .models import Estimate, QuarterlyScenario, STAGE_ORDER, Stage


@dataclass(frozen=True, slots=True)
class Distribution:
    p10: float
    p50: float
    p90: float
    mean: float
    minimum: float
    maximum: float

    def as_dict(self) -> dict[str, float]:
        return {
            "p10": self.p10,
            "p50": self.p50,
            "p90": self.p90,
            "mean": self.mean,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


def _quantile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot summarize an empty sample")
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def _binary64_fmean(values: list[float]) -> float:
    """Compute a compensated mean with every intermediate rounded to binary64."""

    partials: list[float] = []
    for value in values:
        partial_index = 0
        partial_value = float(value)
        for existing in partials:
            if abs(partial_value) < abs(existing):
                partial_value, existing = existing, partial_value
            high = partial_value + existing
            low = existing - (high - partial_value)
            if low:
                partials[partial_index] = low
                partial_index += 1
            partial_value = high
        partials[partial_index:] = [partial_value]

    total = 0.0
    for partial in partials:
        total += partial
    return total / len(values)


def summarize(values: Iterable[float]) -> Distribution:
    materialized = list(values)
    ordered = sorted(materialized)
    return Distribution(
        p10=_quantile(ordered, 0.10),
        p50=_quantile(ordered, 0.50),
        p90=_quantile(ordered, 0.90),
        mean=_binary64_fmean(materialized),
        minimum=ordered[0],
        maximum=ordered[-1],
    )


def _triangular(estimate: Estimate, draw: float) -> float:
    low, mode, high = estimate.low, estimate.base, estimate.high
    if low == high:
        return low
    mode_fraction = (mode - low) / (high - low)
    if draw < mode_fraction:
        return low + sqrt(draw * (high - low) * (mode - low))
    return high - sqrt((1 - draw) * (high - low) * (high - mode))


class EstimateSampler:
    def __init__(self, random: Random) -> None:
        self.random = random
        self.correlated_draws: dict[str, float] = {}

    def estimate(self, estimate: Estimate) -> float:
        if estimate.correlation_group:
            draw = self.correlated_draws.setdefault(
                estimate.correlation_group, self.random.random()
            )
        else:
            draw = self.random.random()
        return _triangular(estimate, draw)


def _allocate(total: float, weights: dict[str, float], caps: dict[str, float]) -> dict[str, float]:
    allocations = {key: 0.0 for key in weights}
    active = {key for key, weight in weights.items() if weight > 0 and caps[key] > 0}
    remaining = max(0.0, total)

    while active and remaining > 1e-12:
        weight_total = sum(weights[key] for key in active)
        if weight_total <= 0:
            break
        saturated: list[str] = []
        proposed = {
            key: remaining * weights[key] / weight_total
            for key in active
        }
        for key in active:
            capacity_left = max(0.0, caps[key] - allocations[key])
            if proposed[key] >= capacity_left - 1e-12:
                allocations[key] += capacity_left
                remaining -= capacity_left
                saturated.append(key)
        if saturated:
            active.difference_update(saturated)
            continue
        for key, amount in proposed.items():
            allocations[key] += amount
        remaining = 0.0

    allocations["unallocated"] = max(0.0, remaining)
    return allocations


def _stage_constraints(scenario: QuarterlyScenario, stage: Stage) -> tuple[Any, ...]:
    stage_rank = STAGE_ORDER[stage]
    return tuple(
        constraint
        for constraint in scenario.constraints
        if STAGE_ORDER[constraint.stage] <= stage_rank
    )


def _factor(estimate: Estimate, sampler: EstimateSampler) -> float:
    return sampler.estimate(estimate)


def _input_estimate(estimate: Estimate) -> dict[str, Any]:
    return {
        "low": estimate.low,
        "base": estimate.base,
        "high": estimate.high,
        "unit": estimate.unit,
        "posture": estimate.posture.value,
        "methodology": estimate.methodology,
        "confidence": estimate.confidence,
        "last_updated": estimate.last_updated,
        "evidence_ids": list(estimate.evidence_ids),
        "confirming_evidence": estimate.confirming_evidence,
        "falsifying_evidence": estimate.falsifying_evidence,
        "correlation_group": estimate.correlation_group,
    }


def _scenario_inputs(scenario: QuarterlyScenario) -> dict[str, Any]:
    return {
        "platform": {
            "id": scenario.platform.id,
            "name": scenario.platform.name,
            "vendor": scenario.platform.vendor,
            "system_unit": scenario.platform.system_unit,
            "accelerator_packages_per_system": _input_estimate(
                scenario.platform.accelerator_packages_per_system
            ),
            "servers_per_system": _input_estimate(scenario.platform.servers_per_system),
            "racks_per_system": _input_estimate(scenario.platform.racks_per_system),
            "notes": scenario.platform.notes,
        },
        "constraints": [
            {
                "id": item.id,
                "resource_kind": item.resource_kind.value,
                "resource_name": item.resource_name,
                "stage": item.stage.value,
                "capacity_basis": item.capacity_basis.value,
                "capacity": _input_estimate(item.capacity),
                "effective_yield": _input_estimate(item.effective_yield),
                "platform_allocation": _input_estimate(item.platform_allocation),
                "units_per_system": _input_estimate(item.units_per_system),
                "notes": item.notes,
            }
            for item in scenario.constraints
        ],
        "allocations": [
            {
                "id": item.id,
                "customer": item.customer,
                "category": item.category.value,
                "share": _input_estimate(item.share),
                "demand_cap": _input_estimate(item.demand_cap),
                "notes": item.notes,
            }
            for item in scenario.allocations
        ],
        "supplier_economics": [
            {
                "id": item.id,
                "supplier": item.supplier,
                "ticker": item.ticker,
                "revenue_category": item.revenue_category,
                "recognition_stage": item.recognition_stage.value,
                "units_per_system": _input_estimate(item.units_per_system),
                "revenue_per_unit": _input_estimate(item.revenue_per_unit),
                "gross_margin": _input_estimate(item.gross_margin),
            }
            for item in scenario.supplier_economics
        ],
        "consensus": [
            {
                "id": item.id,
                "supplier": item.supplier,
                "ticker": item.ticker,
                "revenue": _input_estimate(item.revenue),
            }
            for item in scenario.consensus
        ],
        "opportunity_factors": [
            {
                "id": item.id,
                "supplier": item.supplier,
                "ticker": item.ticker,
                "confidence": _input_estimate(item.confidence),
                "liquidity": _input_estimate(item.liquidity),
                "timing": _input_estimate(item.timing),
                "catalyst_strength": _input_estimate(item.catalyst_strength),
                "actionability": item.actionability,
                "variant_wedge": item.variant_wedge,
                "what_is_priced_in": item.what_is_priced_in,
                "why_now": item.why_now,
                "catalyst": item.catalyst,
                "first_rejection": item.first_rejection,
                "investable_if": item.investable_if,
                "thesis_kill": item.thesis_kill,
                "next_workflow": item.next_workflow,
            }
            for item in scenario.opportunity_factors
        ],
    }


def reconcile(
    scenario: QuarterlyScenario,
    *,
    constraint_capacity_draws: Mapping[str, Sequence[float]] | None = None,
    output_draws: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Reconcile one quarterly scenario to the minimum feasible complete-system output."""

    override_draws = dict(constraint_capacity_draws or {})
    constraint_ids = {item.id for item in scenario.constraints}
    if unknown := set(override_draws) - constraint_ids:
        raise ValueError(f"capacity draws reference unknown constraints: {sorted(unknown)}")
    for constraint_id, values in override_draws.items():
        if len(values) != scenario.samples:
            raise ValueError(
                f"capacity draws for {constraint_id} must contain {scenario.samples} rows"
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or float(value) < 0
            for value in values
        ):
            raise ValueError(
                f"capacity draws for {constraint_id} must be finite and nonnegative"
            )
    random = Random(scenario.seed)
    stages = tuple(sorted(Stage, key=STAGE_ORDER.__getitem__))
    eligible_by_stage = {
        stage: _stage_constraints(scenario, stage)
        for stage in stages
    }

    constraint_capacity: dict[str, list[float]] = defaultdict(list)
    constraint_utilization: dict[str, list[float]] = defaultdict(list)
    constraint_headroom: dict[str, list[float]] = defaultdict(list)
    stage_systems: dict[Stage, list[float]] = defaultdict(list)
    physical_outputs: dict[str, list[float]] = defaultdict(list)
    bottleneck_counts: dict[Stage, dict[str, float]] = {
        stage: defaultdict(float) for stage in stages
    }
    allocation_samples: dict[str, list[float]] = defaultdict(list)
    supplier_revenue_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    supplier_gross_profit_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    consensus_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    revision_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    score_samples: dict[tuple[str, str], list[float]] = defaultdict(list)

    consensus_by_key = {(item.supplier, item.ticker): item for item in scenario.consensus}
    factors_by_key = {
        (item.supplier, item.ticker): item for item in scenario.opportunity_factors
    }

    for draw_index in range(scenario.samples):
        sampler = EstimateSampler(random)
        sampled_caps: dict[str, float] = {}
        for constraint in scenario.constraints:
            if constraint.id in override_draws:
                capacity = float(override_draws[constraint.id][draw_index])
            else:
                capacity = sampler.estimate(constraint.capacity)
            effective_yield = sampler.estimate(constraint.effective_yield)
            allocation = sampler.estimate(constraint.platform_allocation)
            units_per_system = sampler.estimate(constraint.units_per_system)
            sampled_caps[constraint.id] = (
                capacity * effective_yield * allocation / units_per_system
            )
            constraint_capacity[constraint.id].append(sampled_caps[constraint.id])

        sampled_stage_systems: dict[Stage, float] = {}
        for stage in stages:
            eligible = eligible_by_stage[stage]
            stage_output = min(sampled_caps[item.id] for item in eligible)
            sampled_stage_systems[stage] = stage_output
            stage_systems[stage].append(stage_output)
            tied = [
                item.id
                for item in eligible
                if isclose(sampled_caps[item.id], stage_output, rel_tol=1e-10, abs_tol=1e-12)
            ]
            for constraint_id in tied:
                bottleneck_counts[stage][constraint_id] += 1 / len(tied)

        for constraint in scenario.constraints:
            output = sampled_stage_systems[constraint.stage]
            cap = sampled_caps[constraint.id]
            constraint_utilization[constraint.id].append(0.0 if cap == 0 else output / cap)
            constraint_headroom[constraint.id].append(max(0.0, cap - output))

        package_factor = _factor(
            scenario.platform.accelerator_packages_per_system, sampler
        )
        server_factor = _factor(scenario.platform.servers_per_system, sampler)
        rack_factor = _factor(scenario.platform.racks_per_system, sampler)
        physical_outputs["accelerator_packages_produced"].append(
            sampled_stage_systems[Stage.ACCELERATOR_PACKAGE] * package_factor
        )
        physical_outputs["complete_servers"].append(
            sampled_stage_systems[Stage.SERVER_ASSEMBLY] * server_factor
        )
        physical_outputs["integrated_racks"].append(
            sampled_stage_systems[Stage.RACK_INTEGRATION] * rack_factor
        )
        physical_outputs["systems_shipped"].append(
            sampled_stage_systems[Stage.SHIPPED]
        )
        physical_outputs["systems_installed"].append(
            sampled_stage_systems[Stage.INSTALLED]
        )
        physical_outputs["systems_operational"].append(
            sampled_stage_systems[Stage.OPERATIONAL]
        )
        if output_draws is not None:
            output_draws.append(
                {
                    "draw_index": draw_index,
                    **{
                        f"constraint.{constraint_id}.system_equivalents": value
                        for constraint_id, value in sampled_caps.items()
                    },
                    **{
                        f"stage.{stage.value}.system_equivalents": value
                        for stage, value in sampled_stage_systems.items()
                    },
                    "physical.accelerator_packages_produced": (
                        sampled_stage_systems[Stage.ACCELERATOR_PACKAGE]
                        * package_factor
                    ),
                    "physical.complete_servers": (
                        sampled_stage_systems[Stage.SERVER_ASSEMBLY] * server_factor
                    ),
                    "physical.integrated_racks": (
                        sampled_stage_systems[Stage.RACK_INTEGRATION] * rack_factor
                    ),
                    "physical.systems_shipped": sampled_stage_systems[Stage.SHIPPED],
                    "physical.systems_installed": sampled_stage_systems[Stage.INSTALLED],
                    "physical.systems_operational": sampled_stage_systems[Stage.OPERATIONAL],
                }
            )

        if scenario.allocations:
            weights = {item.id: sampler.estimate(item.share) for item in scenario.allocations}
            caps = {item.id: sampler.estimate(item.demand_cap) for item in scenario.allocations}
            allocation = _allocate(
                sampled_stage_systems[Stage.SHIPPED], weights=weights, caps=caps
            )
            for key, value in allocation.items():
                allocation_samples[key].append(value)

        revenue_for_sample: dict[tuple[str, str], float] = defaultdict(float)
        gross_profit_for_sample: dict[tuple[str, str], float] = defaultdict(float)
        for economics in scenario.supplier_economics:
            key = (economics.supplier, economics.ticker)
            units = (
                sampled_stage_systems[economics.recognition_stage]
                * sampler.estimate(economics.units_per_system)
            )
            revenue = units * sampler.estimate(economics.revenue_per_unit)
            gross_profit = revenue * sampler.estimate(economics.gross_margin)
            revenue_for_sample[key] += revenue
            gross_profit_for_sample[key] += gross_profit
        for key, revenue in revenue_for_sample.items():
            supplier_revenue_samples[key].append(revenue)
            supplier_gross_profit_samples[key].append(gross_profit_for_sample[key])

        for key, consensus in consensus_by_key.items():
            consensus_revenue = sampler.estimate(consensus.revenue)
            consensus_samples[key].append(consensus_revenue)
            bottom_up = revenue_for_sample.get(key, 0.0)
            revision = 0.0 if consensus_revenue == 0 else (bottom_up - consensus_revenue) / consensus_revenue
            revision_samples[key].append(revision * 100)
            factors = factors_by_key.get(key)
            if factors:
                score_samples[key].append(
                    abs(revision)
                    * sampler.estimate(factors.confidence)
                    * sampler.estimate(factors.liquidity)
                    * sampler.estimate(factors.timing)
                    * sampler.estimate(factors.catalyst_strength)
                )

    stage_results = []
    for stage in stages:
        stage_results.append(
            {
                "stage": stage.value,
                "system_equivalents": summarize(stage_systems[stage]).as_dict(),
                "unit": scenario.platform.system_unit,
            }
        )

    constraint_results = []
    for constraint in scenario.constraints:
        constraint_results.append(
            {
                "id": constraint.id,
                "resource_kind": constraint.resource_kind.value,
                "resource_name": constraint.resource_name,
                "stage": constraint.stage.value,
                "equivalent_system_capacity": summarize(
                    constraint_capacity[constraint.id]
                ).as_dict(),
                "utilization": summarize(constraint_utilization[constraint.id]).as_dict(),
                "headroom_system_equivalents": summarize(
                    constraint_headroom[constraint.id]
                ).as_dict(),
                "bottleneck_probability": {
                    stage.value: bottleneck_counts[stage].get(constraint.id, 0.0)
                    / scenario.samples
                    for stage in stages
                    if constraint in eligible_by_stage[stage]
                },
            }
        )

    bottlenecks = []
    for stage in stages:
        probabilities = [
            {
                "constraint_id": item.id,
                "resource_name": item.resource_name,
                "probability": bottleneck_counts[stage].get(item.id, 0.0)
                / scenario.samples,
            }
            for item in eligible_by_stage[stage]
        ]
        bottlenecks.append(
            {
                "stage": stage.value,
                "constraints": sorted(
                    probabilities, key=lambda item: (-item["probability"], item["constraint_id"])
                ),
            }
        )

    allocation_by_id = {item.id: item for item in scenario.allocations}
    allocation_results = []
    for allocation_id, values in allocation_samples.items():
        if allocation_id == "unallocated":
            allocation_results.append(
                {
                    "id": allocation_id,
                    "customer": "Unallocated",
                    "category": "unallocated",
                    "systems_shipped": summarize(values).as_dict(),
                }
            )
            continue
        rule = allocation_by_id[allocation_id]
        allocation_results.append(
            {
                "id": rule.id,
                "customer": rule.customer,
                "category": rule.category.value,
                "systems_shipped": summarize(values).as_dict(),
            }
        )
    allocation_results.sort(
        key=lambda item: (-item["systems_shipped"]["p50"], item["customer"])
    )

    supplier_results = []
    for key, revenue_values in supplier_revenue_samples.items():
        supplier, ticker = key
        row: dict[str, Any] = {
            "supplier": supplier,
            "ticker": ticker,
            "bottom_up_revenue_usd": summarize(revenue_values).as_dict(),
            "bottom_up_gross_profit_usd": summarize(
                supplier_gross_profit_samples[key]
            ).as_dict(),
        }
        if key in consensus_samples:
            row["consensus_revenue_usd"] = summarize(consensus_samples[key]).as_dict()
            row["expected_revenue_revision_pct"] = summarize(
                revision_samples[key]
            ).as_dict()
        supplier_results.append(row)
    supplier_results.sort(key=lambda item: item["ticker"])

    opportunity_results = []
    for key, values in score_samples.items():
        supplier, ticker = key
        factors = factors_by_key[key]
        revision = summarize(revision_samples[key])
        opportunity_results.append(
            {
                "supplier": supplier,
                "ticker": ticker,
                "direction": (
                    "positive_revision_candidate"
                    if revision.p50 >= 0
                    else "negative_revision_candidate"
                ),
                "expected_revenue_revision_pct": revision.as_dict(),
                "screen_score": summarize(values).as_dict(),
                "actionability": factors.actionability,
                "variant_wedge": factors.variant_wedge,
                "what_is_priced_in": factors.what_is_priced_in,
                "why_now": factors.why_now,
                "catalyst": factors.catalyst,
                "first_rejection": factors.first_rejection,
                "investable_if": factors.investable_if,
                "thesis_kill": factors.thesis_kill,
                "next_workflow": factors.next_workflow,
                "status": "wait_for_proof" if scenario.synthetic else "deeper_research_candidate",
            }
        )
    opportunity_results.sort(
        key=lambda item: (-item["screen_score"]["p50"], item["ticker"])
    )
    for rank, item in enumerate(opportunity_results, start=1):
        item["rank"] = rank

    warnings = []
    if scenario.synthetic:
        warnings.append(
            "Capacity, yield, allocation, economics, and consensus inputs marked synthetic are demonstration data, not market estimates."
        )
    if scenario.scope_notes:
        warnings.append(scenario.scope_notes)
    present_stages = {item.stage for item in scenario.constraints}
    for required_stage in (Stage.SHIPPED, Stage.OPERATIONAL):
        if required_stage not in present_stages:
            warnings.append(
                f"No new {required_stage.value} constraint is present; output carries forward from upstream stages."
            )
    if not scenario.allocations:
        warnings.append("No customer allocation rules are present.")
    if not scenario.consensus:
        warnings.append("No sell-side consensus inputs are present; discrepancy ranking is unavailable.")

    scenario_payload = {
        "id": scenario.id,
        "name": scenario.name,
        "quarter": scenario.quarter,
        "as_of_date": scenario.as_of_date,
        "recorded_at": scenario.recorded_at,
        "synthetic": scenario.synthetic,
        "samples": scenario.samples,
        "seed": scenario.seed,
        "notes": scenario.notes,
    }
    if scenario.scope_notes:
        scenario_payload["scope_notes"] = scenario.scope_notes

    methodology = {
        "distribution": "Independent triangular draws unless estimates share a correlation_group; reported ranges are not assumed normal.",
        "constraint_reconciliation": "For each draw and stage, output is the minimum system-equivalent capacity of all constraints required up to that stage.",
        "bottleneck_probability": "Share of Monte Carlo draws in which a constraint is the stage minimum; exact ties split probability equally.",
        "customer_allocation": "Shipped systems are allocated by sampled share, capped by sampled demand, with residual supply redistributed proportionally.",
        "opportunity_ranking": "Research-priority score equals absolute bottom-up revenue revision times confidence, liquidity, timing, and catalyst-strength factors. It is not an investment recommendation.",
    }
    if override_draws:
        methodology["constraint_capacity_draws"] = (
            "The named linked constraints use exact hash-validated source capacity draws; "
            "their yield, allocation, and unit conversions remain explicit in this engine. "
            "All other estimates retain the stated triangular and correlation-group policy."
        )
        methodology["draw_override_constraint_ids"] = sorted(override_draws)
    return {
        "format": "ai-supply-reconciliation.v1",
        "scenario": scenario_payload,
        "platform": {
            "id": scenario.platform.id,
            "name": scenario.platform.name,
            "vendor": scenario.platform.vendor,
            "system_unit": scenario.platform.system_unit,
        },
        "physical_outputs": {
            key: summarize(values).as_dict() for key, values in physical_outputs.items()
        },
        "stage_outputs": stage_results,
        "constraints": constraint_results,
        "bottlenecks": bottlenecks,
        "customer_allocations": allocation_results,
        "supplier_estimates": supplier_results,
        "opportunity_candidates": opportunity_results,
        "inputs": _scenario_inputs(scenario),
        "evidence": [
            {
                "id": item.id,
                "kind": item.kind.value,
                "title": item.title,
                "source_url": item.source_url,
                "publisher": item.publisher,
                "published_at": item.published_at,
                "retrieved_at": item.retrieved_at,
                "source_family": item.source_family,
                "license": item.license,
                "excerpt": item.excerpt,
                "content_hash": item.content_hash,
            }
            for item in scenario.evidence
        ],
        "methodology": methodology,
        "warnings": warnings,
    }
