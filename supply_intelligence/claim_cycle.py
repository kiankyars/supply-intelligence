"""Scheduler-safe claim ingestion cycles with frozen prior snapshots."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .claim_ledger import (
    INGEST_PACK_FORMAT,
    diff_claim_snapshot_documents,
    ingest_claim_pack,
    query_claim_snapshot,
)
from .notifications import (
    deliver_claim_notifications_to_jsonl,
    enqueue_claim_notifications,
)


CLAIM_CYCLE_FORMAT = "ai-supply-claim-cycle.v1"
CLAIM_CYCLE_CHECKPOINT_FORMAT = "ai-supply-claim-cycle-checkpoint.v1"
CLAIM_CYCLE_RUN_FORMAT = "ai-supply-claim-cycle-run.v1"
CLAIM_CYCLE_RELEASE_FORMAT = "ai-supply-claim-cycle-release.v1"
CLAIM_CYCLE_RESULT_FORMAT = "ai-supply-claim-cycle-result.v1"
JOB_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


@dataclass(frozen=True)
class ClaimCyclePack:
    relative_path: str
    path: Path
    expected_sha256: str
    recorded_at: str
    raw: bytes


@dataclass(frozen=True)
class ClaimCycleJob:
    job_id: str
    valid_at: str
    baseline_known_at: str
    minimum_interval_minutes: int
    packs: tuple[ClaimCyclePack, ...]
    source_path: Path
    source_raw: bytes
    source_sha256: str


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _timestamp(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalized_timestamp(value: str, path: str) -> str:
    return _timestamp(value, path).isoformat().replace("+00:00", "Z")


def _read_json(raw: bytes, path: str) -> Mapping[str, Any]:
    try:
        return _mapping(json.loads(raw), path)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def load_claim_cycle(path: str | Path) -> ClaimCycleJob:
    source_path = Path(path)
    source_raw = source_path.read_bytes()
    document = _read_json(source_raw, str(source_path))
    if document.get("format") != CLAIM_CYCLE_FORMAT:
        raise ValueError(f"claim cycle format must be {CLAIM_CYCLE_FORMAT}")
    _only(
        document,
        {"format", "job_id", "valid_at", "baseline_known_at", "schedule", "packs"},
        "claim cycle",
    )
    job_id = _required_text(document.get("job_id"), "job_id")
    if JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise ValueError("job_id must be a lowercase filesystem-safe identifier")
    valid_at = _required_text(document.get("valid_at"), "valid_at")
    try:
        valid_at = date.fromisoformat(valid_at).isoformat()
    except ValueError as exc:
        raise ValueError("valid_at must be an ISO date") from exc
    baseline_known_at = _normalized_timestamp(
        _required_text(document.get("baseline_known_at"), "baseline_known_at"),
        "baseline_known_at",
    )
    schedule = _mapping(document.get("schedule"), "schedule")
    _only(schedule, {"minimum_interval_minutes"}, "schedule")
    interval = schedule.get("minimum_interval_minutes")
    if isinstance(interval, bool) or not isinstance(interval, int):
        raise ValueError("schedule.minimum_interval_minutes must be an integer")
    if not 1 <= interval <= 525_600:
        raise ValueError("schedule.minimum_interval_minutes must be between 1 and 525600")
    pack_values = document.get("packs")
    if not isinstance(pack_values, list) or not pack_values:
        raise ValueError("packs requires at least one pack")
    job_root = source_path.parent.resolve()
    packs = []
    seen_paths = set()
    seen_hashes = set()
    prior_recorded_at: datetime | None = None
    for index, value in enumerate(pack_values):
        item_path = f"packs[{index}]"
        item = _mapping(value, item_path)
        _only(item, {"path", "expected_sha256"}, item_path)
        relative_text = _required_text(item.get("path"), f"{item_path}.path")
        relative = Path(relative_text)
        if relative.is_absolute():
            raise ValueError(f"{item_path}.path must be relative to the job")
        resolved = (source_path.parent / relative).resolve()
        try:
            resolved.relative_to(job_root)
        except ValueError as exc:
            raise ValueError(f"{item_path}.path escapes the job directory") from exc
        if resolved in seen_paths:
            raise ValueError("claim cycle pack paths must be unique")
        seen_paths.add(resolved)
        raw = resolved.read_bytes()
        actual_sha256 = _sha256(raw)
        expected_sha256 = _required_text(
            item.get("expected_sha256"),
            f"{item_path}.expected_sha256",
        )
        if actual_sha256 != expected_sha256:
            raise ValueError(f"{item_path} SHA-256 mismatch")
        if expected_sha256 in seen_hashes:
            raise ValueError("claim cycle pack hashes must be unique")
        seen_hashes.add(expected_sha256)
        pack_document = _read_json(raw, str(resolved))
        if pack_document.get("format") != INGEST_PACK_FORMAT:
            raise ValueError(f"{item_path} is not an {INGEST_PACK_FORMAT} document")
        recorded_at = _normalized_timestamp(
            _required_text(pack_document.get("recorded_at"), f"{item_path}.recorded_at"),
            f"{item_path}.recorded_at",
        )
        recorded_timestamp = _timestamp(recorded_at, f"{item_path}.recorded_at")
        if prior_recorded_at is not None and recorded_timestamp < prior_recorded_at:
            raise ValueError("claim cycle packs must be ordered by recorded_at")
        prior_recorded_at = recorded_timestamp
        packs.append(
            ClaimCyclePack(
                relative_path=relative_text,
                path=resolved,
                expected_sha256=expected_sha256,
                recorded_at=recorded_at,
                raw=raw,
            )
        )
    return ClaimCycleJob(
        job_id=job_id,
        valid_at=valid_at,
        baseline_known_at=baseline_known_at,
        minimum_interval_minutes=interval,
        packs=tuple(packs),
        source_path=source_path.resolve(),
        source_raw=source_raw,
        source_sha256=_sha256(source_raw),
    )


def _load_checkpoint(path: Path, job: ClaimCycleJob) -> dict[str, Any] | None:
    if not path.exists():
        return None
    document = dict(_read_json(path.read_bytes(), str(path)))
    _only(
        document,
        {
            "format",
            "job_id",
            "valid_at",
            "last_successful_run_at",
            "cycle_id",
            "release_dir",
            "current_snapshot_sha256",
            "processed_pack_sha256",
        },
        "checkpoint",
    )
    if document.get("format") != CLAIM_CYCLE_CHECKPOINT_FORMAT:
        raise ValueError(f"unsupported claim-cycle checkpoint: {path}")
    if document.get("job_id") != job.job_id:
        raise ValueError("claim-cycle checkpoint job_id does not match")
    if document.get("valid_at") != job.valid_at:
        raise ValueError("claim-cycle checkpoint valid_at does not match")
    document["last_successful_run_at"] = _normalized_timestamp(
        _required_text(
            document.get("last_successful_run_at"),
            "checkpoint.last_successful_run_at",
        ),
        "checkpoint.last_successful_run_at",
    )
    _required_text(document.get("cycle_id"), "checkpoint.cycle_id")
    _required_text(document.get("release_dir"), "checkpoint.release_dir")
    snapshot_hash = _required_text(
        document.get("current_snapshot_sha256"),
        "checkpoint.current_snapshot_sha256",
    )
    if len(snapshot_hash) != 64:
        raise ValueError("checkpoint.current_snapshot_sha256 must be SHA-256")
    processed = document.get("processed_pack_sha256")
    if not isinstance(processed, list) or not all(
        isinstance(item, str) and len(item) == 64 for item in processed
    ):
        raise ValueError("checkpoint.processed_pack_sha256 must be a SHA-256 array")
    if len(processed) != len(set(processed)):
        raise ValueError("checkpoint.processed_pack_sha256 contains duplicates")
    return document


def _load_frozen_snapshot(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_path = Path(checkpoint["release_dir"]) / "current_snapshot.json"
    content = snapshot_path.read_bytes()
    if _sha256(content) != checkpoint["current_snapshot_sha256"]:
        raise ValueError("prior frozen claim snapshot SHA-256 mismatch")
    snapshot = dict(_read_json(content, str(snapshot_path)))
    if snapshot.get("known_at") != checkpoint["last_successful_run_at"]:
        raise ValueError("prior frozen claim snapshot known_at does not match checkpoint")
    return snapshot


@contextmanager
def _job_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"claim cycle is already running: {path.stem}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_durable(path: Path, content: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _verify_existing_release(
    destination: Path,
    payloads: Mapping[str, bytes],
    cycle_id: str,
) -> dict[str, Any]:
    manifest_path = destination / "manifest.json"
    manifest = dict(_read_json(manifest_path.read_bytes(), str(manifest_path)))
    if manifest.get("format") != CLAIM_CYCLE_RELEASE_FORMAT:
        raise ValueError(f"existing cycle release has the wrong format: {destination}")
    if manifest.get("cycle_id") != cycle_id:
        raise ValueError(f"existing cycle release has the wrong cycle ID: {destination}")
    files = _mapping(manifest.get("files"), "manifest.files")
    if set(files) != set(payloads):
        raise ValueError(f"existing cycle release payload set differs: {destination}")
    for name, expected_content in payloads.items():
        actual = (destination / name).read_bytes()
        if actual != expected_content:
            raise ValueError(f"existing cycle release payload differs: {name}")
        metadata = _mapping(files[name], f"manifest.files.{name}")
        if metadata.get("bytes") != len(actual) or metadata.get("sha256") != _sha256(actual):
            raise ValueError(f"existing cycle release manifest mismatch: {name}")
    return manifest


def _write_cycle_release(
    destination: Path,
    payloads: Mapping[str, bytes],
    *,
    cycle_id: str,
    job_id: str,
    run_at: str,
) -> dict[str, Any]:
    if destination.exists():
        return _verify_existing_release(destination, payloads, cycle_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".claim-cycle-", dir=str(destination.parent))
    )
    try:
        for name, content in payloads.items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_durable(target, content)
        manifest = {
            "format": CLAIM_CYCLE_RELEASE_FORMAT,
            "cycle_id": cycle_id,
            "job_id": job_id,
            "run_at": run_at,
            "files": {
                name: {"bytes": len(content), "sha256": _sha256(content)}
                for name, content in sorted(payloads.items())
            },
        }
        _write_durable(temporary / "manifest.json", _json_bytes(manifest))
        os.replace(temporary, destination)
        return manifest
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _write_checkpoint(path: Path, checkpoint: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(_json_bytes(checkpoint))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _stable_ingest_results(
    job: ClaimCycleJob,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": "ai-supply-claim-cycle-ingest-lineage.v1",
        "packs": [
            {
                "sequence": index,
                "job_relative_path": pack.relative_path,
                "pack_sha256": pack.expected_sha256,
                "recorded_at": result["recorded_at"],
                "run_id": result["run_id"],
                "source_count": result["source_count"],
                "claim_count": result["claim_count"],
            }
            for index, (pack, result) in enumerate(zip(job.packs, results, strict=True))
        ],
    }


def _release_directory_name(run_at: str, job_id: str, cycle_id: str) -> str:
    timestamp = run_at.replace("-", "").replace(":", "")
    return f"{timestamp}-{job_id}-{cycle_id.removeprefix('claim-cycle:')[:10]}"


def run_claim_cycle(
    job_path: str | Path,
    *,
    database: str | Path,
    outbox: str | Path,
    state_dir: str | Path,
    release_root: str | Path,
    run_at: str,
    force: bool = False,
    notification_sink: str | Path | None = None,
) -> dict[str, Any]:
    job = load_claim_cycle(job_path)
    run_timestamp = _normalized_timestamp(run_at, "run_at")
    run_datetime = _timestamp(run_timestamp, "run_at")
    state_root = Path(state_dir)
    checkpoint_path = state_root / "checkpoints" / f"{job.job_id}.json"
    lock_path = state_root / "locks" / f"{job.job_id}.lock"
    with _job_lock(lock_path):
        checkpoint = _load_checkpoint(checkpoint_path, job)
        if checkpoint is None:
            previous_known_at = job.baseline_known_at
            processed_pack_hashes: set[str] = set()
        else:
            previous_known_at = checkpoint["last_successful_run_at"]
            processed_pack_hashes = set(checkpoint["processed_pack_sha256"])
            prior_run = _timestamp(previous_known_at, "checkpoint.last_successful_run_at")
            if run_datetime <= prior_run:
                raise ValueError("run_at must follow the last successful cycle")
            due_at_datetime = prior_run + timedelta(
                minutes=job.minimum_interval_minutes
            )
            if not force and run_datetime < due_at_datetime:
                return {
                    "format": CLAIM_CYCLE_RESULT_FORMAT,
                    "status": "not_due",
                    "job_id": job.job_id,
                    "run_at": run_timestamp,
                    "last_successful_run_at": previous_known_at,
                    "next_due_at": due_at_datetime.isoformat().replace("+00:00", "Z"),
                }
        if run_datetime <= _timestamp(previous_known_at, "previous_known_at"):
            raise ValueError("run_at must follow the previous known-time cutoff")
        for pack in job.packs:
            pack_recorded = _timestamp(pack.recorded_at, f"pack {pack.relative_path}")
            if pack_recorded > run_datetime:
                raise ValueError(
                    f"pack {pack.relative_path} is recorded after the cycle run_at"
                )
            if (
                pack.expected_sha256 not in processed_pack_hashes
                and pack_recorded <= _timestamp(previous_known_at, "previous_known_at")
            ):
                raise ValueError(
                    f"new pack {pack.relative_path} is not later than the prior checkpoint"
                )
        if checkpoint is None:
            previous_snapshot = None
        else:
            previous_snapshot = _load_frozen_snapshot(checkpoint)
            if previous_snapshot.get("valid_at") != job.valid_at:
                raise ValueError("prior frozen claim snapshot valid_at does not match job")

        ingest_results = [
            ingest_claim_pack(database, pack.path) for pack in job.packs
        ]
        if previous_snapshot is None:
            previous_snapshot = query_claim_snapshot(
                database,
                valid_at=job.valid_at,
                known_at=previous_known_at,
            )
        current_snapshot = query_claim_snapshot(
            database,
            valid_at=job.valid_at,
            known_at=run_timestamp,
        )
        claim_diff = diff_claim_snapshot_documents(
            previous_snapshot,
            current_snapshot,
        )
        notification_result = enqueue_claim_notifications(
            outbox,
            claim_diff,
            created_at=run_timestamp,
        )
        previous_bytes = _json_bytes(previous_snapshot)
        current_bytes = _json_bytes(current_snapshot)
        diff_bytes = _json_bytes(claim_diff)
        cycle_identity = {
            "job_sha256": job.source_sha256,
            "job_id": job.job_id,
            "run_at": run_timestamp,
            "previous_snapshot_sha256": _sha256(previous_bytes),
            "current_snapshot_sha256": _sha256(current_bytes),
            "claim_diff_sha256": _sha256(diff_bytes),
        }
        cycle_id = f"claim-cycle:{_digest(cycle_identity)[:32]}"
        stable_notifications = {
            "format": "ai-supply-claim-cycle-notification-lineage.v1",
            "created_at": run_timestamp,
            "event_count": len(notification_result["event_ids"]),
            "event_ids": notification_result["event_ids"],
        }
        run_document = {
            "format": CLAIM_CYCLE_RUN_FORMAT,
            "cycle_id": cycle_id,
            "job_id": job.job_id,
            "run_at": run_timestamp,
            "previous_known_at": previous_snapshot["known_at"],
            "current_known_at": current_snapshot["known_at"],
            "pack_count": len(job.packs),
            "claim_count": current_snapshot["claim_count"],
            "alert_count": claim_diff["alert_count"],
            "job_sha256": job.source_sha256,
        }
        payloads: dict[str, bytes] = {
            "job.json": job.source_raw,
            "run.json": _json_bytes(run_document),
            "ingest_lineage.json": _json_bytes(
                _stable_ingest_results(job, ingest_results)
            ),
            "previous_snapshot.json": previous_bytes,
            "current_snapshot.json": current_bytes,
            "claim_diff.json": diff_bytes,
            "notification_lineage.json": _json_bytes(stable_notifications),
        }
        for index, pack in enumerate(job.packs):
            payloads[f"packs/{index:03d}-{pack.path.name}"] = pack.raw
        release_dir = (
            Path(release_root)
            / job.job_id
            / _release_directory_name(run_timestamp, job.job_id, cycle_id)
        ).resolve()
        manifest = _write_cycle_release(
            release_dir,
            payloads,
            cycle_id=cycle_id,
            job_id=job.job_id,
            run_at=run_timestamp,
        )
        delivery_result = None
        if notification_sink is not None:
            delivery_result = deliver_claim_notifications_to_jsonl(
                outbox,
                notification_sink,
                delivered_at=run_timestamp,
                limit=10_000,
            )
        processed_pack_hashes.update(
            pack.expected_sha256 for pack in job.packs
        )
        checkpoint_document = {
            "format": CLAIM_CYCLE_CHECKPOINT_FORMAT,
            "job_id": job.job_id,
            "valid_at": job.valid_at,
            "last_successful_run_at": run_timestamp,
            "cycle_id": cycle_id,
            "release_dir": str(release_dir),
            "current_snapshot_sha256": _sha256(current_bytes),
            "processed_pack_sha256": sorted(processed_pack_hashes),
        }
        _write_checkpoint(checkpoint_path, checkpoint_document)
        next_due_at = (
            run_datetime + timedelta(minutes=job.minimum_interval_minutes)
        ).isoformat().replace("+00:00", "Z")
        return {
            "format": CLAIM_CYCLE_RESULT_FORMAT,
            "status": "completed",
            "job_id": job.job_id,
            "cycle_id": cycle_id,
            "run_at": run_timestamp,
            "next_due_at": next_due_at,
            "release_dir": str(release_dir),
            "release_file_count": len(manifest["files"]),
            "ingest_results": ingest_results,
            "claim_count": current_snapshot["claim_count"],
            "alert_count": claim_diff["alert_count"],
            "notification_enqueue": notification_result,
            "notification_delivery": delivery_result,
        }
