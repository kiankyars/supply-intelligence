from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

from supply_intelligence.alert_release import write_revision_alert_release
from supply_intelligence.alerts import detect_revision_alerts
from supply_intelligence.cli import main
from supply_intelligence.datacenter_operational_engine import (
    reconcile_datacenter_operational,
)
from supply_intelligence.manufacturing_engine import reconcile_manufacturing

from tests.datacenter_operational_helpers import deterministic_operational_case
from tests.helpers import estimate
from tests.manufacturing_helpers import (
    deterministic_manufacturing,
    with_logic_wafer_starts,
)


def revision_pair() -> tuple[dict[str, object], dict[str, object]]:
    scenario = deterministic_manufacturing()
    previous = reconcile_manufacturing(scenario)
    current_scenario = with_logic_wafer_starts(scenario, 0.1)
    current_scenario = replace(
        current_scenario,
        recorded_at="2026-07-18T12:00:00Z",
    )
    current = reconcile_manufacturing(current_scenario)
    return previous, current


class RevisionAlertTests(unittest.TestCase):
    def test_single_and_portfolio_results_share_the_alert_contract(self) -> None:
        release_root = Path(__file__).resolve().parents[1] / "releases"
        paths = (
            release_root / "2026-07-17-gb200-illustrative" / "result.json",
            release_root
            / "2026-07-17-gb200-gb300-shared-illustrative"
            / "result.json",
            release_root
            / "2026-07-17-abilene-operational-illustrative"
            / "result.json",
        )
        for path in paths:
            with self.subTest(path=path):
                previous = json.loads(path.read_text(encoding="utf-8"))
                current = deepcopy(previous)
                current["scenario"]["recorded_at"] = "2026-07-19T12:00:00Z"
                report = detect_revision_alerts(previous, current)
                self.assertEqual(0, report["alert_count"])

    def test_operational_results_alert_on_power_commissioning_bottleneck_shift(self) -> None:
        case = deterministic_operational_case()
        previous = reconcile_datacenter_operational(case)
        current_scenario = replace(
            case.scenario,
            commissioning_slots=estimate(1000, "rack"),
            commissioning_completion_ratio=estimate(1, "ratio"),
            recorded_at="2026-07-18T12:00:00Z",
        )
        current = reconcile_datacenter_operational(
            replace(case, scenario=current_scenario)
        )
        report = detect_revision_alerts(previous, current)
        binding = next(
            item
            for item in report["alerts"]
            if item["type"] == "binding_bottleneck_changed"
        )
        self.assertEqual("commissioning", binding["previous_constraint"])
        self.assertEqual("power", binding["current_constraint"])
        self.assertEqual("bottlenecks.operational", binding["path"])

    def test_detects_range_output_and_binding_bottleneck_changes(self) -> None:
        previous, current = revision_pair()
        report = detect_revision_alerts(previous, current)
        types = {item["type"] for item in report["alerts"]}
        self.assertIn("estimate_range_breach", types)
        self.assertIn("output_revision", types)
        self.assertIn("binding_bottleneck_changed", types)
        range_alert = next(
            item
            for item in report["alerts"]
            if item["type"] == "estimate_range_breach"
        )
        self.assertEqual("inputs.logic.wafer.wafer_starts", range_alert["path"])
        binding_alert = next(
            item
            for item in report["alerts"]
            if item["type"] == "binding_bottleneck_changed"
        )
        self.assertEqual("hbm_good_stacks", binding_alert["previous_constraint"])
        self.assertEqual("logic_binned_dies", binding_alert["current_constraint"])
        self.assertEqual(report, detect_revision_alerts(previous, current))

    def test_changed_payload_requires_later_recorded_at(self) -> None:
        previous, current = revision_pair()
        current["scenario"]["recorded_at"] = previous["scenario"]["recorded_at"]
        with self.assertRaisesRegex(ValueError, "later current recorded_at"):
            detect_revision_alerts(previous, current)

    def test_alert_release_hashes_every_payload(self) -> None:
        previous, current = revision_pair()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous_path = root / "previous.json"
            current_path = root / "current.json"
            previous_path.write_text(json.dumps(previous), encoding="utf-8")
            current_path.write_text(json.dumps(current), encoding="utf-8")
            destination = root / "alerts"
            metadata = write_revision_alert_release(
                previous_path,
                current_path,
                destination,
            )
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertGreater(metadata["alert_count"], 0)
            self.assertIn("dashboard.html", manifest["files"])
            self.assertIn("lineage.json", manifest["files"])
            for name, expected in manifest["files"].items():
                content = (destination / name).read_bytes()
                self.assertEqual(expected["bytes"], len(content))
                self.assertEqual(expected["sha256"], hashlib.sha256(content).hexdigest())
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Revision alerts", dashboard)
            self.assertIn("binding bottleneck changed", dashboard)

    def test_compare_releases_cli_writes_alert_bundle(self) -> None:
        previous, current = revision_pair()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous_path = root / "previous.json"
            current_path = root / "current.json"
            previous_path.write_text(json.dumps(previous), encoding="utf-8")
            current_path.write_text(json.dumps(current), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "compare-releases",
                        "--previous-result",
                        str(previous_path),
                        "--current-result",
                        str(current_path),
                        "--output-dir",
                        str(root / "alerts"),
                    ]
                )
            self.assertEqual(0, status)
            payload = json.loads(output.getvalue())
            self.assertGreater(payload["alert_count"], 0)
            self.assertEqual("ai-supply-revision-alert-release.v1", payload["format"])


if __name__ == "__main__":
    unittest.main()
