from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.forecast_outcome_review import (
    FORECAST_OUTCOME_REVIEW_RESULT_FORMAT,
    build_forecast_outcome_review_result,
    load_forecast_outcome_review,
)
from supply_intelligence.forecast_outcome_review_release import (
    FORECAST_OUTCOME_REVIEW_RELEASE_FORMAT,
    write_forecast_outcome_review_release,
)
from supply_intelligence.forecast_registry import load_forecast_registry
from supply_intelligence.forecast_registry_release import write_forecast_registry_release
from supply_intelligence.release import _json

from tests.test_forecast_registry import _write_fixture


ROOT = Path(__file__).resolve().parents[1]
CHECKED_REVIEW = (
    ROOT
    / "examples"
    / "calibration"
    / "blackwell-linked-chain-outcome-review-preperiod-2026q3.json"
)
CHECKED_RELEASE = (
    ROOT
    / "releases"
    / "forecast-outcome-reviews"
    / "2026-07-19-blackwell-linked-chain-preperiod"
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_review_fixture(
    root: Path,
    *,
    status: str = "pending",
) -> tuple[Path, Path]:
    status_id = status.replace("_", "-")
    registry_path, _ = _write_fixture(root)
    registry_case = load_forecast_registry(registry_path, source_root=root)
    registry_release = root / "registry-release"
    write_forecast_registry_release(registry_case, registry_release)
    manifest_raw = (registry_release / "manifest.json").read_bytes()
    result_raw = (registry_release / "result.json").read_bytes()
    source_registry_raw = (registry_release / "registry.json").read_bytes()
    future = status != "pending"
    review = {
        "format": "ai-supply-forecast-outcome-review.v1",
        "id": f"test-{status_id}-outcome-review",
        "as_of_date": "2027-01-02" if status == "unobservable" else (
            "2026-10-15" if future else "2026-07-19"
        ),
        "recorded_at": "2027-01-03T00:00:00Z" if status == "unobservable" else (
            "2026-10-16T00:00:00Z" if future else "2026-07-20T06:20:00Z"
        ),
        "registry_release": {
            "path": "registry-release",
            "manifest_sha256": _sha(manifest_raw),
            "manifest_format": "ai-supply-forecast-registry-release.v1",
            "result_file": "result.json",
            "result_sha256": _sha(result_raw),
            "result_format": "ai-supply-forecast-registry-result.v1",
            "registry_file": "registry.json",
            "registry_sha256": _sha(source_registry_raw),
            "registry_id": "native-test-vintage-2026q3",
        },
        "evidence": [],
        "dispositions": [
            {
                "id": f"test-{status_id}-disposition",
                "forecast_id": "test-operational-systems-2026q3",
                "status": status,
                "reviewer": "test-reviewer",
                "reviewed_at": (
                    "2027-01-02T12:00:00Z"
                    if status == "unobservable"
                    else (
                        "2026-10-15T12:00:00Z"
                        if future
                        else "2026-07-20T06:15:00Z"
                    )
                ),
                "rationale": "Test disposition rationale.",
            }
        ],
        "notes": "Test complete outcome review.",
    }
    if status in {"observed", "not_comparable"}:
        evidence_path = root / "outcome-source.txt"
        evidence_raw = b"Three and a half accepted systems at the test site.\n"
        evidence_path.write_bytes(evidence_raw)
        review["evidence"] = [
            {
                "id": "test-outcome-source",
                "path": "outcome-source.txt",
                "sha256": _sha(evidence_raw),
                "kind": "official_record",
                "title": "Test outcome source",
                "source_url": "https://example.invalid/test-outcome",
                "publisher": "Test operator",
                "published_at": "2026-10-05",
                "retrieved_at": "2026-10-06T00:00:00Z",
                "source_family": "test-operator",
                "license": None,
                "excerpt": "Three and a half accepted systems.",
            }
        ]
    disposition = review["dispositions"][0]
    if status == "observed":
        disposition.update(
            {
                "actual_value": 3.5,
                "unit": "rack-scale system",
                "posture": "reported",
                "observed_at": "2026-10-05",
                "source_family": "test-operator",
                "evidence_ids": ["test-outcome-source"],
                "methodology": "Use the directly reported accepted-system count.",
                "revision_risk": "The operator may revise acceptance records.",
            }
        )
    elif status == "not_comparable":
        disposition.update(
            {
                "evidence_ids": ["test-outcome-source"],
                "candidate_description": "The source covers another geography.",
                "mismatch_dimensions": ["geography"],
            }
        )
    elif status == "unobservable":
        disposition.update(
            {
                "reason_code": "no_public_disclosure",
                "search_summary": "No scope-matched source was published by the expected date.",
            }
        )
    review_path = root / "review.json"
    review_path.write_text(_json(review), encoding="utf-8")
    return review_path, registry_release


def _mutate(path: Path, transform) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    transform(document)
    path.write_text(_json(document), encoding="utf-8")


class ForecastOutcomeReviewTests(unittest.TestCase):
    def test_checked_preperiod_review_is_complete_unscored_and_hash_valid(self) -> None:
        case = load_forecast_outcome_review(CHECKED_REVIEW, source_root=ROOT)
        result = json.loads((CHECKED_RELEASE / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(5, len(case["dispositions"]))
        self.assertEqual({"pending": 5}, result["summary"]["disposition_status_counts"])
        self.assertEqual(0, result["summary"]["score_count"])
        self.assertIsNone(result["summary"]["interval_coverage_rate"])
        manifest = json.loads(
            (CHECKED_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(_sha(CHECKED_REVIEW.read_bytes()), manifest["review_sha256"])
        for name, expected in manifest["files"].items():
            raw = (CHECKED_RELEASE / name).read_bytes()
            self.assertEqual(expected["bytes"], len(raw))
            self.assertEqual(expected["sha256"], _sha(raw))

    def test_pending_review_covers_every_forecast_without_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_path, _ = _write_review_fixture(root)
            case = load_forecast_outcome_review(review_path, source_root=root)
            result = build_forecast_outcome_review_result(case)
            self.assertEqual(FORECAST_OUTCOME_REVIEW_RESULT_FORMAT, result["format"])
            self.assertEqual(1, result["summary"]["forecast_count"])
            self.assertEqual(1, result["summary"]["disposition_count"])
            self.assertEqual({"pending": 1}, result["summary"]["disposition_status_counts"])
            self.assertEqual(0, result["summary"]["score_count"])
            self.assertIsNone(result["summary"]["interval_coverage_rate"])
            self.assertEqual(
                "pending_period_end", result["dispositions"][0]["calendar_status"]
            )

    def test_observed_outcome_scores_interval_pinball_and_exact_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_path, _ = _write_review_fixture(root, status="observed")
            case = load_forecast_outcome_review(review_path, source_root=root)
            result = build_forecast_outcome_review_result(case)
            disposition = result["dispositions"][0]
            score = disposition["score"]
            self.assertEqual(1, result["summary"]["score_count"])
            self.assertTrue(score["inside_p10_p90"])
            self.assertEqual(-1.5, score["signed_error"])
            self.assertAlmostEqual(0.4, score["event_score"]["forecast_probability"])
            self.assertTrue(score["event_score"]["realized"])
            self.assertAlmostEqual(0.36, score["event_score"]["brier_score"])
            self.assertFalse(disposition["eligible_for_evidence_backed_scoring"])
            self.assertFalse(disposition["eligible_for_model_calibration"])

    def test_mismatch_and_unobservable_rows_never_receive_scores(self) -> None:
        for status, calendar in (
            ("not_comparable", "closed_not_comparable"),
            ("unobservable", "closed_unobservable"),
        ):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                review_path, _ = _write_review_fixture(root, status=status)
                case = load_forecast_outcome_review(review_path, source_root=root)
                disposition = case["dispositions"][0]
                self.assertEqual(calendar, disposition["calendar_status"])
                self.assertIsNone(disposition["score"])

    def test_rejects_incomplete_overdue_early_and_evidence_failures(self) -> None:
        cases = (
            (
                "requires one row per forecast",
                "pending",
                lambda document: document.__setitem__("dispositions", []),
            ),
            (
                "overdue forecast requires explicit disposition",
                "pending",
                lambda document: (
                    document.__setitem__("as_of_date", "2027-01-02"),
                    document.__setitem__("recorded_at", "2027-01-03T00:00:00Z"),
                    document["dispositions"][0].__setitem__(
                        "reviewed_at", "2027-01-02T12:00:00Z"
                    ),
                ),
            ),
            (
                "cannot declare unobservable before expected evidence date",
                "unobservable",
                lambda document: (
                    document.__setitem__("as_of_date", "2026-10-15"),
                    document.__setitem__("recorded_at", "2026-10-16T00:00:00Z"),
                    document["dispositions"][0].__setitem__(
                        "reviewed_at", "2026-10-15T12:00:00Z"
                    ),
                ),
            ),
            (
                "source_family does not match",
                "observed",
                lambda document: document["dispositions"][0].__setitem__(
                    "source_family", "wrong-family"
                ),
            ),
            (
                "SHA-256 mismatch",
                "observed",
                lambda document: document["evidence"][0].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
        )
        for message, status, mutation in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                review_path, _ = _write_review_fixture(root, status=status)
                _mutate(review_path, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    load_forecast_outcome_review(review_path, source_root=root)

    def test_release_and_cli_are_replayable_hash_complete_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            review_path, registry_release = _write_review_fixture(
                root, status="observed"
            )
            case = load_forecast_outcome_review(review_path, source_root=root)
            destination = root / "release"
            metadata = write_forecast_outcome_review_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(FORECAST_OUTCOME_REVIEW_RELEASE_FORMAT, manifest["format"])
            self.assertEqual(1, manifest["score_count"])
            self.assertEqual(1, manifest["evidence_count"])
            for required in (
                "dashboard.html",
                "result.json",
                "dispositions.csv",
                "scores.csv",
                "review.json",
                "replay-review.json",
                "sources/registry-release/manifest.json",
                "sources/registry-release/result.json",
                "sources/registry-release/registry.json",
                "sources/evidence/test-outcome-source.txt",
                "README.md",
            ):
                self.assertIn(required, manifest["files"])
            for name, expected in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(raw))
                self.assertEqual(expected["sha256"], _sha(raw))
            self.assertEqual(
                (registry_release / "result.json").read_bytes(),
                (destination / "sources/registry-release/result.json").read_bytes(),
            )
            replay_case = load_forecast_outcome_review(
                destination / "replay-review.json", source_root=destination
            )
            self.assertEqual(
                case["dispositions"][0]["score"],
                replay_case["dispositions"][0]["score"],
            )
            replay = write_forecast_outcome_review_release(case, destination)
            self.assertEqual(metadata["review_id"], replay["review_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_forecast_outcome_review_release(case, destination)

            cli_output = StringIO()
            with redirect_stdout(cli_output):
                status_code = main(
                    [
                        "validate-forecast-outcome-review",
                        "--review",
                        str(review_path),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status_code)
            self.assertEqual(1, json.loads(cli_output.getvalue())["scores"])


if __name__ == "__main__":
    unittest.main()
