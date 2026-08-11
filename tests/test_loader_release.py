from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.loader import load_scenario
from supply_intelligence.release import write_release


SCENARIO_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "gb200-nvl72-illustrative-2026q3.json"
)


class LoaderReleaseTests(unittest.TestCase):
    def test_checked_scenario_separates_reported_bom_from_synthetic_capacity(self) -> None:
        scenario = load_scenario(SCENARIO_PATH)
        self.assertTrue(scenario.synthetic)
        self.assertEqual(scenario.platform.name, "NVIDIA GB200 NVL72")
        self.assertEqual(len(scenario.constraints), 17)
        self.assertEqual(
            scenario.platform.servers_per_system.posture.value,
            "reported",
        )
        self.assertTrue(all(item.capacity.posture.value == "synthetic" for item in scenario.constraints))
        self.assertIn(
            "nvidia:dgx-gb-hardware",
            scenario.platform.servers_per_system.evidence_ids,
        )

    def test_release_is_auditable_and_hashes_match(self) -> None:
        scenario = load_scenario(SCENARIO_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_release(
                scenario,
                destination,
                source_document=SCENARIO_PATH.read_text(encoding="utf-8"),
            )
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata["synthetic"])
            self.assertIn("dashboard.html", manifest["files"])
            self.assertIn("scenario.json", manifest["files"])
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(len(content), expected["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), expected["sha256"])
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Illustrative scenario", dashboard)
            self.assertIn("What would make it investable", dashboard)
            self.assertIn("https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html", dashboard)

    def test_validate_cli_reports_scenario_scope(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = main(["validate", "--scenario", str(SCENARIO_PATH)])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["valid"])
        self.assertEqual(result["constraints"], 17)


if __name__ == "__main__":
    unittest.main()
