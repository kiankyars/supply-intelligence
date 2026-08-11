from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.earnings_loader import load_earnings_case
from supply_intelligence.earnings_release import (
    EARNINGS_RELEASE_FORMAT,
    write_earnings_release,
)

from tests.earnings_helpers import earnings_documents


ROOT = Path(__file__).resolve().parents[1]
CHECKED_SCENARIO = (
    ROOT / "examples" / "blackwell-supplier-earnings-illustrative-2026q3.json"
)
CHECKED_SOURCE = (
    ROOT
    / "releases"
    / "2026-07-17-blackwell-manufacturing-illustrative"
    / "result.json"
)
CHECKED_RELEASE = (
    ROOT / "releases" / "2026-07-19-blackwell-supplier-earnings-illustrative"
)


class EarningsReleaseTests(unittest.TestCase):
    def test_checked_release_has_both_research_directions_but_no_actionable_rows(self) -> None:
        case = load_earnings_case(CHECKED_SCENARIO, CHECKED_SOURCE)
        self.assertEqual(3, len(case.scenario.companies))
        self.assertTrue(case.scenario.synthetic)
        result = json.loads((CHECKED_RELEASE / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"long_research_candidate", "short_research_candidate"},
            {item["direction"] for item in result["rankings"]},
        )
        self.assertEqual(
            {"wait_for_proof"},
            {item["status"] for item in result["rankings"]},
        )
        self.assertEqual("MU", result["rankings"][0]["ticker"])
        self.assertEqual(
            "short_research_candidate",
            result["rankings"][0]["direction"],
        )
        manifest = json.loads(
            (CHECKED_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            hashlib.sha256(CHECKED_SOURCE.read_bytes()).hexdigest(),
            manifest["source_result_sha256"],
        )
        for name, expected in manifest["files"].items():
            raw = (CHECKED_RELEASE / name).read_bytes()
            self.assertEqual(expected["bytes"], len(raw))
            self.assertEqual(expected["sha256"], hashlib.sha256(raw).hexdigest())

    def test_release_hashes_every_audit_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_path, source_path, _ = earnings_documents(root)
            case = load_earnings_case(scenario_path, source_path)
            destination = root / "release"
            metadata = write_earnings_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(EARNINGS_RELEASE_FORMAT, manifest["format"])
            self.assertTrue(metadata["synthetic"])
            for required in (
                "dashboard.html",
                "result.json",
                "company_summary.csv",
                "line_items.csv",
                "named_cases.csv",
                "rankings.csv",
                "input_estimates.csv",
                "evidence.csv",
                "scenario.json",
                "source_result.json",
            ):
                self.assertIn(required, manifest["files"])
            for name, expected in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(raw))
                self.assertEqual(expected["sha256"], hashlib.sha256(raw).hexdigest())

            with (destination / "company_summary.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                self.assertEqual(2, len(list(csv.DictReader(stream))))
            with (destination / "named_cases.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                self.assertEqual(6, len(list(csv.DictReader(stream))))
            with (destination / "input_estimates.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                self.assertEqual(48, len(list(csv.DictReader(stream))))
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Physical output now reaches revenue", dashboard)
            self.assertIn("Long / short research queue", dashboard)
            self.assertIn("wait_for_proof", dashboard)
            self.assertIn("First rejection", dashboard)

            replay = write_earnings_release(case, destination)
            self.assertEqual(metadata["scenario_id"], replay["scenario_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_earnings_release(case, destination)

    def test_validate_and_reconcile_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scenario_path, source_path, _ = earnings_documents(root)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-earnings",
                        "--source-result",
                        str(source_path),
                        "--scenario",
                        str(scenario_path),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertEqual(2, validation["companies"])
            self.assertEqual(2, validation["line_items"])
            self.assertTrue(validation["source_synthetic"])

            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "reconcile-earnings",
                        "--source-result",
                        str(source_path),
                        "--scenario",
                        str(scenario_path),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            release = json.loads(output.getvalue())
            self.assertEqual(EARNINGS_RELEASE_FORMAT, release["format"])
            self.assertTrue((destination / "rankings.csv").is_file())


if __name__ == "__main__":
    unittest.main()
