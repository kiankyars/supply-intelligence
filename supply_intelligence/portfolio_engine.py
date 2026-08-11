"""Sequential allocation of shared resources across accelerator platforms."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from random import Random
from typing import Any

from .engine import EstimateSampler, _input_estimate, summarize
from .models import STAGE_ORDER, Stage
from .portfolio_models import PortfolioScenario


TOLERANCE = 1e-10


@dataclass(frozen=True, slots=True)
class AllocationResult:
    outputs: dict[str, float]
    consumption: dict[str, float]
    utilization: dict[str, float]
    blockers: dict[str, tuple[str, ...]]
    binding_resources: tuple[str, ...]


def _progressive_allocate(
    *,
    demand: dict[str, float],
    weights: dict[str, float],
    capacities: dict[str, float],
    requirements: dict[tuple[str, str], float],
) -> AllocationResult:
    """Apply weighted progressive filling under several resource constraints."""

    outputs = {platform_id: 0.0 for platform_id in demand}
    active = {
        platform_id
        for platform_id, value in demand.items()
        if value > TOLERANCE and weights[platform_id] > TOLERANCE
    }
    blockers: dict[str, set[str]] = defaultdict(set)
    binding_resources: set[str] = set()

    while active:
        demand_steps = {
            platform_id: (demand[platform_id] - outputs[platform_id])
            / weights[platform_id]
            for platform_id in active
        }
        resource_steps: dict[str, float] = {}
        for resource_id, capacity in capacities.items():
            consumption = sum(
                requirements.get((platform_id, resource_id), 0.0)
                * outputs[platform_id]
                for platform_id in demand
            )
            direction = sum(
                requirements.get((platform_id, resource_id), 0.0)
                * weights[platform_id]
                for platform_id in active
            )
            if direction > TOLERANCE:
                resource_steps[resource_id] = max(0.0, capacity - consumption) / direction

        candidates = list(demand_steps.values()) + list(resource_steps.values())
        if not candidates:
            break
        step = max(0.0, min(candidates))
        for platform_id in active:
            outputs[platform_id] = min(
                demand[platform_id],
                outputs[platform_id] + weights[platform_id] * step,
            )

        hit_demand = {
            platform_id
            for platform_id in active
            if demand[platform_id] - outputs[platform_id] <= TOLERANCE
        }
        newly_binding: set[str] = set()
        for resource_id, capacity in capacities.items():
            consumption = sum(
                requirements.get((platform_id, resource_id), 0.0)
                * outputs[platform_id]
                for platform_id in demand
            )
            if capacity - consumption <= TOLERANCE:
                blocked = {
                    platform_id
                    for platform_id in active
                    if platform_id not in hit_demand
                    and requirements.get((platform_id, resource_id), 0.0) > 0
                }
                if blocked:
                    newly_binding.add(resource_id)
                    binding_resources.add(resource_id)
                    for platform_id in blocked:
                        blockers[platform_id].add(resource_id)

        blocked_platforms = {
            platform_id
            for platform_id in active
            if blockers.get(platform_id)
        }
        removed = hit_demand | blocked_platforms
        active.difference_update(removed)
        if step <= TOLERANCE and not removed and not newly_binding:
            break

    consumption = {
        resource_id: sum(
            requirements.get((platform_id, resource_id), 0.0)
            * outputs[platform_id]
            for platform_id in demand
        )
        for resource_id in capacities
    }
    utilization = {
        resource_id: (
            0.0
            if capacities[resource_id] <= TOLERANCE
            else min(1.0, consumption[resource_id] / capacities[resource_id])
        )
        for resource_id in capacities
    }
    return AllocationResult(
        outputs=outputs,
        consumption=consumption,
        utilization=utilization,
        blockers={key: tuple(sorted(value)) for key, value in blockers.items()},
        binding_resources=tuple(sorted(binding_resources)),
    )


def reconcile_portfolio(scenario: PortfolioScenario) -> dict[str, Any]:
    """Allocate shared resources once, then carry each platform through later stages."""

    random = Random(scenario.seed)
    stages = tuple(sorted(Stage, key=STAGE_ORDER.__getitem__))
    platforms = {item.platform.id: item for item in scenario.platforms}
    resources = {item.id: item for item in scenario.resource_pools}
    requirements = {
        (item.platform_id, item.resource_pool_id): item
        for item in scenario.requirements
    }
    resources_by_stage = {
        stage: tuple(
            item for item in scenario.resource_pools if item.stage is stage
        )
        for stage in stages
    }

    platform_stage_samples: dict[tuple[str, Stage], list[float]] = defaultdict(list)
    platform_physical_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    platform_unfilled_demand: dict[str, list[float]] = defaultdict(list)
    inventory_samples: dict[tuple[str, Stage, Stage], list[float]] = defaultdict(list)
    resource_capacity_samples: dict[str, list[float]] = defaultdict(list)
    resource_consumption_samples: dict[str, list[float]] = defaultdict(list)
    resource_utilization_samples: dict[str, list[float]] = defaultdict(list)
    stage_binding_counts: dict[Stage, dict[str, float]] = {
        stage: defaultdict(float) for stage in stages
    }
    platform_binding_counts: dict[tuple[str, Stage], dict[str, float]] = {
        (platform_id, stage): defaultdict(float)
        for platform_id in platforms
        for stage in stages
    }

    for _ in range(scenario.samples):
        sampler = EstimateSampler(random)
        original_demand = {
            platform_id: sampler.estimate(item.demand)
            for platform_id, item in platforms.items()
        }
        weights = {
            platform_id: sampler.estimate(item.priority_weight)
            for platform_id, item in platforms.items()
        }
        sampled_capacity = {
            resource_id: sampler.estimate(item.capacity)
            * sampler.estimate(item.effective_yield)
            for resource_id, item in resources.items()
        }
        sampled_requirements = {
            key: sampler.estimate(item.units_per_system)
            for key, item in requirements.items()
        }

        current_demand = dict(original_demand)
        previous_stage: Stage | None = None
        sampled_stage_outputs: dict[tuple[str, Stage], float] = {}

        for stage in stages:
            stage_resources = resources_by_stage[stage]
            if stage_resources:
                stage_capacities = {
                    item.id: sampled_capacity[item.id] for item in stage_resources
                }
                stage_requirements = {
                    (platform_id, item.id): sampled_requirements[(platform_id, item.id)]
                    for item in stage_resources
                    for platform_id in platforms
                    if (platform_id, item.id) in sampled_requirements
                }
                allocation = _progressive_allocate(
                    demand=current_demand,
                    weights=weights,
                    capacities=stage_capacities,
                    requirements=stage_requirements,
                )
            else:
                allocation = AllocationResult(
                    outputs=dict(current_demand),
                    consumption={},
                    utilization={},
                    blockers={},
                    binding_resources=(),
                )

            for platform_id, output in allocation.outputs.items():
                sampled_stage_outputs[(platform_id, stage)] = output
                platform_stage_samples[(platform_id, stage)].append(output)
                if previous_stage is None:
                    platform_unfilled_demand[platform_id].append(
                        max(0.0, original_demand[platform_id] - output)
                    )
                else:
                    inventory_samples[(platform_id, previous_stage, stage)].append(
                        max(0.0, current_demand[platform_id] - output)
                    )

                blockers = allocation.blockers.get(platform_id, ())
                if blockers:
                    for resource_id in blockers:
                        platform_binding_counts[(platform_id, stage)][resource_id] += (
                            1 / len(blockers)
                        )
                else:
                    platform_binding_counts[(platform_id, stage)]["demand_or_carry"] += 1

            if allocation.binding_resources:
                for resource_id in allocation.binding_resources:
                    stage_binding_counts[stage][resource_id] += (
                        1 / len(allocation.binding_resources)
                    )
            else:
                stage_binding_counts[stage]["demand_or_carry"] += 1

            for resource in stage_resources:
                resource_capacity_samples[resource.id].append(
                    sampled_capacity[resource.id]
                )
                resource_consumption_samples[resource.id].append(
                    allocation.consumption[resource.id]
                )
                resource_utilization_samples[resource.id].append(
                    allocation.utilization[resource.id]
                )

            current_demand = dict(allocation.outputs)
            previous_stage = stage

        for platform_id, item in platforms.items():
            package_factor = sampler.estimate(
                item.platform.accelerator_packages_per_system
            )
            server_factor = sampler.estimate(item.platform.servers_per_system)
            rack_factor = sampler.estimate(item.platform.racks_per_system)
            platform_physical_samples[(platform_id, "accelerator_packages_produced")].append(
                sampled_stage_outputs[(platform_id, Stage.ACCELERATOR_PACKAGE)]
                * package_factor
            )
            platform_physical_samples[(platform_id, "complete_servers")].append(
                sampled_stage_outputs[(platform_id, Stage.SERVER_ASSEMBLY)]
                * server_factor
            )
            platform_physical_samples[(platform_id, "integrated_racks")].append(
                sampled_stage_outputs[(platform_id, Stage.RACK_INTEGRATION)]
                * rack_factor
            )
            for output_name, stage in (
                ("systems_shipped", Stage.SHIPPED),
                ("systems_installed", Stage.INSTALLED),
                ("systems_operational", Stage.OPERATIONAL),
            ):
                platform_physical_samples[(platform_id, output_name)].append(
                    sampled_stage_outputs[(platform_id, stage)]
                )

    platform_results = []
    for platform_id, item in platforms.items():
        stage_outputs = [
            {
                "stage": stage.value,
                "system_equivalents": summarize(
                    platform_stage_samples[(platform_id, stage)]
                ).as_dict(),
            }
            for stage in stages
        ]
        bottlenecks = []
        for stage in stages:
            counts = platform_binding_counts[(platform_id, stage)]
            rows = [
                {
                    "resource_id": resource_id,
                    "resource_name": (
                        "Demand or upstream carry-forward"
                        if resource_id == "demand_or_carry"
                        else resources[resource_id].resource_name
                    ),
                    "probability": count / scenario.samples,
                }
                for resource_id, count in counts.items()
            ]
            bottlenecks.append(
                {
                    "stage": stage.value,
                    "constraints": sorted(
                        rows,
                        key=lambda row: (-row["probability"], row["resource_id"]),
                    ),
                }
            )
        platform_results.append(
            {
                "id": platform_id,
                "name": item.platform.name,
                "vendor": item.platform.vendor,
                "system_unit": item.platform.system_unit,
                "unfilled_quarterly_demand": summarize(
                    platform_unfilled_demand[platform_id]
                ).as_dict(),
                "stage_outputs": stage_outputs,
                "physical_outputs": {
                    output_name: summarize(
                        platform_physical_samples[(platform_id, output_name)]
                    ).as_dict()
                    for output_name in (
                        "accelerator_packages_produced",
                        "complete_servers",
                        "integrated_racks",
                        "systems_shipped",
                        "systems_installed",
                        "systems_operational",
                    )
                },
                "bottlenecks": bottlenecks,
            }
        )

    resource_results = []
    for resource_id, item in resources.items():
        resource_results.append(
            {
                "id": resource_id,
                "resource_kind": item.resource_kind.value,
                "resource_name": item.resource_name,
                "stage": item.stage.value,
                "unit": item.capacity.unit,
                "effective_capacity": summarize(
                    resource_capacity_samples[resource_id]
                ).as_dict(),
                "consumption": summarize(
                    resource_consumption_samples[resource_id]
                ).as_dict(),
                "utilization": summarize(
                    resource_utilization_samples[resource_id]
                ).as_dict(),
                "binding_probability": (
                    stage_binding_counts[item.stage].get(resource_id, 0.0)
                    / scenario.samples
                ),
            }
        )

    inventory_results = []
    for (platform_id, from_stage, to_stage), values in inventory_samples.items():
        inventory_results.append(
            {
                "platform_id": platform_id,
                "platform_name": platforms[platform_id].platform.name,
                "from_stage": from_stage.value,
                "to_stage": to_stage.value,
                "systems_held_back": summarize(values).as_dict(),
            }
        )

    stage_bottlenecks = []
    for stage in stages:
        rows = []
        for resource_id, count in stage_binding_counts[stage].items():
            rows.append(
                {
                    "resource_id": resource_id,
                    "resource_name": (
                        "Demand or upstream carry-forward"
                        if resource_id == "demand_or_carry"
                        else resources[resource_id].resource_name
                    ),
                    "probability": count / scenario.samples,
                }
            )
        stage_bottlenecks.append(
            {
                "stage": stage.value,
                "constraints": sorted(
                    rows, key=lambda row: (-row["probability"], row["resource_id"])
                ),
            }
        )

    warnings = []
    if scenario.synthetic:
        warnings.append(
            "Inputs marked synthetic are allocation tests, not production or demand estimates."
        )
    warnings.append(
        "Weighted progressive filling encodes an allocation policy. It does not infer contractual priority from market evidence."
    )

    return {
        "format": "ai-supply-portfolio-reconciliation.v1",
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "quarter": scenario.quarter,
            "as_of_date": scenario.as_of_date,
            "recorded_at": scenario.recorded_at,
            "synthetic": scenario.synthetic,
            "samples": scenario.samples,
            "seed": scenario.seed,
            "allocation_policy": scenario.allocation_policy,
            "notes": scenario.notes,
        },
        "platforms": sorted(platform_results, key=lambda row: row["id"]),
        "resource_pools": sorted(resource_results, key=lambda row: row["id"]),
        "inventory": sorted(
            inventory_results,
            key=lambda row: (row["platform_id"], row["from_stage"]),
        ),
        "stage_bottlenecks": stage_bottlenecks,
        "inputs": {
            "platforms": [
                {
                    "id": item.platform.id,
                    "name": item.platform.name,
                    "vendor": item.platform.vendor,
                    "system_unit": item.platform.system_unit,
                    "accelerator_packages_per_system": _input_estimate(
                        item.platform.accelerator_packages_per_system
                    ),
                    "servers_per_system": _input_estimate(
                        item.platform.servers_per_system
                    ),
                    "racks_per_system": _input_estimate(
                        item.platform.racks_per_system
                    ),
                    "demand": _input_estimate(item.demand),
                    "priority_weight": _input_estimate(item.priority_weight),
                    "notes": item.platform.notes,
                }
                for item in scenario.platforms
            ],
            "resource_pools": [
                {
                    "id": item.id,
                    "resource_kind": item.resource_kind.value,
                    "resource_name": item.resource_name,
                    "stage": item.stage.value,
                    "capacity_basis": item.capacity_basis.value,
                    "capacity": _input_estimate(item.capacity),
                    "effective_yield": _input_estimate(item.effective_yield),
                    "notes": item.notes,
                }
                for item in scenario.resource_pools
            ],
            "requirements": [
                {
                    "id": item.id,
                    "platform_id": item.platform_id,
                    "resource_pool_id": item.resource_pool_id,
                    "units_per_system": _input_estimate(item.units_per_system),
                    "notes": item.notes,
                }
                for item in scenario.requirements
            ],
        },
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
        "methodology": {
            "allocation": "At each production stage, platform outputs rise in proportion to sampled priority weights until demand or a shared resource binds.",
            "stage_flow": "Each stage uses the prior stage output as its demand ceiling, so downstream allocation cannot exceed platform-specific upstream production.",
            "conservation": "Each resource pool is consumed once across all platform requirements at its assigned stage.",
        },
        "warnings": warnings,
    }


__all__ = ["AllocationResult", "_progressive_allocate", "reconcile_portfolio"]
