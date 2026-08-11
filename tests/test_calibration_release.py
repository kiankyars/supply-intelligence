from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.calibration import load_calibration_dataset
from supply_intelligence.calibration_release import (
    CALIBRATION_RELEASE_FORMAT,
    write_calibration_release,
)
from supply_intelligence.cli import main

from tests.test_calibration import _documents


ROOT = Path(__file__).resolve().parents[1]
CHECKED_DATASET = (
    ROOT
    / "examples"
    / "calibration"
    / "blackwell-manufacturing-calibration-synthetic-2026-07-19.json"
)
CHECKED_FORECAST = (
    ROOT
    / "releases"
    / "2026-07-17-blackwell-manufacturing-illustrative"
    / "result.json"
)
CHECKED_RELEASE = (
    ROOT
    / "releases"
    / "calibration"
    / "2026-07-19-blackwell-manufacturing-synthetic-scorecard"
)


class CalibrationReleaseTests(unittest.TestCase):
    def test_checked_scorecard_is_synthetic_and_hash_complete(self) -> None:
        result = json.loads((CHECKED_RELEASE / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["dataset"]["synthetic"])
        self.assertEqual(6, result["summary"]["count"])
        self.assertAlmostEqual(2 / 3, result["summary"]["p10_p90_coverage_rate"])
        self.assertEqual(
            {"insufficient_history"},
            {
                item["calibration_proposal"]["status"]
                for item in result["by_metric_class"].values()
            },
        )
        manifest = json.loads(
            (CHECKED_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            hashlib.sha256(CHECKED_DATASET.read_bytes()).hexdigest(),
            manifest["dataset_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(CHECKED_FORECAST.read_bytes()).hexdigest(),
            manifest["files"][
                "sources/forecasts/blackwell-manufacturing-2026q3-v1.json"
            ]["sha256"],
        )
        for name, expected in manifest["files"].items():
            raw = (CHECKED_RELEASE / name).read_bytes()
            self.assertEqual(expected["bytes"], len(raw))
            self.assertEqual(expected["sha256"], hashlib.sha256(raw).hexdigest())

    def test_release_hashes_exact_inputs_and_every_audit_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, forecast_path, _ = _documents(
                root,
                ["finished_accelerator_packages", "complete_system_equivalents"],
            )
            case = load_calibration_dataset(dataset_path, source_root=root)
            destination = root / "release"
            metadata = write_calibration_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(CALIBRATION_RELEASE_FORMAT, manifest["format"])
            self.assertEqual(2, manifest["outcome_count"])
            self.assertTrue(metadata["synthetic"])
            for required in (
                "dashboard.html",
                "result.json",
                "scores.csv",
                "metric_class_summary.csv",
                "source_family_summary.csv",
                "evidence.csv",
                "dataset.json",
                "replay-dataset.json",
                "sources/forecasts/forecast-2026q3.json",
                "README.md",
            ):
                self.assertIn(required, manifest["files"])
            for name, expected in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(raw))
                self.assertEqual(expected["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(dataset_path.read_bytes(), (destination / "dataset.json").read_bytes())
            self.assertEqual(
                forecast_path.read_bytes(),
                (destination / "sources/forecasts/forecast-2026q3.json").read_bytes(),
            )
            replay_case = load_calibration_dataset(
                destination / "replay-dataset.json",
                source_root=destination,
            )
            self.assertEqual(case["dataset"]["id"], replay_case["dataset"]["id"])
            self.assertEqual(
                case["outcomes"][0]["actual_value"],
                replay_case["outcomes"][0]["actual_value"],
            )
            with (destination / "scores.csv").open(encoding="utf-8", newline="") as stream:
                self.assertEqual(2, len(list(csv.DictReader(stream))))
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Score frozen forecasts before changing their ranges", dashboard)
            self.assertIn("this checked dataset is synthetic", dashboard)
            self.assertIn("never auto-applied", dashboard)

            replay = write_calibration_release(case, destination)
            self.assertEqual(metadata["dataset_id"], replay["dataset_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_calibration_release(case, destination)

    def test_validate_and_build_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, _ = _documents(
                root,
                ["finished_accelerator_packages"],
            )
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-calibration",
                        "--dataset",
                        str(dataset_path),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertEqual(1, validation["forecast_vintages"])
            self.assertEqual(1, validation["outcomes"])
            self.assertTrue(validation["synthetic"])

            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-calibration-scorecard",
                        "--dataset",
                        str(dataset_path),
                        "--source-root",
                        str(root),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            release = json.loads(output.getvalue())
            self.assertEqual(CALIBRATION_RELEASE_FORMAT, release["format"])
            self.assertTrue((destination / "scores.csv").is_file())


if __name__ == "__main__":
    unittest.main()
