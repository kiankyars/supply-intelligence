from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.manufacturing_evidence_coverage import (
    MANUFACTURING_EVIDENCE_COVERAGE_FORMAT,
    MANUFACTURING_EVIDENCE_RELEASE_FORMAT,
    load_manufacturing_evidence_coverage,
    write_manufacturing_evidence_coverage_release,
)


ROOT = Path(__file__).resolve().parents[1]
RECIPE = (
    ROOT
    / "examples"
    / "coverage"
    / "blackwell-manufacturing-evidence-coverage-2026-07-19.json"
)


def _copy_checked_sources(destination: Path) -> tuple[Path, Path]:
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    release_relative = Path(recipe["manufacturing_release"]["path"])
    shutil.copytree(ROOT / release_relative, destination / release_relative)
    catalog_relative = Path(recipe["constraint_target_catalog"]["path"])
    catalog_target = destination / catalog_relative
    catalog_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / catalog_relative, catalog_target)
    copied: set[Path] = set()
    for case in recipe["claim_cases"]:
        for field in ("snapshot_path", "selection_path"):
            relative = Path(case[field])
            if relative in copied:
                continue
            copied.add(relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
    recipe_relative = RECIPE.relative_to(ROOT)
    recipe_target = destination / recipe_relative
    recipe_target.parent.mkdir(parents=True, exist_ok=True)
    recipe_target.write_text(
        json.dumps(recipe, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination, recipe_target


class ManufacturingEvidenceCoverageTests(unittest.TestCase):
    def test_checked_coverage_keeps_every_source_input_synthetic(self) -> None:
        case = load_manufacturing_evidence_coverage(RECIPE, source_root=ROOT)
        document = case["document"]
        self.assertEqual(MANUFACTURING_EVIDENCE_COVERAGE_FORMAT, document["format"])
        self.assertEqual(
            {
                "synthetic_inputs": 21,
                "synthetic_inputs_replaced": 0,
                "eligible_claim_candidate_inputs": 0,
                "scope_rejected_inputs": 1,
                "other_rejected_inputs": 0,
                "inputs_without_constraint_claim": 20,
                "accepted_scale_controls": 1,
                "accepted_directional_signals": 8,
                "rejected_claim_assessments": 1,
                "eligible_research_priority_share": 0.0,
            },
            document["summary"],
        )
        self.assertTrue(all(not item["source_replaced"] for item in document["inputs"]))
        target = next(
            item
            for item in document["inputs"]
            if item["input_path"] == "logic.wafer.wafer_starts"
        )
        self.assertEqual("scope_rejected_claim", target["input_status"])
        self.assertEqual(7, len(target["blocking_codes"]))
        self.assertIn("dimension_mismatch:product", target["blocking_codes"])
        self.assertIn("dimension_mismatch:period", target["blocking_codes"])

        scale_control = next(
            item
            for item in document["assessments"]
            if item["id"] == "tsmc-wafer-shipments-scale-control"
        )
        self.assertEqual("scale_control", scale_control["assessment_status"])
        self.assertFalse(scale_control["eligible_as_constraint"])
        self.assertEqual(4336000.0, scale_control["normalized_base"])
        self.assertFalse(Path(scale_control["lineage"]["snapshot_path"]).is_absolute())

    def test_cli_writes_hash_complete_release_and_exact_replay_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "coverage"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-manufacturing-evidence-coverage",
                        "--recipe",
                        str(RECIPE),
                        "--source-root",
                        str(ROOT),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            metadata = json.loads(output.getvalue())
            self.assertEqual(0, metadata["summary"]["eligible_claim_candidate_inputs"])
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(MANUFACTURING_EVIDENCE_RELEASE_FORMAT, manifest["format"])
            self.assertIn("dashboard.html", manifest["files"])
            self.assertIn(
                "sources/claim-cases/tsmc-wafer-shipments-rejected/assessment.json",
                manifest["files"],
            )
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(content))
                self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("zero replacements were applied", dashboard)
            self.assertIn("Signals stay separate from capacity", dashboard)
            self.assertIn("Scope-rejected claim", dashboard)

            replay = write_manufacturing_evidence_coverage_release(
                RECIPE,
                destination,
                source_root=ROOT,
            )
            self.assertEqual(manifest["id"], replay["id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_manufacturing_evidence_coverage_release(
                    RECIPE,
                    destination,
                    source_root=ROOT,
                )

    def test_source_release_drift_is_rejected_before_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, recipe_path = _copy_checked_sources(Path(temporary) / "source")
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            gaps = (
                root
                / recipe["manufacturing_release"]["path"]
                / "evidence_gaps.csv"
            )
            gaps.write_text(gaps.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release file drift: evidence_gaps.csv"):
                load_manufacturing_evidence_coverage(recipe_path, source_root=root)

    def test_target_catalog_blocks_a_self_authored_scope_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, recipe_path = _copy_checked_sources(Path(temporary) / "source")
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            case = recipe["claim_cases"][0]
            selection_path = root / case["selection_path"]
            selection = json.loads(selection_path.read_text(encoding="utf-8"))
            selection["target_dimensions"] = selection["expected_claim_dimensions"]
            selection_path.write_text(
                json.dumps(selection, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            case["selection_sha256"] = hashlib.sha256(
                selection_path.read_bytes()
            ).hexdigest()
            recipe_path.write_text(
                json.dumps(recipe, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "target dimensions do not match catalog"):
                load_manufacturing_evidence_coverage(recipe_path, source_root=root)

    def test_recipe_paths_hashes_and_case_identity_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, recipe_path = _copy_checked_sources(Path(temporary) / "source")
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            recipe["claim_cases"][0]["selection_path"] = "../outside.json"
            recipe_path.write_text(
                json.dumps(recipe, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "path below source_root"):
                load_manufacturing_evidence_coverage(recipe_path, source_root=root)

            second_root, recipe_path = _copy_checked_sources(
                Path(temporary) / "second-source"
            )
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            recipe["claim_cases"][1]["id"] = recipe["claim_cases"][0]["id"]
            recipe_path.write_text(
                json.dumps(recipe, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate claim case id"):
                load_manufacturing_evidence_coverage(
                    recipe_path,
                    source_root=second_root,
                )


if __name__ == "__main__":
    unittest.main()
