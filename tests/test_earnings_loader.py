from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from supply_intelligence.earnings_engine import reconcile_earnings
from supply_intelligence.earnings_loader import load_earnings_case

from tests.earnings_helpers import earnings_documents


class EarningsLoaderTests(unittest.TestCase):
    def test_loader_pins_source_and_validates_company_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path, source_path, _ = earnings_documents(Path(temporary))
            case = load_earnings_case(scenario_path, source_path)
            self.assertEqual("earnings-fixture-2026q3", case.scenario.id)
            self.assertEqual(2, len(case.scenario.companies))
            self.assertTrue(case.source_synthetic)
            self.assertEqual(
                "package",
                case.source_metrics["finished_accelerator_packages"]["unit"],
            )
            result = reconcile_earnings(case)
            self.assertEqual(2, len(result["rankings"]))

    def test_source_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path, source_path, _ = earnings_documents(Path(temporary))
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["scenario"]["recorded_at"] = "2026-07-19T21:00:01Z"
            source_path.write_text(
                json.dumps(source, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_earnings_case(scenario_path, source_path)

    def test_line_item_metric_unit_must_match_frozen_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path, source_path, document = earnings_documents(Path(temporary))
            line_item = document["companies"][0]["line_items"][0]
            line_item["source_unit"] = "stack"
            line_item["units_per_source_unit"]["unit"] = "unit/stack"
            scenario_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "source unit does not match"):
                load_earnings_case(scenario_path, source_path)

    def test_source_time_and_unexpected_fields_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path, source_path, document = earnings_documents(Path(temporary))
            document["unexpected"] = True
            scenario_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unexpected earnings scenario fields"):
                load_earnings_case(scenario_path, source_path)

        with tempfile.TemporaryDirectory() as temporary:
            scenario_path, source_path, document = earnings_documents(Path(temporary))
            document["recorded_at"] = "2026-07-19T20:00:00Z"
            scenario_path.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "cannot precede its source result"):
                load_earnings_case(scenario_path, source_path)


if __name__ == "__main__":
    unittest.main()
