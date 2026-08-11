from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.system_assembly_engine import (
    reconcile_system_assembly,
    reconcile_system_assembly_capacity_draws,
)
from supply_intelligence.system_assembly_loader import (
    load_system_assembly_scenario,
    system_assembly_scenario_from_dict,
)
from supply_intelligence.system_assembly_release import (
    SYSTEM_ASSEMBLY_RELEASE_FORMAT,
    write_system_assembly_release,
)


ROOT = Path(__file__).parents[1]
SOURCE_ROOT = ROOT / "examples/system-assembly"
SCENARIO = SOURCE_ROOT / "gb200-nvl72-odm-assembly-illustrative-2026q3.json"


class SystemAssemblyTests(unittest.TestCase):
    def test_checked_scenario_reconciles_every_scope_once(self) -> None:
        scenario = load_system_assembly_scenario(SCENARIO, source_root=SOURCE_ROOT)
        result, draws = reconcile_system_assembly_capacity_draws(scenario)
        self.assertEqual("ai-supply-system-assembly-result.v1", result["format"])
        self.assertEqual(20000, len(draws))
        self.assertEqual(1.0, sum(item["probability"] for item in result["bottlenecks"]))
        self.assertEqual(
            "component_cleared_complete_racks",
            result["coverage"]["complete_rack_output"]["output_basis"],
        )
        for draw in draws:
            odm_total = sum(
                values["assembly_supported_racks"]
                for values in draw["odms"].values()
            )
            self.assertAlmostEqual(draw["odm_assembly_capacity_racks"], odm_total)
            self.assertLessEqual(draw["complete_racks"], odm_total + 1e-9)
            self.assertAlmostEqual(
                draw["accelerator_package_equivalents"],
                draw["complete_racks"] * 72,
            )
            for values in draw["odms"].values():
                self.assertAlmostEqual(
                    values["assembly_supported_racks"],
                    min(
                        values["customer_allocated_compute_trays"] / 18,
                        values["customer_allocated_integrated_racks"],
                    ),
                )
            for values in draw["components"].values():
                self.assertLessEqual(
                    draw["complete_racks"], values["rack_equivalents"] + 1e-9
                )

    def test_capacity_scopes_must_be_unique(self) -> None:
        document = json.loads(SCENARIO.read_text(encoding="utf-8"))
        document["components"][0]["capacity_scope_id"] = document["odms"][0][
            "tray_capacity_scope_id"
        ]
        with self.assertRaisesRegex(ValueError, "double count"):
            system_assembly_scenario_from_dict(document, source_root=SOURCE_ROOT)

    def test_coverage_must_exactly_match_modeled_resources(self) -> None:
        document = json.loads(SCENARIO.read_text(encoding="utf-8"))
        document["coverage"]["absorbed_constraints"].pop()
        with self.assertRaisesRegex(ValueError, "exactly match"):
            system_assembly_scenario_from_dict(document, source_root=SOURCE_ROOT)

    def test_platform_allocated_basis_rejects_another_allocation(self) -> None:
        document = json.loads(SCENARIO.read_text(encoding="utf-8"))
        document["odms"][0]["tray_capacity_basis"] = "platform_allocated"
        with self.assertRaisesRegex(ValueError, "must be fixed at one"):
            system_assembly_scenario_from_dict(document, source_root=SOURCE_ROOT)

    def test_source_hash_is_enforced(self) -> None:
        document = json.loads(SCENARIO.read_text(encoding="utf-8"))
        document["source_files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            system_assembly_scenario_from_dict(document, source_root=SOURCE_ROOT)

    def test_release_is_replay_safe_and_manifest_complete(self) -> None:
        scenario = load_system_assembly_scenario(SCENARIO, source_root=SOURCE_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_system_assembly_release(
                scenario,
                destination,
                source_document=SCENARIO.read_text(encoding="utf-8"),
            )
            self.assertEqual(SYSTEM_ASSEMBLY_RELEASE_FORMAT, metadata["format"])
            self.assertEqual(20000, metadata["capacity_draw_count"])
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(
                    descriptor["sha256"], hashlib.sha256(raw).hexdigest()
                )
            replay = write_system_assembly_release(
                scenario,
                destination,
                source_document=SCENARIO.read_text(encoding="utf-8"),
            )
            self.assertEqual(metadata["files"], replay["files"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_system_assembly_release(
                    scenario,
                    destination,
                    source_document=SCENARIO.read_text(encoding="utf-8"),
                )

    def test_cli_exposes_coverage_scope(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = main(
                [
                    "validate-system-assembly",
                    "--scenario",
                    str(SCENARIO),
                    "--source-root",
                    str(SOURCE_ROOT),
                ]
            )
        validation = json.loads(output.getvalue())
        self.assertEqual(0, status)
        self.assertTrue(validation["valid"])
        self.assertEqual(3, validation["odms"])
        self.assertEqual(6, validation["component_pools"])
        self.assertEqual(
            "component_cleared_complete_racks",
            validation["complete_rack_output_basis"],
        )

    def test_reconciliation_is_deterministic(self) -> None:
        scenario = load_system_assembly_scenario(SCENARIO, source_root=SOURCE_ROOT)
        self.assertEqual(
            reconcile_system_assembly(scenario),
            reconcile_system_assembly(scenario),
        )


if __name__ == "__main__":
    unittest.main()
