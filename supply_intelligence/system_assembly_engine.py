"""Monte Carlo reconciliation for ODM assembly and component-cleared racks."""

from __future__ import annotations

from collections import defaultdict
from math import isclose
from random import Random
from typing import Any, Iterable

from .engine import EstimateSampler, _input_estimate, summarize
from .models import Estimate, EstimatePosture
from .system_assembly_models import (
    AssemblyComponentPool,
    OdmAssemblyFlow,
    SystemAssemblyScenario,
)


SYSTEM_ASSEMBLY_RESULT_FORMAT = "ai-supply-system-assembly-result.v1"

ODM_OUTPUT_UNITS = {
    "compute_tray_capacity": "tray",
    "good_compute_trays": "tray",
    "platform_qualified_compute_trays": "tray",
    "customer_allocated_compute_trays": "tray",
    "compute_tray_rack_equivalents": "rack",
    "rack_integration_capacity": "rack",
    "good_integrated_racks": "rack",
    "platform_qualified_integrated_racks": "rack",
    "customer_allocated_integrated_racks": "rack",
    "assembly_supported_racks": "rack",
    "unused_customer_allocated_compute_trays": "tray",
    "unused_customer_allocated_rack_slots": "rack",
    "assembly_rack_share": "ratio",
}

COMPONENT_OUTPUT_UNITS = {
    "capacity": None,
    "good_output": None,
    "platform_qualified_output": None,
    "customer_allocated_output": None,
    "rack_equivalents": "rack",
    "consumed_output": None,
    "unused_customer_allocated_output": None,
    "customer_allocated_utilization": "ratio",
}

OUTPUT_UNITS = {
    "odm_assembly_capacity_racks": "rack",
    "component_cleared_rack_capacity": "rack",
    "rack_demand": "rack",
    "complete_racks": "rack",
    "unfilled_rack_demand": "rack",
    "shadow_assembly_racks": "rack",
    "accelerator_package_equivalents": "package",
    "odm_concentration_hhi": "ratio",
    "largest_odm_share": "ratio",
}


def _evidence_payload(scenario: SystemAssemblyScenario) -> list[dict[str, Any]]:
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
        for item in scenario.evidence
    ]


def _inputs(scenario: SystemAssemblyScenario) -> dict[str, Any]:
    platform = scenario.platform
    return {
        "platform": {
            "id": platform.id,
            "name": platform.name,
            "customer": platform.customer,
            "accelerator_packages_per_compute_tray": _input_estimate(
                platform.accelerator_packages_per_compute_tray
            ),
            "compute_trays_per_rack": _input_estimate(
                platform.compute_trays_per_rack
            ),
            "rack_demand": _input_estimate(platform.rack_demand),
            "notes": platform.notes,
        },
        "odms": [
            {
                "id": odm.id,
                "name": odm.name,
                "geography": odm.geography,
                "tray_capacity_scope_id": odm.tray_capacity_scope_id,
                "tray_capacity_scope": odm.tray_capacity_scope,
                "tray_capacity_basis": odm.tray_capacity_basis,
                "compute_tray_capacity": _input_estimate(
                    odm.compute_tray_capacity
                ),
                "compute_tray_effective_yield": _input_estimate(
                    odm.compute_tray_effective_yield
                ),
                "compute_tray_platform_qualified_share": _input_estimate(
                    odm.compute_tray_platform_qualified_share
                ),
                "compute_tray_customer_allocation_share": _input_estimate(
                    odm.compute_tray_customer_allocation_share
                ),
                "rack_capacity_scope_id": odm.rack_capacity_scope_id,
                "rack_capacity_scope": odm.rack_capacity_scope,
                "rack_capacity_basis": odm.rack_capacity_basis,
                "rack_integration_capacity": _input_estimate(
                    odm.rack_integration_capacity
                ),
                "rack_integration_effective_yield": _input_estimate(
                    odm.rack_integration_effective_yield
                ),
                "rack_platform_qualified_share": _input_estimate(
                    odm.rack_platform_qualified_share
                ),
                "rack_customer_allocation_share": _input_estimate(
                    odm.rack_customer_allocation_share
                ),
                "notes": odm.notes,
            }
            for odm in scenario.odms
        ],
        "components": [
            {
                "id": component.id,
                "name": component.name,
                "stage": component.stage,
                "resource_kind": component.resource_kind,
                "capacity_scope_id": component.capacity_scope_id,
                "capacity_scope": component.capacity_scope,
                "capacity_basis": component.capacity_basis,
                "capacity": _input_estimate(component.capacity),
                "effective_yield": _input_estimate(component.effective_yield),
                "platform_qualified_share": _input_estimate(
                    component.platform_qualified_share
                ),
                "customer_allocation_share": _input_estimate(
                    component.customer_allocation_share
                ),
                "units_per_rack": _input_estimate(component.units_per_rack),
                "notes": component.notes,
            }
            for component in scenario.components
        ],
    }


def _odm_estimates(odm: OdmAssemblyFlow) -> Iterable[tuple[str, Estimate]]:
    yield "compute_tray_capacity", odm.compute_tray_capacity
    yield "compute_tray_effective_yield", odm.compute_tray_effective_yield
    yield "compute_tray_platform_qualified_share", (
        odm.compute_tray_platform_qualified_share
    )
    yield "compute_tray_customer_allocation_share", (
        odm.compute_tray_customer_allocation_share
    )
    yield "rack_integration_capacity", odm.rack_integration_capacity
    yield "rack_integration_effective_yield", odm.rack_integration_effective_yield
    yield "rack_platform_qualified_share", odm.rack_platform_qualified_share
    yield "rack_customer_allocation_share", odm.rack_customer_allocation_share


def _component_estimates(
    component: AssemblyComponentPool,
) -> Iterable[tuple[str, Estimate]]:
    yield "capacity", component.capacity
    yield "effective_yield", component.effective_yield
    yield "platform_qualified_share", component.platform_qualified_share
    yield "customer_allocation_share", component.customer_allocation_share
    yield "units_per_rack", component.units_per_rack


def _gap_row(
    *,
    owner_type: str,
    owner_id: str,
    parameter: str,
    estimate: Estimate,
    influence: float,
) -> dict[str, Any]:
    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "parameter": parameter,
        "low": estimate.low,
        "base": estimate.base,
        "high": estimate.high,
        "unit": estimate.unit,
        "confidence": estimate.confidence,
        "last_updated": estimate.last_updated,
        "influence_probability": influence,
        "research_priority": max(influence, 0.05) * (1 - estimate.confidence),
        "methodology": estimate.methodology,
        "evidence_ids": list(estimate.evidence_ids),
        "confirming_evidence": estimate.confirming_evidence,
        "falsifying_evidence": estimate.falsifying_evidence,
    }


def _research_queue(
    scenario: SystemAssemblyScenario,
    bottleneck_probabilities: dict[str, float],
    odm_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for parameter, estimate in (
        (
            "accelerator_packages_per_compute_tray",
            scenario.platform.accelerator_packages_per_compute_tray,
        ),
        ("compute_trays_per_rack", scenario.platform.compute_trays_per_rack),
        ("rack_demand", scenario.platform.rack_demand),
    ):
        if estimate.posture is EstimatePosture.SYNTHETIC:
            rows.append(
                _gap_row(
                    owner_type="platform",
                    owner_id=scenario.platform.id,
                    parameter=parameter,
                    estimate=estimate,
                    influence=1.0,
                )
            )
    odm_shares = {
        item["id"]: item["outputs"]["assembly_rack_share"]["p50"]
        for item in odm_results
    }
    odm_influence = bottleneck_probabilities.get("odm_assembly", 0.0)
    for odm in scenario.odms:
        influence = odm_influence * max(odm_shares.get(odm.id, 0.0), 0.05)
        for parameter, estimate in _odm_estimates(odm):
            if estimate.posture is EstimatePosture.SYNTHETIC:
                rows.append(
                    _gap_row(
                        owner_type="odm",
                        owner_id=odm.id,
                        parameter=parameter,
                        estimate=estimate,
                        influence=influence,
                    )
                )
    for component in scenario.components:
        influence = bottleneck_probabilities.get(f"component:{component.id}", 0.0)
        for parameter, estimate in _component_estimates(component):
            if estimate.posture is EstimatePosture.SYNTHETIC:
                rows.append(
                    _gap_row(
                        owner_type="component",
                        owner_id=component.id,
                        parameter=parameter,
                        estimate=estimate,
                        influence=influence,
                    )
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


def reconcile_system_assembly(
    scenario: SystemAssemblyScenario,
    *,
    _capacity_draws: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reconcile non-overlapping ODM flows and required component pools once."""

    random = Random(scenario.seed)
    total_samples: dict[str, list[float]] = defaultdict(list)
    odm_samples: dict[str, dict[str, list[float]]] = {
        item.id: defaultdict(list) for item in scenario.odms
    }
    component_samples: dict[str, dict[str, list[float]]] = {
        item.id: defaultdict(list) for item in scenario.components
    }
    bottleneck_counts: dict[str, float] = defaultdict(float)
    odm_stage_counts: dict[str, dict[str, float]] = {
        item.id: defaultdict(float) for item in scenario.odms
    }
    demand_limited_draws = 0

    for draw_index in range(scenario.samples):
        sampler = EstimateSampler(random)
        packages_per_tray = sampler.estimate(
            scenario.platform.accelerator_packages_per_compute_tray
        )
        trays_per_rack = sampler.estimate(scenario.platform.compute_trays_per_rack)
        packages_per_rack = packages_per_tray * trays_per_rack
        rack_demand = sampler.estimate(scenario.platform.rack_demand)

        current_odms: dict[str, dict[str, float]] = {}
        for odm in scenario.odms:
            tray_capacity = sampler.estimate(odm.compute_tray_capacity)
            good_trays = tray_capacity * sampler.estimate(
                odm.compute_tray_effective_yield
            )
            qualified_trays = good_trays * sampler.estimate(
                odm.compute_tray_platform_qualified_share
            )
            allocated_trays = qualified_trays * sampler.estimate(
                odm.compute_tray_customer_allocation_share
            )
            tray_racks = allocated_trays / trays_per_rack

            rack_capacity = sampler.estimate(odm.rack_integration_capacity)
            good_racks = rack_capacity * sampler.estimate(
                odm.rack_integration_effective_yield
            )
            qualified_racks = good_racks * sampler.estimate(
                odm.rack_platform_qualified_share
            )
            allocated_rack_slots = qualified_racks * sampler.estimate(
                odm.rack_customer_allocation_share
            )
            assembly_racks = min(tray_racks, allocated_rack_slots)
            local_candidates = {
                "compute_trays": tray_racks,
                "rack_integration": allocated_rack_slots,
            }
            tied = [
                key
                for key, value in local_candidates.items()
                if isclose(value, assembly_racks, rel_tol=1e-10, abs_tol=1e-8)
            ]
            for key in tied:
                odm_stage_counts[odm.id][key] += 1 / len(tied)
            current_odms[odm.id] = {
                "compute_tray_capacity": tray_capacity,
                "good_compute_trays": good_trays,
                "platform_qualified_compute_trays": qualified_trays,
                "customer_allocated_compute_trays": allocated_trays,
                "compute_tray_rack_equivalents": tray_racks,
                "rack_integration_capacity": rack_capacity,
                "good_integrated_racks": good_racks,
                "platform_qualified_integrated_racks": qualified_racks,
                "customer_allocated_integrated_racks": allocated_rack_slots,
                "assembly_supported_racks": assembly_racks,
                "unused_customer_allocated_compute_trays": (
                    allocated_trays - assembly_racks * trays_per_rack
                ),
                "unused_customer_allocated_rack_slots": (
                    allocated_rack_slots - assembly_racks
                ),
            }

        odm_capacity = sum(
            values["assembly_supported_racks"] for values in current_odms.values()
        )
        current_components: dict[str, dict[str, float]] = {}
        for component in scenario.components:
            capacity = sampler.estimate(component.capacity)
            good_output = capacity * sampler.estimate(component.effective_yield)
            qualified_output = good_output * sampler.estimate(
                component.platform_qualified_share
            )
            allocated_output = qualified_output * sampler.estimate(
                component.customer_allocation_share
            )
            units_per_rack = sampler.estimate(component.units_per_rack)
            current_components[component.id] = {
                "capacity": capacity,
                "good_output": good_output,
                "platform_qualified_output": qualified_output,
                "customer_allocated_output": allocated_output,
                "rack_equivalents": allocated_output / units_per_rack,
                "units_per_rack": units_per_rack,
            }

        supply_candidates = {
            "odm_assembly": odm_capacity,
            **{
                f"component:{component_id}": values["rack_equivalents"]
                for component_id, values in current_components.items()
            },
        }
        component_cleared_capacity = min(supply_candidates.values())
        complete_racks = min(component_cleared_capacity, rack_demand)
        all_candidates = {**supply_candidates, "rack_demand": rack_demand}
        tied = [
            key
            for key, value in all_candidates.items()
            if isclose(value, complete_racks, rel_tol=1e-10, abs_tol=1e-8)
        ]
        for key in tied:
            bottleneck_counts[key] += 1 / len(tied)
        if rack_demand <= component_cleared_capacity:
            demand_limited_draws += 1

        odm_shares = [
            0.0
            if odm_capacity == 0
            else values["assembly_supported_racks"] / odm_capacity
            for values in current_odms.values()
        ]
        for odm, share in zip(scenario.odms, odm_shares, strict=True):
            current_odms[odm.id]["assembly_rack_share"] = share
            for key, value in current_odms[odm.id].items():
                odm_samples[odm.id][key].append(value)

        for component in scenario.components:
            values = current_components[component.id]
            consumed = complete_racks * values.pop("units_per_rack")
            allocated_output = values["customer_allocated_output"]
            values["consumed_output"] = consumed
            values["unused_customer_allocated_output"] = max(
                0.0, allocated_output - consumed
            )
            values["customer_allocated_utilization"] = (
                0.0 if allocated_output == 0 else consumed / allocated_output
            )
            for key, value in values.items():
                component_samples[component.id][key].append(value)

        totals = {
            "odm_assembly_capacity_racks": odm_capacity,
            "component_cleared_rack_capacity": component_cleared_capacity,
            "rack_demand": rack_demand,
            "complete_racks": complete_racks,
            "unfilled_rack_demand": max(0.0, rack_demand - complete_racks),
            "shadow_assembly_racks": max(0.0, odm_capacity - complete_racks),
            "accelerator_package_equivalents": complete_racks * packages_per_rack,
            "odm_concentration_hhi": sum(share**2 for share in odm_shares),
            "largest_odm_share": max(odm_shares, default=0.0),
        }
        for key, value in totals.items():
            total_samples[key].append(value)
        if _capacity_draws is not None:
            _capacity_draws.append(
                {
                    "draw_index": draw_index,
                    **totals,
                    "odms": {
                        odm_id: {
                            "customer_allocated_compute_trays": values[
                                "customer_allocated_compute_trays"
                            ],
                            "customer_allocated_integrated_racks": values[
                                "customer_allocated_integrated_racks"
                            ],
                            "assembly_supported_racks": values[
                                "assembly_supported_racks"
                            ],
                        }
                        for odm_id, values in current_odms.items()
                    },
                    "components": {
                        component_id: {
                            "customer_allocated_output": values[
                                "customer_allocated_output"
                            ],
                            "rack_equivalents": values["rack_equivalents"],
                        }
                        for component_id, values in current_components.items()
                    },
                }
            )

    bottlenecks = [
        {
            "constraint": key,
            "probability": count / scenario.samples,
        }
        for key, count in sorted(
            bottleneck_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    bottleneck_probabilities = {
        item["constraint"]: item["probability"] for item in bottlenecks
    }
    odm_results = [
        {
            "id": odm.id,
            "name": odm.name,
            "geography": odm.geography,
            "tray_capacity_scope_id": odm.tray_capacity_scope_id,
            "rack_capacity_scope_id": odm.rack_capacity_scope_id,
            "outputs": {
                key: summarize(values).as_dict()
                for key, values in odm_samples[odm.id].items()
            },
            "stage_bottleneck_probabilities": {
                key: value / scenario.samples
                for key, value in sorted(odm_stage_counts[odm.id].items())
            },
        }
        for odm in scenario.odms
    ]
    component_results = [
        {
            "id": component.id,
            "name": component.name,
            "stage": component.stage,
            "resource_kind": component.resource_kind,
            "capacity_scope_id": component.capacity_scope_id,
            "unit": component.capacity.unit,
            "outputs": {
                key: summarize(values).as_dict()
                for key, values in component_samples[component.id].items()
            },
            "bottleneck_probability": bottleneck_probabilities.get(
                f"component:{component.id}", 0.0
            ),
        }
        for component in scenario.components
    ]
    coverage = scenario.coverage
    result = {
        "format": SYSTEM_ASSEMBLY_RESULT_FORMAT,
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "quarter": scenario.quarter,
            "as_of_date": scenario.as_of_date,
            "recorded_at": scenario.recorded_at,
            "synthetic": scenario.synthetic,
            "samples": scenario.samples,
            "seed": scenario.seed,
            "notes": scenario.notes,
        },
        "topology": {
            "platform_id": scenario.platform.id,
            "accelerator_packages_per_compute_tray": _input_estimate(
                scenario.platform.accelerator_packages_per_compute_tray
            ),
            "compute_trays_per_rack": _input_estimate(
                scenario.platform.compute_trays_per_rack
            ),
            "accelerator_packages_per_rack": (
                scenario.platform.accelerator_packages_per_compute_tray.base
                * scenario.platform.compute_trays_per_rack.base
            ),
        },
        "inputs": _inputs(scenario),
        "odms": odm_results,
        "components": component_results,
        "conversion_outputs": {
            key: summarize(values).as_dict()
            for key, values in total_samples.items()
        },
        "bottlenecks": bottlenecks,
        "demand_sufficiency": {
            "probability_demand_limited": demand_limited_draws / scenario.samples,
            "probability_supply_limited": 1 - demand_limited_draws / scenario.samples,
        },
        "coverage": {
            "complete_rack_output": {
                "output_basis": coverage.output_basis,
                "absorbed_constraints": [
                    {
                        "stage": selector.stage,
                        "resource_kind": selector.resource_kind,
                    }
                    for selector in coverage.absorbed_constraints
                ],
                "posture": coverage.posture,
                "methodology": coverage.methodology,
                "confirming_evidence": coverage.confirming_evidence,
                "falsifying_evidence": coverage.falsifying_evidence,
                "notes": coverage.notes,
            }
        },
        "research_queue": _research_queue(
            scenario,
            bottleneck_probabilities,
            odm_results,
        ),
        "evidence": _evidence_payload(scenario),
        "warnings": [
            "ODM and component capacities, yields, qualification, allocation, and demand remain synthetic; output is illustrative.",
            "Unique capacity-scope IDs prevent overlap inside this scenario but do not prove that external disclosures are complete or independent.",
            "The component-cleared output basis prevents modeled server and rack resources from being counted again downstream; it is not direct capacity evidence.",
            "ODM contributions are summed only after each supplier's compute-tray and rack-integration stages are reconciled locally; cross-ODM work transfer is not assumed.",
        ],
        "methodology": {
            "odm_flow": "For each ODM, take the minimum of customer-allocated compute-tray rack equivalents and customer-allocated rack-integration output, then sum non-overlapping supplier scopes.",
            "component_flow": "Convert each required customer-allocated component pool to rack equivalents and take one minimum with ODM assembly and rack demand.",
            "scope_guard": "Complete racks are component-cleared only for the declared stage and resource-kind selectors. Any linked base constraint in that coverage must be removed exactly once.",
        },
    }
    return result


def reconcile_system_assembly_capacity_draws(
    scenario: SystemAssemblyScenario,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    draws: list[dict[str, Any]] = []
    result = reconcile_system_assembly(scenario, _capacity_draws=draws)
    return result, draws
