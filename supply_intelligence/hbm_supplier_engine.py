"""Monte Carlo HBM supply aggregation across non-overlapping supplier scopes."""

from __future__ import annotations

from collections import defaultdict
from random import Random
from typing import Any, Iterable

from .engine import EstimateSampler, _input_estimate, summarize
from .hbm_supplier_models import HbmSupplierFlow, HbmSupplierScenario
from .manufacturing_engine import gross_dies_per_wafer
from .models import Estimate, EstimatePosture


HBM_SUPPLIER_RESULT_FORMAT = "ai-supply-hbm-supplier-result.v1"


SUPPLIER_OUTPUT_UNITS = {
    "gross_dies_per_wafer": "die/wafer",
    "gross_dies": "die",
    "known_good_dies": "die",
    "raw_stacks": "stack",
    "good_stacks": "stack",
    "platform_qualified_stacks": "stack",
    "customer_allocated_stacks": "stack",
    "platform_package_equivalents": "package",
    "unqualified_good_stacks": "stack",
    "qualified_stacks_allocated_elsewhere": "stack",
    "stacks_consumed_for_demand": "stack",
    "unconsumed_customer_reserved_stacks": "stack",
    "customer_allocated_stack_share": "ratio",
}


TOTAL_OUTPUT_UNITS = {
    "good_stacks": "stack",
    "platform_qualified_stacks": "stack",
    "customer_allocated_stacks": "stack",
    "hbm_package_equivalents": "package",
    "accelerator_package_demand": "package",
    "demanded_stacks": "stack",
    "packages_supported": "package",
    "unfilled_package_demand": "package",
    "excess_customer_reserved_stacks": "stack",
    "customer_reserved_stack_utilization": "ratio",
    "supplier_concentration_hhi": "ratio",
    "largest_supplier_share": "ratio",
}


def _wafer_inputs(supplier: HbmSupplierFlow) -> dict[str, Any]:
    wafer = supplier.wafer
    return {
        "id": wafer.id,
        "name": wafer.name,
        "wafer_starts": _input_estimate(wafer.wafer_starts),
        "wafer_diameter_mm": _input_estimate(wafer.wafer_diameter_mm),
        "edge_exclusion_mm": _input_estimate(wafer.edge_exclusion_mm),
        "die_width_mm": _input_estimate(wafer.die_width_mm),
        "die_height_mm": _input_estimate(wafer.die_height_mm),
        "scribe_width_mm": _input_estimate(wafer.scribe_width_mm),
        "notes": wafer.notes,
    }


def _inputs(scenario: HbmSupplierScenario) -> dict[str, Any]:
    platform = scenario.platform
    return {
        "platform": {
            "id": platform.id,
            "name": platform.name,
            "customer": platform.customer,
            "hbm_generation": platform.hbm_generation,
            "memory_dies_per_stack": _input_estimate(
                platform.memory_dies_per_stack
            ),
            "stack_capacity_gb": _input_estimate(platform.stack_capacity_gb),
            "stacks_per_accelerator": _input_estimate(
                platform.stacks_per_accelerator
            ),
            "accelerator_package_demand": _input_estimate(
                platform.accelerator_package_demand
            ),
            "notes": platform.notes,
        },
        "suppliers": [
            {
                "id": supplier.id,
                "name": supplier.name,
                "capacity_scope_id": supplier.capacity_scope_id,
                "capacity_scope": supplier.capacity_scope,
                "geography": supplier.geography,
                "product": supplier.product,
                "process_node": supplier.process_node,
                "wafer_start_basis": supplier.wafer_start_basis,
                "wafer": _wafer_inputs(supplier),
                "known_good_die_yield": _input_estimate(
                    supplier.known_good_die_yield
                ),
                "stack_assembly_yield": _input_estimate(
                    supplier.stack_assembly_yield
                ),
                "stack_final_test_yield": _input_estimate(
                    supplier.stack_final_test_yield
                ),
                "platform_qualified_share": _input_estimate(
                    supplier.platform_qualified_share
                ),
                "customer_allocation_share": _input_estimate(
                    supplier.customer_allocation_share
                ),
                "notes": supplier.notes,
            }
            for supplier in scenario.suppliers
        ],
    }


def _evidence_payload(scenario: HbmSupplierScenario) -> list[dict[str, Any]]:
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


def _supplier_estimates(
    supplier: HbmSupplierFlow,
) -> Iterable[tuple[str, Estimate]]:
    wafer = supplier.wafer
    yield "wafer.wafer_starts", wafer.wafer_starts
    yield "wafer.wafer_diameter_mm", wafer.wafer_diameter_mm
    yield "wafer.edge_exclusion_mm", wafer.edge_exclusion_mm
    yield "wafer.die_width_mm", wafer.die_width_mm
    yield "wafer.die_height_mm", wafer.die_height_mm
    yield "wafer.scribe_width_mm", wafer.scribe_width_mm
    yield "known_good_die_yield", supplier.known_good_die_yield
    yield "stack_assembly_yield", supplier.stack_assembly_yield
    yield "stack_final_test_yield", supplier.stack_final_test_yield
    yield "platform_qualified_share", supplier.platform_qualified_share
    yield "customer_allocation_share", supplier.customer_allocation_share


def _research_queue(
    scenario: HbmSupplierScenario,
    supplier_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    shares = {
        item["id"]: item["outputs"]["customer_allocated_stack_share"]["p50"]
        for item in supplier_results
    }
    rows = []
    platform_estimates = (
        ("memory_dies_per_stack", scenario.platform.memory_dies_per_stack),
        ("stack_capacity_gb", scenario.platform.stack_capacity_gb),
        ("stacks_per_accelerator", scenario.platform.stacks_per_accelerator),
        (
            "accelerator_package_demand",
            scenario.platform.accelerator_package_demand,
        ),
    )
    for parameter, estimate in platform_estimates:
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
    for supplier in scenario.suppliers:
        influence = shares[supplier.id]
        for parameter, estimate in _supplier_estimates(supplier):
            if estimate.posture is EstimatePosture.SYNTHETIC:
                rows.append(
                    _gap_row(
                        owner_type="supplier",
                        owner_id=supplier.id,
                        parameter=parameter,
                        estimate=estimate,
                        influence=influence,
                    )
                )
    return sorted(
        rows,
        key=lambda item: (-item["research_priority"], item["owner_id"], item["parameter"]),
    )


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
        "influence_share": influence,
        "research_priority": max(influence, 0.05) * (1 - estimate.confidence),
        "methodology": estimate.methodology,
        "evidence_ids": list(estimate.evidence_ids),
        "confirming_evidence": estimate.confirming_evidence,
        "falsifying_evidence": estimate.falsifying_evidence,
    }


def reconcile_hbm_suppliers(
    scenario: HbmSupplierScenario,
    *,
    _capacity_draws: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate supplier HBM stacks once, then apply qualification and allocation."""

    random = Random(scenario.seed)
    total_samples: dict[str, list[float]] = defaultdict(list)
    supplier_samples: dict[str, dict[str, list[float]]] = {
        item.id: defaultdict(list) for item in scenario.suppliers
    }
    supplier_critical_counts = defaultdict(int)
    hbm_limited_count = 0

    for draw_index in range(scenario.samples):
        sampler = EstimateSampler(random)
        memory_dies_per_stack = sampler.estimate(
            scenario.platform.memory_dies_per_stack
        )
        stacks_per_accelerator = sampler.estimate(
            scenario.platform.stacks_per_accelerator
        )
        package_demand = sampler.estimate(
            scenario.platform.accelerator_package_demand
        )
        demanded_stacks = package_demand * stacks_per_accelerator
        current: dict[str, dict[str, float]] = {}

        for supplier in scenario.suppliers:
            wafer = supplier.wafer
            gross_per_wafer = gross_dies_per_wafer(
                wafer_diameter_mm=sampler.estimate(wafer.wafer_diameter_mm),
                edge_exclusion_mm=sampler.estimate(wafer.edge_exclusion_mm),
                die_width_mm=sampler.estimate(wafer.die_width_mm),
                die_height_mm=sampler.estimate(wafer.die_height_mm),
                scribe_width_mm=sampler.estimate(wafer.scribe_width_mm),
            )
            gross_dies = sampler.estimate(wafer.wafer_starts) * gross_per_wafer
            known_good_dies = gross_dies * sampler.estimate(
                supplier.known_good_die_yield
            )
            raw_stacks = known_good_dies / memory_dies_per_stack
            good_stacks = (
                raw_stacks
                * sampler.estimate(supplier.stack_assembly_yield)
                * sampler.estimate(supplier.stack_final_test_yield)
            )
            qualified_stacks = good_stacks * sampler.estimate(
                supplier.platform_qualified_share
            )
            allocated_stacks = qualified_stacks * sampler.estimate(
                supplier.customer_allocation_share
            )
            current[supplier.id] = {
                "gross_dies_per_wafer": gross_per_wafer,
                "gross_dies": gross_dies,
                "known_good_dies": known_good_dies,
                "raw_stacks": raw_stacks,
                "good_stacks": good_stacks,
                "platform_qualified_stacks": qualified_stacks,
                "customer_allocated_stacks": allocated_stacks,
                "platform_package_equivalents": (
                    allocated_stacks / stacks_per_accelerator
                ),
                "unqualified_good_stacks": good_stacks - qualified_stacks,
                "qualified_stacks_allocated_elsewhere": (
                    qualified_stacks - allocated_stacks
                ),
            }

        total_good = sum(item["good_stacks"] for item in current.values())
        total_qualified = sum(
            item["platform_qualified_stacks"] for item in current.values()
        )
        total_allocated = sum(
            item["customer_allocated_stacks"] for item in current.values()
        )
        package_capacity = total_allocated / stacks_per_accelerator
        packages_supported = min(package_capacity, package_demand)
        consumed_stacks = packages_supported * stacks_per_accelerator
        fill_fraction = 0.0 if total_allocated == 0 else consumed_stacks / total_allocated
        shares = [
            0.0
            if total_allocated == 0
            else item["customer_allocated_stacks"] / total_allocated
            for item in current.values()
        ]
        if package_capacity < package_demand:
            hbm_limited_count += 1

        for supplier, share in zip(scenario.suppliers, shares, strict=True):
            values = current[supplier.id]
            values["stacks_consumed_for_demand"] = (
                values["customer_allocated_stacks"] * fill_fraction
            )
            values["unconsumed_customer_reserved_stacks"] = (
                values["customer_allocated_stacks"]
                - values["stacks_consumed_for_demand"]
            )
            values["customer_allocated_stack_share"] = share
            if total_allocated - values["customer_allocated_stacks"] < demanded_stacks:
                supplier_critical_counts[supplier.id] += 1
            for key, value in values.items():
                supplier_samples[supplier.id][key].append(value)

        total_values = {
            "good_stacks": total_good,
            "platform_qualified_stacks": total_qualified,
            "customer_allocated_stacks": total_allocated,
            "hbm_package_equivalents": package_capacity,
            "accelerator_package_demand": package_demand,
            "demanded_stacks": demanded_stacks,
            "packages_supported": packages_supported,
            "unfilled_package_demand": max(0.0, package_demand - package_capacity),
            "excess_customer_reserved_stacks": max(
                0.0,
                total_allocated - demanded_stacks,
            ),
            "customer_reserved_stack_utilization": (
                0.0 if total_allocated == 0 else consumed_stacks / total_allocated
            ),
            "supplier_concentration_hhi": sum(share**2 for share in shares),
            "largest_supplier_share": max(shares, default=0.0),
        }
        for key, value in total_values.items():
            total_samples[key].append(value)
        if _capacity_draws is not None:
            _capacity_draws.append(
                {
                    "draw_index": draw_index,
                    "memory_dies_per_stack": memory_dies_per_stack,
                    "stacks_per_accelerator": stacks_per_accelerator,
                    "accelerator_package_demand": package_demand,
                    "demanded_stacks": demanded_stacks,
                    "good_stacks": total_good,
                    "platform_qualified_stacks": total_qualified,
                    "customer_allocated_stacks": total_allocated,
                    "hbm_package_equivalents": package_capacity,
                    "packages_supported": packages_supported,
                    "supplier_customer_allocated_stacks": {
                        supplier.id: current[supplier.id][
                            "customer_allocated_stacks"
                        ]
                        for supplier in scenario.suppliers
                    },
                }
            )

    supplier_results = []
    for supplier in scenario.suppliers:
        supplier_results.append(
            {
                "id": supplier.id,
                "name": supplier.name,
                "capacity_scope_id": supplier.capacity_scope_id,
                "capacity_scope": supplier.capacity_scope,
                "geography": supplier.geography,
                "product": supplier.product,
                "process_node": supplier.process_node,
                "wafer_start_basis": supplier.wafer_start_basis,
                "outputs": {
                    key: summarize(values).as_dict()
                    for key, values in sorted(supplier_samples[supplier.id].items())
                },
                "criticality_probability": (
                    supplier_critical_counts[supplier.id] / scenario.samples
                ),
                "notes": supplier.notes,
            }
        )

    warnings = [
        "Capacity is summed only across unique declared capacity-scope IDs; each declaration still requires source review for real-world overlap.",
        "Platform qualification and customer allocation are separate multiplicative estimates and must not be inferred from supplier-wide HBM output.",
        "Gross die counts use the manufacturing engine's area and edge-loss approximation; reticle layout, repair, and partial dies are not modeled.",
    ]
    if scenario.synthetic:
        warnings.append(
            "One or more supplier wafer, yield, qualification, allocation, or demand inputs are synthetic; this is not an estimate of actual HBM supply."
        )
    result = {
        "format": HBM_SUPPLIER_RESULT_FORMAT,
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
        "platform": {
            "id": scenario.platform.id,
            "name": scenario.platform.name,
            "customer": scenario.platform.customer,
            "hbm_generation": scenario.platform.hbm_generation,
            "memory_dies_per_stack": _input_estimate(
                scenario.platform.memory_dies_per_stack
            ),
            "stack_capacity_gb": _input_estimate(
                scenario.platform.stack_capacity_gb
            ),
            "stacks_per_accelerator": _input_estimate(
                scenario.platform.stacks_per_accelerator
            ),
        },
        "totals": {
            key: summarize(values).as_dict()
            for key, values in sorted(total_samples.items())
        },
        "suppliers": supplier_results,
        "supply_sufficiency": {
            "probability_hbm_limited": hbm_limited_count / scenario.samples,
            "probability_demand_covered": 1 - hbm_limited_count / scenario.samples,
        },
        "inputs": _inputs(scenario),
        "evidence": _evidence_payload(scenario),
        "source_documents": [
            {
                "evidence_id": item.evidence_id,
                "path": item.path,
                "sha256": item.sha256,
                "bytes": len(item.raw),
            }
            for item in scenario.source_documents
        ],
        "warnings": warnings,
    }
    result["research_queue"] = _research_queue(scenario, supplier_results)
    return result


def reconcile_hbm_supplier_capacity_draws(
    scenario: HbmSupplierScenario,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the standard result plus lossless capacity draws for downstream links."""

    draws: list[dict[str, Any]] = []
    result = reconcile_hbm_suppliers(scenario, _capacity_draws=draws)
    return result, draws
