from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.portfolio_loader import load_portfolio
from supply_intelligence.portfolio_release import write_portfolio_release


PORTFOLIO_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "gb200-gb300-shared-illustrative-2026q3.json"
)


class PortfolioLoaderReleaseTests(unittest.TestCase):
    def test_checked_portfolio_separates_product_bom_from_synthetic_pools(self) -> None:
        portfolio = load_portfolio(PORTFOLIO_PATH)
        self.assertTrue(portfolio.synthetic)
        self.assertEqual(len(portfolio.platforms), 2)
        self.assertEqual(len(portfolio.resource_pools), 13)
        self.assertEqual(len(portfolio.requirements), 26)
        self.assertTrue(
            all(
                resource.capacity.posture.value == "synthetic"
                for resource in portfolio.resource_pools
            )
        )
        gb300 = next(
            item
            for item in portfolio.platforms
            if item.platform.id == "nvidia-gb300-nvl72"
        )
        self.assertIn(
            "nvidia:gb300-product",
            gb300.platform.accelerator_packages_per_system.evidence_ids,
        )

    def test_release_is_auditable_and_hashes_match(self) -> None:
        portfolio = load_portfolio(PORTFOLIO_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_portfolio_release(
                portfolio,
                destination,
                source_document=PORTFOLIO_PATH.read_text(encoding="utf-8"),
            )
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["synthetic"])
            self.assertIn("dashboard.html", manifest["files"])
            self.assertIn("portfolio.json", manifest["files"])
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(len(content), expected["bytes"])
                self.assertEqual(
                    hashlib.sha256(content).hexdigest(), expected["sha256"]
                )
            dashboard = (destination / "dashboard.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("Shared-resource allocation", dashboard)
            self.assertIn("Illustrative portfolio", dashboard)
            self.assertIn(
                "https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
                dashboard,
            )

    def test_validate_portfolio_cli_reports_scope(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = main(
                ["validate-portfolio", "--portfolio", str(PORTFOLIO_PATH)]
            )
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["valid"])
        self.assertEqual(result["platforms"], 2)
        self.assertEqual(result["resource_pools"], 13)
        self.assertEqual(result["requirements"], 26)


if __name__ == "__main__":
    unittest.main()
