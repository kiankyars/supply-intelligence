from __future__ import annotations

import unittest

from supply_intelligence.engine import reconcile

from tests.helpers import deterministic_scenario


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = reconcile(deterministic_scenario())

    def test_stage_output_is_minimum_feasible_capacity(self) -> None:
        outputs = {
            row["stage"]: row["system_equivalents"]["p50"]
            for row in self.result["stage_outputs"]
        }
        self.assertEqual(
            outputs,
            {
                "accelerator_package": 100,
                "server_assembly": 80,
                "rack_integration": 70,
                "shipped": 60,
                "installed": 50,
                "operational": 40,
            },
        )

    def test_physical_outputs_preserve_stage_semantics(self) -> None:
        outputs = self.result["physical_outputs"]
        self.assertEqual(outputs["accelerator_packages_produced"]["p50"], 400)
        self.assertEqual(outputs["complete_servers"]["p50"], 160)
        self.assertEqual(outputs["integrated_racks"]["p50"], 70)
        self.assertEqual(outputs["systems_shipped"]["p50"], 60)
        self.assertEqual(outputs["systems_operational"]["p50"], 40)

    def test_bottleneck_probabilities_sum_to_one(self) -> None:
        for stage in self.result["bottlenecks"]:
            self.assertAlmostEqual(
                sum(item["probability"] for item in stage["constraints"]), 1.0
            )

    def test_customer_caps_redistribute_residual_supply(self) -> None:
        allocations = {
            row["customer"]: row["systems_shipped"]["p50"]
            for row in self.result["customer_allocations"]
        }
        self.assertEqual(allocations["Customer A"], 30)
        self.assertEqual(allocations["Customer B"], 30)
        self.assertEqual(allocations["Unallocated"], 0)

    def test_supplier_estimate_and_opportunity_screen(self) -> None:
        supplier = self.result["supplier_estimates"][0]
        self.assertEqual(supplier["bottom_up_revenue_usd"]["p50"], 600)
        self.assertEqual(supplier["bottom_up_gross_profit_usd"]["p50"], 300)
        self.assertAlmostEqual(supplier["expected_revenue_revision_pct"]["p50"], 20)
        candidate = self.result["opportunity_candidates"][0]
        self.assertEqual(candidate["direction"], "positive_revision_candidate")
        self.assertAlmostEqual(candidate["screen_score"]["p50"], 0.2)
        self.assertEqual(candidate["status"], "wait_for_proof")
        self.assertEqual(candidate["actionability"], "Wait for proof.")

    def test_fixed_seed_is_reproducible(self) -> None:
        self.assertEqual(self.result, reconcile(deterministic_scenario()))


if __name__ == "__main__":
    unittest.main()
