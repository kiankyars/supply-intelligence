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
from supply_intelligence.engine import summarize
from supply_intelligence.hbm_manufacturing_link import (
    DRAW_MAPPING,
    IMPORTED_METRIC,
    TRIANGULAR_MAPPING,
    load_hbm_manufacturing_link_case,
    reconcile_hbm_manufacturing_link,
)
from supply_intelligence.hbm_manufacturing_release import (
    HBM_MANUFACTURING_COVERAGE_LINK_RELEASE_FORMAT,
    HBM_MANUFACTURING_DRAW_LINK_RELEASE_FORMAT,
    HBM_MANUFACTURING_LINK_RELEASE_FORMAT,
    HBM_MANUFACTURING_OUTPUT_DRAW_RELEASE_FORMAT,
    write_hbm_manufacturing_link_release,
)


ROOT = Path(__file__).parents[1]
MANUFACTURING = ROOT / "releases/2026-07-19-blackwell-manufacturing-wafer-format-evidence/scenario.json"
HBM_RESULT = ROOT / "releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v2/result.json"
RECIPE = ROOT / "examples/hbm-suppliers/blackwell-manufacturing-link-illustrative-2026q3.json"
DRAW_RECIPE = ROOT / "examples/hbm-suppliers/blackwell-manufacturing-draw-link-illustrative-2026q3.json"
HBM_DRAWS = ROOT / "releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/capacity_draws.csv"
COVERAGE_RECIPE = ROOT / "examples/hbm-suppliers/blackwell-manufacturing-draw-material-cleared-link-illustrative-2026q3.json"
RETICLE_MANUFACTURING = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-reticle-geometry-evidence"
    / "scenario.json"
)
RETICLE_COVERAGE_RECIPE = (
    ROOT
    / "examples"
    / "hbm-suppliers"
    / "blackwell-manufacturing-draw-material-cleared-reticle-geometry-link-illustrative-2026q3.json"
)
RETICLE_OUTPUT_DRAW_RELEASE = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws"
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_case(
    root: Path,
    *,
    manufacturing_mutator=None,
    hbm_mutator=None,
    recipe_mutator=None,
) -> tuple[Path, Path, Path]:
    manufacturing = json.loads(MANUFACTURING.read_text(encoding="utf-8"))
    hbm_result = json.loads(HBM_RESULT.read_text(encoding="utf-8"))
    recipe = json.loads(RECIPE.read_text(encoding="utf-8"))
    recipe["scenario"]["samples"] = 500
    if manufacturing_mutator:
        manufacturing_mutator(manufacturing)
    if hbm_mutator:
        hbm_mutator(hbm_result)
    manufacturing_raw = _json_bytes(manufacturing)
    hbm_raw = _json_bytes(hbm_result)
    recipe["manufacturing_scenario"]["sha256"] = hashlib.sha256(
        manufacturing_raw
    ).hexdigest()
    recipe["hbm_supplier_result"]["sha256"] = hashlib.sha256(hbm_raw).hexdigest()
    if recipe_mutator:
        recipe_mutator(recipe)
    paths = (
        root / "manufacturing.json",
        root / "hbm-result.json",
        root / "recipe.json",
    )
    paths[0].write_bytes(manufacturing_raw)
    paths[1].write_bytes(hbm_raw)
    paths[2].write_bytes(_json_bytes(recipe))
    return paths


class HbmManufacturingLinkTests(unittest.TestCase):
    def test_reticle_geometry_revision_survives_supplier_hbm_draw_link(self) -> None:
        case = load_hbm_manufacturing_link_case(
            RETICLE_MANUFACTURING,
            HBM_RESULT,
            RETICLE_COVERAGE_RECIPE,
            HBM_DRAWS,
        )
        self.assertEqual("derived", case.manufacturing.logic.wafer.wafer_diameter_mm.posture.value)
        self.assertEqual("derived", case.manufacturing.logic.wafer.die_height_mm.posture.value)
        self.assertEqual("derived", case.manufacturing.logic.wafer.die_width_mm.posture.value)
        with tempfile.TemporaryDirectory() as temporary:
            replay = write_hbm_manufacturing_link_release(
                case,
                Path(temporary) / "release",
                include_output_draws=True,
            )
        checked_manifest = json.loads(
            (RETICLE_OUTPUT_DRAW_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checked_manifest["files"], replay["files"])
        frozen = json.loads(
            (RETICLE_OUTPUT_DRAW_RELEASE / "result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            3719.1216147203795,
            frozen["conversion_outputs"]["complete_system_equivalents"]["p50"],
        )

    def test_output_draw_release_reproduces_result_and_is_replay_safe(self) -> None:
        case = load_hbm_manufacturing_link_case(
            MANUFACTURING,
            HBM_RESULT,
            COVERAGE_RECIPE,
            HBM_DRAWS,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            first = write_hbm_manufacturing_link_release(
                case,
                destination,
                include_output_draws=True,
            )
            self.assertEqual(
                HBM_MANUFACTURING_OUTPUT_DRAW_RELEASE_FORMAT,
                first["format"],
            )
            self.assertEqual(20000, first["manufacturing_draw_count"])
            with (destination / "manufacturing_draws.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(20000, len(rows))
            self.assertEqual(
                list(rows[0]),
                first["manufacturing_draw_fields"],
            )
            result = json.loads(
                (destination / "result.json").read_text(encoding="utf-8")
            )
            for field in (
                "finished_accelerator_packages",
                "complete_system_equivalents",
            ):
                reproduced = summarize(
                    [float(row[field]) for row in rows]
                ).as_dict()
                self.assertEqual(
                    result["conversion_outputs"][field],
                    reproduced,
                )
            replay = write_hbm_manufacturing_link_release(
                case,
                destination,
                include_output_draws=True,
            )
            self.assertEqual(first["files"], replay["files"])
            (destination / "manufacturing_draws.csv").write_text(
                "drift\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_hbm_manufacturing_link_release(
                    case,
                    destination,
                    include_output_draws=True,
                )

    def test_material_cleared_scope_is_explicit_and_release_versioned(self) -> None:
        case = load_hbm_manufacturing_link_case(
            MANUFACTURING,
            HBM_RESULT,
            COVERAGE_RECIPE,
            HBM_DRAWS,
        )
        result = reconcile_hbm_manufacturing_link(case)
        coverage = result["coverage"]["package_assembly_starts"]
        self.assertEqual("material_cleared_starts", coverage["assembly_start_basis"])
        self.assertEqual(
            {"silicon_interposer", "abf_substrate"},
            set(coverage["absorbed_resource_kinds"]),
        )
        self.assertEqual("synthetic", coverage["posture"])
        with tempfile.TemporaryDirectory() as temporary:
            metadata = write_hbm_manufacturing_link_release(
                case,
                Path(temporary) / "release",
            )
        self.assertEqual(
            HBM_MANUFACTURING_COVERAGE_LINK_RELEASE_FORMAT,
            metadata["format"],
        )
        output = StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "validate-hbm-manufacturing-link",
                    "--manufacturing-scenario",
                    str(MANUFACTURING),
                    "--hbm-result",
                    str(HBM_RESULT),
                    "--hbm-capacity-draws",
                    str(HBM_DRAWS),
                    "--link-recipe",
                    str(COVERAGE_RECIPE),
                ]
            )
        validation = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertEqual(
            "material_cleared_starts",
            validation["package_assembly_start_basis"],
        )
        self.assertEqual(
            ["silicon_interposer", "abf_substrate"],
            validation["absorbed_resource_kinds"],
        )

    def test_draw_link_preserves_source_tails_and_supplier_conservation(self) -> None:
        case = load_hbm_manufacturing_link_case(
            MANUFACTURING,
            HBM_RESULT,
            DRAW_RECIPE,
            HBM_DRAWS,
        )
        result = reconcile_hbm_manufacturing_link(case)
        self.assertEqual(DRAW_MAPPING, result["methodology"]["distribution_mapping"])
        self.assertEqual(
            case.hbm_result["totals"]["customer_allocated_stacks"],
            result["conversion_outputs"]["hbm_good_stacks"],
        )
        self.assertEqual(20000, len(case.capacity_draws))
        self.assertEqual(
            hashlib.sha256(HBM_DRAWS.read_bytes()).hexdigest(),
            case.capacity_draws_sha256,
        )
        self.assertIn("within-draw supplier allocation", " ".join(result["warnings"]))

    def test_draw_link_release_pins_exact_capacity_bytes(self) -> None:
        case = load_hbm_manufacturing_link_case(
            MANUFACTURING,
            HBM_RESULT,
            DRAW_RECIPE,
            HBM_DRAWS,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_hbm_manufacturing_link_release(case, destination)
            self.assertEqual(
                HBM_MANUFACTURING_DRAW_LINK_RELEASE_FORMAT,
                metadata["format"],
            )
            self.assertEqual(20000, metadata["capacity_draw_count"])
            self.assertEqual(
                HBM_DRAWS.read_bytes(),
                (destination / "hbm_supplier_capacity_draws.csv").read_bytes(),
            )

    def test_draw_link_rejects_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            drifted = Path(temporary) / "draws.csv"
            drifted.write_bytes(HBM_DRAWS.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "capacity draws SHA-256"):
                load_hbm_manufacturing_link_case(
                    MANUFACTURING,
                    HBM_RESULT,
                    DRAW_RECIPE,
                    drifted,
                )

    def test_link_removes_aggregate_hbm_and_conserves_branch_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = load_hbm_manufacturing_link_case(
                *_write_case(Path(temporary))
            )
        result = reconcile_hbm_manufacturing_link(case)
        self.assertNotIn("wafer", result["inputs"]["hbm"])
        self.assertEqual(
            "hbm3e-memory-wafer",
            result["lineage"]["replacement"][
                "removed_aggregate_hbm_wafer_flow_id"
            ],
        )
        self.assertEqual(
            IMPORTED_METRIC,
            result["lineage"]["replacement"]["imported_metric"],
        )
        imported = case.imported_distribution
        allocated = result["conversion_outputs"]["hbm_good_stacks"]
        self.assertGreaterEqual(allocated["minimum"], imported["p10"])
        self.assertLessEqual(allocated["maximum"], imported["p90"])
        attempts = result["conversion_outputs"]["package_attempts"]
        for branch in (
            "logic_package_equivalents",
            "hbm_package_equivalents",
            "package_assembly_start_capacity",
        ):
            self.assertLessEqual(attempts["p50"], result["conversion_outputs"][branch]["p90"])
        self.assertAlmostEqual(
            1.0,
            sum(item["probability"] for item in result["bottlenecks"]),
        )

    def test_topology_mismatch_is_rejected(self) -> None:
        def mutate(result: dict) -> None:
            estimate = result["platform"]["stack_capacity_gb"]
            estimate["low"] = estimate["base"] = estimate["high"] = 25

        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_case(Path(temporary), hbm_mutator=mutate)
            with self.assertRaisesRegex(ValueError, "topology mismatch"):
                load_hbm_manufacturing_link_case(*paths)

    def test_overlapping_supplier_scope_is_rejected(self) -> None:
        def mutate(result: dict) -> None:
            result["suppliers"][1]["capacity_scope_id"] = result["suppliers"][0][
                "capacity_scope_id"
            ]

        with tempfile.TemporaryDirectory() as temporary:
            paths = _write_case(Path(temporary), hbm_mutator=mutate)
            with self.assertRaisesRegex(ValueError, "overlapping capacity scopes"):
                load_hbm_manufacturing_link_case(*paths)

    def test_hash_time_and_mapping_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _write_case(root)
            recipe = json.loads(paths[2].read_text(encoding="utf-8"))
            recipe["hbm_supplier_result"]["sha256"] = "0" * 64
            paths[2].write_bytes(_json_bytes(recipe))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_hbm_manufacturing_link_case(*paths)

            paths = _write_case(
                root,
                recipe_mutator=lambda value: value["scenario"].__setitem__(
                    "recorded_at",
                    "2026-07-19T23:00:00Z",
                ),
            )
            with self.assertRaisesRegex(ValueError, "must follow HBM supplier"):
                load_hbm_manufacturing_link_case(*paths)

            paths = _write_case(
                root,
                recipe_mutator=lambda value: value["mapping"].__setitem__(
                    "distribution_mapping",
                    "independent_normal",
                ),
            )
            with self.assertRaisesRegex(ValueError, TRIANGULAR_MAPPING):
                load_hbm_manufacturing_link_case(*paths)

    def test_release_and_cli_are_replay_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _write_case(root)
            case = load_hbm_manufacturing_link_case(*paths)
            destination = root / "release"
            metadata = write_hbm_manufacturing_link_release(case, destination)
            self.assertEqual(HBM_MANUFACTURING_LINK_RELEASE_FORMAT, metadata["format"])
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            replay = write_hbm_manufacturing_link_release(case, destination)
            self.assertEqual(metadata["scenario_id"], replay["scenario_id"])
            self.assertEqual(
                paths[0].read_bytes(),
                (destination / "manufacturing_scenario.json").read_bytes(),
            )
            self.assertEqual(
                paths[1].read_bytes(),
                (destination / "hbm_supplier_result.json").read_bytes(),
            )
            self.assertEqual(
                paths[2].read_bytes(),
                (destination / "link_recipe.json").read_bytes(),
            )

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-hbm-manufacturing-link",
                        "--manufacturing-scenario",
                        str(paths[0]),
                        "--hbm-result",
                        str(paths[1]),
                        "--link-recipe",
                        str(paths[2]),
                    ]
                )
            self.assertEqual(0, status)
            self.assertTrue(json.loads(output.getvalue())["valid"])

            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_hbm_manufacturing_link_release(case, destination)

    def test_checked_recipe_pins_frozen_sources(self) -> None:
        case = load_hbm_manufacturing_link_case(MANUFACTURING, HBM_RESULT, RECIPE)
        self.assertEqual(
            hashlib.sha256(MANUFACTURING.read_bytes()).hexdigest(),
            case.manufacturing_sha256,
        )
        self.assertEqual(
            hashlib.sha256(HBM_RESULT.read_bytes()).hexdigest(),
            case.hbm_result_sha256,
        )
        self.assertEqual(
            TRIANGULAR_MAPPING,
            case.lineage["replacement"]["distribution_mapping"],
        )


if __name__ == "__main__":
    unittest.main()
