from __future__ import annotations

import unittest
from dataclasses import replace

from supply_intelligence.datacenter_operational_engine import (
    reconcile_datacenter_operational,
)

from tests.datacenter_operational_helpers import deterministic_operational_case
from tests.helpers import estimate


class DatacenterOperationalEngineTests(unittest.TestCase):
    def test_commissioning_limits_operational_racks_after_gross_to_net_bridge(self) -> None:
        result = reconcile_datacenter_operational(deterministic_operational_case())
        outputs = result["conversion_outputs"]
        self.assertEqual(60, outputs["net_uncommitted_compatible_power"]["p50"])
        self.assertEqual(30, outputs["target_allocatable_power"]["p50"])
        self.assertAlmostEqual(300, outputs["power_limited_racks"]["p50"])
        self.assertEqual(100, outputs["commissioning_completed_capacity"]["p50"])
        self.assertEqual(100, outputs["operational_racks"]["p50"])
        self.assertEqual(20, outputs["shadow_allocatable_power"]["p50"])
        self.assertEqual("commissioning", result["bottlenecks"][0]["constraint"])
        self.assertEqual(1, result["bottlenecks"][0]["probability"])

    def test_power_can_bind_and_leave_shadow_commissioning_capacity(self) -> None:
        case = deterministic_operational_case()
        scenario = replace(
            case.scenario,
            commissioning_slots=estimate(1000, "rack"),
            commissioning_completion_ratio=estimate(1, "ratio"),
        )
        result = reconcile_datacenter_operational(replace(case, scenario=scenario))
        outputs = result["conversion_outputs"]
        self.assertAlmostEqual(300, outputs["operational_racks"]["p50"])
        self.assertAlmostEqual(
            700,
            outputs["shadow_commissioning_capacity"]["p50"],
        )
        self.assertEqual("power", result["bottlenecks"][0]["constraint"])

    def test_deductions_above_gross_floor_residual_power_at_zero(self) -> None:
        case = deterministic_operational_case()
        deductions = replace(
            case.scenario.deductions,
            current_critical_it_load=estimate(120, "MW"),
        )
        scenario = replace(case.scenario, deductions=deductions)
        result = reconcile_datacenter_operational(replace(case, scenario=scenario))
        outputs = result["conversion_outputs"]
        self.assertEqual(0, outputs["net_uncommitted_compatible_power"]["p50"])
        self.assertEqual(40, outputs["oversubscribed_deductions"]["p50"])
        self.assertEqual(0, outputs["operational_racks"]["p50"])
        self.assertEqual(1, result["diagnostics"]["zero_residual_probability"])

    def test_synthetic_scenario_cannot_be_marked_usable(self) -> None:
        result = reconcile_datacenter_operational(deterministic_operational_case())
        self.assertFalse(result["usable_as_operational_capacity"])
        self.assertTrue(result["research_queue"])
        self.assertTrue(
            all(item["conditional_on_current_scenario"] for item in result["research_queue"])
        )


if __name__ == "__main__":
    unittest.main()
