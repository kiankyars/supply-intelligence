from __future__ import annotations

import unittest
from dataclasses import replace

from supply_intelligence.models import Estimate, EstimatePosture, Stage

from tests.helpers import deterministic_scenario, estimate


class ModelTests(unittest.TestCase):
    def test_estimate_requires_ordered_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "low <= base <= high"):
            Estimate(
                low=2,
                base=1,
                high=3,
                unit="unit",
                posture=EstimatePosture.MODELED,
                methodology="test",
                confidence=0.5,
                last_updated="2026-07-17",
                evidence_ids=("evidence:test",),
                confirming_evidence="confirm",
                falsifying_evidence="falsify",
            )

    def test_ratio_cannot_exceed_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot exceed 1"):
            estimate(1.1, "ratio")

    def test_scenario_rejects_missing_evidence(self) -> None:
        scenario = deterministic_scenario()
        bad_platform = replace(
            scenario.platform,
            racks_per_system=replace(
                scenario.platform.racks_per_system,
                evidence_ids=("evidence:missing",),
            ),
        )
        with self.assertRaisesRegex(ValueError, "missing evidence"):
            replace(scenario, platform=bad_platform)

    def test_scenario_requires_package_stage(self) -> None:
        scenario = deterministic_scenario()
        later = tuple(
            replace(item, stage=Stage.SERVER_ASSEMBLY)
            for item in scenario.constraints
        )
        with self.assertRaisesRegex(ValueError, "accelerator_package constraint"):
            replace(scenario, constraints=later)


if __name__ == "__main__":
    unittest.main()
