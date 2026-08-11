from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.claim_ledger import diff_claim_snapshots, ingest_claim_pack
from supply_intelligence.cli import main
from supply_intelligence.notifications import (
    NOTIFICATION_BATCH_FORMAT,
    NOTIFICATION_EVENT_FORMAT,
    acknowledge_claim_notification,
    deliver_claim_notifications_to_jsonl,
    enqueue_claim_notifications,
    list_claim_notifications,
)


ROOT = Path(__file__).resolve().parents[1]
CHECKED_PACK = ROOT / "examples" / "ingestion" / "2026-07-19-official-controls-pack.json"


def _checked_diff(root: Path) -> dict[str, object]:
    ledger = root / "claims.sqlite3"
    ingest_claim_pack(ledger, CHECKED_PACK)
    return diff_claim_snapshots(
        ledger,
        valid_at="2026-06-30",
        previous_known_at="2026-07-19T18:59:59Z",
        current_known_at="2026-07-19T19:00:00Z",
    )


class NotificationOutboxTests(unittest.TestCase):
    def test_enqueue_is_idempotent_and_lists_pending_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outbox = root / "state" / "notifications.sqlite3"
            difference = _checked_diff(root)
            first = enqueue_claim_notifications(
                outbox,
                difference,
                created_at="2026-07-19T12:01:00-07:00",
            )
            self.assertEqual(4, first["inserted"])
            self.assertEqual(0, first["skipped"])
            self.assertEqual(4, len(set(first["event_ids"])))

            repeated = enqueue_claim_notifications(
                outbox,
                difference,
                created_at="2026-07-19T19:02:00Z",
            )
            self.assertEqual(0, repeated["inserted"])
            self.assertEqual(4, repeated["skipped"])
            self.assertEqual(first["event_ids"], repeated["event_ids"])

            pending = list_claim_notifications(outbox, status="pending")
            self.assertEqual(NOTIFICATION_BATCH_FORMAT, pending["format"])
            self.assertEqual(4, pending["notification_count"])
            self.assertEqual(4, pending["counts"]["pending"])
            self.assertTrue(
                all(
                    item["format"] == NOTIFICATION_EVENT_FORMAT
                    and item["status"] == "pending"
                    for item in pending["notifications"]
                )
            )

    def test_tampered_alert_id_and_early_enqueue_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            difference = _checked_diff(root)
            tampered = copy.deepcopy(difference)
            tampered["alerts"][0]["id"] = "claim-alert:not-the-payload"
            with self.assertRaisesRegex(ValueError, "does not match its payload"):
                enqueue_claim_notifications(
                    root / "tampered.sqlite3",
                    tampered,
                    created_at="2026-07-19T19:01:00Z",
                )
            with self.assertRaisesRegex(ValueError, "cannot precede"):
                enqueue_claim_notifications(
                    root / "early.sqlite3",
                    difference,
                    created_at="2026-07-19T18:59:59Z",
                )

    def test_jsonl_delivery_is_durable_bounded_and_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outbox = root / "notifications.sqlite3"
            sink = root / "delivered" / "claim-alerts.jsonl"
            difference = _checked_diff(root)
            enqueue = enqueue_claim_notifications(
                outbox,
                difference,
                created_at="2026-07-19T19:01:00Z",
            )

            first = deliver_claim_notifications_to_jsonl(
                outbox,
                sink,
                delivered_at="2026-07-19T19:02:00Z",
                limit=2,
            )
            self.assertEqual(2, first["delivered_count"])
            self.assertEqual(
                "at_least_once_with_event_id_deduplication",
                first["delivery_semantics"],
            )
            after_first = list_claim_notifications(outbox)
            self.assertEqual(2, after_first["counts"]["pending"])
            self.assertEqual(2, after_first["counts"]["delivered"])

            second = deliver_claim_notifications_to_jsonl(
                outbox,
                sink,
                delivered_at="2026-07-19T19:03:00Z",
                limit=100,
            )
            self.assertEqual(2, second["delivered_count"])
            third = deliver_claim_notifications_to_jsonl(
                outbox,
                sink,
                delivered_at="2026-07-19T19:04:00Z",
            )
            self.assertEqual(0, third["delivered_count"])

            lines = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(4, len(lines))
            self.assertEqual(set(enqueue["event_ids"]), {item["event_id"] for item in lines})
            self.assertTrue(all(item["format"] == NOTIFICATION_EVENT_FORMAT for item in lines))
            self.assertTrue(all(item["delivered_at"] for item in lines))

    def test_acknowledgement_is_audited_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outbox = root / "notifications.sqlite3"
            sink = root / "notifications.jsonl"
            difference = _checked_diff(root)
            queued = enqueue_claim_notifications(
                outbox,
                difference,
                created_at="2026-07-19T19:01:00Z",
            )
            deliver_claim_notifications_to_jsonl(
                outbox,
                sink,
                delivered_at="2026-07-19T19:02:00Z",
            )
            event_id = queued["event_ids"][0]
            acknowledged = acknowledge_claim_notification(
                outbox,
                event_id,
                acknowledged_at="2026-07-19T19:03:00Z",
                note="Reviewed source scope; no model rerun yet.",
            )
            self.assertEqual("acknowledged", acknowledged["status"])
            self.assertEqual(
                acknowledged,
                acknowledge_claim_notification(
                    outbox,
                    event_id,
                    acknowledged_at="2026-07-19T19:03:00Z",
                    note="Reviewed source scope; no model rerun yet.",
                ),
            )
            with self.assertRaisesRegex(ValueError, "already acknowledged"):
                acknowledge_claim_notification(
                    outbox,
                    event_id,
                    acknowledged_at="2026-07-19T19:04:00Z",
                    note="Different acknowledgement",
                )
            listed = list_claim_notifications(outbox, status="acknowledged")
            self.assertEqual(1, listed["notification_count"])
            self.assertEqual(
                "Reviewed source scope; no model rerun yet.",
                listed["notifications"][0]["acknowledgement_note"],
            )

    def test_notification_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outbox = root / "notifications.sqlite3"
            sink = root / "notifications.jsonl"
            difference_path = root / "claim-diff.json"
            difference_path.write_text(
                json.dumps(_checked_diff(root), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "enqueue-claim-notifications",
                        "--outbox",
                        str(outbox),
                        "--diff",
                        str(difference_path),
                        "--created-at",
                        "2026-07-19T19:01:00Z",
                    ]
                )
            self.assertEqual(0, status)
            event_id = json.loads(output.getvalue())["event_ids"][0]

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "deliver-claim-notifications",
                        "--outbox",
                        str(outbox),
                        "--sink",
                        str(sink),
                        "--delivered-at",
                        "2026-07-19T19:02:00Z",
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual(4, json.loads(output.getvalue())["delivered_count"])

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "ack-claim-notification",
                        "--outbox",
                        str(outbox),
                        "--event-id",
                        event_id,
                        "--acknowledged-at",
                        "2026-07-19T19:03:00Z",
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual("acknowledged", json.loads(output.getvalue())["status"])

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "list-claim-notifications",
                        "--outbox",
                        str(outbox),
                        "--status",
                        "acknowledged",
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual(1, json.loads(output.getvalue())["notification_count"])

    def test_listing_missing_outbox_does_not_create_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outbox = Path(temporary) / "missing.sqlite3"
            with self.assertRaisesRegex(ValueError, "does not exist"):
                list_claim_notifications(outbox)
            self.assertFalse(outbox.exists())


if __name__ == "__main__":
    unittest.main()
