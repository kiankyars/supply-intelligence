from __future__ import annotations

import unittest
from dataclasses import replace

from supply_intelligence.manufacturing_engine import (
    gross_dies_per_wafer,
    negative_binomial_die_yield,
    reconcile_manufacturing,
)
from supply_intelligence.manufacturing_models import (
    ManufacturingReference,
    PackageAssemblyFlow,
)

from tests.helpers import estimate
from tests.manufacturing_helpers import (
    deterministic_manufacturing,
    with_logic_wafer_starts,
)


class ManufacturingMathTests(unittest.TestCase):
    def test_gross_die_approximation_responds_to_geometry(self) -> None:
        large_die = gross_dies_per_wafer(
            wafer_diameter_mm=300,
            edge_exclusion_mm=0,
            die_width_mm=30,
            die_height_mm=30,
            scribe_width_mm=0,
        )
        small_die = gross_dies_per_wafer(
            wafer_diameter_mm=300,
            edge_exclusion_mm=0,
            die_width_mm=10,
            die_height_mm=10,
            scribe_width_mm=0,
        )
        excluded_edge = gross_dies_per_wafer(
            wafer_diameter_mm=300,
            edge_exclusion_mm=3,
            die_width_mm=10,
            die_height_mm=10,
            scribe_width_mm=0,
        )
        self.assertGreater(small_die, large_die)
        self.assertLess(excluded_edge, small_die)
        self.assertGreater(large_die, 0)

    def test_negative_binomial_yield_is_bounded_and_monotone(self) -> None:
        clean = negative_binomial_die_yield(
            defect_density_per_cm2=0,
            die_area_mm2=800,
            clustering_alpha=2,
        )
        low_defect = negative_binomial_die_yield(
            defect_density_per_cm2=0.05,
            die_area_mm2=800,
            clustering_alpha=2,
        )
        high_defect = negative_binomial_die_yield(
            defect_density_per_cm2=0.2,
            die_area_mm2=800,
            clustering_alpha=2,
        )
        self.assertEqual(1, clean)
        self.assertGreater(low_defect, high_defect)
        self.assertGreater(high_defect, 0)
        self.assertLess(low_defect, 1)

    def test_hbm_stack_supply_binds_deterministic_fixture(self) -> None:
        result = reconcile_manufacturing(deterministic_manufacturing())
        outputs = result["conversion_outputs"]
        self.assertAlmostEqual(192, outputs["hbm_gb_per_accelerator"]["p50"])
        self.assertAlmostEqual(
            64,
            outputs["hbm_memory_dies_per_accelerator"]["p50"],
        )
        self.assertAlmostEqual(
            outputs["hbm_package_equivalents"]["p50"],
            outputs["finished_accelerator_packages"]["p50"],
        )
        self.assertAlmostEqual(
            outputs["finished_accelerator_packages"]["p50"] / 2,
            outputs["complete_system_equivalents"]["p50"],
        )
        self.assertEqual(
            "hbm_good_stacks",
            result["bottlenecks"][0]["constraint"],
        )
        self.assertEqual(1, result["bottlenecks"][0]["probability"])
        self.assertGreater(outputs["surplus_binned_logic_dies"]["p50"], 0)
        self.assertAlmostEqual(0, outputs["surplus_good_hbm_stacks"]["p50"])

    def test_logic_shortage_becomes_binding_constraint(self) -> None:
        scenario = with_logic_wafer_starts(deterministic_manufacturing(), 0.1)
        result = reconcile_manufacturing(scenario)
        self.assertEqual(
            "logic_binned_dies",
            result["bottlenecks"][0]["constraint"],
        )
        self.assertEqual(1, result["bottlenecks"][0]["probability"])

    def test_seeded_uncertainty_is_reproducible(self) -> None:
        scenario = deterministic_manufacturing()
        wafer = replace(
            scenario.hbm.wafer,
            wafer_starts=estimate(1, "wafer", low=0.8, high=1.2),
        )
        scenario = replace(scenario, hbm=replace(scenario.hbm, wafer=wafer))
        self.assertEqual(
            reconcile_manufacturing(scenario),
            reconcile_manufacturing(scenario),
        )

    def test_external_reference_is_a_nonbinding_scale_control(self) -> None:
        scenario = deterministic_manufacturing()
        baseline = reconcile_manufacturing(scenario)
        reference = ManufacturingReference(
            id="reference:test",
            name="Reported company total",
            period="2026-Q2",
            comparison_target="logic_wafer_starts",
            estimate=estimate(100, "wafer"),
            usable_as_product_capacity=False,
            notes="Scale check only.",
        )
        scenario = replace(scenario, references=(reference,))
        result = reconcile_manufacturing(scenario)
        comparison = result["reference_comparisons"][0]
        self.assertEqual(baseline["conversion_outputs"], result["conversion_outputs"])
        self.assertEqual(baseline["bottlenecks"], result["bottlenecks"])
        self.assertEqual(100, comparison["reference_value"]["p50"])
        self.assertEqual(1, comparison["modeled_target"]["p50"])
        self.assertEqual(0.01, comparison["target_share"]["p50"])
        self.assertFalse(comparison["usable_as_product_capacity"])

    def test_topology_requires_fixed_positive_integers(self) -> None:
        scenario = deterministic_manufacturing()
        with self.assertRaisesRegex(ValueError, "fixed positive integer"):
            PackageAssemblyFlow(
                assembly_starts=scenario.package.assembly_starts,
                assembly_yield=scenario.package.assembly_yield,
                logic_dies_per_accelerator=estimate(
                    2,
                    "die/accelerator",
                    low=1,
                    high=3,
                ),
                accelerators_per_system=scenario.package.accelerators_per_system,
            )


if __name__ == "__main__":
    unittest.main()
