from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.guidance_backtest import (
    GUIDANCE_BACKTEST_RESULT_FORMAT,
    load_guidance_backtest,
    score_guidance_backtest,
)
from supply_intelligence.guidance_backtest_release import (
    GUIDANCE_BACKTEST_RELEASE_FORMAT,
    write_guidance_backtest_release,
)
from supply_intelligence.guidance_backtest_report import (
    render_guidance_backtest_dashboard,
)


def _write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(
    metric_id: str,
    *,
    label: str,
    basis: str,
    low: float,
    midpoint: float,
    high: float,
    unit: str,
    semantics: str = "management_range",
) -> dict[str, object]:
    return {
        "basis": basis,
        "high": high,
        "id": metric_id,
        "label": label,
        "low": low,
        "methodology": "Record the company guidance without changing its stated range semantics.",
        "metric_class": "supplier-financial",
        "midpoint": midpoint,
        "range_semantics": semantics,
        "unit": unit,
    }


def _case_documents(root: Path) -> tuple[Path, dict[str, object]]:
    entity = {"id": "memory-company", "name": "Memory Company", "ticker": "MEM"}
    period = {"end": "2026-05-28", "label": "FY2026-Q3", "start": "2026-02-27"}
    guidance = _write_json(
        root / "guidance.json",
        {
            "captured_at": "2026-07-19T21:00:00Z",
            "entity": entity,
            "format": "ai-supply-reported-guidance-observation.v1",
            "limitations": [
                "Management guidance is an external range, not a native probabilistic model forecast."
            ],
            "metrics": [
                _metric(
                    "revenue",
                    label="Revenue",
                    basis="GAAP and non-GAAP",
                    low=32.75,
                    midpoint=33.5,
                    high=34.25,
                    unit="USD billion",
                ),
                _metric(
                    "gross-margin",
                    label="Gross margin",
                    basis="GAAP",
                    low=0.81,
                    midpoint=0.81,
                    high=0.81,
                    unit="ratio",
                    semantics="approximate_point",
                ),
            ],
            "observation_id": "memory-company-fy2026q3-guidance",
            "period": period,
            "source": {
                "excerpt": "The company reported a revenue range and an approximate gross-margin outlook.",
                "license": "Company website terms",
                "published_at": "2026-03-18",
                "publisher": "Memory Company",
                "retrieved_at": "2026-07-19T20:45:00Z",
                "source_family": "memory-company-results",
                "source_url": "https://example.com/guidance",
            },
        },
    )
    outcome = _write_json(
        root / "outcome.json",
        {
            "captured_at": "2026-07-19T21:00:00Z",
            "entity": entity,
            "format": "ai-supply-reported-outcome-observation.v1",
            "limitations": [
                "The reported result may be revised in a later regulatory filing."
            ],
            "metrics": [
                {
                    "basis": "GAAP and non-GAAP",
                    "id": "revenue",
                    "label": "Revenue",
                    "methodology": "Record reported quarterly revenue.",
                    "metric_class": "supplier-financial",
                    "revision_risk": "Unaudited quarterly value; monitor later filings.",
                    "unit": "USD billion",
                    "value": 41.456,
                },
                {
                    "basis": "GAAP",
                    "id": "gross-margin",
                    "label": "Gross margin",
                    "methodology": "Record reported GAAP gross margin.",
                    "metric_class": "supplier-financial",
                    "revision_risk": "Unaudited quarterly value; monitor later filings.",
                    "unit": "ratio",
                    "value": 0.846,
                },
            ],
            "observation_id": "memory-company-fy2026q3-outcome",
            "period": period,
            "source": {
                "excerpt": "The company reported revenue and gross margin after the quarter ended.",
                "license": "Company website terms",
                "published_at": "2026-06-24",
                "publisher": "Memory Company",
                "retrieved_at": "2026-07-19T20:45:00Z",
                "source_family": "memory-company-results",
                "source_url": "https://example.com/outcome",
            },
        },
    )
    case_document = {
        "as_of_date": "2026-07-19",
        "entity": entity,
        "format": "ai-supply-guidance-backtest-case.v1",
        "guidance_observation": {"path": guidance.name, "sha256": _sha(guidance)},
        "id": "memory-company-fy2026q3-guidance-backtest",
        "metric_ids": ["revenue", "gross-margin"],
        "notes": "Test fixture for an external reported-guidance benchmark.",
        "outcome_observation": {"path": outcome.name, "sha256": _sha(outcome)},
        "period": period,
        "recorded_at": "2026-07-19T21:15:00Z",
    }
    return _write_json(root / "case.json", case_document), case_document


class GuidanceBacktestTests(unittest.TestCase):
    def test_scores_external_guidance_without_probability_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_path, _ = _case_documents(root)
            case = load_guidance_backtest(case_path, source_root=root)
            result = score_guidance_backtest(case)
            self.assertEqual(GUIDANCE_BACKTEST_RESULT_FORMAT, result["format"])
            self.assertFalse(result["benchmark"]["native_model_forecast"])
            self.assertFalse(result["benchmark"]["eligible_for_model_calibration"])
            self.assertEqual(2, result["summary"]["metric_count"])
            self.assertEqual(0, result["summary"]["inside_guidance_range_count"])
            self.assertEqual(2, result["summary"]["above_range_count"])
            revenue = next(item for item in result["scores"] if item["id"] == "revenue")
            self.assertAlmostEqual(-7.956, revenue["signed_error"])
            self.assertEqual("above_range", revenue["surprise_direction"])
            self.assertAlmostEqual(
                41.456 / 33.5,
                revenue["actual_to_guidance_midpoint_ratio"],
            )
            dashboard = render_guidance_backtest_dashboard(result)
            self.assertIn("23.7%", dashboard)
            self.assertNotIn("pinball", result["methodology"])

    def test_release_is_hash_complete_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_path, _ = _case_documents(root)
            case = load_guidance_backtest(case_path, source_root=root)
            destination = root / "release"
            metadata = write_guidance_backtest_release(case, destination)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(GUIDANCE_BACKTEST_RELEASE_FORMAT, manifest["format"])
            self.assertFalse(metadata["native_model_forecast"])
            for required in (
                "dashboard.html",
                "result.json",
                "scores.csv",
                "evidence.csv",
                "case.json",
                "sources/guidance-observation.json",
                "sources/outcome-observation.json",
            ):
                self.assertIn(required, manifest["files"])
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            replay = write_guidance_backtest_release(case, destination)
            self.assertEqual(metadata["case_id"], replay["case_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_guidance_backtest_release(case, destination)

    def test_hash_time_and_metric_guards_reject_invalid_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_path, case_document = _case_documents(root)
            drifted = json.loads(json.dumps(case_document))
            drifted["guidance_observation"]["sha256"] = "0" * 64
            drifted_path = _write_json(root / "drifted.json", drifted)
            with self.assertRaisesRegex(ValueError, "guidance_observation SHA-256 mismatch"):
                load_guidance_backtest(drifted_path, source_root=root)

            guidance = json.loads((root / "guidance.json").read_text(encoding="utf-8"))
            guidance["source"]["published_at"] = "2026-05-28"
            _write_json(root / "guidance.json", guidance)
            late = json.loads(json.dumps(case_document))
            late["guidance_observation"]["sha256"] = _sha(root / "guidance.json")
            late_path = _write_json(root / "late.json", late)
            with self.assertRaisesRegex(ValueError, "guidance must be published before"):
                load_guidance_backtest(late_path, source_root=root)

            guidance["source"]["published_at"] = "2026-03-18"
            guidance["metrics"][0]["basis"] = "non-GAAP"
            _write_json(root / "guidance.json", guidance)
            mismatch = json.loads(json.dumps(case_document))
            mismatch["guidance_observation"]["sha256"] = _sha(root / "guidance.json")
            mismatch_path = _write_json(root / "mismatch.json", mismatch)
            with self.assertRaisesRegex(ValueError, "metric revenue basis does not match"):
                load_guidance_backtest(mismatch_path, source_root=root)

    def test_validate_and_build_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case_path, _ = _case_documents(root)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-guidance-backtest",
                        "--case",
                        str(case_path),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertTrue(validation["valid"])
            self.assertEqual(2, validation["metric_count"])
            self.assertFalse(validation["eligible_for_model_calibration"])

            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-guidance-backtest",
                        "--case",
                        str(case_path),
                        "--source-root",
                        str(root),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            release = json.loads(output.getvalue())
            self.assertEqual(GUIDANCE_BACKTEST_RELEASE_FORMAT, release["format"])
            self.assertTrue((destination / "scores.csv").is_file())


if __name__ == "__main__":
    unittest.main()
