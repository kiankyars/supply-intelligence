from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.claim_ledger import (
    CLAIM_DIFF_FORMAT,
    CLAIM_SNAPSHOT_FORMAT,
    INGEST_PACK_FORMAT,
    diff_claim_snapshots,
    ingest_claim_pack,
    query_claim_snapshot,
)
from supply_intelligence.cli import main


ROOT = Path(__file__).resolve().parents[1]
CHECKED_PACK = ROOT / "examples" / "ingestion" / "2026-07-19-official-controls-pack.json"
MANUFACTURING_SIGNALS_PACK = (
    ROOT / "examples" / "ingestion" / "2026-07-19-manufacturing-signals-pack.json"
)


def _write_observation(root: Path, name: str, value: float) -> tuple[Path, str]:
    path = root / name
    content = {
        "format": "ai-supply-normalized-observation.v1",
        "metric": "example rack power",
        "value": value,
        "unit": "MW/rack",
    }
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(
    *,
    claim_key: str = "nvidia.gb200_nvl72.rack_it_load_mw",
    value: float | None = 0.12,
    status: str = "asserted",
    source_id: str = "nvidia-guide",
    supersedes_revision_id: str | None = None,
) -> dict[str, object]:
    return {
        "claim_key": claim_key,
        "subject": "NVIDIA GB200 NVL72",
        "predicate": "approximate rack IT load",
        "value": value,
        "unit": "MW/rack",
        "dimensions": {
            "entity_scope": "product",
            "geography": "global",
            "period": "current_design",
            "stage": "datacenter_power",
            "capacity_basis": "design_power",
            "quantity_semantics": "point_specification",
            "product": "NVIDIA GB200 NVL72",
            "process_node": None,
            "customer": None,
        },
        "posture": "reported",
        "status": status,
        "valid_from": "2026-03-03",
        "valid_to": None,
        "methodology": "Normalize the vendor guide value from kW to MW per rack.",
        "confidence": 0.96,
        "confirming_evidence": "A current vendor hardware guide repeats the rack-level value.",
        "falsifying_evidence": "A superseding vendor guide changes the rack-level power specification.",
        "supersedes_revision_id": supersedes_revision_id,
        "evidence": [
            {
                "source_id": source_id,
                "role": "primary",
                "independence_group": "nvidia-product-documentation",
            }
        ],
    }


def _write_pack(
    root: Path,
    *,
    name: str,
    recorded_at: str,
    observation_name: str,
    observation_sha256: str,
    observation_retrieved_at: str,
    claims: list[dict[str, object]],
    source_id: str = "nvidia-guide",
) -> Path:
    pack = {
        "format": INGEST_PACK_FORMAT,
        "recorded_at": recorded_at,
        "sources": [
            {
                "id": source_id,
                "content_file": observation_name,
                "expected_sha256": observation_sha256,
                "capture_kind": "normalized_observation",
                "media_type": "application/json",
                "source_url": "https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html",
                "publisher": "NVIDIA",
                "source_family": "NVIDIA product documentation",
                "published_at": "2026-03-03",
                "retrieved_at": observation_retrieved_at,
            }
        ],
        "claims": claims,
    }
    path = root / name
    path.write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class ClaimLedgerTests(unittest.TestCase):
    def test_manufacturing_signals_remain_directional_not_product_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "claims.sqlite3"
            result = ingest_claim_pack(database, MANUFACTURING_SIGNALS_PACK)
            self.assertEqual(2, result["inserted_sources"])
            self.assertEqual(9, result["inserted_claims"])
            snapshot = query_claim_snapshot(
                database,
                valid_at="2026-07-19",
                known_at="2026-07-19T20:00:00Z",
            )
            self.assertEqual(8, snapshot["claim_count"])
            claims = {item["claim_key"]: item for item in snapshot["claims"]}
            hbm_revenue = claims[
                "company.micron.hbm4.cumulative_revenue_lower_bound_fq3_2026"
            ]
            self.assertEqual("cumulative_lower_bound", hbm_revenue["dimensions"]["quantity_semantics"])
            self.assertIn("cannot be converted into stacks", hbm_revenue["methodology"])
            backend = claims["company.tsmc.backend.capacity_status.2026q2"]
            self.assertEqual("supply_demand_status", backend["dimensions"]["capacity_basis"])
            self.assertEqual("status", backend["unit"])
            self.assertNotIn(
                "facility.micron.singapore.hbm_packaging_contribution_timing",
                claims,
            )

    def test_checked_pack_preserves_scope_and_normalized_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "claims.sqlite3"
            result = ingest_claim_pack(database, CHECKED_PACK)
            self.assertEqual(2, result["inserted_sources"])
            self.assertEqual(4, result["inserted_claims"])

            quarter_end = query_claim_snapshot(
                database,
                valid_at="2026-06-30",
                known_at="2026-07-19T19:00:00Z",
            )
            self.assertEqual(4, quarter_end["claim_count"])
            claims = {item["claim_key"]: item for item in quarter_end["claims"]}
            self.assertEqual(
                4336000,
                claims["company.tsmc.wafer_shipments.2026q2_wafers"]["value"],
            )
            self.assertEqual(
                "derived",
                claims["company.tsmc.wafer_shipments.2026q2_wafers"]["posture"],
            )
            self.assertIn(
                "cannot be allocated",
                claims["company.tsmc.wafer_shipments.2026q2_wafers"]["methodology"],
            )
            self.assertEqual(
                {
                    "capacity_basis": "shipments",
                    "customer": "all customers",
                    "entity_scope": "company",
                    "geography": "global",
                    "period": "2026-Q2",
                    "process_node": "all process nodes",
                    "product": "all products",
                    "quantity_semantics": "quarter_total",
                    "stage": "wafer_shipment",
                },
                claims["company.tsmc.wafer_shipments.2026q2_wafers"]["dimensions"],
            )
            self.assertEqual(
                "2eb321eea07833570c6e5947d996a9ffaecd562385aa466faa5646137b6c9e38",
                claims["platform.nvidia.gb200_nvl72.rack_power_kw"]["evidence"][0][
                    "content_sha256"
                ],
            )

            after_quarter = query_claim_snapshot(
                database,
                valid_at="2026-07-19",
                known_at="2026-07-19T19:00:00Z",
            )
            self.assertEqual(2, after_quarter["claim_count"])
            self.assertTrue(
                all(
                    item["claim_key"].startswith("platform.nvidia")
                    for item in after_quarter["claims"]
                )
            )

    def test_ingest_is_idempotent_and_cli_query_respects_transaction_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "ledger" / "claims.sqlite3"
            observation, digest = _write_observation(root, "observation.json", 0.12)
            pack = _write_pack(
                root,
                name="pack.json",
                recorded_at="2026-07-17T12:00:00-07:00",
                observation_name=observation.name,
                observation_sha256=digest,
                observation_retrieved_at="2026-07-17T11:55:00-07:00",
                claims=[_claim()],
            )

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "ingest-claims",
                        "--database",
                        str(database),
                        "--pack",
                        str(pack),
                    ]
                )
            self.assertEqual(0, status)
            ingested = json.loads(output.getvalue())
            self.assertEqual(1, ingested["inserted_sources"])
            self.assertEqual(1, ingested["inserted_claims"])
            self.assertEqual("2026-07-17T19:00:00Z", ingested["recorded_at"])

            repeated = ingest_claim_pack(database, pack)
            self.assertEqual(0, repeated["inserted_sources"])
            self.assertEqual(0, repeated["inserted_claims"])
            self.assertEqual(1, repeated["skipped_claims"])
            self.assertEqual(ingested["run_id"], repeated["run_id"])

            before = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-17T18:59:59Z",
            )
            self.assertEqual(CLAIM_SNAPSHOT_FORMAT, before["format"])
            self.assertEqual(0, before["claim_count"])

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "query-claims",
                        "--database",
                        str(database),
                        "--valid-at",
                        "2026-07-17",
                        "--known-at",
                        "2026-07-17T12:00:00-07:00",
                    ]
                )
            self.assertEqual(0, status)
            current = json.loads(output.getvalue())
            self.assertEqual(1, current["claim_count"])
            self.assertEqual(0.12, current["claims"][0]["value"])
            self.assertEqual("2026-07-17T19:00:00Z", current["known_at"])
            self.assertEqual(digest, current["claims"][0]["evidence"][0]["content_sha256"])

    def test_revision_requires_latest_supersession_and_produces_deterministic_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "claims.sqlite3"
            old_observation, old_digest = _write_observation(root, "old.json", 0.12)
            first_pack = _write_pack(
                root,
                name="first-pack.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=old_observation.name,
                observation_sha256=old_digest,
                observation_retrieved_at="2026-07-17T18:55:00Z",
                claims=[_claim()],
            )
            ingest_claim_pack(database, first_pack)
            first = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-17T19:00:00Z",
            )["claims"][0]

            new_observation, new_digest = _write_observation(root, "new.json", 0.118)
            second_pack = _write_pack(
                root,
                name="second-pack.json",
                recorded_at="2026-07-18T19:00:00Z",
                observation_name=new_observation.name,
                observation_sha256=new_digest,
                observation_retrieved_at="2026-07-18T18:55:00Z",
                claims=[
                    _claim(value=0.118, supersedes_revision_id=first["revision_id"])
                ],
            )
            ingest_claim_pack(database, second_pack)

            prior = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-18T18:59:59Z",
            )
            current = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-18T19:00:00Z",
            )
            self.assertEqual(0.12, prior["claims"][0]["value"])
            self.assertEqual(0.118, current["claims"][0]["value"])

            difference = diff_claim_snapshots(
                database,
                valid_at="2026-07-17",
                previous_known_at="2026-07-18T18:59:59Z",
                current_known_at="2026-07-18T19:00:00Z",
            )
            self.assertEqual(CLAIM_DIFF_FORMAT, difference["format"])
            self.assertEqual(1, difference["alert_count"])
            self.assertEqual("claim_revised", difference["alerts"][0]["type"])
            self.assertEqual(
                difference,
                diff_claim_snapshots(
                    database,
                    valid_at="2026-07-17",
                    previous_known_at="2026-07-18T18:59:59Z",
                    current_known_at="2026-07-18T19:00:00Z",
                ),
            )

    def test_retraction_removes_claim_at_later_known_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "claims.sqlite3"
            observation, digest = _write_observation(root, "observation.json", 0.12)
            first_pack = _write_pack(
                root,
                name="first-pack.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=observation.name,
                observation_sha256=digest,
                observation_retrieved_at="2026-07-17T18:55:00Z",
                claims=[_claim()],
            )
            ingest_claim_pack(database, first_pack)
            revision_id = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-17T19:00:00Z",
            )["claims"][0]["revision_id"]
            retraction_pack = _write_pack(
                root,
                name="retraction-pack.json",
                recorded_at="2026-07-19T19:00:00Z",
                observation_name=observation.name,
                observation_sha256=digest,
                observation_retrieved_at="2026-07-19T18:55:00Z",
                claims=[
                    _claim(
                        value=None,
                        status="retracted",
                        supersedes_revision_id=revision_id,
                    )
                ],
            )
            ingest_claim_pack(database, retraction_pack)

            difference = diff_claim_snapshots(
                database,
                valid_at="2026-07-17",
                previous_known_at="2026-07-19T18:59:59Z",
                current_known_at="2026-07-19T19:00:00Z",
            )
            self.assertEqual(1, difference["alert_count"])
            self.assertEqual("claim_removed", difference["alerts"][0]["type"])
            self.assertEqual("high", difference["alerts"][0]["severity"])
            self.assertIsNone(difference["alerts"][0]["current"])

    def test_pack_rejects_hash_mismatch_path_escape_and_future_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack_root = root / "pack"
            pack_root.mkdir()
            observation, digest = _write_observation(pack_root, "observation.json", 0.12)
            mismatch = _write_pack(
                pack_root,
                name="mismatch.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=observation.name,
                observation_sha256="0" * 64,
                observation_retrieved_at="2026-07-17T18:55:00Z",
                claims=[_claim()],
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                ingest_claim_pack(root / "mismatch.sqlite3", mismatch)

            outside, outside_digest = _write_observation(root, "outside.json", 0.12)
            escaped = _write_pack(
                pack_root,
                name="escaped.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=f"../{outside.name}",
                observation_sha256=outside_digest,
                observation_retrieved_at="2026-07-17T18:55:00Z",
                claims=[_claim()],
            )
            with self.assertRaisesRegex(ValueError, "escapes the pack directory"):
                ingest_claim_pack(root / "escaped.sqlite3", escaped)

            future = _write_pack(
                pack_root,
                name="future.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=observation.name,
                observation_sha256=digest,
                observation_retrieved_at="2026-07-17T19:00:01Z",
                claims=[_claim()],
            )
            with self.assertRaisesRegex(ValueError, "cannot follow pack.recorded_at"):
                ingest_claim_pack(root / "future.sqlite3", future)

    def test_invalid_supersession_rolls_back_every_row_in_the_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "claims.sqlite3"
            observation, digest = _write_observation(root, "observation.json", 0.12)
            first_pack = _write_pack(
                root,
                name="first-pack.json",
                recorded_at="2026-07-17T19:00:00Z",
                observation_name=observation.name,
                observation_sha256=digest,
                observation_retrieved_at="2026-07-17T18:55:00Z",
                claims=[_claim()],
            )
            ingest_claim_pack(database, first_pack)

            later_observation, later_digest = _write_observation(root, "later.json", 0.118)
            invalid_pack = _write_pack(
                root,
                name="invalid-pack.json",
                recorded_at="2026-07-18T19:00:00Z",
                observation_name=later_observation.name,
                observation_sha256=later_digest,
                observation_retrieved_at="2026-07-18T18:55:00Z",
                claims=[
                    _claim(
                        claim_key="new.claim.that.must.rollback",
                        value=0.5,
                    ),
                    _claim(value=0.118, supersedes_revision_id="claimrev:not-the-latest"),
                ],
            )
            with self.assertRaisesRegex(ValueError, "must supersede"):
                ingest_claim_pack(database, invalid_pack)

            snapshot = query_claim_snapshot(
                database,
                valid_at="2026-07-17",
                known_at="2026-07-18T19:00:00Z",
            )
            self.assertEqual(1, snapshot["claim_count"])
            self.assertEqual(
                "nvidia.gb200_nvl72.rack_it_load_mw",
                snapshot["claims"][0]["claim_key"],
            )

    def test_query_missing_database_is_read_only_and_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "missing.sqlite3"
            with self.assertRaisesRegex(ValueError, "does not exist"):
                query_claim_snapshot(
                    database,
                    valid_at="2026-07-17",
                    known_at="2026-07-17T19:00:00Z",
                )
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
