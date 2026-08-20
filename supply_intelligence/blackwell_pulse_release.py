"""Deterministic, immutable release writer for the Blackwell weekly pulse."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .blackwell_pulse import (
    CLASSIFICATIONS,
    NO_EVIDENCE_BACKED_ESTIMATE,
    PRODUCT,
    TARGET_QUARTER,
    build_blackwell_pulse,
    load_synthetic_input_audit,
)
from .upstream_release import (
    _open_directory_path,
    ensure_not_upstream_worktree_path,
    load_cached_release,
    load_upstream_release_lock,
)


PULSE_CONFIG_FORMAT = "ai-supply-blackwell-constraint-pulse-config.v1"
PULSE_RELEASE_FORMAT = "ai-supply-blackwell-constraint-pulse-release.v1"
CLAIM_CLASSIFICATIONS_FORMAT = "ai-supply-blackwell-claim-classifications.v1"


@dataclass(frozen=True, slots=True)
class BlackwellPulseConfig:
    pulse_id: str
    target_quarter: str
    week_ending: str
    recorded_at: str
    raw: bytes
    sha256: str


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    actual = set(value)
    if actual != fields:
        raise ValueError(
            f"{path} fields must be exact; "
            f"missing={sorted(fields - actual)}, unexpected={sorted(actual - fields)}"
        )


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be non-empty text")
    return value


def _read_json_object(raw: bytes, path: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path} contains duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except ValueError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path} must be valid UTF-8 JSON") from exc
    return _mapping(value, path)


def _normalized_timestamp(value: Any, path: str) -> str:
    text = _required_text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_blackwell_pulse_config(path: str | Path) -> BlackwellPulseConfig:
    """Load a frozen weekly cutoff; no wall-clock values are introduced."""

    source = ensure_not_upstream_worktree_path(path, "pulse config")
    raw = source.read_bytes()
    document = _read_json_object(raw, str(source))
    _only(
        document,
        {"format", "pulse_id", "target_quarter", "week_ending", "recorded_at"},
        "pulse config",
    )
    if document["format"] != PULSE_CONFIG_FORMAT:
        raise ValueError(f"pulse config format must be {PULSE_CONFIG_FORMAT}")
    if document["target_quarter"] != TARGET_QUARTER:
        raise ValueError(f"pulse config target_quarter must be {TARGET_QUARTER}")
    week_ending = _required_text(document["week_ending"], "pulse config.week_ending")
    try:
        week = date.fromisoformat(week_ending)
    except ValueError as exc:
        raise ValueError("pulse config.week_ending must be an ISO date") from exc
    if week.weekday() != 6:
        raise ValueError("pulse config.week_ending must be a Sunday")
    if not date(2026, 10, 1) <= week <= date(2026, 12, 31):
        raise ValueError("pulse config.week_ending must fall in 2026-Q4")
    pulse_id = _required_text(document["pulse_id"], "pulse config.pulse_id")
    expected_id = f"blackwell-constraint-pulse:{week_ending}"
    if pulse_id != expected_id:
        raise ValueError(f"pulse config.pulse_id must be {expected_id}")
    recorded_at = _normalized_timestamp(
        document["recorded_at"],
        "pulse config.recorded_at",
    )
    if datetime.fromisoformat(recorded_at.replace("Z", "+00:00")).date() < week:
        raise ValueError("pulse config.recorded_at cannot precede week_ending")
    return BlackwellPulseConfig(
        pulse_id=pulse_id,
        target_quarter=TARGET_QUARTER,
        week_ending=week_ending,
        recorded_at=recorded_at,
        raw=raw,
        sha256=_sha256(raw),
    )


def build_blackwell_pulse_release_documents(
    config_path: str | Path,
    lock_path: str | Path,
    cache_root: str | Path,
    synthetic_audit_path: str | Path,
) -> dict[str, bytes]:
    """Build a byte-stable pulse bundle from verified cache objects only."""

    config = load_blackwell_pulse_config(config_path)
    lock = load_upstream_release_lock(lock_path)
    audit = load_synthetic_input_audit(synthetic_audit_path)
    releases = [
        load_cached_release(entry, cache_root)
        for entry in lock.upstreams
    ]
    pulse = build_blackwell_pulse(
        audit,
        releases,
        week_ending=config.week_ending,
        recorded_at=config.recorded_at,
        lock_sha256=lock.sha256,
    )
    if pulse["id"] != config.pulse_id:
        raise ValueError("pulse output ID does not match its frozen configuration")

    counts = Counter(
        assessment["classification"]
        for assessment in pulse["claim_assessments"]
    )
    classifications = {
        "format": CLAIM_CLASSIFICATIONS_FORMAT,
        "pulse_id": config.pulse_id,
        "classification_counts": {
            name: counts.get(name, 0) for name in sorted(CLASSIFICATIONS)
        },
        "assessments": pulse["claim_assessments"],
    }
    result_summary = (
        pulse["supply_to_site_estimate"]
        if isinstance(pulse["supply_to_site_estimate"], str)
        else "evidence gates passed; inspect pulse.json"
    )
    readme = (
        "# Supply Intelligence — Blackwell Constraint Pulse v1\n\n"
        f"Target quarter: `{TARGET_QUARTER}`. Week ending: `{config.week_ending}`. "
        f"Recorded at: `{config.recorded_at}`.\n\n"
        "Supply-to-site result: `"
        f"{result_summary}`\n\n"
        "`pulse.json` answers what changed, which synthetic inputs have eligible evidence "
        "candidates, and what remains unknowable. An eligible candidate is not applied: "
        "the checked synthetic-input audit remains explicitly synthetic. Change statuses are "
        "upstream-reported; v1 does not locally replay prior release assets.\n\n"
        "`claim-classifications.json` assigns exactly one of the five allowed evidence "
        "classes to every assessed claim or missing required target. "
        "`upstream-releases.lock.json` "
        "pins immutable public release lineage; upstream payloads are not republished here.\n\n"
        f"When any numerical evidence gate is unresolved, the result is exactly "
        f"`{NO_EVIDENCE_BACKED_ESTIMATE}`\n"
    ).encode("utf-8")

    payloads = {
        "README.md": readme,
        "claim-classifications.json": _json_bytes(classifications),
        "pulse-config.json": config.raw,
        "pulse.json": _json_bytes(pulse),
        "synthetic-input-audit.json": audit.raw,
        "upstream-releases.lock.json": lock.raw,
    }
    manifest = {
        "format": PULSE_RELEASE_FORMAT,
        "pulse_id": config.pulse_id,
        "product": PRODUCT,
        "target_quarter": TARGET_QUARTER,
        "week_ending": config.week_ending,
        "recorded_at": config.recorded_at,
        "supply_to_site_estimate": pulse["supply_to_site_estimate"],
        "input_hashes": {
            "pulse_config_sha256": config.sha256,
            "synthetic_input_audit_sha256": audit.sha256,
            "synthetic_input_audit_semantic_sha256": audit.semantic_sha256,
            "upstream_release_lock_sha256": lock.sha256,
        },
        "files": {
            name: {"bytes": len(raw), "sha256": _sha256(raw)}
            for name, raw in sorted(payloads.items())
        },
    }
    payloads["manifest.json"] = _json_bytes(manifest)
    return payloads


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW_ANY", os.O_NOFOLLOW)
_DARWIN_RENAME_EXCL = 0x04
_DARWIN_RENAME_NOFOLLOW_ANY = 0x10
_DARWIN_RENAME_RESOLVE_BENEATH = 0x20
_LINUX_RENAME_NOREPLACE = 0x01


def _write_durable_at(directory_descriptor: int, name: str, raw: bytes) -> None:
    descriptor = os.open(
        name,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_descriptor,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_regular_at(directory_descriptor: int, name: str) -> bytes:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY
            | os.O_CLOEXEC
            | os.O_NONBLOCK
            | _FILE_NOFOLLOW_FLAG,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise ValueError(f"existing pulse release contains an unsafe file: {name}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(
                f"existing pulse release contains a non-regular file: {name}"
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _verify_existing_release_at(
    parent_descriptor: int,
    destination_name: str,
    expected: Mapping[str, bytes],
) -> Mapping[str, Any]:
    try:
        destination_descriptor = os.open(
            destination_name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        raise ValueError(
            "existing pulse release is not a no-follow regular directory"
        ) from exc
    try:
        try:
            actual_files = set(os.listdir(destination_descriptor))
        except OSError as exc:
            raise ValueError("unable to enumerate existing pulse release") from exc
        if actual_files != set(expected):
            raise ValueError("existing pulse release file set differs")
        for name, expected_raw in expected.items():
            if _read_regular_at(destination_descriptor, name) != expected_raw:
                raise ValueError(f"existing pulse release payload differs: {name}")
        return _mapping(
            _read_json_object(expected["manifest.json"], "manifest.json"),
            "manifest.json",
        )
    finally:
        os.close(destination_descriptor)


def _rename_directory_exclusive(
    parent_descriptor: int,
    source_name: str,
    destination_name: str,
) -> None:
    """Publish a directory atomically without ever replacing a destination."""

    for name in (source_name, destination_name):
        if not name or name in {".", ".."} or "/" in name or "\0" in name:
            raise ValueError("release rename names must be safe relative components")
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_name)
    destination = os.fsencode(destination_name)
    if sys.platform == "darwin":
        rename = libc.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = rename(
            parent_descriptor,
            source,
            parent_descriptor,
            destination,
            _DARWIN_RENAME_EXCL
            | _DARWIN_RENAME_NOFOLLOW_ANY
            | _DARWIN_RENAME_RESOLVE_BENEATH,
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        ctypes.set_errno(0)
        result = rename(
            parent_descriptor,
            source,
            parent_descriptor,
            destination,
            _LINUX_RENAME_NOREPLACE,
        )
    else:
        raise OSError(
            errno.ENOTSUP,
            "no atomic no-replace directory rename is available",
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            os.strerror(error_number),
            destination_name,
        )
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _remove_temporary_release(
    parent_descriptor: int,
    temporary_descriptor: int,
    temporary_name: str,
) -> None:
    try:
        names = os.listdir(temporary_descriptor)
    except OSError:
        names = []
    for name in names:
        try:
            os.unlink(name, dir_fd=temporary_descriptor)
        except OSError:
            pass
    try:
        os.rmdir(temporary_name, dir_fd=parent_descriptor)
    except OSError:
        pass


def write_blackwell_pulse_release(
    config_path: str | Path,
    lock_path: str | Path,
    cache_root: str | Path,
    synthetic_audit_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Validate all inputs, then atomically write or verify an immutable release."""

    payloads = build_blackwell_pulse_release_documents(
        config_path,
        lock_path,
        cache_root,
        synthetic_audit_path,
    )
    destination = ensure_not_upstream_worktree_path(output_dir, "pulse output")
    if destination == destination.parent or not destination.name:
        raise ValueError("pulse output must name a directory below its parent")
    parent_descriptor = _open_directory_path(
        destination.parent,
        create=True,
        missing_message="pulse output parent is missing",
        error_message="unable to open pulse output parent",
        symlink_message=(
            "pulse output parent cannot contain symbolic links or non-directories"
        ),
    )
    temporary_name = f".blackwell-pulse-{os.urandom(16).hex()}"
    temporary_descriptor = -1
    temporary_created = False
    published = False
    try:
        os.mkdir(temporary_name, mode=0o700, dir_fd=parent_descriptor)
        temporary_created = True
        temporary_descriptor = os.open(
            temporary_name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )
        for name, raw in sorted(payloads.items()):
            _write_durable_at(temporary_descriptor, name, raw)
        os.fsync(temporary_descriptor)
        try:
            _rename_directory_exclusive(
                parent_descriptor,
                temporary_name,
                destination.name,
            )
            published = True
            manifest = _mapping(
                _read_json_object(payloads["manifest.json"], "manifest.json"),
                "manifest.json",
            )
        except FileExistsError:
            manifest = _verify_existing_release_at(
                parent_descriptor,
                destination.name,
                payloads,
            )
        try:
            os.fsync(parent_descriptor)
        except OSError as exc:
            if published:
                raise OSError(
                    exc.errno,
                    "pulse release was published but parent durability sync failed; "
                    "retry the same build to verify the committed release",
                    str(destination),
                ) from exc
            raise
        return {"output_dir": str(destination), **manifest}
    finally:
        if not published and temporary_created:
            if temporary_descriptor >= 0:
                _remove_temporary_release(
                    parent_descriptor,
                    temporary_descriptor,
                    temporary_name,
                )
            else:
                try:
                    os.rmdir(temporary_name, dir_fd=parent_descriptor)
                except OSError:
                    pass
            try:
                os.fsync(parent_descriptor)
            except OSError:
                pass
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        os.close(parent_descriptor)
