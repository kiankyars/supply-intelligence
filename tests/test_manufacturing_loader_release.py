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
from supply_intelligence.manufacturing_loader import (
    load_manufacturing,
    manufacturing_from_dict,
)
from supply_intelligence.manufacturing_release import write_manufacturing_release


MANUFACTURING_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "blackwell-wafer-hbm-illustrative-2026q3.json"
)


class ManufacturingLoaderReleaseTests(unittest.TestCase):
    def test_checked_pack_separates_product_topology_from_synthetic_process(self) -> None:
        scenario = load_manufacturing(MANUFACTURING_PATH)
        self.assertTrue(scenario.synthetic)
        self.assertEqual(6, len(scenario.evidence))
        self.assertEqual("reported", scenario.package.logic_dies_per_accelerator.posture.value)
        self.assertEqual("derived", scenario.hbm.stacks_per_accelerator.posture.value)
        self.assertEqual("reported", scenario.hbm.stack_capacity_gb.posture.value)
        self.assertEqual("synthetic", scenario.logic.wafer.wafer_starts.posture.value)
        self.assertEqual("synthetic", scenario.hbm.known_good_die_yield.posture.value)
        self.assertEqual("synthetic", scenario.package.assembly_starts.posture.value)
        self.assertIn("micron:hbm3e-reference", scenario.hbm.stack_capacity_gb.evidence_ids)
        self.assertNotIn("supplier", scenario.hbm.wafer.name.lower())
        self.assertEqual(1, len(scenario.references))
        self.assertFalse(scenario.references[0].usable_as_product_capacity)
        self.assertEqual("reported", scenario.references[0].estimate.posture.value)

    def test_release_is_auditable_and_hashes_match(self) -> None:
        scenario = load_manufacturing(MANUFACTURING_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_manufacturing_release(
                scenario,
                destination,
                source_document=MANUFACTURING_PATH.read_text(encoding="utf-8"),
            )
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["synthetic"])
            self.assertEqual("ai-supply-manufacturing-release.v1", manifest["format"])
            self.assertIn("dashboard.html", manifest["files"])
            self.assertIn("scenario.json", manifest["files"])
            self.assertIn("reference_comparisons.csv", manifest["files"])
            self.assertIn("evidence_gaps.csv", manifest["files"])
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(content))
                self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())

            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Illustrative manufacturing run", dashboard)
            self.assertIn("Two upstream branches converge", dashboard)
            self.assertIn(
                "https://nvidianews.nvidia.com/news/nvidia-blackwell-platform-arrives-to-power-a-new-era-of-computing",
                dashboard,
            )
            self.assertIn("does not identify the GB200 memory supplier", dashboard)
            self.assertIn("Reported totals bound", dashboard)
            self.assertIn("4.34M", dashboard)
            self.assertIn("Source the assumptions that can move output first", dashboard)

            result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(21, len(result["research_queue"]))
            self.assertEqual("assembly_yield", result["research_queue"][0]["parameter"])
            self.assertEqual(1, result["research_queue"][0]["influence_probability"])

            with (destination / "input_estimates.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(27, len(rows))
            self.assertEqual(
                {"reported", "derived", "synthetic"},
                {row["posture"] for row in rows},
            )

            with (destination / "evidence_gaps.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                gap_rows = list(csv.DictReader(stream))
            self.assertEqual(21, len(gap_rows))
            self.assertEqual("assembly_yield", gap_rows[0]["parameter"])

    def test_validate_manufacturing_cli_reports_scope(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = main(
                ["validate-manufacturing", "--scenario", str(MANUFACTURING_PATH)]
            )
        self.assertEqual(0, status)
        result = json.loads(output.getvalue())
        self.assertTrue(result["valid"])
        self.assertEqual("blackwell-logic-wafer", result["logic_wafer_flow"])
        self.assertEqual("hbm3e-memory-wafer", result["hbm_wafer_flow"])
        self.assertEqual(1, result["external_references"])
        self.assertEqual(6, result["evidence_records"])

    def test_loader_rejects_wrong_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "ai-supply-manufacturing.v1"):
            manufacturing_from_dict({"format": "wrong"})


if __name__ == "__main__":
    unittest.main()
