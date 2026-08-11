from __future__ import annotations

import unittest

from supply_intelligence.earnings_engine import reconcile_earnings

from tests.earnings_helpers import earnings_case


class EarningsEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = reconcile_earnings(earnings_case(samples=4000))

    def test_inventory_and_revenue_bridge_are_explicit(self) -> None:
        positive = next(
            item for item in self.result["companies"] if item["ticker"] == "POS"
        )
        base = positive["named_cases"]["base"]
        line = base["line_items"][0]
        self.assertEqual(100, line["produced_units"])
        self.assertEqual(110, line["available_units"])
        self.assertEqual(90, line["shipped_units"])
        self.assertEqual(90, line["recognized_units"])
        self.assertEqual(900, line["revenue_usd"])
        self.assertEqual(1000, base["total_revenue_usd"])
        self.assertAlmostEqual(2.32, base["eps_usd"])

    def test_named_cases_hold_consensus_fixed_and_order_model_outcomes(self) -> None:
        positive = next(
            item for item in self.result["companies"] if item["ticker"] == "POS"
        )
        bear = positive["named_cases"]["bear"]
        base = positive["named_cases"]["base"]
        bull = positive["named_cases"]["bull"]
        self.assertLess(bear["total_revenue_usd"], base["total_revenue_usd"])
        self.assertLess(base["total_revenue_usd"], bull["total_revenue_usd"])
        self.assertEqual(
            bear["consensus_revenue_usd"],
            bull["consensus_revenue_usd"],
        )
        self.assertLess(bear["eps_usd"], base["eps_usd"])
        self.assertLess(base["eps_usd"], bull["eps_usd"])

    def test_long_short_direction_and_ranking_remain_research_only(self) -> None:
        by_ticker = {item["ticker"]: item for item in self.result["rankings"]}
        self.assertEqual("long_research_candidate", by_ticker["POS"]["direction"])
        self.assertEqual("short_research_candidate", by_ticker["NEG"]["direction"])
        self.assertEqual("wait_for_proof", by_ticker["POS"]["status"])
        self.assertEqual("wait_for_proof", by_ticker["NEG"]["status"])
        self.assertEqual(
            {1, 2},
            {by_ticker["POS"]["rank"], by_ticker["NEG"]["rank"]},
        )
        self.assertIn("not a recommendation", self.result["warnings"][3])

    def test_source_lineage_and_inputs_remain_in_result(self) -> None:
        self.assertEqual("ai-supply-earnings-result.v1", self.result["format"])
        self.assertTrue(self.result["source_result"]["synthetic"])
        self.assertEqual("a" * 64, self.result["source_result"]["sha256"])
        self.assertEqual(2, len(self.result["inputs"]["companies"]))
        self.assertEqual("synthetic", self.result["evidence"][0]["kind"])


if __name__ == "__main__":
    unittest.main()
