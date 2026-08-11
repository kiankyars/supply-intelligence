from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.engine import summarize
from supply_intelligence.forecast_registry import (
    FORECAST_REGISTRY_FORMAT,
    FORECAST_REGISTRY_RESULT_FORMAT,
    build_forecast_registry_result,
    evaluate_forecast_registry_maturity,
    load_forecast_registry,
)
from supply_intelligence.forecast_registry_release import (
    FORECAST_REGISTRY_RELEASE_FORMAT,
    write_forecast_registry_release,
)
from supply_intelligence.release import _csv, _json


ROOT = Path(__file__).resolve().parents[1]
CHECKED_REGISTRY = (
    ROOT
    / "examples"
    / "calibration"
    / "blackwell-linked-chain-native-forecast-registry-2026q3.json"
)
CHECKED_RELEASE = (
    ROOT
    / "releases"
    / "forecast-vintages"
    / "2026-07-19-blackwell-linked-chain-native-vintage-v2"
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_fixture(root: Path) -> tuple[Path, Path]:
    release = root / "source-release"
    release.mkdir(parents=True)
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    draws_raw = _csv(
        ["draw_index", "physical.systems_operational"],
        [
            {
                "draw_index": index,
                "physical.systems_operational": value,
            }
            for index, value in enumerate(values)
        ],
    ).encode("utf-8")
    result = {
        "format": "ai-supply-reconciliation.v1",
        "scenario": {
            "id": "native-test-scenario-2026q3",
            "quarter": "2026-Q3",
            "as_of_date": "2026-07-19",
            "recorded_at": "2026-07-20T06:00:00Z",
            "synthetic": True,
        },
        "physical_outputs": {
            "systems_operational": summarize(values).as_dict(),
        },
    }
    result_raw = _json(result).encode("utf-8")
    (release / "result.json").write_bytes(result_raw)
    (release / "chain_draws.csv").write_bytes(draws_raw)
    manifest = {
        "format": "ai-supply-linked-chain-release.v2",
        "scenario_id": "native-test-scenario-2026q3",
        "quarter": "2026-Q3",
        "as_of_date": "2026-07-19",
        "recorded_at": "2026-07-20T06:00:00Z",
        "synthetic": True,
        "chain_draw_count": len(values),
        "chain_draw_fields": [
            "draw_index",
            "physical.systems_operational",
        ],
        "files": {
            "result.json": {"bytes": len(result_raw), "sha256": _sha(result_raw)},
            "chain_draws.csv": {
                "bytes": len(draws_raw),
                "sha256": _sha(draws_raw),
            },
        },
    }
    manifest_raw = _json(manifest).encode("utf-8")
    (release / "manifest.json").write_bytes(manifest_raw)
    registry = {
        "format": FORECAST_REGISTRY_FORMAT,
        "id": "native-test-vintage-2026q3",
        "as_of_date": "2026-07-19",
        "recorded_at": "2026-07-20T06:10:00Z",
        "forecast_kind": "native_model",
        "source_release": {
            "path": "source-release",
            "manifest_sha256": _sha(manifest_raw),
            "manifest_format": "ai-supply-linked-chain-release.v2",
            "result_file": "result.json",
            "result_sha256": _sha(result_raw),
            "result_format": "ai-supply-reconciliation.v1",
            "draws_file": "chain_draws.csv",
            "draws_sha256": _sha(draws_raw),
            "scenario_id": "native-test-scenario-2026q3",
        },
        "forecasts": [
            {
                "id": "test-operational-systems-2026q3",
                "metric": "systems_operational",
                "metric_class": "site-operation",
                "draw_column": "physical.systems_operational",
                "period": "2026-Q3",
                "unit": "rack-scale system",
                "target": {
                    "entity": "Test site",
                    "product": "Test rack-scale system",
                    "geography": "Test geography",
                    "quantity_semantics": "commissioned systems available by quarter end",
                    "aggregation": "end-of-quarter stock",
                    "cutoff_date": "2026-09-30",
                    "scope_definition": "Count unique commissioned test systems at the target site.",
                },
                "outcome_contract": {
                    "earliest_observed_at": "2026-10-01",
                    "expected_evidence_by": "2026-12-31",
                    "revision_window_end": "2027-03-31",
                    "acceptable_postures": ["reported", "derived"],
                    "required_evidence": "A publication-dated primary commissioning record.",
                    "measurement_method": "Count unique accepted systems at the cutoff.",
                    "confirming_evidence": "A scope-matched commissioned-system count.",
                    "falsifying_evidence": "A scope-matched count outside the interval.",
                    "known_observability_gap": "The required count may not be public.",
                },
                "event": {
                    "operator": "at_least",
                    "threshold": 3,
                    "unit": "rack-scale system",
                    "rationale": "Test threshold fixed before period end.",
                },
            }
        ],
        "notes": "Test pre-outcome native vintage.",
    }
    registry_path = root / "registry.json"
    registry_path.write_text(_json(registry), encoding="utf-8")
    return registry_path, release


def _rewrite_registry(path: Path, transform) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    transform(document)
    path.write_text(_json(document), encoding="utf-8")


class ForecastRegistryTests(unittest.TestCase):
    def test_checked_native_vintage_is_pre_outcome_and_hash_complete(self) -> None:
        case = load_forecast_registry(CHECKED_REGISTRY, source_root=ROOT)
        result = json.loads((CHECKED_RELEASE / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(5, len(case["forecasts"]))
        self.assertEqual(20000, result["summary"]["raw_draw_count"])
        self.assertEqual(
            {"pending_period_end": 5},
            result["summary"]["maturity_status_counts"],
        )
        self.assertEqual(0, result["summary"]["outcomes_attached"])
        self.assertEqual(0, result["summary"]["scores_emitted"])
        self.assertTrue(result["summary"]["native_model_forecast"])
        self.assertTrue(result["summary"]["source_synthetic"])
        self.assertFalse(result["summary"]["eligible_for_model_calibration"])
        manifest = json.loads(
            (CHECKED_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(_sha(CHECKED_REGISTRY.read_bytes()), manifest["registry_sha256"])
        for name, expected in manifest["files"].items():
            raw = (CHECKED_RELEASE / name).read_bytes()
            self.assertEqual(expected["bytes"], len(raw))
            self.assertEqual(expected["sha256"], _sha(raw))

    def test_loads_pre_outcome_vintage_and_exact_draw_probability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, _ = _write_fixture(root)
            case = load_forecast_registry(registry_path, source_root=root)
            result = build_forecast_registry_result(case)

            self.assertEqual(FORECAST_REGISTRY_RESULT_FORMAT, result["format"])
            self.assertEqual(1, result["summary"]["forecast_count"])
            self.assertEqual(5, result["summary"]["raw_draw_count"])
            self.assertEqual(0, result["summary"]["outcomes_attached"])
            self.assertEqual(0, result["summary"]["scores_emitted"])
            forecast = result["forecasts"][0]
            self.assertEqual(2.0, forecast["distribution"]["p50"])
            self.assertEqual(0.4, forecast["event"]["forecast_probability"])
            self.assertEqual("pending_period_end", forecast["maturity"]["status"])
            self.assertFalse(forecast["maturity"]["eligible_to_score"])
            self.assertIn(
                "source_scenario_is_synthetic", forecast["maturity"]["blockers"]
            )
            waiting = evaluate_forecast_registry_maturity(
                case, as_of_date="2026-10-15"
            )
            self.assertEqual(
                {"awaiting_outcome": 1}, waiting["maturity_status_counts"]
            )
            self.assertFalse(waiting["forecasts"][0]["eligible_to_score"])
            overdue = evaluate_forecast_registry_maturity(
                case, as_of_date="2027-01-01"
            )
            self.assertEqual(
                {"outcome_overdue": 1}, overdue["maturity_status_counts"]
            )
            self.assertIn(
                "expected_evidence_date_passed", overdue["forecasts"][0]["blockers"]
            )

    def test_rejects_hash_time_scope_and_schema_failures(self) -> None:
        mutations = (
            (
                "manifest SHA-256 mismatch",
                lambda document: document["source_release"].__setitem__(
                    "manifest_sha256", "0" * 64
                ),
            ),
            (
                "must equal the forecast quarter end",
                lambda document: document["forecasts"][0]["target"].__setitem__(
                    "cutoff_date", "2026-09-29"
                ),
            ),
            (
                "must follow the quarter end",
                lambda document: document["forecasts"][0][
                    "outcome_contract"
                ].__setitem__("earliest_observed_at", "2026-09-30"),
            ),
            (
                "must be native_model",
                lambda document: document.__setitem__(
                    "forecast_kind", "external_guidance"
                ),
            ),
            (
                r"unexpected forecasts\[0\] fields",
                lambda document: document["forecasts"][0].__setitem__(
                    "actual_value", 4
                ),
            ),
        )
        for index, (message, mutation) in enumerate(mutations):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                registry_path, _ = _write_fixture(root)
                _rewrite_registry(registry_path, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    load_forecast_registry(registry_path, source_root=root)

    def test_rejects_semantically_drifted_summary_even_when_hashes_are_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, release = _write_fixture(root)
            drifted_draws = _csv(
                ["draw_index", "physical.systems_operational"],
                [
                    {
                        "draw_index": index,
                        "physical.systems_operational": value,
                    }
                    for index, value in enumerate([0.0, 1.0, 2.0, 3.0, 40.0])
                ],
            ).encode("utf-8")
            (release / "chain_draws.csv").write_bytes(drifted_draws)
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"]["chain_draws.csv"] = {
                "bytes": len(drifted_draws),
                "sha256": _sha(drifted_draws),
            }
            manifest_raw = _json(manifest).encode("utf-8")
            (release / "manifest.json").write_bytes(manifest_raw)

            def update_hashes(document):
                document["source_release"]["draws_sha256"] = _sha(drifted_draws)
                document["source_release"]["manifest_sha256"] = _sha(manifest_raw)

            _rewrite_registry(registry_path, update_hashes)
            with self.assertRaisesRegex(ValueError, "does not match raw draws"):
                load_forecast_registry(registry_path, source_root=root)

    def test_release_is_hash_complete_replayable_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, source_release = _write_fixture(root)
            case = load_forecast_registry(registry_path, source_root=root)
            destination = root / "release"
            metadata = write_forecast_registry_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(FORECAST_REGISTRY_RELEASE_FORMAT, manifest["format"])
            self.assertEqual(1, manifest["forecast_count"])
            self.assertEqual(0, manifest["outcome_count"])
            self.assertEqual(0, manifest["score_count"])
            for required in (
                "dashboard.html",
                "result.json",
                "forecasts.csv",
                "outcome_contracts.csv",
                "registry.json",
                "replay-registry.json",
                "sources/source-release/manifest.json",
                "sources/source-release/result.json",
                "sources/source-release/chain_draws.csv",
                "README.md",
            ):
                self.assertIn(required, manifest["files"])
            for name, expected in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(raw))
                self.assertEqual(expected["sha256"], _sha(raw))
            self.assertEqual(
                (source_release / "chain_draws.csv").read_bytes(),
                (destination / "sources/source-release/chain_draws.csv").read_bytes(),
            )
            replay_case = load_forecast_registry(
                destination / "replay-registry.json", source_root=destination
            )
            self.assertEqual(
                case["forecasts"][0]["distribution"],
                replay_case["forecasts"][0]["distribution"],
            )
            replay = write_forecast_registry_release(case, destination)
            self.assertEqual(metadata["registry_id"], replay["registry_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_forecast_registry_release(case, destination)

    def test_validate_and_build_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, _ = _write_fixture(root)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-forecast-registry",
                        "--registry",
                        str(registry_path),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertEqual(1, validation["forecasts"])
            self.assertEqual(5, validation["raw_draws"])
            self.assertEqual(0, validation["outcomes"])

            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-forecast-registry",
                        "--registry",
                        str(registry_path),
                        "--source-root",
                        str(root),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            release = json.loads(output.getvalue())
            self.assertEqual(FORECAST_REGISTRY_RELEASE_FORMAT, release["format"])
            self.assertTrue((destination / "forecasts.csv").is_file())


if __name__ == "__main__":
    unittest.main()
