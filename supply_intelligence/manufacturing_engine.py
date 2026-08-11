"""Monte Carlo conversion from wafer starts to finished accelerator packages."""

from __future__ import annotations

from collections import defaultdict
from math import isclose, pi, sqrt
from random import Random
from typing import Any

from .engine import EstimateSampler, _input_estimate, summarize
from .manufacturing_models import ManufacturingScenario, WaferFlow
from .manufacturing_research import build_manufacturing_research_queue


OUTPUT_UNITS = {
    "logic_gross_dies_per_wafer": "die/wafer",
    "logic_defect_yield": "ratio",
    "logic_effective_known_good_yield": "ratio",
    "logic_binned_yield": "ratio",
    "logic_gross_dies": "die",
    "logic_known_good_dies": "die",
    "logic_binned_dies": "die",
    "logic_package_equivalents": "package",
    "hbm_gross_dies_per_wafer": "die/wafer",
    "hbm_gross_dies": "die",
    "hbm_known_good_dies": "die",
    "hbm_raw_stacks": "stack",
    "hbm_good_stacks": "stack",
    "hbm_package_equivalents": "package",
    "hbm_gb_per_accelerator": "GB/accelerator",
    "hbm_memory_dies_per_accelerator": "die/accelerator",
    "package_assembly_start_capacity": "package",
    "package_attempts": "package",
    "package_assembly_yield": "ratio",
    "finished_accelerator_packages": "package",
    "complete_system_equivalents": "system",
    "surplus_binned_logic_dies": "die",
    "surplus_good_hbm_stacks": "stack",
    "logic_die_utilization": "ratio",
    "hbm_stack_utilization": "ratio",
    "assembly_start_utilization": "ratio",
}


def gross_dies_per_wafer(
    *,
    wafer_diameter_mm: float,
    edge_exclusion_mm: float,
    die_width_mm: float,
    die_height_mm: float,
    scribe_width_mm: float,
) -> float:
    """Approximate gross rectangular dies with circular-area and edge-loss terms."""

    if wafer_diameter_mm <= 0:
        raise ValueError("wafer_diameter_mm must be positive")
    if edge_exclusion_mm < 0 or edge_exclusion_mm * 2 >= wafer_diameter_mm:
        raise ValueError("edge_exclusion_mm must leave a positive usable diameter")
    if die_width_mm <= 0 or die_height_mm <= 0 or scribe_width_mm < 0:
        raise ValueError("die dimensions must be positive and scribe width nonnegative")
    usable_diameter = wafer_diameter_mm - 2 * edge_exclusion_mm
    effective_area = (die_width_mm + scribe_width_mm) * (
        die_height_mm + scribe_width_mm
    )
    area_term = pi * (usable_diameter / 2) ** 2 / effective_area
    edge_term = pi * usable_diameter / sqrt(2 * effective_area)
    return max(0.0, area_term - edge_term)


def negative_binomial_die_yield(
    *,
    defect_density_per_cm2: float,
    die_area_mm2: float,
    clustering_alpha: float,
) -> float:
    """Calculate defect-limited die yield with a negative-binomial model."""

    if defect_density_per_cm2 < 0:
        raise ValueError("defect density must be nonnegative")
    if die_area_mm2 <= 0 or clustering_alpha <= 0:
        raise ValueError("die area and clustering alpha must be positive")
    die_area_cm2 = die_area_mm2 / 100
    return (1 + defect_density_per_cm2 * die_area_cm2 / clustering_alpha) ** (
        -clustering_alpha
    )


def _wafer_inputs(wafer: WaferFlow) -> dict[str, Any]:
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


def _evidence_payload(scenario: ManufacturingScenario) -> list[dict[str, Any]]:
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


def _inputs(scenario: ManufacturingScenario) -> dict[str, Any]:
    return {
        "logic": {
            "wafer": _wafer_inputs(scenario.logic.wafer),
            "defect_density_per_cm2": _input_estimate(
                scenario.logic.defect_density_per_cm2
            ),
            "clustering_alpha": _input_estimate(scenario.logic.clustering_alpha),
            "wafer_sort_yield": _input_estimate(scenario.logic.wafer_sort_yield),
            "performance_bin_share": _input_estimate(
                scenario.logic.performance_bin_share
            ),
        },
        "hbm": {
            "wafer": _wafer_inputs(scenario.hbm.wafer),
            "known_good_die_yield": _input_estimate(
                scenario.hbm.known_good_die_yield
            ),
            "memory_dies_per_stack": _input_estimate(
                scenario.hbm.memory_dies_per_stack
            ),
            "stack_assembly_yield": _input_estimate(
                scenario.hbm.stack_assembly_yield
            ),
            "stack_final_test_yield": _input_estimate(
                scenario.hbm.stack_final_test_yield
            ),
            "stack_capacity_gb": _input_estimate(scenario.hbm.stack_capacity_gb),
            "stacks_per_accelerator": _input_estimate(
                scenario.hbm.stacks_per_accelerator
            ),
        },
        "package": {
            "assembly_starts": _input_estimate(scenario.package.assembly_starts),
            "assembly_yield": _input_estimate(scenario.package.assembly_yield),
            "logic_dies_per_accelerator": _input_estimate(
                scenario.package.logic_dies_per_accelerator
            ),
            "accelerators_per_system": _input_estimate(
                scenario.package.accelerators_per_system
            ),
        },
        "references": [
            {
                "id": item.id,
                "name": item.name,
                "period": item.period,
                "comparison_target": item.comparison_target,
                "estimate": _input_estimate(item.estimate),
                "usable_as_product_capacity": item.usable_as_product_capacity,
                "notes": item.notes,
            }
            for item in scenario.references
        ],
    }


def reconcile_manufacturing(scenario: ManufacturingScenario) -> dict[str, Any]:
    """Convert sampled wafer, yield, HBM, and assembly inputs into package output."""

    random = Random(scenario.seed)
    samples: dict[str, list[float]] = defaultdict(list)
    bottleneck_counts: dict[str, float] = defaultdict(float)
    reference_samples: dict[str, dict[str, list[float]]] = {
        item.id: defaultdict(list) for item in scenario.references
    }
    comparison_target_samples: dict[str, list[float]] = defaultdict(list)

    for _ in range(scenario.samples):
        sampler = EstimateSampler(random)

        logic_wafer_starts = sampler.estimate(scenario.logic.wafer.wafer_starts)
        logic_diameter = sampler.estimate(
            scenario.logic.wafer.wafer_diameter_mm
        )
        logic_edge = sampler.estimate(scenario.logic.wafer.edge_exclusion_mm)
        logic_width = sampler.estimate(scenario.logic.wafer.die_width_mm)
        logic_height = sampler.estimate(scenario.logic.wafer.die_height_mm)
        logic_scribe = sampler.estimate(scenario.logic.wafer.scribe_width_mm)
        logic_gross_per_wafer = gross_dies_per_wafer(
            wafer_diameter_mm=logic_diameter,
            edge_exclusion_mm=logic_edge,
            die_width_mm=logic_width,
            die_height_mm=logic_height,
            scribe_width_mm=logic_scribe,
        )
        defect_yield = negative_binomial_die_yield(
            defect_density_per_cm2=sampler.estimate(
                scenario.logic.defect_density_per_cm2
            ),
            die_area_mm2=logic_width * logic_height,
            clustering_alpha=sampler.estimate(scenario.logic.clustering_alpha),
        )
        sort_yield = sampler.estimate(scenario.logic.wafer_sort_yield)
        bin_share = sampler.estimate(scenario.logic.performance_bin_share)
        logic_gross_dies = logic_wafer_starts * logic_gross_per_wafer
        logic_known_good_dies = logic_gross_dies * defect_yield * sort_yield
        logic_binned_dies = logic_known_good_dies * bin_share
        logic_dies_per_accelerator = sampler.estimate(
            scenario.package.logic_dies_per_accelerator
        )
        logic_package_equivalents = (
            logic_binned_dies / logic_dies_per_accelerator
        )

        hbm_wafer_starts = sampler.estimate(scenario.hbm.wafer.wafer_starts)
        hbm_gross_per_wafer = gross_dies_per_wafer(
            wafer_diameter_mm=sampler.estimate(
                scenario.hbm.wafer.wafer_diameter_mm
            ),
            edge_exclusion_mm=sampler.estimate(
                scenario.hbm.wafer.edge_exclusion_mm
            ),
            die_width_mm=sampler.estimate(scenario.hbm.wafer.die_width_mm),
            die_height_mm=sampler.estimate(scenario.hbm.wafer.die_height_mm),
            scribe_width_mm=sampler.estimate(
                scenario.hbm.wafer.scribe_width_mm
            ),
        )
        hbm_gross_dies = hbm_wafer_starts * hbm_gross_per_wafer
        hbm_known_good_dies = hbm_gross_dies * sampler.estimate(
            scenario.hbm.known_good_die_yield
        )
        memory_dies_per_stack = sampler.estimate(
            scenario.hbm.memory_dies_per_stack
        )
        raw_hbm_stacks = hbm_known_good_dies / memory_dies_per_stack
        good_hbm_stacks = (
            raw_hbm_stacks
            * sampler.estimate(scenario.hbm.stack_assembly_yield)
            * sampler.estimate(scenario.hbm.stack_final_test_yield)
        )
        stacks_per_accelerator = sampler.estimate(
            scenario.hbm.stacks_per_accelerator
        )
        hbm_package_equivalents = good_hbm_stacks / stacks_per_accelerator

        assembly_starts = sampler.estimate(scenario.package.assembly_starts)
        candidates = {
            "logic_binned_dies": logic_package_equivalents,
            "hbm_good_stacks": hbm_package_equivalents,
            "package_assembly_starts": assembly_starts,
        }
        attempted_packages = min(candidates.values())
        tied = [
            key
            for key, value in candidates.items()
            if isclose(value, attempted_packages, rel_tol=1e-10, abs_tol=1e-8)
        ]
        for key in tied:
            bottleneck_counts[key] += 1 / len(tied)
        assembly_yield = sampler.estimate(scenario.package.assembly_yield)
        finished_packages = attempted_packages * assembly_yield
        accelerators_per_system = sampler.estimate(
            scenario.package.accelerators_per_system
        )
        complete_systems = finished_packages / accelerators_per_system
        stack_capacity_gb = sampler.estimate(scenario.hbm.stack_capacity_gb)

        comparison_targets = {
            "logic_wafer_starts": logic_wafer_starts,
            "hbm_wafer_starts": hbm_wafer_starts,
            "package_assembly_starts": assembly_starts,
        }
        for target, value in comparison_targets.items():
            comparison_target_samples[target].append(value)

        values = {
            "logic_gross_dies_per_wafer": logic_gross_per_wafer,
            "logic_defect_yield": defect_yield,
            "logic_effective_known_good_yield": defect_yield * sort_yield,
            "logic_binned_yield": defect_yield * sort_yield * bin_share,
            "logic_gross_dies": logic_gross_dies,
            "logic_known_good_dies": logic_known_good_dies,
            "logic_binned_dies": logic_binned_dies,
            "logic_package_equivalents": logic_package_equivalents,
            "hbm_gross_dies_per_wafer": hbm_gross_per_wafer,
            "hbm_gross_dies": hbm_gross_dies,
            "hbm_known_good_dies": hbm_known_good_dies,
            "hbm_raw_stacks": raw_hbm_stacks,
            "hbm_good_stacks": good_hbm_stacks,
            "hbm_package_equivalents": hbm_package_equivalents,
            "hbm_gb_per_accelerator": stack_capacity_gb
            * stacks_per_accelerator,
            "hbm_memory_dies_per_accelerator": memory_dies_per_stack
            * stacks_per_accelerator,
            "package_assembly_start_capacity": assembly_starts,
            "package_attempts": attempted_packages,
            "package_assembly_yield": assembly_yield,
            "finished_accelerator_packages": finished_packages,
            "complete_system_equivalents": complete_systems,
            "surplus_binned_logic_dies": max(
                0.0,
                logic_binned_dies
                - attempted_packages * logic_dies_per_accelerator,
            ),
            "surplus_good_hbm_stacks": max(
                0.0,
                good_hbm_stacks - attempted_packages * stacks_per_accelerator,
            ),
            "logic_die_utilization": (
                0.0
                if logic_binned_dies == 0
                else attempted_packages
                * logic_dies_per_accelerator
                / logic_binned_dies
            ),
            "hbm_stack_utilization": (
                0.0
                if good_hbm_stacks == 0
                else attempted_packages * stacks_per_accelerator / good_hbm_stacks
            ),
            "assembly_start_utilization": (
                0.0 if assembly_starts == 0 else attempted_packages / assembly_starts
            ),
        }
        for key, value in values.items():
            samples[key].append(value)

    for reference in scenario.references:
        reference_random = Random(f"{scenario.seed}:{reference.id}")
        for target_value in comparison_target_samples[reference.comparison_target]:
            reference_sampler = EstimateSampler(reference_random)
            reference_value = reference_sampler.estimate(reference.estimate)
            reference_samples[reference.id]["reference_value"].append(
                reference_value
            )
            reference_samples[reference.id]["modeled_target"].append(target_value)
            reference_samples[reference.id]["target_share"].append(
                target_value / reference_value
            )

    warnings = [
        "Gross dies per wafer use an area and edge-loss approximation. Reticle stepping, partial dies, and layout phase are not modeled."
    ]
    if scenario.synthetic:
        warnings.append(
            "Inputs marked synthetic test the conversion chain and are not supplier capacity or yield estimates."
        )
    if any(not item.usable_as_product_capacity for item in scenario.references):
        warnings.append(
            "External reference controls are scale checks only and do not replace product-specific capacity or allocation inputs."
        )
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
    input_payload = _inputs(scenario)
    return {
        "format": "ai-supply-manufacturing-result.v1",
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
            "logic_dies_per_accelerator": _input_estimate(
                scenario.package.logic_dies_per_accelerator
            ),
            "hbm_memory_dies_per_stack": _input_estimate(
                scenario.hbm.memory_dies_per_stack
            ),
            "hbm_stacks_per_accelerator": _input_estimate(
                scenario.hbm.stacks_per_accelerator
            ),
            "hbm_stack_capacity_gb": _input_estimate(
                scenario.hbm.stack_capacity_gb
            ),
            "accelerators_per_system": _input_estimate(
                scenario.package.accelerators_per_system
            ),
        },
        "conversion_outputs": {
            key: summarize(values).as_dict() for key, values in sorted(samples.items())
        },
        "bottlenecks": bottlenecks,
        "reference_comparisons": [
            {
                "id": item.id,
                "name": item.name,
                "period": item.period,
                "comparison_target": item.comparison_target,
                "reference_value": summarize(
                    reference_samples[item.id]["reference_value"]
                ).as_dict(),
                "modeled_target": summarize(
                    reference_samples[item.id]["modeled_target"]
                ).as_dict(),
                "target_share": summarize(
                    reference_samples[item.id]["target_share"]
                ).as_dict(),
                "unit": item.estimate.unit,
                "usable_as_product_capacity": item.usable_as_product_capacity,
                "notes": item.notes,
            }
            for item in scenario.references
        ],
        "methodology": {
            "gross_dies_per_wafer": (
                "Circular wafer area divided by effective die and scribe area, "
                "less an analytical edge-loss term."
            ),
            "logic_yield": (
                "Negative-binomial random-defect yield multiplied by wafer-sort "
                "yield and performance-bin share."
            ),
            "hbm_yield": (
                "Known-good memory dies divided by dies per stack, then multiplied "
                "by stack-assembly and final-test yields."
            ),
            "package_output": (
                "The minimum of logic-die, HBM-stack, and assembly-start package "
                "equivalents, multiplied by final assembly yield."
            ),
        },
        "inputs": input_payload,
        "research_queue": build_manufacturing_research_queue(
            input_payload,
            bottlenecks,
        ),
        "evidence": _evidence_payload(scenario),
        "warnings": warnings,
    }
