"""Replay-safe replacement of synthetic manufacturing inputs with gated claims."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .claim_ledger import CLAIM_SNAPSHOT_FORMAT
from .manufacturing_claim_gate import assess_manufacturing_claim
from .manufacturing_loader import manufacturing_from_dict
from .manufacturing_release import build_manufacturing_release_documents
from .models import EvidenceKind
from .release import _json, _sha256


MANUFACTURING_REVISION_RECIPE_FORMAT = (
    "ai-supply-manufacturing-revision-recipe.v1"
)
MANUFACTURING_REVISION_RESULT_FORMAT = (
    "ai-supply-manufacturing-revision-result.v1"
)
MANUFACTURING_TARGET_CATALOG_FORMAT = "ai-supply-manufacturing-target-catalog.v1"
MANUFACTURING_RELEASE_FORMAT = "ai-supply-manufacturing-release.v1"
REVISION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expected_sha256(value: Any, path: str) -> str:
    text = _required_text(value, path)
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return text


def _json_document(raw: bytes, path: str) -> dict[str, Any]:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    return dict(_mapping(document, path))


def _utc_timestamp(value: Any, path: str) -> datetime:
    text = _required_text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso_date(value: Any, path: str) -> date:
    text = _required_text(value, path)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _resolve_under(root: Path, value: Any, path: str) -> tuple[str, Path]:
    relative_text = _required_text(value, path)
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{path} must be a path below source_root")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"{path} escapes source_root")
    return relative.as_posix(), resolved


def _read_pinned(
    root: Path,
    value: Any,
    path: str,
) -> tuple[str, Path, bytes, dict[str, Any], str]:
    descriptor = _mapping(value, path)
    _only(descriptor, {"path", "sha256"}, path)
    relative, source = _resolve_under(root, descriptor.get("path"), f"{path}.path")
    expected = _expected_sha256(descriptor.get("sha256"), f"{path}.sha256")
    raw = source.read_bytes()
    actual = _sha256_bytes(raw)
    if actual != expected:
        raise ValueError(f"{path} SHA-256 mismatch: expected {expected}, got {actual}")
    return relative, source, raw, _json_document(raw, str(source)), expected


def _dimensions(value: Any, path: str) -> dict[str, str | None]:
    source = _mapping(value, path)
    required = {
        "entity_scope",
        "geography",
        "period",
        "stage",
        "capacity_basis",
        "quantity_semantics",
    }
    missing = required - set(source)
    if missing:
        raise ValueError(f"{path} is missing core dimensions: {sorted(missing)}")
    result: dict[str, str | None] = {}
    for key, item in source.items():
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f"{path}.{key} must be nonempty text or null")
        result[key] = item
    return result


def _load_targets(
    document: Mapping[str, Any],
    *,
    scenario_id: str,
    quarter: str,
) -> dict[str, dict[str, Any]]:
    if document.get("format") != MANUFACTURING_TARGET_CATALOG_FORMAT:
        raise ValueError(
            f"target catalog format must be {MANUFACTURING_TARGET_CATALOG_FORMAT}"
        )
    _only(document, {"format", "scenario_id", "quarter", "targets"}, "target catalog")
    if document.get("scenario_id") != scenario_id:
        raise ValueError("target catalog scenario does not match source scenario")
    if document.get("quarter") != quarter:
        raise ValueError("target catalog quarter does not match source scenario")
    values = document.get("targets")
    if not isinstance(values, list) or not values:
        raise ValueError("target catalog requires at least one target")
    targets = {}
    for index, value in enumerate(values):
        item_path = f"target catalog.targets[{index}]"
        item = _mapping(value, item_path)
        _only(item, {"input_path", "unit", "dimensions", "rationale"}, item_path)
        input_path = _required_text(item.get("input_path"), f"{item_path}.input_path")
        if input_path in targets:
            raise ValueError(f"duplicate target catalog input: {input_path}")
        targets[input_path] = {
            "input_path": input_path,
            "unit": _required_text(item.get("unit"), f"{item_path}.unit"),
            "dimensions": _dimensions(item.get("dimensions"), f"{item_path}.dimensions"),
            "rationale": _required_text(item.get("rationale"), f"{item_path}.rationale"),
        }
    return targets


def _nested(document: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    value: Any = document
    for segment in dotted_path.split("."):
        if not isinstance(value, dict) or segment not in value:
            raise ValueError(f"source scenario has no estimate at {dotted_path}")
        value = value[segment]
    estimate = _mapping(value, f"source scenario.{dotted_path}")
    required = {
        "low",
        "base",
        "high",
        "unit",
        "posture",
        "methodology",
        "confidence",
        "last_updated",
        "evidence_ids",
        "confirming_evidence",
        "falsifying_evidence",
        "correlation_group",
    }
    if set(estimate) != required:
        raise ValueError(f"source scenario estimate shape is unsupported: {dotted_path}")
    return estimate


def _set_nested(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    owner: Any = document
    segments = dotted_path.split(".")
    for segment in segments[:-1]:
        owner = owner[segment]
    owner[segments[-1]] = value


def _claim(snapshot: Mapping[str, Any], claim_key: str) -> Mapping[str, Any]:
    if snapshot.get("format") != CLAIM_SNAPSHOT_FORMAT:
        raise ValueError(f"claim snapshot format must be {CLAIM_SNAPSHOT_FORMAT}")
    claims = snapshot.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claim snapshot claims must be an array")
    matches = [
        item
        for item in claims
        if isinstance(item, dict) and item.get("claim_key") == claim_key
    ]
    if len(matches) != 1:
        raise ValueError(f"claim snapshot must contain exactly one {claim_key} claim")
    return matches[0]


def _evidence_metadata(
    value: Any,
    *,
    evidence: list[Mapping[str, Any]],
    path: str,
) -> dict[str, dict[str, Any]]:
    values = value
    if not isinstance(values, list):
        raise ValueError(f"{path} must be an array")
    metadata = {}
    allowed_kinds = {item.value for item in EvidenceKind}
    for index, raw_item in enumerate(values):
        item_path = f"{path}[{index}]"
        item = _mapping(raw_item, item_path)
        _only(item, {"snapshot_id", "kind", "title", "excerpt"}, item_path)
        snapshot_id = _required_text(item.get("snapshot_id"), f"{item_path}.snapshot_id")
        if snapshot_id in metadata:
            raise ValueError(f"{path} contains duplicate snapshot metadata")
        kind = _required_text(item.get("kind"), f"{item_path}.kind")
        if kind not in allowed_kinds:
            raise ValueError(f"{item_path}.kind is unsupported")
        metadata[snapshot_id] = {
            "kind": kind,
            "title": _required_text(item.get("title"), f"{item_path}.title"),
            "excerpt": _optional_text(item.get("excerpt"), f"{item_path}.excerpt"),
        }
    expected = {item["snapshot_id"] for item in evidence}
    if set(metadata) != expected:
        raise ValueError(f"{path} must describe every and only the selected claim snapshots")
    return metadata


def _scenario_evidence(
    claim: Mapping[str, Any],
    metadata: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for source in claim["evidence"]:
        supplemental = metadata[source["snapshot_id"]]
        records.append(
            {
                "id": source["snapshot_id"],
                "kind": supplemental["kind"],
                "title": supplemental["title"],
                "source_url": source["source_url"],
                "publisher": source["publisher"],
                "retrieved_at": source["retrieved_at"],
                "published_at": source["published_at"],
                "source_family": source["source_family"],
                "license": source["license"],
                "excerpt": supplemental["excerpt"],
                "content_hash": source["content_sha256"],
            }
        )
    return records


def _synthetic_input_count(document: Mapping[str, Any]) -> int:
    count = 0

    def visit(value: Any) -> None:
        nonlocal count
        if isinstance(value, dict):
            if {"low", "base", "high", "posture"} <= set(value):
                if value["posture"] == "synthetic":
                    count += 1
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for key in ("logic", "hbm", "package", "references"):
        visit(document.get(key))
    return count


def load_manufacturing_revision(
    recipe_path: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise ValueError("source_root must be an existing directory")
    recipe_source = Path(recipe_path).resolve()
    if recipe_source != root and root not in recipe_source.parents:
        raise ValueError("recipe must be below source_root")
    recipe_raw = recipe_source.read_bytes()
    recipe = _json_document(recipe_raw, str(recipe_source))
    if recipe.get("format") != MANUFACTURING_REVISION_RECIPE_FORMAT:
        raise ValueError(
            f"revision recipe format must be {MANUFACTURING_REVISION_RECIPE_FORMAT}"
        )
    _only(
        recipe,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "source_scenario",
            "target_catalog",
            "replacements",
            "notes",
        },
        "revision recipe",
    )
    revision_id = _required_text(recipe.get("id"), "revision recipe.id")
    if REVISION_ID_PATTERN.fullmatch(revision_id) is None:
        raise ValueError("revision recipe.id must be a lowercase filesystem-safe identifier")
    as_of_date = _iso_date(recipe.get("as_of_date"), "revision recipe.as_of_date")
    recorded_at = _utc_timestamp(recipe.get("recorded_at"), "revision recipe.recorded_at")
    notes = _required_text(recipe.get("notes"), "revision recipe.notes")

    source_relative, _, source_raw, source_document, source_sha = _read_pinned(
        root,
        recipe.get("source_scenario"),
        "revision recipe.source_scenario",
    )
    source_scenario = manufacturing_from_dict(source_document)
    source_as_of = _iso_date(source_scenario.as_of_date, "source scenario.as_of_date")
    source_recorded_at = _utc_timestamp(
        source_scenario.recorded_at,
        "source scenario.recorded_at",
    )
    if as_of_date < source_as_of:
        raise ValueError("revision as_of_date cannot precede source scenario as_of_date")
    if recorded_at <= source_recorded_at:
        raise ValueError("revision recorded_at must follow source scenario recorded_at")
    if as_of_date > recorded_at.date():
        raise ValueError("revision as_of_date cannot follow revision recorded_at")

    target_relative, _, target_raw, target_document, target_sha = _read_pinned(
        root,
        recipe.get("target_catalog"),
        "revision recipe.target_catalog",
    )
    targets = _load_targets(
        target_document,
        scenario_id=source_scenario.id,
        quarter=source_scenario.quarter,
    )
    replacement_values = recipe.get("replacements")
    if not isinstance(replacement_values, list) or not replacement_values:
        raise ValueError("revision recipe.replacements requires at least one replacement")

    revised_document = deepcopy(source_document)
    existing_evidence = {
        item["id"]: item
        for item in revised_document.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    lineage_documents: dict[str, bytes] = {
        "lineage/source-scenario.json": source_raw,
        "lineage/target-catalog.json": target_raw,
    }
    replacements = []
    seen_paths = set()
    for index, raw_value in enumerate(replacement_values):
        item_path = f"revision recipe.replacements[{index}]"
        item = _mapping(raw_value, item_path)
        _only(item, {"snapshot", "selection", "evidence_metadata"}, item_path)
        snapshot_relative, snapshot_path, snapshot_raw, snapshot, snapshot_sha = _read_pinned(
            root,
            item.get("snapshot"),
            f"{item_path}.snapshot",
        )
        selection_relative, selection_path, selection_raw, selection, selection_sha = _read_pinned(
            root,
            item.get("selection"),
            f"{item_path}.selection",
        )
        assessment = assess_manufacturing_claim(snapshot_path, selection_path)
        if not assessment["eligible_as_constraint"]:
            codes = [item["code"] for item in assessment["blocking_reasons"]]
            raise ValueError(f"replacement claim is not eligible as a constraint: {codes}")
        target_path = assessment["target_input_path"]
        if target_path in seen_paths:
            raise ValueError(f"revision recipe contains duplicate target: {target_path}")
        seen_paths.add(target_path)
        if target_path not in targets:
            raise ValueError(f"replacement target is absent from target catalog: {target_path}")
        target = targets[target_path]
        if assessment["target_dimensions"] != target["dimensions"]:
            raise ValueError(f"replacement dimensions do not match target catalog: {target_path}")
        estimate = assessment["constraint_estimate"]
        if estimate["unit"] != target["unit"]:
            raise ValueError(f"replacement unit does not match target catalog: {target_path}")
        if snapshot.get("valid_at") != as_of_date.isoformat():
            raise ValueError("replacement snapshot valid_at must equal revision as_of_date")
        if _utc_timestamp(snapshot.get("known_at"), "snapshot.known_at") > recorded_at:
            raise ValueError("replacement snapshot cannot be known after revision recorded_at")
        claim = _claim(snapshot, assessment["claim_key"])
        if claim.get("revision_id") != assessment["revision_id"]:
            raise ValueError("replacement claim revision drifted after assessment")
        if _utc_timestamp(claim.get("recorded_at"), "claim.recorded_at") > recorded_at:
            raise ValueError("replacement claim cannot be recorded after the revision")
        claim_evidence = claim.get("evidence")
        if not isinstance(claim_evidence, list) or not claim_evidence:
            raise ValueError("replacement claim requires evidence")
        supplemental = _evidence_metadata(
            item.get("evidence_metadata"),
            evidence=claim_evidence,
            path=f"{item_path}.evidence_metadata",
        )
        prior = dict(_nested(revised_document, target_path))
        if prior["posture"] != "synthetic":
            raise ValueError(f"revision can replace only a synthetic estimate: {target_path}")
        if prior["unit"] != target["unit"]:
            raise ValueError(f"source estimate unit does not match target catalog: {target_path}")
        evidence_records = _scenario_evidence(claim, supplemental)
        for evidence_record in evidence_records:
            evidence_id = evidence_record["id"]
            existing = existing_evidence.get(evidence_id)
            if existing is not None and existing != evidence_record:
                raise ValueError(f"scenario evidence ID collision: {evidence_id}")
            if existing is None:
                revised_document["evidence"].append(evidence_record)
                existing_evidence[evidence_id] = evidence_record
        revised_estimate = {
            "low": estimate["low"],
            "base": estimate["base"],
            "high": estimate["high"],
            "unit": estimate["unit"],
            "posture": estimate["posture"],
            "methodology": estimate["methodology"],
            "confidence": estimate["confidence"],
            "last_updated": estimate["last_updated"],
            "evidence_ids": [item["snapshot_id"] for item in claim_evidence],
            "confirming_evidence": claim["confirming_evidence"],
            "falsifying_evidence": claim["falsifying_evidence"],
            "correlation_group": prior["correlation_group"],
        }
        _set_nested(revised_document, target_path, revised_estimate)
        numeric_changed = any(
            prior[key] != revised_estimate[key] for key in ("low", "base", "high")
        )
        replacements.append(
            {
                "target_input_path": target_path,
                "target_dimensions": target["dimensions"],
                "target_rationale": target["rationale"],
                "claim_key": claim["claim_key"],
                "claim_revision_id": claim["revision_id"],
                "claim_posture": claim["posture"],
                "source_snapshot_ids": [item["snapshot_id"] for item in claim_evidence],
                "previous_estimate": prior,
                "revised_estimate": revised_estimate,
                "numeric_changed": numeric_changed,
                "lineage": {
                    "snapshot_path": snapshot_relative,
                    "snapshot_sha256": snapshot_sha,
                    "selection_path": selection_relative,
                    "selection_sha256": selection_sha,
                },
            }
        )
        lineage_documents[f"lineage/claims/{index:03d}-snapshot.json"] = snapshot_raw
        lineage_documents[f"lineage/claims/{index:03d}-selection.json"] = selection_raw

    scenario_metadata = revised_document["scenario"]
    scenario_metadata["as_of_date"] = as_of_date.isoformat()
    scenario_metadata["recorded_at"] = recorded_at.isoformat().replace("+00:00", "Z")
    scenario_metadata["notes"] = f"{scenario_metadata.get('notes', '').strip()} Revision {revision_id}: {notes}".strip()
    remaining_synthetic = _synthetic_input_count(revised_document)
    scenario_metadata["synthetic"] = remaining_synthetic > 0
    revised_scenario = manufacturing_from_dict(revised_document)
    revision_result = {
        "format": MANUFACTURING_REVISION_RESULT_FORMAT,
        "revision_id": revision_id,
        "scenario_id": revised_scenario.id,
        "quarter": revised_scenario.quarter,
        "as_of_date": revised_scenario.as_of_date,
        "recorded_at": revised_scenario.recorded_at,
        "source_scenario": {
            "path": source_relative,
            "sha256": source_sha,
            "as_of_date": source_scenario.as_of_date,
            "recorded_at": source_scenario.recorded_at,
        },
        "target_catalog": {"path": target_relative, "sha256": target_sha},
        "replacement_count": len(replacements),
        "remaining_synthetic_input_count": remaining_synthetic,
        "all_numeric_values_unchanged": not any(
            item["numeric_changed"] for item in replacements
        ),
        "replacements": replacements,
        "notes": notes,
    }
    return {
        "recipe": recipe,
        "recipe_raw": recipe_raw,
        "recipe_sha256": _sha256_bytes(recipe_raw),
        "scenario": revised_scenario,
        "scenario_document": revised_document,
        "revision_result": revision_result,
        "lineage_documents": lineage_documents,
    }


def build_manufacturing_revision_release_documents(
    case: Mapping[str, Any],
) -> dict[str, str]:
    scenario_document = _json(case["scenario_document"])
    documents = build_manufacturing_release_documents(
        case["scenario"],
        source_document=scenario_document,
    )
    documents.pop("manifest.json")
    documents["revision.json"] = _json(case["revision_result"])
    documents["revision-recipe.json"] = case["recipe_raw"].decode("utf-8")
    for name, raw in case["lineage_documents"].items():
        documents[name] = raw.decode("utf-8")
    result = case["revision_result"]
    documents["README.md"] = (
        f"# {case['scenario'].name}\n\n"
        f"Revision: `{result['revision_id']}`. Quarter: `{result['quarter']}`. "
        f"As of: `{result['as_of_date']}`.\n\n"
        f"This release replaced `{result['replacement_count']}` synthetic input with "
        "an exact-scope, hash-pinned claim. "
        f"`{result['remaining_synthetic_input_count']}` modeled inputs remain synthetic, "
        "so the scenario remains illustrative.\n\n"
        "Open `dashboard.html` first. `revision.json` records each before/after estimate "
        "and whether its numeric value changed. `lineage/` retains the exact predecessor, "
        "target catalog, claim snapshots, and selections needed to audit the revision.\n"
    )
    manifest = {
        "format": MANUFACTURING_RELEASE_FORMAT,
        "scenario_id": case["scenario"].id,
        "quarter": case["scenario"].quarter,
        "as_of_date": case["scenario"].as_of_date,
        "recorded_at": case["scenario"].recorded_at,
        "synthetic": case["scenario"].synthetic,
        "revision_id": result["revision_id"],
        "revision_result_format": MANUFACTURING_REVISION_RESULT_FORMAT,
        "source_scenario_sha256": result["source_scenario"]["sha256"],
        "replacement_count": result["replacement_count"],
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_manufacturing_revision_release(
    case: Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_manufacturing_revision_release_documents(case)
    destination = Path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != text.encode("utf-8")
            for name, text in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, text in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
