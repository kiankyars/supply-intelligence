from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.chain_link_release import write_linked_chain_release
from supply_intelligence.chain_linker import load_linked_chain_case
from supply_intelligence.cli import main
from supply_intelligence.engine import reconcile


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "examples" / "gb200-nvl72-illustrative-2026q3.json"
RECIPE_PATH = ROOT / "examples" / "gb200-to-abilene-linked-illustrative-2026q3.json"
MANUFACTURING_PATH = (
    ROOT
    / "releases"
    / "2026-07-17-blackwell-manufacturing-illustrative"
    / "result.json"
)
OPERATIONAL_PATH = (
    ROOT
    / "releases"
    / "2026-07-17-abilene-operational-illustrative"
    / "result.json"
)
SUPPLIER_HBM_RECIPE_PATH = (
    ROOT
    / "examples"
    / "gb200-to-abilene-supplier-hbm-draw-linked-illustrative-2026q3.json"
)
SUPPLIER_HBM_MANUFACTURING_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v3-draws"
    / "result.json"
)
MATERIAL_CLEARED_RECIPE_PATH = (
    ROOT
    / "examples"
    / "gb200-to-abilene-material-cleared-supplier-hbm-linked-illustrative-2026q3.json"
)
MATERIAL_CLEARED_MANUFACTURING_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v4-material-cleared-draws"
    / "result.json"
)
ASSEMBLY_RECIPE_PATH = (
    ROOT
    / "examples"
    / "gb200-to-abilene-odm-assembly-linked-illustrative-2026q3.json"
)
ASSEMBLY_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-gb200-nvl72-odm-assembly-illustrative"
    / "result.json"
)
DRAW_LINK_RECIPE_PATH = (
    ROOT
    / "examples"
    / "gb200-to-abilene-odm-assembly-draw-linked-illustrative-2026q3.json"
)
OUTPUT_DRAW_MANUFACTURING_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v5-output-draws"
    / "result.json"
)
MANUFACTURING_DRAWS_PATH = OUTPUT_DRAW_MANUFACTURING_PATH.with_name(
    "manufacturing_draws.csv"
)
ASSEMBLY_DRAWS_PATH = ASSEMBLY_PATH.with_name("capacity_draws.csv")
OUTPUT_DRAW_OPERATIONAL_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-abilene-operational-illustrative-v2-draws"
    / "result.json"
)
OPERATIONAL_DRAWS_PATH = OUTPUT_DRAW_OPERATIONAL_PATH.with_name(
    "capacity_draws.csv"
)
RETICLE_DRAW_LINK_RECIPE_PATH = (
    ROOT
    / "examples"
    / "gb200-to-abilene-odm-assembly-draw-linked-reticle-geometry-illustrative-2026q3.json"
)
RETICLE_OUTPUT_DRAW_MANUFACTURING_PATH = (
    ROOT
    / "releases"
    / "2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws"
    / "result.json"
)
RETICLE_MANUFACTURING_DRAWS_PATH = RETICLE_OUTPUT_DRAW_MANUFACTURING_PATH.with_name(
    "manufacturing_draws.csv"
)
RETICLE_CHAIN_RELEASE = (
    ROOT
    / "releases"
    / "2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative"
)


def load_checked_case():
    return load_linked_chain_case(
        BASE_PATH,
        RECIPE_PATH,
        MANUFACTURING_PATH,
        OPERATIONAL_PATH,
    )


def load_draw_link_case(
    *,
    recipe_path: Path = DRAW_LINK_RECIPE_PATH,
    manufacturing_draws_path: Path = MANUFACTURING_DRAWS_PATH,
    assembly_draws_path: Path = ASSEMBLY_DRAWS_PATH,
    operational_draws_path: Path = OPERATIONAL_DRAWS_PATH,
):
    return load_linked_chain_case(
        BASE_PATH,
        recipe_path,
        OUTPUT_DRAW_MANUFACTURING_PATH,
        OUTPUT_DRAW_OPERATIONAL_PATH,
        ASSEMBLY_PATH,
        manufacturing_draws_path=manufacturing_draws_path,
        assembly_draws_path=assembly_draws_path,
        operational_draws_path=operational_draws_path,
    )


def _draw_column(path: Path, field: str) -> tuple[float, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(float(row[field]) for row in csv.DictReader(handle))


class ChainLinkerTests(unittest.TestCase):
    def test_reticle_geometry_revision_propagates_then_yields_to_downstream_bottlenecks(self) -> None:
        case = load_linked_chain_case(
            BASE_PATH,
            RETICLE_DRAW_LINK_RECIPE_PATH,
            RETICLE_OUTPUT_DRAW_MANUFACTURING_PATH,
            OUTPUT_DRAW_OPERATIONAL_PATH,
            ASSEMBLY_PATH,
            manufacturing_draws_path=RETICLE_MANUFACTURING_DRAWS_PATH,
            assembly_draws_path=ASSEMBLY_DRAWS_PATH,
            operational_draws_path=OPERATIONAL_DRAWS_PATH,
        )
        self.assertEqual(
            hashlib.sha256(RETICLE_OUTPUT_DRAW_MANUFACTURING_PATH.read_bytes()).hexdigest(),
            case.lineage["sources"]["manufacturing"]["sha256"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            replay = write_linked_chain_release(case, Path(temporary) / "release")
        checked_manifest = json.loads(
            (RETICLE_CHAIN_RELEASE / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checked_manifest["files"], replay["files"])

        prior = json.loads(
            (
                ROOT
                / "releases"
                / "2026-07-19-gb200-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative"
                / "result.json"
            ).read_text(encoding="utf-8")
        )
        current = json.loads(
            (RETICLE_CHAIN_RELEASE / "result.json").read_text(encoding="utf-8")
        )
        prior_package = next(
            item for item in prior["stage_outputs"] if item["stage"] == "accelerator_package"
        )["system_equivalents"]["p50"]
        current_package = next(
            item for item in current["stage_outputs"] if item["stage"] == "accelerator_package"
        )["system_equivalents"]["p50"]
        self.assertGreater(current_package, prior_package)
        self.assertEqual(
            prior["physical_outputs"]["integrated_racks"],
            current["physical_outputs"]["integrated_racks"],
        )
        self.assertEqual(
            prior["physical_outputs"]["systems_operational"],
            current["physical_outputs"]["systems_operational"],
        )

    def test_draw_link_preserves_exact_source_marginals_and_reuses_metrics(self) -> None:
        case = load_draw_link_case()
        overrides = case.constraint_capacity_draws
        manufacturing_id = (
            "linked-material-cleared-supplier-hbm-manufacturing-output"
        )
        assembly_id = "linked-component-cleared-odm-complete-racks"
        site_id = "linked-abilene-complete-rack-allocation"
        operational_id = "linked-abilene-operational-racks"

        self.assertEqual(
            sorted(_draw_column(MANUFACTURING_DRAWS_PATH, "complete_system_equivalents")),
            sorted(overrides[manufacturing_id]),
        )
        self.assertEqual(
            sorted(_draw_column(ASSEMBLY_DRAWS_PATH, "complete_racks")),
            sorted(overrides[assembly_id]),
        )
        self.assertEqual(overrides[assembly_id], overrides[site_id])
        self.assertEqual(
            sorted(_draw_column(OPERATIONAL_DRAWS_PATH, "operational_racks")),
            sorted(overrides[operational_id]),
        )

        chain_draws: list[dict[str, float]] = []
        result = reconcile(
            case.scenario,
            constraint_capacity_draws=overrides,
            output_draws=chain_draws,
        )
        assembly_field = f"constraint.{assembly_id}.system_equivalents"
        site_field = f"constraint.{site_id}.system_equivalents"
        self.assertEqual(case.scenario.samples, len(chain_draws))
        self.assertTrue(
            all(row[site_field] <= row[assembly_field] for row in chain_draws)
        )
        self.assertTrue(
            all(row[site_field] < row[assembly_field] for row in chain_draws)
        )
        self.assertEqual(
            "source_capacity_draws_deterministic_cross_source_permutation",
            case.lineage["links"][0]["distribution_mapping"],
        )
        self.assertEqual(
            sorted(overrides),
            result["methodology"]["draw_override_constraint_ids"],
        )

    def test_draw_link_rejects_capacity_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            drifted = Path(temporary) / "manufacturing_draws.csv"
            drifted.write_bytes(MANUFACTURING_DRAWS_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "manufacturing capacity-draw SHA-256"):
                load_draw_link_case(manufacturing_draws_path=drifted)

    def test_draw_link_rejects_semantic_summary_drift_after_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with ASSEMBLY_DRAWS_PATH.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
                fields = list(rows[0])
            rows[0]["complete_racks"] = str(float(rows[0]["complete_racks"]) + 1.0)
            document = io.StringIO(newline="")
            writer = csv.DictWriter(document, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            draw_raw = document.getvalue().encode("utf-8")
            draws_path = root / "assembly_draws.csv"
            draws_path.write_bytes(draw_raw)
            recipe = json.loads(DRAW_LINK_RECIPE_PATH.read_text(encoding="utf-8"))
            recipe["sources"]["system_assembly"]["capacity_draws_sha256"] = (
                hashlib.sha256(draw_raw).hexdigest()
            )
            recipe_path = root / "recipe.json"
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                r"system_assembly capacity draws do not reproduce complete_racks\.(mean|maximum)",
            ):
                load_draw_link_case(
                    recipe_path=recipe_path,
                    assembly_draws_path=draws_path,
                )

    def test_draw_link_rejects_bad_row_count_and_index_after_rehash(self) -> None:
        original = ASSEMBLY_DRAWS_PATH.read_text(encoding="utf-8")
        mutations = {
            "row count": "\n".join(original.rstrip("\n").splitlines()[:-1]) + "\n",
            "contiguous": original.replace("\n0,", "\n1,", 1),
        }
        expectations = {
            "row count": "must contain 20000 rows",
            "contiguous": "must be contiguous from zero",
        }
        for label, document in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                draws_path = root / "assembly_draws.csv"
                draws_path.write_text(document, encoding="utf-8")
                recipe = json.loads(
                    DRAW_LINK_RECIPE_PATH.read_text(encoding="utf-8")
                )
                recipe["sources"]["system_assembly"]["capacity_draws_sha256"] = (
                    hashlib.sha256(document.encode("utf-8")).hexdigest()
                )
                recipe_path = root / "recipe.json"
                recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, expectations[label]):
                    load_draw_link_case(
                        recipe_path=recipe_path,
                        assembly_draws_path=draws_path,
                    )

    def test_draw_linked_release_preserves_source_and_chain_draws_on_replay(self) -> None:
        case = load_draw_link_case()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            first = write_linked_chain_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual("ai-supply-linked-chain-release.v2", manifest["format"])
            self.assertEqual(20000, manifest["chain_draw_count"])
            self.assertEqual(
                MANUFACTURING_DRAWS_PATH.read_bytes(),
                (destination / "manufacturing_draws.csv").read_bytes(),
            )
            self.assertEqual(
                ASSEMBLY_DRAWS_PATH.read_bytes(),
                (destination / "system_assembly_draws.csv").read_bytes(),
            )
            self.assertEqual(
                OPERATIONAL_DRAWS_PATH.read_bytes(),
                (destination / "datacenter_operational_draws.csv").read_bytes(),
            )
            with (destination / "chain_draws.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(20000, len(rows))
            self.assertIn(
                "physical.systems_operational",
                manifest["chain_draw_fields"],
            )
            replay = write_linked_chain_release(case, destination)
            self.assertEqual(first["files"], replay["files"])
            (destination / "chain_draws.csv").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_linked_chain_release(case, destination)

    def test_component_cleared_assembly_replaces_only_covered_stages(self) -> None:
        case = load_linked_chain_case(
            BASE_PATH,
            ASSEMBLY_RECIPE_PATH,
            MATERIAL_CLEARED_MANUFACTURING_PATH,
            OPERATIONAL_PATH,
            ASSEMBLY_PATH,
        )
        constraint_ids = {item.id for item in case.scenario.constraints}
        for constraint_id in (
            "compute-tray-assembly",
            "connectx7-nics",
            "bluefield3-dpus",
            "nvlink-switch-trays",
            "management-tor-switches",
            "power-shelves",
            "liquid-cooling-integration",
        ):
            self.assertNotIn(constraint_id, constraint_ids)
        self.assertIn("site-installation", constraint_ids)
        self.assertIn(
            "linked-component-cleared-odm-complete-racks",
            constraint_ids,
        )
        assembly_link = case.lineage["links"][1]
        self.assertEqual(
            {
                ("rack_integration", "cooling"),
                ("rack_integration", "network_switch"),
                ("rack_integration", "power_delivery"),
                ("rack_integration", "rack_integration"),
                ("server_assembly", "network_switch"),
                ("server_assembly", "retimer"),
                ("server_assembly", "server_assembly"),
            },
            {
                (item["stage"], item["resource_kind"])
                for item in assembly_link[
                    "required_source_coverage_selectors"
                ]
            },
        )
        self.assertEqual(
            hashlib.sha256(ASSEMBLY_PATH.read_bytes()).hexdigest(),
            case.lineage["sources"]["system_assembly"]["sha256"],
        )

    def test_component_coverage_cannot_leave_a_matching_constraint(self) -> None:
        recipe = json.loads(ASSEMBLY_RECIPE_PATH.read_text(encoding="utf-8"))
        recipe["links"][1]["replace_constraint_ids"].remove("connectx7-nics")
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "recipe.json"
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prevent double counting"):
                load_linked_chain_case(
                    BASE_PATH,
                    recipe_path,
                    MATERIAL_CLEARED_MANUFACTURING_PATH,
                    OPERATIONAL_PATH,
                    ASSEMBLY_PATH,
                )

    def test_assembly_source_requires_exact_coverage_handoff(self) -> None:
        recipe = json.loads(ASSEMBLY_RECIPE_PATH.read_text(encoding="utf-8"))
        recipe["links"][1].pop("require_source_coverage_selectors")
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "recipe.json"
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires one exact"):
                load_linked_chain_case(
                    BASE_PATH,
                    recipe_path,
                    MATERIAL_CLEARED_MANUFACTURING_PATH,
                    OPERATIONAL_PATH,
                    ASSEMBLY_PATH,
                )

    def test_three_source_linked_release_preserves_assembly_bytes(self) -> None:
        case = load_linked_chain_case(
            BASE_PATH,
            ASSEMBLY_RECIPE_PATH,
            MATERIAL_CLEARED_MANUFACTURING_PATH,
            OPERATIONAL_PATH,
            ASSEMBLY_PATH,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            first = write_linked_chain_release(case, destination)
            self.assertEqual(
                ASSEMBLY_PATH.read_bytes(),
                (destination / "system_assembly_result.json").read_bytes(),
            )
            replay = write_linked_chain_release(case, destination)
            self.assertEqual(first["files"], replay["files"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_linked_chain_release(case, destination)

    def test_material_cleared_source_replaces_absorbed_constraints_once(self) -> None:
        case = load_linked_chain_case(
            BASE_PATH,
            MATERIAL_CLEARED_RECIPE_PATH,
            MATERIAL_CLEARED_MANUFACTURING_PATH,
            OPERATIONAL_PATH,
        )
        constraint_ids = {item.id for item in case.scenario.constraints}
        self.assertNotIn("silicon-interposers", constraint_ids)
        self.assertNotIn("abf-substrates", constraint_ids)
        self.assertIn(
            "linked-material-cleared-supplier-hbm-manufacturing-output",
            constraint_ids,
        )
        manufacturing_link = case.lineage["links"][0]
        self.assertEqual(
            {"silicon_interposer", "abf_substrate"},
            set(manufacturing_link["required_source_coverage"]),
        )

    def test_covered_constraint_cannot_be_left_to_double_count(self) -> None:
        recipe = json.loads(MATERIAL_CLEARED_RECIPE_PATH.read_text(encoding="utf-8"))
        recipe["links"][0]["replace_constraint_ids"].remove("abf-substrates")
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "recipe.json"
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prevent double counting"):
                load_linked_chain_case(
                    BASE_PATH,
                    recipe_path,
                    MATERIAL_CLEARED_MANUFACTURING_PATH,
                    OPERATIONAL_PATH,
                )

    def test_supplier_hbm_result_feeds_the_checked_full_chain_once(self) -> None:
        case = load_linked_chain_case(
            BASE_PATH,
            SUPPLIER_HBM_RECIPE_PATH,
            SUPPLIER_HBM_MANUFACTURING_PATH,
            OPERATIONAL_PATH,
        )
        constraint_ids = {item.id for item in case.scenario.constraints}
        self.assertIn("linked-supplier-hbm-draw-manufacturing-output", constraint_ids)
        self.assertNotIn("hbm3e-capacity", constraint_ids)
        source = case.lineage["sources"]["manufacturing"]
        self.assertEqual(
            hashlib.sha256(SUPPLIER_HBM_MANUFACTURING_PATH.read_bytes()).hexdigest(),
            source["sha256"],
        )
        self.assertIn("supplier-qualified", case.scenario.scope_notes)

    def test_checked_link_replaces_overlapping_constraints_and_clears_market_views(self) -> None:
        case = load_checked_case()
        constraint_ids = {item.id for item in case.scenario.constraints}
        self.assertEqual(15, len(constraint_ids))
        self.assertNotIn("blackwell-reticle-dies", constraint_ids)
        self.assertNotIn("blackwell-packages", constraint_ids)
        self.assertNotIn("hbm3e-capacity", constraint_ids)
        self.assertNotIn("energized-datacenter-power", constraint_ids)
        self.assertNotIn("datacenter-commissioning", constraint_ids)
        self.assertIn("linked-manufacturing-system-output", constraint_ids)
        self.assertIn("linked-abilene-shipment-allocation", constraint_ids)
        self.assertIn("linked-abilene-operational-racks", constraint_ids)
        self.assertFalse(case.scenario.allocations)
        self.assertFalse(case.scenario.supplier_economics)
        self.assertFalse(case.scenario.consensus)
        self.assertFalse(case.scenario.opportunity_factors)
        self.assertIn("Abilene-target subset", case.scenario.scope_notes)

    def test_link_preserves_source_quantiles_and_coordinates_reused_capacity(self) -> None:
        case = load_checked_case()
        constraints = {item.id: item for item in case.scenario.constraints}
        manufacturing = constraints["linked-manufacturing-system-output"]
        site_allocation = constraints["linked-abilene-shipment-allocation"]
        operational = constraints["linked-abilene-operational-racks"]
        source = json.loads(MANUFACTURING_PATH.read_text(encoding="utf-8"))
        distribution = source["conversion_outputs"]["complete_system_equivalents"]
        self.assertEqual(distribution["p10"], manufacturing.capacity.low)
        self.assertEqual(distribution["p50"], manufacturing.capacity.base)
        self.assertEqual(distribution["p90"], manufacturing.capacity.high)
        self.assertEqual(
            manufacturing.capacity.correlation_group,
            site_allocation.capacity.correlation_group,
        )
        self.assertEqual("system", manufacturing.capacity.unit)
        self.assertEqual("rack", operational.capacity.unit)
        self.assertEqual("synthetic", operational.capacity.posture.value)
        self.assertIn("does not preserve source tails", manufacturing.capacity.methodology)

    def test_link_rejects_source_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary) / "manufacturing.json"
            altered.write_bytes(MANUFACTURING_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "manufacturing result SHA-256"):
                load_linked_chain_case(
                    BASE_PATH,
                    RECIPE_PATH,
                    altered,
                    OPERATIONAL_PATH,
                )

    def test_link_rejects_platform_topology_mismatch(self) -> None:
        source = json.loads(MANUFACTURING_PATH.read_text(encoding="utf-8"))
        topology = source["topology"]["accelerators_per_system"]
        topology["low"] = topology["base"] = topology["high"] = 36
        source_text = json.dumps(source, indent=2, sort_keys=True) + "\n"
        recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
        recipe["sources"]["manufacturing"]["sha256"] = hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "manufacturing.json"
            recipe_path = root / "recipe.json"
            source_path.write_text(source_text, encoding="utf-8")
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "topology does not match"):
                load_linked_chain_case(
                    BASE_PATH,
                    recipe_path,
                    source_path,
                    OPERATIONAL_PATH,
                )

    def test_link_rejects_duplicate_constraint_replacement(self) -> None:
        recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
        recipe["links"][1]["replace_constraint_ids"] = ["blackwell-reticle-dies"]
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "recipe.json"
            recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "replaced more than once"):
                load_linked_chain_case(
                    BASE_PATH,
                    recipe_path,
                    MANUFACTURING_PATH,
                    OPERATIONAL_PATH,
                )

    def test_linked_release_is_self_contained_and_hashes_match(self) -> None:
        case = load_checked_case()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_linked_chain_release(case, destination)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["synthetic"])
            self.assertEqual("ai-supply-linked-chain-release.v1", manifest["format"])
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(content))
                self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(BASE_PATH.read_bytes(), (destination / "base_scenario.json").read_bytes())
            self.assertEqual(
                MANUFACTURING_PATH.read_bytes(),
                (destination / "manufacturing_result.json").read_bytes(),
            )
            self.assertEqual(
                OPERATIONAL_PATH.read_bytes(),
                (destination / "datacenter_operational_result.json").read_bytes(),
            )
            result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(result["customer_allocations"])
            self.assertFalse(result["supplier_estimates"])
            self.assertIn("Abilene-target subset", " ".join(result["warnings"]))
            operational = next(
                item for item in result["bottlenecks"] if item["stage"] == "operational"
            )
            identifiers = {item["constraint_id"] for item in operational["constraints"]}
            self.assertIn("linked-abilene-operational-racks", identifiers)
            self.assertIn("linked-abilene-shipment-allocation", identifiers)

    def test_validate_and_reconcile_linked_cli(self) -> None:
        arguments = [
            "--base-scenario",
            str(BASE_PATH),
            "--link-recipe",
            str(RECIPE_PATH),
            "--manufacturing-result",
            str(MANUFACTURING_PATH),
            "--operational-result",
            str(OPERATIONAL_PATH),
        ]
        output = StringIO()
        with redirect_stdout(output):
            status = main(["validate-linked-chain", *arguments])
        self.assertEqual(0, status)
        self.assertEqual(3, json.loads(output.getvalue())["links"])

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "reconcile-linked-chain",
                        *arguments,
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            self.assertTrue((destination / "link_lineage.json").exists())
            self.assertEqual(
                str(destination.resolve()),
                json.loads(output.getvalue())["output_dir"],
            )


if __name__ == "__main__":
    unittest.main()
