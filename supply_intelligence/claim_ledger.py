"""Append-only source snapshots and bitemporal claim revisions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping


INGEST_PACK_FORMAT = "ai-supply-ingest-pack.v1"
CLAIM_SNAPSHOT_FORMAT = "ai-supply-claim-snapshot.v1"
CLAIM_DIFF_FORMAT = "ai-supply-claim-diff.v1"
CAPTURE_KINDS = {
    "raw_source",
    "normalized_observation",
    "structured_export",
    "model_result",
}
CLAIM_POSTURES = {"reported", "derived", "modeled", "synthetic"}
CLAIM_STATUSES = {"asserted", "retracted"}


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS ledger_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  content_sha256 TEXT NOT NULL,
  byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
  content BLOB NOT NULL,
  capture_kind TEXT NOT NULL,
  media_type TEXT NOT NULL,
  source_url TEXT NOT NULL,
  publisher TEXT NOT NULL,
  source_family TEXT,
  published_at TEXT,
  retrieved_at TEXT NOT NULL,
  license TEXT,
  UNIQUE (content_sha256, source_url, retrieved_at, capture_kind)
);
CREATE TABLE IF NOT EXISTS claim_revisions (
  revision_id TEXT PRIMARY KEY,
  claim_key TEXT NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  value_json TEXT,
  unit TEXT NOT NULL,
  posture TEXT NOT NULL,
  status TEXT NOT NULL,
  valid_from TEXT NOT NULL,
  valid_to TEXT,
  recorded_at TEXT NOT NULL,
  methodology TEXT NOT NULL,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  confirming_evidence TEXT NOT NULL,
  falsifying_evidence TEXT NOT NULL,
  supersedes_revision_id TEXT REFERENCES claim_revisions(revision_id),
  UNIQUE (claim_key, recorded_at)
);
CREATE TABLE IF NOT EXISTS claim_evidence (
  revision_id TEXT NOT NULL REFERENCES claim_revisions(revision_id),
  snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id),
  evidence_role TEXT NOT NULL,
  independence_group TEXT NOT NULL,
  PRIMARY KEY (revision_id, snapshot_id, evidence_role)
);
CREATE TABLE IF NOT EXISTS claim_dimensions (
  revision_id TEXT PRIMARY KEY REFERENCES claim_revisions(revision_id),
  dimensions_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id TEXT PRIMARY KEY,
  pack_sha256 TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  source_count INTEGER NOT NULL,
  claim_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS claim_revision_lookup
  ON claim_revisions (claim_key, recorded_at DESC, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS claim_evidence_revision
  ON claim_evidence (revision_id);
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


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


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    return value


def _only(data: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unexpected = set(data) - allowed
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _iso_timestamp(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed


def _normalized_timestamp(value: str, path: str) -> str:
    return (
        _iso_timestamp(value, path)
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _iso_date(value: str, path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _published_at(value: str | None, path: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
        return
    except ValueError as exc:
        try:
            _iso_timestamp(value, path)
        except ValueError:
            raise ValueError(f"{path} must be an ISO date or timezone-aware timestamp") from exc


def _connect(
    database: str | Path,
    *,
    initialize: bool = False,
) -> sqlite3.Connection:
    database_path = Path(database)
    if initialize:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, isolation_level=None)
    else:
        if not database_path.is_file():
            raise ValueError(f"claim ledger does not exist: {database_path}")
        connection = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro",
            uri=True,
            isolation_level=None,
        )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if initialize:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO ledger_metadata(key, value) VALUES ('schema_version', '1')"
        )
    else:
        try:
            version = connection.execute(
                "SELECT value FROM ledger_metadata WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.Error as exc:
            connection.close()
            raise ValueError(f"invalid claim ledger schema: {database_path}") from exc
        if version is None or version["value"] != "1":
            connection.close()
            raise ValueError(f"unsupported claim ledger schema: {database_path}")
    return connection


def _source_snapshot(
    source: Mapping[str, Any],
    path: str,
    pack_dir: Path,
) -> tuple[str, dict[str, Any], bytes]:
    _only(
        source,
        {
            "id",
            "content_file",
            "expected_sha256",
            "capture_kind",
            "media_type",
            "source_url",
            "publisher",
            "source_family",
            "published_at",
            "retrieved_at",
            "license",
        },
        path,
    )
    alias = _required_text(source.get("id"), f"{path}.id")
    content_file = _required_text(source.get("content_file"), f"{path}.content_file")
    relative = Path(content_file)
    if relative.is_absolute():
        raise ValueError(f"{path}.content_file must be relative to the pack")
    resolved_pack = pack_dir.resolve()
    resolved_content = (pack_dir / relative).resolve()
    try:
        resolved_content.relative_to(resolved_pack)
    except ValueError as exc:
        raise ValueError(f"{path}.content_file escapes the pack directory") from exc
    content = resolved_content.read_bytes()
    content_sha256 = hashlib.sha256(content).hexdigest()
    expected = _required_text(source.get("expected_sha256"), f"{path}.expected_sha256")
    if content_sha256 != expected:
        raise ValueError(f"{path} content SHA-256 mismatch")
    capture_kind = _required_text(source.get("capture_kind"), f"{path}.capture_kind")
    if capture_kind not in CAPTURE_KINDS:
        raise ValueError(f"{path}.capture_kind is not supported")
    published = _optional_text(source.get("published_at"), f"{path}.published_at")
    _published_at(published, f"{path}.published_at")
    retrieved = _normalized_timestamp(
        _required_text(source.get("retrieved_at"), f"{path}.retrieved_at"),
        f"{path}.retrieved_at",
    )
    metadata = {
        "content_sha256": content_sha256,
        "byte_count": len(content),
        "capture_kind": capture_kind,
        "media_type": _required_text(source.get("media_type"), f"{path}.media_type"),
        "source_url": _required_text(source.get("source_url"), f"{path}.source_url"),
        "publisher": _required_text(source.get("publisher"), f"{path}.publisher"),
        "source_family": _optional_text(source.get("source_family"), f"{path}.source_family"),
        "published_at": published,
        "retrieved_at": retrieved,
        "license": _optional_text(source.get("license"), f"{path}.license"),
    }
    snapshot_id = f"snapshot:{_digest(metadata)[:32]}"
    return alias, {"snapshot_id": snapshot_id, **metadata}, content


def _claim_revision(
    claim: Mapping[str, Any],
    path: str,
    recorded_at: str,
    source_aliases: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    _only(
        claim,
        {
            "claim_key",
            "subject",
            "predicate",
            "value",
            "unit",
            "dimensions",
            "posture",
            "status",
            "valid_from",
            "valid_to",
            "methodology",
            "confidence",
            "confirming_evidence",
            "falsifying_evidence",
            "supersedes_revision_id",
            "evidence",
        },
        path,
    )
    status = _required_text(claim.get("status"), f"{path}.status")
    if status not in CLAIM_STATUSES:
        raise ValueError(f"{path}.status is not supported")
    value = claim.get("value")
    if status == "asserted" and value is None:
        raise ValueError(f"{path}.value is required for an asserted claim")
    if status == "retracted" and value is not None:
        raise ValueError(f"{path}.value must be null for a retracted claim")
    posture = _required_text(claim.get("posture"), f"{path}.posture")
    if posture not in CLAIM_POSTURES:
        raise ValueError(f"{path}.posture is not supported")
    dimensions = _mapping(claim.get("dimensions"), f"{path}.dimensions")
    required_dimensions = {
        "entity_scope",
        "geography",
        "period",
        "stage",
        "capacity_basis",
        "quantity_semantics",
    }
    optional_dimensions = {
        "product",
        "process_node",
        "customer",
        "technology",
        "qualifier",
    }
    _only(
        dimensions,
        required_dimensions | optional_dimensions,
        f"{path}.dimensions",
    )
    for field in required_dimensions:
        _required_text(dimensions.get(field), f"{path}.dimensions.{field}")
    for field in optional_dimensions:
        if field in dimensions:
            _optional_text(dimensions[field], f"{path}.dimensions.{field}")
    valid_from = _required_text(claim.get("valid_from"), f"{path}.valid_from")
    start = _iso_date(valid_from, f"{path}.valid_from")
    valid_to = _optional_text(claim.get("valid_to"), f"{path}.valid_to")
    if valid_to is not None and _iso_date(valid_to, f"{path}.valid_to") <= start:
        raise ValueError(f"{path}.valid_to must follow valid_from")
    confidence = claim.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError(f"{path}.confidence must be numeric")
    confidence_value = float(confidence)
    if not 0 <= confidence_value <= 1:
        raise ValueError(f"{path}.confidence must be between zero and one")
    evidence_values = _list(claim.get("evidence"), f"{path}.evidence")
    if not evidence_values:
        raise ValueError(f"{path}.evidence requires at least one source")
    evidence = []
    seen_evidence = set()
    for index, evidence_value in enumerate(evidence_values):
        evidence_path = f"{path}.evidence[{index}]"
        item = _mapping(evidence_value, evidence_path)
        _only(item, {"source_id", "role", "independence_group"}, evidence_path)
        alias = _required_text(item.get("source_id"), f"{evidence_path}.source_id")
        if alias not in source_aliases:
            raise ValueError(f"{evidence_path} references an unknown source id")
        row = {
            "snapshot_id": source_aliases[alias],
            "evidence_role": _required_text(item.get("role"), f"{evidence_path}.role"),
            "independence_group": _required_text(
                item.get("independence_group"),
                f"{evidence_path}.independence_group",
            ),
        }
        identity = (row["snapshot_id"], row["evidence_role"])
        if identity in seen_evidence:
            raise ValueError(f"{path}.evidence contains a duplicate source and role")
        seen_evidence.add(identity)
        evidence.append(row)
    supersedes = _optional_text(
        claim.get("supersedes_revision_id"),
        f"{path}.supersedes_revision_id",
    )
    payload = {
        "claim_key": _required_text(claim.get("claim_key"), f"{path}.claim_key"),
        "subject": _required_text(claim.get("subject"), f"{path}.subject"),
        "predicate": _required_text(claim.get("predicate"), f"{path}.predicate"),
        "value_json": None if value is None else _canonical(value),
        "unit": _required_text(claim.get("unit"), f"{path}.unit"),
        "dimensions_json": _canonical(dict(dimensions)),
        "posture": posture,
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "recorded_at": recorded_at,
        "methodology": _required_text(claim.get("methodology"), f"{path}.methodology"),
        "confidence": confidence_value,
        "confirming_evidence": _required_text(
            claim.get("confirming_evidence"),
            f"{path}.confirming_evidence",
        ),
        "falsifying_evidence": _required_text(
            claim.get("falsifying_evidence"),
            f"{path}.falsifying_evidence",
        ),
        "supersedes_revision_id": supersedes,
    }
    revision_identity = {**payload, "evidence": sorted(evidence, key=_canonical)}
    payload["revision_id"] = f"claimrev:{_digest(revision_identity)[:32]}"
    return payload, evidence


def ingest_claim_pack(database: str | Path, pack_path: str | Path) -> dict[str, Any]:
    pack_source = Path(pack_path)
    pack_raw = pack_source.read_bytes()
    try:
        pack = _mapping(json.loads(pack_raw), "pack")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {pack_source}: {exc}") from exc
    if pack.get("format") != INGEST_PACK_FORMAT:
        raise ValueError(f"pack format must be {INGEST_PACK_FORMAT}")
    _only(pack, {"format", "recorded_at", "sources", "claims"}, "pack")
    recorded_at = _normalized_timestamp(
        _required_text(pack.get("recorded_at"), "pack.recorded_at"),
        "pack.recorded_at",
    )
    recorded_timestamp = _iso_timestamp(recorded_at, "pack.recorded_at")
    source_values = _list(pack.get("sources"), "pack.sources")
    claim_values = _list(pack.get("claims"), "pack.claims")
    if not source_values:
        raise ValueError("pack.sources requires at least one source")
    if not claim_values:
        raise ValueError("pack.claims requires at least one claim")

    snapshots = [
        _source_snapshot(
            _mapping(value, f"sources[{index}]"),
            f"sources[{index}]",
            pack_source.parent,
        )
        for index, value in enumerate(source_values)
    ]
    aliases = [alias for alias, _, _ in snapshots]
    if len(aliases) != len(set(aliases)):
        raise ValueError("pack source ids must be unique")
    source_aliases = {
        alias: metadata["snapshot_id"] for alias, metadata, _ in snapshots
    }
    for alias, metadata, _ in snapshots:
        if _iso_timestamp(
            metadata["retrieved_at"],
            f"source {alias}.retrieved_at",
        ) > recorded_timestamp:
            raise ValueError(
                f"source {alias}.retrieved_at cannot follow pack.recorded_at"
            )
    revisions = [
        _claim_revision(
            _mapping(value, f"claims[{index}]"),
            f"claims[{index}]",
            recorded_at,
            source_aliases,
        )
        for index, value in enumerate(claim_values)
    ]
    claim_keys = [revision["claim_key"] for revision, _ in revisions]
    if len(claim_keys) != len(set(claim_keys)):
        raise ValueError("a pack can contain only one revision per claim key")
    run_payload = {
        "pack_sha256": hashlib.sha256(pack_raw).hexdigest(),
        "recorded_at": recorded_at,
        "source_ids": sorted(source_aliases.values()),
        "revision_ids": sorted(revision["revision_id"] for revision, _ in revisions),
    }
    run_id = f"ingest:{_digest(run_payload)[:32]}"
    inserted_sources = 0
    inserted_claims = 0
    skipped_claims = 0

    with closing(_connect(database, initialize=True)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for _, metadata, content in snapshots:
                existing = connection.execute(
                    "SELECT * FROM source_snapshots WHERE snapshot_id = ?",
                    (metadata["snapshot_id"],),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO source_snapshots(
                          snapshot_id, content_sha256, byte_count, content,
                          capture_kind, media_type, source_url, publisher,
                          source_family, published_at, retrieved_at, license
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            metadata["snapshot_id"],
                            metadata["content_sha256"],
                            metadata["byte_count"],
                            content,
                            metadata["capture_kind"],
                            metadata["media_type"],
                            metadata["source_url"],
                            metadata["publisher"],
                            metadata["source_family"],
                            metadata["published_at"],
                            metadata["retrieved_at"],
                            metadata["license"],
                        ),
                    )
                    inserted_sources += 1
                elif bytes(existing["content"]) != content:
                    raise ValueError("source snapshot ID collision")

            for revision, evidence in revisions:
                existing = connection.execute(
                    "SELECT revision_id FROM claim_revisions WHERE revision_id = ?",
                    (revision["revision_id"],),
                ).fetchone()
                if existing is not None:
                    stored_dimensions = connection.execute(
                        "SELECT dimensions_json FROM claim_dimensions WHERE revision_id = ?",
                        (revision["revision_id"],),
                    ).fetchone()
                    if (
                        stored_dimensions is None
                        or stored_dimensions["dimensions_json"]
                        != revision["dimensions_json"]
                    ):
                        raise ValueError(
                            f"claim revision dimension mismatch: {revision['revision_id']}"
                        )
                    skipped_claims += 1
                    continue
                latest = connection.execute(
                    """
                    SELECT revision_id, recorded_at
                    FROM claim_revisions
                    WHERE claim_key = ?
                    ORDER BY julianday(recorded_at) DESC, revision_id DESC
                    LIMIT 1
                    """,
                    (revision["claim_key"],),
                ).fetchone()
                if latest is None:
                    if revision["supersedes_revision_id"] is not None:
                        raise ValueError(
                            f"first revision for {revision['claim_key']} cannot supersede another revision"
                        )
                else:
                    if revision["supersedes_revision_id"] != latest["revision_id"]:
                        raise ValueError(
                            f"revision for {revision['claim_key']} must supersede {latest['revision_id']}"
                        )
                    if recorded_timestamp <= _iso_timestamp(
                        latest["recorded_at"],
                        "latest.recorded_at",
                    ):
                        raise ValueError(
                            f"revision for {revision['claim_key']} must have a later recorded_at"
                        )
                columns = (
                    "revision_id",
                    "claim_key",
                    "subject",
                    "predicate",
                    "value_json",
                    "unit",
                    "posture",
                    "status",
                    "valid_from",
                    "valid_to",
                    "recorded_at",
                    "methodology",
                    "confidence",
                    "confirming_evidence",
                    "falsifying_evidence",
                    "supersedes_revision_id",
                )
                connection.execute(
                    f"INSERT INTO claim_revisions({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    tuple(revision[column] for column in columns),
                )
                connection.execute(
                    "INSERT INTO claim_dimensions(revision_id, dimensions_json) VALUES (?, ?)",
                    (revision["revision_id"], revision["dimensions_json"]),
                )
                for item in evidence:
                    connection.execute(
                        """
                        INSERT INTO claim_evidence(
                          revision_id, snapshot_id, evidence_role, independence_group
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            revision["revision_id"],
                            item["snapshot_id"],
                            item["evidence_role"],
                            item["independence_group"],
                        ),
                    )
                inserted_claims += 1
            connection.execute(
                """
                INSERT OR IGNORE INTO ingest_runs(
                  run_id, pack_sha256, recorded_at, source_count, claim_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_payload["pack_sha256"],
                    recorded_at,
                    len(snapshots),
                    len(revisions),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "format": "ai-supply-ingest-result.v1",
        "run_id": run_id,
        "pack_sha256": run_payload["pack_sha256"],
        "recorded_at": recorded_at,
        "source_count": len(snapshots),
        "claim_count": len(revisions),
        "inserted_sources": inserted_sources,
        "inserted_claims": inserted_claims,
        "skipped_claims": skipped_claims,
    }


def query_claim_snapshot(
    database: str | Path,
    *,
    valid_at: str,
    known_at: str,
    claim_key: str | None = None,
) -> dict[str, Any]:
    valid_date = _iso_date(valid_at, "valid_at").isoformat()
    known_timestamp = _normalized_timestamp(known_at, "known_at")
    parameters: list[Any] = [known_timestamp, valid_date, valid_date]
    claim_filter = ""
    if claim_key is not None:
        claim_filter = "AND claim_key = ?"
        parameters.append(_required_text(claim_key, "claim_key"))
    with closing(_connect(database)) as connection:
        rows = connection.execute(
            f"""
            WITH eligible AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY claim_key
                ORDER BY julianday(recorded_at) DESC, revision_id DESC
              ) AS revision_rank
              FROM claim_revisions
              WHERE julianday(recorded_at) <= julianday(?)
                AND valid_from <= ?
                AND (valid_to IS NULL OR ? < valid_to)
                {claim_filter}
            )
            SELECT * FROM eligible
            WHERE revision_rank = 1 AND status = 'asserted'
            ORDER BY claim_key
            """,
            parameters,
        ).fetchall()
        claims = []
        for row in rows:
            dimensions_row = connection.execute(
                "SELECT dimensions_json FROM claim_dimensions WHERE revision_id = ?",
                (row["revision_id"],),
            ).fetchone()
            if dimensions_row is None:
                raise ValueError(
                    f"claim revision is missing dimensions: {row['revision_id']}"
                )
            evidence_rows = connection.execute(
                """
                SELECT ce.evidence_role, ce.independence_group,
                       ss.snapshot_id, ss.content_sha256, ss.byte_count,
                       ss.capture_kind, ss.media_type, ss.source_url,
                       ss.publisher, ss.source_family, ss.published_at,
                       ss.retrieved_at, ss.license
                FROM claim_evidence ce
                JOIN source_snapshots ss USING (snapshot_id)
                WHERE ce.revision_id = ?
                ORDER BY ce.evidence_role, ss.snapshot_id
                """,
                (row["revision_id"],),
            ).fetchall()
            claims.append(
                {
                    "revision_id": row["revision_id"],
                    "claim_key": row["claim_key"],
                    "subject": row["subject"],
                    "predicate": row["predicate"],
                    "value": json.loads(row["value_json"]),
                    "unit": row["unit"],
                    "dimensions": json.loads(dimensions_row["dimensions_json"]),
                    "posture": row["posture"],
                    "valid_from": row["valid_from"],
                    "valid_to": row["valid_to"],
                    "recorded_at": row["recorded_at"],
                    "methodology": row["methodology"],
                    "confidence": row["confidence"],
                    "confirming_evidence": row["confirming_evidence"],
                    "falsifying_evidence": row["falsifying_evidence"],
                    "supersedes_revision_id": row["supersedes_revision_id"],
                    "evidence": [dict(item) for item in evidence_rows],
                }
            )
    return {
        "format": CLAIM_SNAPSHOT_FORMAT,
        "valid_at": valid_date,
        "known_at": known_timestamp,
        "claim_count": len(claims),
        "claims": claims,
    }


def diff_claim_snapshots(
    database: str | Path,
    *,
    valid_at: str,
    previous_known_at: str,
    current_known_at: str,
) -> dict[str, Any]:
    previous_timestamp = _iso_timestamp(previous_known_at, "previous_known_at")
    current_timestamp = _iso_timestamp(current_known_at, "current_known_at")
    if current_timestamp < previous_timestamp:
        raise ValueError("current_known_at cannot precede previous_known_at")
    previous = query_claim_snapshot(
        database,
        valid_at=valid_at,
        known_at=previous_known_at,
    )
    current = query_claim_snapshot(
        database,
        valid_at=valid_at,
        known_at=current_known_at,
    )
    return diff_claim_snapshot_documents(previous, current)


def diff_claim_snapshot_documents(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> dict[str, Any]:
    for label, snapshot in (("previous", previous), ("current", current)):
        if snapshot.get("format") != CLAIM_SNAPSHOT_FORMAT:
            raise ValueError(f"{label} snapshot format must be {CLAIM_SNAPSHOT_FORMAT}")
        claims = snapshot.get("claims")
        if not isinstance(claims, list):
            raise ValueError(f"{label} snapshot claims must be an array")
        if snapshot.get("claim_count") != len(claims):
            raise ValueError(f"{label} snapshot claim_count does not match claims")
        keys = []
        for index, claim_value in enumerate(claims):
            claim = _mapping(claim_value, f"{label}.claims[{index}]")
            keys.append(_required_text(claim.get("claim_key"), f"{label}.claims[{index}].claim_key"))
            _required_text(
                claim.get("revision_id"),
                f"{label}.claims[{index}].revision_id",
            )
        if len(keys) != len(set(keys)):
            raise ValueError(f"{label} snapshot contains duplicate claim keys")
    previous_valid_at = _iso_date(
        _required_text(previous.get("valid_at"), "previous.valid_at"),
        "previous.valid_at",
    ).isoformat()
    current_valid_at = _iso_date(
        _required_text(current.get("valid_at"), "current.valid_at"),
        "current.valid_at",
    ).isoformat()
    if current_valid_at != previous_valid_at:
        raise ValueError("claim snapshots must use the same valid_at")
    previous_known_at = _normalized_timestamp(
        _required_text(previous.get("known_at"), "previous.known_at"),
        "previous.known_at",
    )
    current_known_at = _normalized_timestamp(
        _required_text(current.get("known_at"), "current.known_at"),
        "current.known_at",
    )
    if _iso_timestamp(current_known_at, "current.known_at") < _iso_timestamp(
        previous_known_at,
        "previous.known_at",
    ):
        raise ValueError("current snapshot cannot precede previous snapshot")
    old = {item["claim_key"]: item for item in previous["claims"]}
    new = {item["claim_key"]: item for item in current["claims"]}
    alerts = []
    for key in sorted(old.keys() | new.keys()):
        prior = old.get(key)
        latest = new.get(key)
        if prior is None:
            kind, severity = "claim_added", "info"
        elif latest is None:
            kind, severity = "claim_removed", "high"
        elif prior["revision_id"] != latest["revision_id"]:
            kind, severity = "claim_revised", "medium"
        else:
            continue
        payload = {
            "type": kind,
            "severity": severity,
            "claim_key": key,
            "previous": prior,
            "current": latest,
        }
        alerts.append(
            {
                "id": f"claim-alert:{_digest(payload)[:16]}",
                **payload,
            }
        )
    return {
        "format": CLAIM_DIFF_FORMAT,
        "valid_at": previous_valid_at,
        "previous_known_at": previous_known_at,
        "current_known_at": current_known_at,
        "alert_count": len(alerts),
        "alerts": alerts,
    }
