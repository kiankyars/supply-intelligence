"""Durable local notification outbox for claim-level changes."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .claim_ledger import CLAIM_DIFF_FORMAT


NOTIFICATION_EVENT_FORMAT = "ai-supply-notification.v1"
NOTIFICATION_BATCH_FORMAT = "ai-supply-notification-batch.v1"
NOTIFICATION_ENQUEUE_FORMAT = "ai-supply-notification-enqueue-result.v1"
NOTIFICATION_DELIVERY_FORMAT = "ai-supply-notification-delivery-result.v1"
NOTIFICATION_ACK_FORMAT = "ai-supply-notification-acknowledgement.v1"
NOTIFICATION_STATUSES = {"pending", "delivered", "acknowledged"}


OUTBOX_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS outbox_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_events (
  event_id TEXT PRIMARY KEY,
  alert_id TEXT NOT NULL UNIQUE,
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  claim_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  source_valid_at TEXT NOT NULL,
  source_previous_known_at TEXT NOT NULL,
  source_current_known_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'acknowledged')),
  delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS delivery_attempts (
  attempt_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES notification_events(event_id),
  sink_kind TEXT NOT NULL,
  sink_target TEXT NOT NULL,
  attempted_at TEXT NOT NULL,
  outcome TEXT NOT NULL,
  error TEXT
);
CREATE TABLE IF NOT EXISTS notification_acknowledgements (
  event_id TEXT PRIMARY KEY REFERENCES notification_events(event_id),
  acknowledged_at TEXT NOT NULL,
  note TEXT
);
CREATE INDEX IF NOT EXISTS notification_status_order
  ON notification_events (status, created_at, event_id);
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _optional_text(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{path} must be text or null")
    return value


def _normalize_timestamp(value: str, path: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _connect(
    outbox: str | Path,
    *,
    initialize: bool = False,
) -> sqlite3.Connection:
    outbox_path = Path(outbox)
    if initialize:
        outbox_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(outbox_path, isolation_level=None)
    else:
        if not outbox_path.is_file():
            raise ValueError(f"notification outbox does not exist: {outbox_path}")
        connection = sqlite3.connect(
            f"{outbox_path.resolve().as_uri()}?mode=ro",
            uri=True,
            isolation_level=None,
        )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if initialize:
        connection.executescript(OUTBOX_SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO outbox_metadata(key, value) "
            "VALUES ('schema_version', '1')"
        )
    else:
        try:
            version = connection.execute(
                "SELECT value FROM outbox_metadata WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.Error as exc:
            connection.close()
            raise ValueError(f"invalid notification outbox schema: {outbox_path}") from exc
        if version is None or version["value"] != "1":
            connection.close()
            raise ValueError(f"unsupported notification outbox schema: {outbox_path}")
    return connection


def _validated_diff(diff: Mapping[str, Any]) -> dict[str, Any]:
    if diff.get("format") != CLAIM_DIFF_FORMAT:
        raise ValueError(f"claim diff format must be {CLAIM_DIFF_FORMAT}")
    allowed = {
        "format",
        "valid_at",
        "previous_known_at",
        "current_known_at",
        "alert_count",
        "alerts",
    }
    unexpected = set(diff) - allowed
    if unexpected:
        raise ValueError(f"unexpected claim diff fields: {sorted(unexpected)}")
    valid_at = _required_text(diff.get("valid_at"), "diff.valid_at")
    try:
        date.fromisoformat(valid_at)
    except ValueError as exc:
        raise ValueError("diff.valid_at must be an ISO date") from exc
    previous_known_at = _normalize_timestamp(
        _required_text(diff.get("previous_known_at"), "diff.previous_known_at"),
        "diff.previous_known_at",
    )
    current_known_at = _normalize_timestamp(
        _required_text(diff.get("current_known_at"), "diff.current_known_at"),
        "diff.current_known_at",
    )
    if current_known_at < previous_known_at:
        raise ValueError("diff.current_known_at cannot precede diff.previous_known_at")
    alerts = diff.get("alerts")
    if not isinstance(alerts, list):
        raise ValueError("diff.alerts must be an array")
    alert_count = diff.get("alert_count")
    if isinstance(alert_count, bool) or not isinstance(alert_count, int):
        raise ValueError("diff.alert_count must be an integer")
    if alert_count != len(alerts):
        raise ValueError("diff.alert_count does not match diff.alerts")
    validated_alerts = []
    seen = set()
    for index, value in enumerate(alerts):
        path = f"diff.alerts[{index}]"
        alert = _mapping(value, path)
        if set(alert) != {
            "id",
            "type",
            "severity",
            "claim_key",
            "previous",
            "current",
        }:
            raise ValueError(f"{path} has invalid fields")
        alert_id = _required_text(alert.get("id"), f"{path}.id")
        if alert_id in seen:
            raise ValueError("diff.alerts contains duplicate IDs")
        seen.add(alert_id)
        payload = {
            "type": _required_text(alert.get("type"), f"{path}.type"),
            "severity": _required_text(alert.get("severity"), f"{path}.severity"),
            "claim_key": _required_text(alert.get("claim_key"), f"{path}.claim_key"),
            "previous": alert.get("previous"),
            "current": alert.get("current"),
        }
        if payload["type"] not in {"claim_added", "claim_revised", "claim_removed"}:
            raise ValueError(f"{path}.type is not supported")
        expected_id = f"claim-alert:{_digest(payload)[:16]}"
        if alert_id != expected_id:
            raise ValueError(f"{path}.id does not match its payload")
        validated_alerts.append({"id": alert_id, **payload})
    return {
        "valid_at": valid_at,
        "previous_known_at": previous_known_at,
        "current_known_at": current_known_at,
        "alerts": validated_alerts,
    }


def enqueue_claim_notifications(
    outbox: str | Path,
    claim_diff: Mapping[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    diff = _validated_diff(claim_diff)
    created = _normalize_timestamp(created_at, "created_at")
    if created < diff["current_known_at"]:
        raise ValueError("created_at cannot precede the diff current_known_at")
    inserted = 0
    skipped = 0
    event_ids = []
    with closing(_connect(outbox, initialize=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for alert in diff["alerts"]:
                event_id = f"notification:{alert['id']}"
                payload = {
                    "format": NOTIFICATION_EVENT_FORMAT,
                    "event_id": event_id,
                    "source": {
                        "format": CLAIM_DIFF_FORMAT,
                        "valid_at": diff["valid_at"],
                        "previous_known_at": diff["previous_known_at"],
                        "current_known_at": diff["current_known_at"],
                    },
                    "alert": alert,
                }
                payload_json = _canonical(payload)
                payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                existing = connection.execute(
                    "SELECT payload_sha256 FROM notification_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_sha256"] != payload_sha256:
                        raise ValueError(f"notification event ID collision: {event_id}")
                    skipped += 1
                    event_ids.append(event_id)
                    continue
                connection.execute(
                    """
                    INSERT INTO notification_events(
                      event_id, alert_id, alert_type, severity, claim_key,
                      payload_json, payload_sha256, source_valid_at,
                      source_previous_known_at, source_current_known_at,
                      created_at, status, delivered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)
                    """,
                    (
                        event_id,
                        alert["id"],
                        alert["type"],
                        alert["severity"],
                        alert["claim_key"],
                        payload_json,
                        payload_sha256,
                        diff["valid_at"],
                        diff["previous_known_at"],
                        diff["current_known_at"],
                        created,
                    ),
                )
                inserted += 1
                event_ids.append(event_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "format": NOTIFICATION_ENQUEUE_FORMAT,
        "created_at": created,
        "source_alert_count": len(diff["alerts"]),
        "inserted": inserted,
        "skipped": skipped,
        "event_ids": event_ids,
    }


def _row_as_notification(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    return {
        **payload,
        "created_at": row["created_at"],
        "status": row["status"],
        "delivered_at": row["delivered_at"],
        "acknowledged_at": row["acknowledged_at"],
        "acknowledgement_note": row["acknowledgement_note"],
    }


def list_claim_notifications(
    outbox: str | Path,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    parameters: tuple[Any, ...] = ()
    condition = ""
    if status is not None:
        if status not in NOTIFICATION_STATUSES:
            raise ValueError(f"unsupported notification status: {status}")
        condition = "WHERE ne.status = ?"
        parameters = (status,)
    with closing(_connect(outbox)) as connection:
        rows = connection.execute(
            f"""
            SELECT ne.*, na.acknowledged_at,
                   na.note AS acknowledgement_note
            FROM notification_events ne
            LEFT JOIN notification_acknowledgements na USING (event_id)
            {condition}
            ORDER BY ne.created_at, ne.event_id
            """,
            parameters,
        ).fetchall()
        notifications = [_row_as_notification(row) for row in rows]
        counts = {item: 0 for item in sorted(NOTIFICATION_STATUSES)}
        for item in connection.execute(
            "SELECT status, COUNT(*) AS count FROM notification_events GROUP BY status"
        ).fetchall():
            counts[item["status"]] = item["count"]
    return {
        "format": NOTIFICATION_BATCH_FORMAT,
        "status_filter": status,
        "counts": counts,
        "notification_count": len(notifications),
        "notifications": notifications,
    }


def deliver_claim_notifications_to_jsonl(
    outbox: str | Path,
    sink: str | Path,
    *,
    delivered_at: str,
    limit: int = 100,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        raise ValueError("limit must be an integer between 1 and 10000")
    delivered = _normalize_timestamp(delivered_at, "delivered_at")
    sink_path = Path(sink)
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    delivered_ids = []
    with closing(_connect(outbox, initialize=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            rows = connection.execute(
                """
                SELECT * FROM notification_events
                WHERE status = 'pending'
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            for row in rows:
                if delivered < row["created_at"]:
                    raise ValueError(
                        f"delivered_at cannot precede created_at for {row['event_id']}"
                    )
            if rows:
                with sink_path.open("a", encoding="utf-8") as handle:
                    for row in rows:
                        envelope = {
                            **json.loads(row["payload_json"]),
                            "created_at": row["created_at"],
                            "delivered_at": delivered,
                        }
                        handle.write(_canonical(envelope) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            for row in rows:
                attempt_payload = {
                    "event_id": row["event_id"],
                    "sink_kind": "jsonl",
                    "sink_target": str(sink_path.resolve()),
                    "attempted_at": delivered,
                    "outcome": "delivered",
                }
                attempt_id = f"delivery:{_digest(attempt_payload)[:32]}"
                connection.execute(
                    """
                    INSERT INTO delivery_attempts(
                      attempt_id, event_id, sink_kind, sink_target,
                      attempted_at, outcome, error
                    ) VALUES (?, ?, 'jsonl', ?, ?, 'delivered', NULL)
                    """,
                    (
                        attempt_id,
                        row["event_id"],
                        str(sink_path.resolve()),
                        delivered,
                    ),
                )
                connection.execute(
                    """
                    UPDATE notification_events
                    SET status = 'delivered', delivered_at = ?
                    WHERE event_id = ? AND status = 'pending'
                    """,
                    (delivered, row["event_id"]),
                )
                delivered_ids.append(row["event_id"])
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "format": NOTIFICATION_DELIVERY_FORMAT,
        "sink_kind": "jsonl",
        "sink": str(sink_path.resolve()),
        "delivered_at": delivered,
        "delivered_count": len(delivered_ids),
        "event_ids": delivered_ids,
        "delivery_semantics": "at_least_once_with_event_id_deduplication",
    }


def acknowledge_claim_notification(
    outbox: str | Path,
    event_id: str,
    *,
    acknowledged_at: str,
    note: str | None = None,
) -> dict[str, Any]:
    identifier = _required_text(event_id, "event_id")
    acknowledged = _normalize_timestamp(acknowledged_at, "acknowledged_at")
    acknowledgement_note = _optional_text(note, "note")
    with closing(_connect(outbox, initialize=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            event = connection.execute(
                "SELECT * FROM notification_events WHERE event_id = ?",
                (identifier,),
            ).fetchone()
            if event is None:
                raise ValueError(f"unknown notification event: {identifier}")
            if acknowledged < event["created_at"]:
                raise ValueError("acknowledged_at cannot precede notification created_at")
            if event["delivered_at"] is not None and acknowledged < event["delivered_at"]:
                raise ValueError("acknowledged_at cannot precede notification delivered_at")
            existing = connection.execute(
                "SELECT * FROM notification_acknowledgements WHERE event_id = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["acknowledged_at"] != acknowledged
                    or existing["note"] != acknowledgement_note
                ):
                    raise ValueError(f"notification is already acknowledged: {identifier}")
            else:
                connection.execute(
                    """
                    INSERT INTO notification_acknowledgements(
                      event_id, acknowledged_at, note
                    ) VALUES (?, ?, ?)
                    """,
                    (identifier, acknowledged, acknowledgement_note),
                )
            connection.execute(
                "UPDATE notification_events SET status = 'acknowledged' WHERE event_id = ?",
                (identifier,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "format": NOTIFICATION_ACK_FORMAT,
        "event_id": identifier,
        "acknowledged_at": acknowledged,
        "note": acknowledgement_note,
        "status": "acknowledged",
    }
