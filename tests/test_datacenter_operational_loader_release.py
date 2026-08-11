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
from supply_intelligence.datacenter_operational_loader import (
    load_datacenter_operational_case,
    operational_scenario_from_dict,
)
from supply_intelligence.datacenter_operational_release import (
    DATACENTER_OPERATIONAL_DRAW_RELEASE_FORMAT,
    write_datacenter_operational_release,
)
from supply_intelligence.engine import summarize


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = (
    ROOT
    / "examples"
    / "datacenter-openai-abilene-net-operational-illustrative-2026q3.json"
)
GROSS_IMPORT_PATH = (
    ROOT
    / "examples"
    / "datacenter-openai-abilene-operational-2026q3-import.json"
)


class DatacenterOperationalLoaderReleaseTests(unittest.TestCase):
    def test_capacity_draw_release_reproduces_result_and_is_replay_safe(self) -> None:
        case = load_datacenter_operational_case(SCENARIO_PATH, GROSS_IMPORT_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            first = write_datacenter_operational_release(
                case,
                destination,
                scenario_document=SCENARIO_PATH.read_text(encoding="utf-8"),
                gross_import_document=GROSS_IMPORT_PATH.read_text(encoding="utf-8"),
                include_capacity_draws=True,
            )
            self.assertEqual(DATACENTER_OPERATIONAL_DRAW_RELEASE_FORMAT, first["format"])
            self.assertEqual(20000, first["capacity_draw_count"])
            with (destination / "capacity_draws.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(20000, len(rows))
            self.assertEqual(list(rows[0]), first["capacity_draw_fields"])
            result = json.loads(
                (destination / "result.json").read_text(encoding="utf-8")
            )
            reproduced = summarize(
                [float(row["operational_racks"]) for row in rows]
            ).as_dict()
            self.assertEqual(
                result["conversion_outputs"]["operational_racks"],
                reproduced,
            )
            replay = write_datacenter_operational_release(
                case,
                destination,
                scenario_document=SCENARIO_PATH.read_text(encoding="utf-8"),
                gross_import_document=GROSS_IMPORT_PATH.read_text(encoding="utf-8"),
                include_capacity_draws=True,
            )
            self.assertEqual(first["files"], replay["files"])
            (destination / "capacity_draws.csv").write_text(
                "drift\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_datacenter_operational_release(
                    case,
                    destination,
                    scenario_document=SCENARIO_PATH.read_text(encoding="utf-8"),
                    gross_import_document=GROSS_IMPORT_PATH.read_text(encoding="utf-8"),
                    include_capacity_draws=True,
                )

    def test_checked_pack_pins_gross_lineage_and_separates_reported_rack_power(self) -> None:
        case = load_datacenter_operational_case(SCENARIO_PATH, GROSS_IMPORT_PATH)
        self.assertTrue(case.scenario.synthetic)
        self.assertEqual(1, len(case.sites))
        self.assertEqual("MW", case.gross_estimate.unit)
        self.assertEqual("reported", case.scenario.rack_it_load.posture.value)
        self.assertEqual(0.12, case.scenario.rack_it_load.base)
        self.assertEqual(
            "synthetic",
            case.scenario.deductions.current_critical_it_load.posture.value,
        )
        self.assertEqual(
            hashlib.sha256(GROSS_IMPORT_PATH.read_bytes()).hexdigest(),
            case.gross_import_sha256,
        )

    def test_loader_rejects_gross_import_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            altered = Path(temporary) / "gross.json"
            altered.write_bytes(GROSS_IMPORT_PATH.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_datacenter_operational_case(SCENARIO_PATH, altered)

    def test_loader_requires_explicit_non_overlap_rationale(self) -> None:
        document = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        document["deductions"]["non_overlap_rationale"] = ""
        with self.assertRaisesRegex(ValueError, "non_overlap_rationale"):
            operational_scenario_from_dict(document)

    def test_loader_rejects_scenario_recorded_before_gross_source(self) -> None:
        document = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
        document["scenario"]["recorded_at"] = "2026-07-18T01:00:00Z"
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path = Path(temporary) / "scenario.json"
            scenario_path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot follow scenario recorded_at"):
                load_datacenter_operational_case(scenario_path, GROSS_IMPORT_PATH)

    def test_release_is_self_contained_and_hashes_match(self) -> None:
        case = load_datacenter_operational_case(SCENARIO_PATH, GROSS_IMPORT_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            metadata = write_datacenter_operational_release(
                case,
                destination,
                scenario_document=SCENARIO_PATH.read_text(encoding="utf-8"),
                gross_import_document=GROSS_IMPORT_PATH.read_text(encoding="utf-8"),
            )
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(metadata["synthetic"])
            self.assertFalse(metadata["usable_as_operational_capacity"])
            self.assertEqual(
                "ai-supply-datacenter-operational-release.v1",
                manifest["format"],
            )
            self.assertEqual(
                case.gross_import_sha256,
                manifest["files"]["gross_import.json"]["sha256"],
            )
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(content))
                self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Illustrative operational run", dashboard)
            self.assertIn("Every unavailable MW is removed", dashboard)
            self.assertIn("approximately 120 kW", dashboard)
            self.assertIn(
                "https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html",
                dashboard,
            )
            result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            self.assertFalse(result["usable_as_operational_capacity"])
            self.assertEqual(7, len(result["research_queue"]))

    def test_validate_and_reconcile_cli(self) -> None:
        validation_output = StringIO()
        with redirect_stdout(validation_output):
            status = main(
                [
                    "validate-datacenter-operational",
                    "--gross-import",
                    str(GROSS_IMPORT_PATH),
                    "--scenario",
                    str(SCENARIO_PATH),
                ]
            )
        self.assertEqual(0, status)
        self.assertEqual(1, json.loads(validation_output.getvalue())["sites"])

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "reconcile-datacenter-operational",
                        "--gross-import",
                        str(GROSS_IMPORT_PATH),
                        "--scenario",
                        str(SCENARIO_PATH),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            self.assertTrue((destination / "dashboard.html").exists())
            self.assertEqual(
                str(destination.resolve()),
                json.loads(output.getvalue())["output_dir"],
            )


if __name__ == "__main__":
    unittest.main()
