from __future__ import annotations

import fcntl
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.claim_cycle import (
    CLAIM_CYCLE_RELEASE_FORMAT,
    load_claim_cycle,
    run_claim_cycle,
)
from supply_intelligence.claim_ledger import query_claim_snapshot
from supply_intelligence.cli import main


ROOT = Path(__file__).resolve().parents[1]
INGESTION_ROOT = ROOT / "examples" / "ingestion"
CHECKED_JOB = INGESTION_ROOT / "official-controls-cycle.json"
CHECKED_PACK = INGESTION_ROOT / "2026-07-19-official-controls-pack.json"
NVIDIA_OBSERVATION = INGESTION_ROOT / "nvidia-gb200-rack-power-observation.json"
TSMC_OBSERVATION = INGESTION_ROOT / "tsmc-2026q2-wafer-shipments-observation.json"


def _paths(root: Path) -> dict[str, Path]:
    return {
        "database": root / "claims.sqlite3",
        "outbox": root / "notifications.sqlite3",
        "state_dir": root / "state",
        "release_root": root / "releases",
        "notification_sink": root / "notifications.jsonl",
    }


class ClaimCycleTests(unittest.TestCase):
    def test_checked_cycle_cli_freezes_release_and_delivers_notifications(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "run-claim-cycle",
                        "--job",
                        str(CHECKED_JOB),
                        "--database",
                        str(paths["database"]),
                        "--outbox",
                        str(paths["outbox"]),
                        "--state-dir",
                        str(paths["state_dir"]),
                        "--release-root",
                        str(paths["release_root"]),
                        "--run-at",
                        "2026-07-19T19:00:00Z",
                        "--notification-sink",
                        str(paths["notification_sink"]),
                    ]
                )
            self.assertEqual(0, status)
            result = json.loads(output.getvalue())
            self.assertEqual("completed", result["status"])
            self.assertEqual(4, result["alert_count"])
            self.assertEqual(4, result["notification_delivery"]["delivered_count"])

            release = Path(result["release_dir"])
            manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(CLAIM_CYCLE_RELEASE_FORMAT, manifest["format"])
            self.assertEqual(8, len(manifest["files"]))
            for name, metadata in manifest["files"].items():
                content = (release / name).read_bytes()
                self.assertEqual(len(content), metadata["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), metadata["sha256"])
            self.assertEqual(CHECKED_JOB.read_bytes(), (release / "job.json").read_bytes())
            self.assertEqual(
                CHECKED_PACK.read_bytes(),
                (release / "packs" / f"000-{CHECKED_PACK.name}").read_bytes(),
            )
            self.assertEqual(0, json.loads((release / "previous_snapshot.json").read_text())["claim_count"])
            self.assertEqual(4, json.loads((release / "current_snapshot.json").read_text())["claim_count"])
            self.assertEqual(
                4,
                len(
                    paths["notification_sink"]
                    .read_text(encoding="utf-8")
                    .splitlines()
                ),
            )

            checkpoint = json.loads(
                (paths["state_dir"] / "checkpoints" / "official-controls.json").read_text(
                    encoding="utf-8"
                )
            )
            current_content = (release / "current_snapshot.json").read_bytes()
            self.assertEqual(
                hashlib.sha256(current_content).hexdigest(),
                checkpoint["current_snapshot_sha256"],
            )
            self.assertEqual(str(release), checkpoint["release_dir"])

    def test_interval_gate_skips_early_run_then_allows_due_no_change_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            first = run_claim_cycle(
                CHECKED_JOB,
                **paths,
                run_at="2026-07-19T19:00:00Z",
            )
            early = run_claim_cycle(
                CHECKED_JOB,
                **paths,
                run_at="2026-07-20T18:59:59Z",
            )
            self.assertEqual("not_due", early["status"])
            self.assertEqual("2026-07-20T19:00:00Z", early["next_due_at"])
            self.assertEqual(1, len(list((paths["release_root"] / "official-controls").iterdir())))

            due = run_claim_cycle(
                CHECKED_JOB,
                **paths,
                run_at="2026-07-20T19:00:00Z",
            )
            self.assertEqual("completed", due["status"])
            self.assertEqual(0, due["alert_count"])
            self.assertNotEqual(first["cycle_id"], due["cycle_id"])
            self.assertEqual(2, len(list((paths["release_root"] / "official-controls").iterdir())))
            previous = json.loads(
                (Path(due["release_dir"]) / "previous_snapshot.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("2026-07-19T19:00:00Z", previous["known_at"])
            self.assertEqual(4, previous["claim_count"])

    def test_prior_frozen_snapshot_hash_drift_blocks_next_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            first = run_claim_cycle(
                CHECKED_JOB,
                **paths,
                run_at="2026-07-19T19:00:00Z",
            )
            snapshot = Path(first["release_dir"]) / "current_snapshot.json"
            snapshot.write_bytes(snapshot.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "snapshot SHA-256 mismatch"):
                run_claim_cycle(
                    CHECKED_JOB,
                    **paths,
                    run_at="2026-07-20T19:00:00Z",
                )

    def test_new_backdated_pack_is_rejected_before_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = _paths(root)
            run_claim_cycle(
                CHECKED_JOB,
                **paths,
                run_at="2026-07-19T19:00:00Z",
            )

            job_root = root / "job"
            job_root.mkdir()
            copied_pack = job_root / CHECKED_PACK.name
            copied_pack.write_bytes(CHECKED_PACK.read_bytes())
            copied_observation = job_root / NVIDIA_OBSERVATION.name
            copied_observation.write_bytes(NVIDIA_OBSERVATION.read_bytes())
            (job_root / TSMC_OBSERVATION.name).write_bytes(TSMC_OBSERVATION.read_bytes())
            observation_hash = hashlib.sha256(copied_observation.read_bytes()).hexdigest()
            backfill = {
                "format": "ai-supply-ingest-pack.v1",
                "recorded_at": "2026-07-19T19:00:00Z",
                "sources": [
                    {
                        "id": "backfill-source",
                        "content_file": copied_observation.name,
                        "expected_sha256": observation_hash,
                        "capture_kind": "normalized_observation",
                        "media_type": "application/json",
                        "source_url": "https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html",
                        "publisher": "NVIDIA",
                        "source_family": "nvidia-product-documentation",
                        "published_at": "2026-03-03",
                        "retrieved_at": "2026-07-19T18:55:00Z",
                    }
                ],
                "claims": [
                    {
                        "claim_key": "backfill.must.not.enter.scheduled.ledger",
                        "subject": "Backfill test",
                        "predicate": "must not be ingested",
                        "value": 1,
                        "unit": "count",
                        "dimensions": {
                            "entity_scope": "model",
                            "geography": "global",
                            "period": "2026-Q2",
                            "stage": "test",
                            "capacity_basis": "test_count",
                            "quantity_semantics": "quarter_total",
                        },
                        "posture": "reported",
                        "status": "asserted",
                        "valid_from": "2026-06-01",
                        "valid_to": None,
                        "methodology": "Exercise the scheduled backfill guard.",
                        "confidence": 1,
                        "confirming_evidence": "The test pack would create the claim.",
                        "falsifying_evidence": "The claim remains absent.",
                        "supersedes_revision_id": None,
                        "evidence": [
                            {
                                "source_id": "backfill-source",
                                "role": "primary",
                                "independence_group": "backfill-test",
                            }
                        ],
                    }
                ],
            }
            backfill_path = job_root / "backfill.json"
            backfill_path.write_text(
                json.dumps(backfill, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            job = json.loads(CHECKED_JOB.read_text(encoding="utf-8"))
            job["packs"] = [
                {
                    "path": copied_pack.name,
                    "expected_sha256": hashlib.sha256(copied_pack.read_bytes()).hexdigest(),
                },
                {
                    "path": backfill_path.name,
                    "expected_sha256": hashlib.sha256(backfill_path.read_bytes()).hexdigest(),
                },
            ]
            job_path = job_root / "cycle.json"
            job_path.write_text(
                json.dumps(job, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not later than the prior checkpoint"):
                run_claim_cycle(
                    job_path,
                    **paths,
                    run_at="2026-07-20T19:00:00Z",
                )
            snapshot = query_claim_snapshot(
                paths["database"],
                valid_at="2026-06-30",
                known_at="2026-07-20T19:00:00Z",
            )
            self.assertEqual(4, snapshot["claim_count"])

    def test_job_hash_drift_and_concurrent_lock_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = json.loads(CHECKED_JOB.read_text(encoding="utf-8"))
            (root / CHECKED_PACK.name).write_bytes(CHECKED_PACK.read_bytes())
            job["packs"][0]["expected_sha256"] = "0" * 64
            job_path = root / "bad-job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_claim_cycle(job_path)

            paths = _paths(root)
            lock = paths["state_dir"] / "locks" / "official-controls.lock"
            lock.parent.mkdir(parents=True)
            with lock.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, "already running"):
                    run_claim_cycle(
                        CHECKED_JOB,
                        **paths,
                        run_at="2026-07-19T19:00:00Z",
                    )


if __name__ == "__main__":
    unittest.main()
