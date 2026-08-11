from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from supply_intelligence.calibration import (
    CALIBRATION_RESULT_FORMAT,
    _event_score,
    load_calibration_dataset,
    score_calibration_dataset,
)
from supply_intelligence.manufacturing_engine import OUTPUT_UNITS


def _documents(
    root: Path,
    metric_names: list[str],
    *,
    synthetic: bool = True,
) -> tuple[Path, Path, dict[str, object]]:
    forecast = {
        "format": "ai-supply-manufacturing-result.v1",
        "scenario": {
            "id": "historical-manufacturing-fixture-2026q3",
            "quarter": "2026-Q3",
            "as_of_date": "2026-07-01",
            "recorded_at": "2026-07-01T12:00:00Z",
            "synthetic": synthetic,
        },
        "conversion_outputs": {
            name: {
                "p10": 80,
                "p50": 100,
                "p90": 120,
                "mean": 100,
                "minimum": 70,
                "maximum": 130,
            }
            for name in metric_names
        },
    }
    forecast_path = root / "forecasts" / "forecast.json"
    forecast_path.parent.mkdir(parents=True, exist_ok=True)
    forecast_path.write_text(
        json.dumps(forecast, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    forecast_sha = hashlib.sha256(forecast_path.read_bytes()).hexdigest()
    outcomes = []
    for index, name in enumerate(metric_names):
        outcomes.append(
            {
                "id": f"outcome-{index:02d}",
                "forecast_id": "forecast-2026q3",
                "metric_class": "production_output",
                "forecast_metric": name,
                "period": "2026-Q3",
                "actual_value": 110 if index == 0 else 130,
                "unit": OUTPUT_UNITS[name],
                "posture": "synthetic" if synthetic else "reported",
                "observed_at": "2026-07-19" if synthetic else "2026-10-20",
                "source_family": "synthetic-calibration-fixture",
                "evidence_ids": ["synthetic:calibration-outcomes"],
                "methodology": "Synthetic realized value for scoring-contract tests.",
                "revision_risk": "Synthetic fixture; never use as a realized market outcome.",
                "event": {
                    "operator": "at_least",
                    "threshold": 105,
                    "unit": OUTPUT_UNITS[name],
                },
            }
        )
    dataset = {
        "format": "ai-supply-calibration-dataset.v1",
        "id": "calibration-fixture",
        "as_of_date": "2026-07-19" if synthetic else "2026-10-20",
        "recorded_at": "2026-07-19T20:00:00Z"
        if synthetic
        else "2026-10-20T20:00:00Z",
        "synthetic": synthetic,
        "minimum_group_size": 10,
        "forecasts": [
            {
                "id": "forecast-2026q3",
                "path": "forecasts/forecast.json",
                "sha256": forecast_sha,
                "format": "ai-supply-manufacturing-result.v1",
                "scenario_id": "historical-manufacturing-fixture-2026q3",
            }
        ],
        "evidence": [
            {
                "id": "synthetic:calibration-outcomes",
                "kind": "synthetic" if synthetic else "company_disclosure",
                "title": "Synthetic calibration outcome fixtures",
                "source_url": "urn:synthetic:calibration-outcomes",
                "publisher": "AI Supply Intelligence",
                "published_at": None if synthetic else "2026-10-20",
                "retrieved_at": "2026-07-19T19:00:00Z"
                if synthetic
                else "2026-10-20T19:00:00Z",
                "source_family": "synthetic-calibration-fixture",
                "license": "Internal demonstration",
                "excerpt": "Not a realized production record.",
                "content_hash": None if synthetic else "0" * 64,
            }
        ],
        "outcomes": outcomes,
        "notes": "Synthetic calibration fixture.",
    }
    dataset_path = root / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return dataset_path, forecast_path, dataset


class CalibrationTests(unittest.TestCase):
    def test_degenerate_event_distribution_preserves_point_mass(self) -> None:
        score = _event_score(
            {"p10": 100, "p50": 100, "p90": 100},
            100,
            {"operator": "at_least", "threshold": 100, "unit": "package"},
        )
        self.assertEqual(1, score["forecast_probability"])
        self.assertTrue(score["realized"])
        self.assertEqual(0, score["brier_score"])

    def test_scores_coverage_bias_pinball_and_brier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics = ["finished_accelerator_packages", "complete_system_equivalents"]
            dataset_path, _, _ = _documents(root, metrics)
            case = load_calibration_dataset(dataset_path, source_root=root)
            result = score_calibration_dataset(case)
            self.assertEqual(CALIBRATION_RESULT_FORMAT, result["format"])
            self.assertEqual(2, result["summary"]["count"])
            self.assertEqual(0.5, result["summary"]["p10_p90_coverage_rate"])
            self.assertEqual(2, len(result["summary"]["units"]))
            self.assertIsNone(result["summary"]["mean_signed_error"])
            self.assertIsNone(result["summary"]["mean_absolute_error"])
            first = result["scores"][0]
            self.assertTrue(first["inside_p10_p90"])
            self.assertEqual(-10, first["signed_error"])
            self.assertAlmostEqual(-10 / 110, first["signed_error_ratio"])
            self.assertAlmostEqual(0.28125, first["event_score"]["forecast_probability"])
            self.assertTrue(first["event_score"]["realized"])
            self.assertAlmostEqual((0.28125 - 1) ** 2, first["event_score"]["brier_score"])
            self.assertEqual(
                "diagnostic_only",
                result["summary"]["calibration_proposal"]["status"],
            )
            self.assertEqual(
                "diagnostic_only",
                result["by_source_family"]["synthetic-calibration-fixture"][
                    "calibration_proposal"
                ]["status"],
            )

    def test_raw_error_aggregation_is_retained_for_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, _ = _documents(
                root, ["finished_accelerator_packages"]
            )
            result = score_calibration_dataset(
                load_calibration_dataset(dataset_path, source_root=root)
            )
            self.assertEqual(["package"], result["summary"]["units"])
            self.assertEqual(-10, result["summary"]["mean_signed_error"])
            self.assertEqual(10, result["summary"]["mean_absolute_error"])

    def test_minimum_history_emits_holdout_only_recalibration_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics = list(OUTPUT_UNITS)[:10]
            dataset_path, _, dataset = _documents(root, metrics)
            for outcome in dataset["outcomes"]:
                outcome["actual_value"] = 110
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = score_calibration_dataset(
                load_calibration_dataset(dataset_path, source_root=root)
            )
            proposal = result["by_metric_class"]["production_output"][
                "calibration_proposal"
            ]
            self.assertEqual("holdout_validation_required", proposal["status"])
            self.assertFalse(proposal["eligible_for_application"])
            self.assertAlmostEqual(1.1, proposal["p50_multiplier"])
            self.assertEqual(1.0, proposal["half_width_multiplier"])

    def test_zero_p50_group_cannot_emit_partial_recalibration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metrics = list(OUTPUT_UNITS)[:10]
            dataset_path, forecast_path, dataset = _documents(root, metrics)
            forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
            for distribution in forecast["conversion_outputs"].values():
                distribution["p10"] = 0
                distribution["p50"] = 0
                distribution["p90"] = 0
            forecast_path.write_text(
                json.dumps(forecast, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            dataset["forecasts"][0]["sha256"] = hashlib.sha256(
                forecast_path.read_bytes()
            ).hexdigest()
            for outcome in dataset["outcomes"]:
                outcome["actual_value"] = 0
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = score_calibration_dataset(
                load_calibration_dataset(dataset_path, source_root=root)
            )
            proposal = result["by_metric_class"]["production_output"][
                "calibration_proposal"
            ]
            self.assertEqual("not_estimable_zero_p50", proposal["status"])
            self.assertIsNone(proposal["p50_multiplier"])
            self.assertIsNone(proposal["half_width_multiplier"])

    def test_hash_paths_units_and_transaction_time_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, forecast_path, dataset = _documents(
                root, ["finished_accelerator_packages"]
            )
            forecast_path.write_text(
                forecast_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_calibration_dataset(dataset_path, source_root=root)

            dataset["forecasts"][0]["path"] = "../outside.json"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "below source_root"):
                load_calibration_dataset(dataset_path, source_root=root)

    def test_evidence_backed_quarter_outcome_must_follow_period_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, dataset = _documents(
                root,
                ["finished_accelerator_packages"],
                synthetic=False,
            )
            dataset["as_of_date"] = "2026-07-19"
            dataset["recorded_at"] = "2026-07-19T20:00:00Z"
            dataset["evidence"][0]["published_at"] = "2026-07-19"
            dataset["evidence"][0]["retrieved_at"] = "2026-07-19T19:00:00Z"
            dataset["outcomes"][0]["observed_at"] = "2026-07-19"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "predates quarter completion"):
                load_calibration_dataset(dataset_path, source_root=root)

    def test_forecast_precedes_outcome_and_source_family_matches_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, dataset = _documents(
                root,
                ["finished_accelerator_packages"],
            )
            dataset["outcomes"][0]["observed_at"] = "2026-07-01"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "was not frozen before outcome"):
                load_calibration_dataset(dataset_path, source_root=root)

            dataset["outcomes"][0]["observed_at"] = "2026-07-19"
            dataset["outcomes"][0]["source_family"] = "different-family"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "does not match its evidence"):
                load_calibration_dataset(dataset_path, source_root=root)

    def test_evidence_backed_outcome_rejects_modeled_posture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, dataset = _documents(
                root,
                ["finished_accelerator_packages"],
                synthetic=False,
            )
            dataset["outcomes"][0]["posture"] = "modeled"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "reported or derived"):
                load_calibration_dataset(dataset_path, source_root=root)

    def test_evidence_cannot_be_retrieved_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset_path, _, dataset = _documents(
                root,
                ["finished_accelerator_packages"],
            )
            dataset["evidence"][0]["published_at"] = "2026-07-20"
            dataset_path.write_text(
                json.dumps(dataset, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "before it was published"):
                load_calibration_dataset(dataset_path, source_root=root)


if __name__ == "__main__":
    unittest.main()
