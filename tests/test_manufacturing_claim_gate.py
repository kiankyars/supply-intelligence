from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.claim_ledger import ingest_claim_pack, query_claim_snapshot
from supply_intelligence.cli import main
from supply_intelligence.manufacturing_claim_gate import (
    MANUFACTURING_CLAIM_ASSESSMENT_FORMAT,
    MANUFACTURING_CLAIM_SELECTION_FORMAT,
    assess_manufacturing_claim,
)


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_PACK = ROOT / "examples" / "ingestion" / "2026-07-19-official-controls-pack.json"
SIGNALS_PACK = ROOT / "examples" / "ingestion" / "2026-07-19-manufacturing-signals-pack.json"
OFFICIAL_SNAPSHOT = (
    ROOT
    / "releases"
    / "claim-cycles"
    / "official-controls"
    / "20260719T190000Z-official-controls-9784ceec7b"
    / "current_snapshot.json"
)
SIGNALS_SNAPSHOT = (
    ROOT
    / "releases"
    / "claim-cycles"
    / "manufacturing-signals"
    / "20260719T200000Z-manufacturing-signals-e93cd9c6b0"
    / "current_snapshot.json"
)
SELECTION_ROOT = ROOT / "examples" / "claim-selections"


def _snapshot(
    root: Path,
    *,
    pack: Path,
    valid_at: str,
    known_at: str,
    name: str,
) -> tuple[Path, dict[str, object]]:
    database = root / f"{name}.sqlite3"
    ingest_claim_pack(database, pack)
    document = query_claim_snapshot(
        database,
        valid_at=valid_at,
        known_at=known_at,
    )
    path = root / f"{name}.json"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, document


def _selection(
    snapshot_path: Path,
    snapshot: dict[str, object],
    *,
    claim_key: str,
    usage: str,
    target_input_path: str,
    target_dimensions: dict[str, object],
    conversion: dict[str, object] | None,
    nonbinding_rationale: str | None,
) -> dict[str, object]:
    claim = next(item for item in snapshot["claims"] if item["claim_key"] == claim_key)
    return {
        "format": MANUFACTURING_CLAIM_SELECTION_FORMAT,
        "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "expected_valid_at": snapshot["valid_at"],
        "expected_known_at": snapshot["known_at"],
        "claim_key": claim_key,
        "expected_revision_id": claim["revision_id"],
        "usage": usage,
        "target_input_path": target_input_path,
        "allowed_postures": ["reported", "derived"],
        "expected_claim_dimensions": claim["dimensions"],
        "target_dimensions": target_dimensions,
        "conversion": conversion,
        "nonbinding_rationale": nonbinding_rationale,
    }


def _write_selection(root: Path, name: str, document: dict[str, object]) -> Path:
    path = root / name
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class ManufacturingClaimGateTests(unittest.TestCase):
    def test_checked_assessments_pin_releases_and_preserve_nonbinding_boundary(self) -> None:
        rejected = assess_manufacturing_claim(
            OFFICIAL_SNAPSHOT,
            SELECTION_ROOT / "tsmc-2026q2-shipments-as-blackwell-wafer-starts.json",
        )
        self.assertFalse(rejected["accepted_for_usage"])
        self.assertEqual(7, len(rejected["blocking_reasons"]))
        self.assertIsNone(rejected["constraint_estimate"])

        control = assess_manufacturing_claim(
            OFFICIAL_SNAPSHOT,
            SELECTION_ROOT / "tsmc-2026q2-shipments-scale-control.json",
        )
        self.assertTrue(control["accepted_for_usage"])
        self.assertFalse(control["eligible_as_constraint"])
        self.assertEqual(4336000.0, control["normalized_estimate"]["base"])

        signal = assess_manufacturing_claim(
            SIGNALS_SNAPSHOT,
            SELECTION_ROOT / "micron-fq3-2026-hbm4-shipment-status-signal.json",
        )
        self.assertTrue(signal["accepted_for_usage"])
        self.assertIsNone(signal["normalized_estimate"])
        self.assertEqual("high_volume_shipments", signal["claim_value"])

    def test_company_shipments_fail_blackwell_wafer_start_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path, snapshot = _snapshot(
                root,
                pack=OFFICIAL_PACK,
                valid_at="2026-06-30",
                known_at="2026-07-19T19:00:00Z",
                name="official",
            )
            selection = _selection(
                snapshot_path,
                snapshot,
                claim_key="company.tsmc.wafer_shipments.2026q2_wafers",
                usage="constraint_input",
                target_input_path="logic.wafer.wafer_starts",
                target_dimensions={
                    "entity_scope": "product",
                    "geography": "global",
                    "period": "2026-Q3",
                    "stage": "logic_wafer_start",
                    "capacity_basis": "wafer_starts",
                    "quantity_semantics": "quarter_total",
                    "product": "NVIDIA Blackwell",
                    "process_node": "TSMC 4NP",
                    "customer": "NVIDIA",
                },
                conversion={
                    "source_unit": "12-inch-equivalent wafer",
                    "target_unit": "wafer",
                    "multiplier": 1,
                },
                nonbinding_rationale=None,
            )
            selection_path = _write_selection(root, "constraint.json", selection)
            assessment = assess_manufacturing_claim(snapshot_path, selection_path)
            self.assertEqual(MANUFACTURING_CLAIM_ASSESSMENT_FORMAT, assessment["format"])
            self.assertFalse(assessment["accepted_for_usage"])
            self.assertFalse(assessment["eligible_as_constraint"])
            self.assertIsNone(assessment["constraint_estimate"])
            self.assertEqual(4336000.0, assessment["normalized_estimate"]["base"])
            codes = {item["code"] for item in assessment["blocking_reasons"]}
            self.assertIn("dimension_mismatch:entity_scope", codes)
            self.assertIn("dimension_mismatch:period", codes)
            self.assertIn("dimension_mismatch:capacity_basis", codes)
            self.assertIn("dimension_mismatch:product", codes)
            self.assertIn("dimension_mismatch:process_node", codes)
            self.assertIn("dimension_mismatch:customer", codes)

    def test_same_claim_is_accepted_only_as_nonbinding_scale_control(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path, snapshot = _snapshot(
                root,
                pack=OFFICIAL_PACK,
                valid_at="2026-06-30",
                known_at="2026-07-19T19:00:00Z",
                name="official",
            )
            selection = _selection(
                snapshot_path,
                snapshot,
                claim_key="company.tsmc.wafer_shipments.2026q2_wafers",
                usage="scale_control",
                target_input_path="references.tsmc_total_wafer_shipments_2026q2",
                target_dimensions={},
                conversion={
                    "source_unit": "12-inch-equivalent wafer",
                    "target_unit": "wafer",
                    "multiplier": 1,
                },
                nonbinding_rationale=(
                    "Company-wide prior-quarter shipments check scale only and cannot constrain Blackwell."
                ),
            )
            selection_path = _write_selection(root, "control.json", selection)
            assessment = assess_manufacturing_claim(snapshot_path, selection_path)
            self.assertTrue(assessment["accepted_for_usage"])
            self.assertFalse(assessment["eligible_as_constraint"])
            self.assertFalse(assessment["blocking_reasons"])
            self.assertEqual(4336000.0, assessment["normalized_estimate"]["base"])
            self.assertIsNone(assessment["constraint_estimate"])

    def test_qualitative_hbm_signal_is_accepted_without_numeric_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path, snapshot = _snapshot(
                root,
                pack=SIGNALS_PACK,
                valid_at="2026-07-19",
                known_at="2026-07-19T20:00:00Z",
                name="signals",
            )
            selection = _selection(
                snapshot_path,
                snapshot,
                claim_key="company.micron.hbm4.lead_platform_shipment_status_fq3_2026",
                usage="directional_signal",
                target_input_path="research.hbm4.production_status",
                target_dimensions={},
                conversion=None,
                nonbinding_rationale=(
                    "High-volume status has no stack count and concerns HBM4, not GB200 HBM3E."
                ),
            )
            selection_path = _write_selection(root, "signal.json", selection)
            assessment = assess_manufacturing_claim(snapshot_path, selection_path)
            self.assertTrue(assessment["accepted_for_usage"])
            self.assertFalse(assessment["eligible_as_constraint"])
            self.assertIsNone(assessment["normalized_estimate"])
            self.assertEqual("high_volume_shipments", assessment["claim_value"])

    def test_exact_scope_numeric_claim_can_pass_constraint_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path, snapshot = _snapshot(
                root,
                pack=OFFICIAL_PACK,
                valid_at="2026-06-30",
                known_at="2026-07-19T19:00:00Z",
                name="official",
            )
            claim = next(
                item
                for item in snapshot["claims"]
                if item["claim_key"] == "platform.nvidia.gb200_nvl72.rack_power_mw"
            )
            selection = _selection(
                snapshot_path,
                snapshot,
                claim_key=claim["claim_key"],
                usage="constraint_input",
                target_input_path="operational.rack_it_load",
                target_dimensions=claim["dimensions"],
                conversion={
                    "source_unit": "MW/rack",
                    "target_unit": "MW/rack",
                    "multiplier": 1,
                },
                nonbinding_rationale=None,
            )
            selection_path = _write_selection(root, "exact.json", selection)
            assessment = assess_manufacturing_claim(snapshot_path, selection_path)
            self.assertTrue(assessment["accepted_for_usage"])
            self.assertTrue(assessment["eligible_as_constraint"])
            self.assertEqual(0.12, assessment["constraint_estimate"]["base"])

    def test_hash_revision_and_cli_contract_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_path, snapshot = _snapshot(
                root,
                pack=OFFICIAL_PACK,
                valid_at="2026-06-30",
                known_at="2026-07-19T19:00:00Z",
                name="official",
            )
            selection = _selection(
                snapshot_path,
                snapshot,
                claim_key="company.tsmc.wafer_shipments.2026q2_wafers",
                usage="scale_control",
                target_input_path="references.tsmc_total_wafer_shipments_2026q2",
                target_dimensions={},
                conversion={
                    "source_unit": "12-inch-equivalent wafer",
                    "target_unit": "wafer",
                    "multiplier": 1,
                },
                nonbinding_rationale="Nonbinding company-wide scale control.",
            )
            drifted = dict(selection)
            drifted["snapshot_sha256"] = "0" * 64
            drifted_path = _write_selection(root, "drifted.json", drifted)
            with self.assertRaisesRegex(ValueError, "snapshot SHA-256 mismatch"):
                assess_manufacturing_claim(snapshot_path, drifted_path)

            selection_path = _write_selection(root, "selection.json", selection)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "assess-manufacturing-claim",
                        "--snapshot",
                        str(snapshot_path),
                        "--selection",
                        str(selection_path),
                    ]
                )
            self.assertEqual(0, status)
            self.assertTrue(json.loads(output.getvalue())["accepted_for_usage"])


if __name__ == "__main__":
    unittest.main()
