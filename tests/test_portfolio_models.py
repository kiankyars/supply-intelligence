from __future__ import annotations

import unittest
from dataclasses import replace

from supply_intelligence.models import Stage

from tests.portfolio_helpers import deterministic_portfolio


class PortfolioModelTests(unittest.TestCase):
    def test_resource_and_requirement_units_must_match(self) -> None:
        scenario = deterministic_portfolio()
        broken = replace(
            scenario.requirements[0],
            units_per_system=replace(
                scenario.requirements[0].units_per_system,
                unit="different_unit",
            ),
        )
        with self.assertRaisesRegex(ValueError, "unit must match"):
            replace(scenario, requirements=(broken, *scenario.requirements[1:]))

    def test_each_platform_requires_a_package_resource(self) -> None:
        scenario = deterministic_portfolio()
        later_resources = tuple(
            replace(item, stage=Stage.SERVER_ASSEMBLY)
            if item.id == "shared_wafers"
            else item
            for item in scenario.resource_pools
        )
        with self.assertRaisesRegex(ValueError, "accelerator_package resource"):
            replace(scenario, resource_pools=later_resources)

    def test_duplicate_platform_resource_pair_is_rejected(self) -> None:
        scenario = deterministic_portfolio()
        duplicate = replace(scenario.requirements[0], id="duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate platform and resource"):
            replace(scenario, requirements=(*scenario.requirements, duplicate))


if __name__ == "__main__":
    unittest.main()
