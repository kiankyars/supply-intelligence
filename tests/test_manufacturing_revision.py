from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from difflib import unified_diff
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.manufacturing_revision import (
    MANUFACTURING_REVISION_RESULT_FORMAT,
    load_manufacturing_revision,
    write_manufacturing_revision_release,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCENARIO = ROOT / "examples" / "blackwell-wafer-hbm-illustrative-2026q3.json"
SOURCE_RESULT = (
    ROOT
    / "releases"
    / "2026-07-17-blackwell-manufacturing-illustrative"
    / "result.json"
)
RETICLE_GEOMETRY_RECIPE = (
    ROOT
    / "examples"
    / "revisions"
    / "blackwell-reticle-geometry-2026-07-19.json"
)
RETICLE_GEOMETRY_RELEASE = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-reticle-geometry-evidence"
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


def _text_diff(expected: Path, actual: Path) -> str:
    return "".join(
        unified_diff(
            expected.read_text(encoding="utf-8").splitlines(keepends=True),
            actual.read_text(encoding="utf-8").splitlines(keepends=True),
            fromfile=str(expected),
            tofile=str(actual),
            n=1,
        )
    )


def _case_documents(root: Path) -> tuple[Path, dict[str, object]]:
    source = root / "source-scenario.json"
    source.write_bytes(SOURCE_SCENARIO.read_bytes())
    dimensions = {
        "capacity_basis": "physical_specification",
        "customer": "NVIDIA",
        "entity_scope": "product",
        "geography": "global",
        "period": "current_design",
        "process_node": "TSMC 4NP",
        "product": "NVIDIA Blackwell",
        "quantity_semantics": "point_specification",
        "stage": "logic_wafer_geometry",
    }
    evidence = {
        "byte_count": 123,
        "capture_kind": "normalized_observation",
        "content_sha256": "a" * 64,
        "evidence_role": "primary",
        "independence_group": "vendor-documentation",
        "license": "Vendor website terms",
        "media_type": "application/json",
        "published_at": "2026-03-12",
        "publisher": "Foundry and product vendors",
        "retrieved_at": "2026-07-19T19:45:00Z",
        "snapshot_id": "snapshot:test-blackwell-wafer-format",
        "source_family": "vendor-wafer-format",
        "source_url": "https://example.com/official-wafer-format",
    }
    claim = {
        "claim_key": "platform.nvidia.blackwell.logic_wafer_diameter_mm",
        "confidence": 0.98,
        "confirming_evidence": "Vendor process and wafer-format documentation remains unchanged.",
        "dimensions": dimensions,
        "evidence": [evidence],
        "falsifying_evidence": "The foundry identifies a different wafer format for 4NP.",
        "methodology": "Derive the nominal 300 mm format from product and foundry documentation.",
        "posture": "derived",
        "predicate": "nominal logic wafer diameter",
        "recorded_at": "2026-07-19T20:00:00Z",
        "revision_id": "claimrev:test-blackwell-wafer-format",
        "subject": "NVIDIA Blackwell",
        "supersedes_revision_id": None,
        "unit": "mm",
        "valid_from": "2024-03-18",
        "valid_to": None,
        "value": 300,
    }
    snapshot = _write_json(
        root / "snapshot.json",
        {
            "claim_count": 1,
            "claims": [claim],
            "format": "ai-supply-claim-snapshot.v1",
            "known_at": "2026-07-19T20:00:00Z",
            "valid_at": "2026-07-19",
        },
    )
    selection = _write_json(
        root / "selection.json",
        {
            "allowed_postures": ["derived"],
            "claim_key": claim["claim_key"],
            "conversion": {
                "multiplier": 1,
                "source_unit": "mm",
                "target_unit": "mm",
            },
            "expected_claim_dimensions": dimensions,
            "expected_known_at": "2026-07-19T20:00:00Z",
            "expected_revision_id": claim["revision_id"],
            "expected_valid_at": "2026-07-19",
            "format": "ai-supply-manufacturing-claim-selection.v1",
            "nonbinding_rationale": None,
            "snapshot_sha256": _sha(snapshot),
            "target_dimensions": dimensions,
            "target_input_path": "logic.wafer.wafer_diameter_mm",
            "usage": "constraint_input",
        },
    )
    target_catalog = _write_json(
        root / "target-catalog.json",
        {
            "format": "ai-supply-manufacturing-target-catalog.v1",
            "quarter": "2026-Q3",
            "scenario_id": "blackwell-wafer-hbm-illustrative-2026q3",
            "targets": [
                {
                    "dimensions": dimensions,
                    "input_path": "logic.wafer.wafer_diameter_mm",
                    "rationale": "The model consumes nominal Blackwell logic-wafer diameter in millimeters.",
                    "unit": "mm",
                }
            ],
        },
    )
    recipe_document = {
        "as_of_date": "2026-07-19",
        "format": "ai-supply-manufacturing-revision-recipe.v1",
        "id": "blackwell-wafer-format-test",
        "notes": "Replace only the synthetic wafer-format posture.",
        "recorded_at": "2026-07-19T20:15:00Z",
        "replacements": [
            {
                "evidence_metadata": [
                    {
                        "excerpt": "The vendor documentation identifies the 300 mm format.",
                        "kind": "company_technical_document",
                        "snapshot_id": evidence["snapshot_id"],
                        "title": "Official wafer-format documentation",
                    }
                ],
                "selection": {"path": selection.name, "sha256": _sha(selection)},
                "snapshot": {"path": snapshot.name, "sha256": _sha(snapshot)},
            }
        ],
        "source_scenario": {"path": source.name, "sha256": _sha(source)},
        "target_catalog": {
            "path": target_catalog.name,
            "sha256": _sha(target_catalog),
        },
    }
    recipe = _write_json(root / "recipe.json", recipe_document)
    return recipe, recipe_document


class ManufacturingRevisionTests(unittest.TestCase):
    def test_checked_reticle_geometry_revision_is_derived_bounded_and_replayable(self) -> None:
        case = load_manufacturing_revision(RETICLE_GEOMETRY_RECIPE, source_root=ROOT)
        result = case["revision_result"]
        self.assertEqual(2, result["replacement_count"])
        self.assertEqual(18, result["remaining_synthetic_input_count"])
        self.assertFalse(result["all_numeric_values_unchanged"])
        self.assertEqual(
            {"logic.wafer.die_height_mm", "logic.wafer.die_width_mm"},
            {item["target_input_path"] for item in result["replacements"]},
        )
        wafer = case["scenario"].logic.wafer
        self.assertEqual("derived", wafer.wafer_diameter_mm.posture.value)
        self.assertEqual("derived", wafer.die_height_mm.posture.value)
        self.assertEqual("derived", wafer.die_width_mm.posture.value)
        self.assertEqual((31.0, 32.0, 33.0), (
            wafer.die_height_mm.low,
            wafer.die_height_mm.base,
            wafer.die_height_mm.high,
        ))
        self.assertEqual((25.5, 26.0, 26.0), (
            wafer.die_width_mm.low,
            wafer.die_width_mm.base,
            wafer.die_width_mm.high,
        ))
        self.assertIn("not a reported or teardown-measured", wafer.die_height_mm.methodology)

        frozen_result = json.loads(
            (RETICLE_GEOMETRY_RELEASE / "result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            5190.675260240835,
            frozen_result["conversion_outputs"]["complete_system_equivalents"]["p50"],
        )
        self.assertEqual(
            [
                {"constraint": "logic_binned_dies", "probability": 0.6869},
                {"constraint": "package_assembly_starts", "probability": 0.3131},
            ],
            frozen_result["bottlenecks"],
        )
        checked_manifest = json.loads(
            (RETICLE_GEOMETRY_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            replay = write_manufacturing_revision_release(case, destination)
            difference = _text_diff(
                RETICLE_GEOMETRY_RELEASE / "conversion_outputs.csv",
                destination / "conversion_outputs.csv",
            )
            self.assertFalse(difference, difference)
            self.assertEqual(checked_manifest["files"], replay["files"])

    def test_replacement_preserves_values_and_builds_hash_complete_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe, _ = _case_documents(root)
            case = load_manufacturing_revision(recipe, source_root=root)
            result = case["revision_result"]
            self.assertEqual(MANUFACTURING_REVISION_RESULT_FORMAT, result["format"])
            self.assertEqual(1, result["replacement_count"])
            self.assertEqual(20, result["remaining_synthetic_input_count"])
            self.assertTrue(result["all_numeric_values_unchanged"])
            self.assertTrue(case["scenario"].synthetic)
            self.assertEqual("derived", case["scenario"].logic.wafer.wafer_diameter_mm.posture.value)
            self.assertEqual(300, case["scenario"].logic.wafer.wafer_diameter_mm.base)

            destination = root / "release"
            metadata = write_manufacturing_revision_release(case, destination)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("ai-supply-manufacturing-release.v1", manifest["format"])
            self.assertEqual(1, metadata["replacement_count"])
            for required in (
                "scenario.json",
                "result.json",
                "revision.json",
                "revision-recipe.json",
                "lineage/source-scenario.json",
                "lineage/target-catalog.json",
                "lineage/claims/000-snapshot.json",
                "lineage/claims/000-selection.json",
            ):
                self.assertIn(required, manifest["files"])
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            previous_result = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))
            current_result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(
                previous_result["conversion_outputs"],
                current_result["conversion_outputs"],
            )
            self.assertEqual(20, len(current_result["research_queue"]))

            replay = write_manufacturing_revision_release(case, destination)
            self.assertEqual(metadata["revision_id"], replay["revision_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_manufacturing_revision_release(case, destination)

    def test_hash_scope_and_time_guards_reject_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe, recipe_document = _case_documents(root)
            drifted = json.loads(json.dumps(recipe_document))
            drifted["source_scenario"]["sha256"] = "0" * 64
            drifted_path = _write_json(root / "drifted.json", drifted)
            with self.assertRaisesRegex(ValueError, "source_scenario SHA-256 mismatch"):
                load_manufacturing_revision(drifted_path, source_root=root)

            future = json.loads(json.dumps(recipe_document))
            future["recorded_at"] = "2026-07-19T19:59:59Z"
            future_path = _write_json(root / "future.json", future)
            with self.assertRaisesRegex(ValueError, "known after revision recorded_at"):
                load_manufacturing_revision(future_path, source_root=root)

            target = json.loads((root / "target-catalog.json").read_text(encoding="utf-8"))
            target["targets"][0]["dimensions"]["customer"] = "all customers"
            _write_json(root / "target-catalog.json", target)
            mismatch = json.loads(json.dumps(recipe_document))
            mismatch["target_catalog"]["sha256"] = _sha(root / "target-catalog.json")
            mismatch_path = _write_json(root / "mismatch.json", mismatch)
            with self.assertRaisesRegex(ValueError, "dimensions do not match target catalog"):
                load_manufacturing_revision(mismatch_path, source_root=root)

    def test_validate_and_build_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe, _ = _case_documents(root)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-manufacturing-revision",
                        "--recipe",
                        str(recipe),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertTrue(validation["valid"])
            self.assertEqual(1, validation["replacement_count"])
            self.assertTrue(validation["all_numeric_values_unchanged"])

            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-manufacturing-revision",
                        "--recipe",
                        str(recipe),
                        "--source-root",
                        str(root),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            release = json.loads(output.getvalue())
            self.assertEqual("blackwell-wafer-format-test", release["revision_id"])
            self.assertTrue((destination / "revision.json").is_file())


if __name__ == "__main__":
    unittest.main()
