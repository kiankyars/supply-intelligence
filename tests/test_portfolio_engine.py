from __future__ import annotations

import unittest

from supply_intelligence.portfolio_engine import reconcile_portfolio

from tests.portfolio_helpers import deterministic_portfolio


class PortfolioEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = reconcile_portfolio(deterministic_portfolio())
        self.platforms = {item["id"]: item for item in self.result["platforms"]}
        self.resources = {item["id"]: item for item in self.result["resource_pools"]}

    def _stages(self, platform_id: str) -> dict[str, float]:
        return {
            item["stage"]: item["system_equivalents"]["p50"]
            for item in self.platforms[platform_id]["stage_outputs"]
        }

    def test_shared_package_pool_is_consumed_once(self) -> None:
        a = self._stages("a")
        b = self._stages("b")
        self.assertEqual(a["accelerator_package"], 50)
        self.assertEqual(b["accelerator_package"], 50)
        wafer = self.resources["shared_wafers"]
        self.assertEqual(wafer["consumption"]["p50"], 100)
        self.assertEqual(wafer["utilization"]["p50"], 1)

    def test_stage_outputs_carry_forward_without_rebalancing_upstream(self) -> None:
        self.assertEqual(
            self._stages("a"),
            {
                "accelerator_package": 50,
                "server_assembly": 20,
                "rack_integration": 20,
                "shipped": 20,
                "installed": 20,
                "operational": 10,
            },
        )
        self.assertEqual(
            self._stages("b"),
            {
                "accelerator_package": 50,
                "server_assembly": 50,
                "rack_integration": 40,
                "shipped": 30,
                "installed": 25,
                "operational": 10,
            },
        )

    def test_resource_conservation_holds_at_every_stage(self) -> None:
        for resource in self.resources.values():
            self.assertLessEqual(
                resource["consumption"]["maximum"],
                resource["effective_capacity"]["minimum"] + 1e-9,
            )

    def test_inventory_exposes_stage_specific_holdback(self) -> None:
        inventory = {
            (item["platform_id"], item["from_stage"], item["to_stage"]): item[
                "systems_held_back"
            ]["p50"]
            for item in self.result["inventory"]
        }
        self.assertEqual(
            inventory[("a", "accelerator_package", "server_assembly")], 30
        )
        self.assertEqual(
            inventory[("b", "server_assembly", "rack_integration")], 10
        )
        self.assertEqual(inventory[("b", "rack_integration", "shipped")], 10)

    def test_platform_physical_outputs_use_own_bom(self) -> None:
        self.assertEqual(
            self.platforms["a"]["physical_outputs"]["accelerator_packages_produced"][
                "p50"
            ],
            200,
        )
        self.assertEqual(
            self.platforms["b"]["physical_outputs"]["accelerator_packages_produced"][
                "p50"
            ],
            400,
        )

    def test_binding_probabilities_are_normalized_by_stage(self) -> None:
        for stage in self.result["stage_bottlenecks"]:
            self.assertAlmostEqual(
                sum(item["probability"] for item in stage["constraints"]), 1.0
            )


if __name__ == "__main__":
    unittest.main()
