"""Hash-pinned coverage audit for synthetic manufacturing inputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .manufacturing_claim_gate import CORE_DIMENSIONS, assess_manufacturing_claim
from .manufacturing_evidence_report import render_manufacturing_evidence_dashboard
from .release import _csv, _json, _sha256


MANUFACTURING_EVIDENCE_RECIPE_FORMAT = (
    "ai-supply-manufacturing-evidence-coverage-recipe.v1"
)
MANUFACTURING_EVIDENCE_COVERAGE_FORMAT = (
    "ai-supply-manufacturing-evidence-coverage.v1"
)
MANUFACTURING_EVIDENCE_RELEASE_FORMAT = (
    "ai-supply-manufacturing-evidence-coverage-release.v1"
)
MANUFACTURING_RELEASE_FORMAT = "ai-supply-manufacturing-release.v1"
MANUFACTURING_TARGET_CATALOG_FORMAT = "ai-supply-manufacturing-target-catalog.v1"
CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GAP_FIELDS = {
    "owner_type",
    "owner_id",
    "parameter",
    "branch",
    "low",
    "base",
    "high",
    "unit",
    "confidence",
    "last_updated",
    "influence_probability",
    "influence_method",
    "research_priority",
    "methodology",
    "evidence_ids",
    "confirming_evidence",
    "falsifying_evidence",
    "conditional_on_current_scenario",
}


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _required_text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expected_sha256(value: Any, path: str) -> str:
    text = _required_text(value, path)
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")
    return text


def _json_document(raw: bytes, path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    return _mapping(value, path)


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


def _read_checked_file(path: Path, expected_sha: str, label: str) -> bytes:
    raw = path.read_bytes()
    actual = _sha256_bytes(raw)
    if actual != expected_sha:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected_sha}, got {actual}")
    return raw


def _verify_manufacturing_release(
    release_dir: Path,
    expected_manifest_sha: str,
) -> dict[str, Any]:
    manifest_path = release_dir / "manifest.json"
    manifest_raw = _read_checked_file(
        manifest_path,
        expected_manifest_sha,
        "manufacturing manifest",
    )
    manifest = _json_document(manifest_raw, str(manifest_path))
    if manifest.get("format") != MANUFACTURING_RELEASE_FORMAT:
        raise ValueError(
            f"manufacturing manifest format must be {MANUFACTURING_RELEASE_FORMAT}"
        )
    files = _mapping(manifest.get("files"), "manufacturing manifest.files")
    release_root = release_dir.resolve()
    for name, descriptor_value in files.items():
        if not isinstance(name, str) or not name:
            raise ValueError("manufacturing manifest file names must be nonempty text")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("manufacturing manifest contains an unsafe file path")
        source_path = (release_root / relative).resolve()
        if source_path != release_root and release_root not in source_path.parents:
            raise ValueError("manufacturing manifest file escapes the release directory")
        descriptor = _mapping(
            descriptor_value,
            f"manufacturing manifest.files.{name}",
        )
        expected_sha = _expected_sha256(
            descriptor.get("sha256"),
            f"manufacturing manifest.files.{name}.sha256",
        )
        expected_bytes = descriptor.get("bytes")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int):
            raise ValueError(
                f"manufacturing manifest.files.{name}.bytes must be an integer"
            )
        raw = source_path.read_bytes()
        if len(raw) != expected_bytes or _sha256_bytes(raw) != expected_sha:
            raise ValueError(f"manufacturing release file drift: {name}")
    for required in ("evidence_gaps.csv", "result.json"):
        if required not in files:
            raise ValueError(f"manufacturing release is missing {required}")
    result_raw = (release_dir / "result.json").read_bytes()
    result = _json_document(result_raw, str(release_dir / "result.json"))
    scenario = _mapping(result.get("scenario"), "manufacturing result.scenario")
    if scenario.get("id") != manifest.get("scenario_id"):
        raise ValueError("manufacturing result scenario does not match manifest")
    if scenario.get("quarter") != manifest.get("quarter"):
        raise ValueError("manufacturing result quarter does not match manifest")
    if scenario.get("synthetic") is not True or manifest.get("synthetic") is not True:
        raise ValueError("coverage audit currently requires a synthetic source release")
    return {
        "manifest": dict(manifest),
        "manifest_raw": manifest_raw,
        "result_raw": result_raw,
        "gaps_raw": (release_dir / "evidence_gaps.csv").read_bytes(),
    }


def _float(value: Any, path: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be numeric") from exc
    if not parsed == parsed or parsed in (float("inf"), float("-inf")):
        raise ValueError(f"{path} must be finite")
    return parsed


def _input_path(row: Mapping[str, str]) -> str:
    prefix = {
        "logic_wafer": "logic.wafer",
        "logic_process": "logic",
        "hbm_wafer": "hbm.wafer",
        "hbm_process": "hbm",
        "package": "package",
    }.get(row["owner_type"])
    if prefix is None:
        raise ValueError(f"unsupported manufacturing evidence owner_type: {row['owner_type']}")
    return f"{prefix}.{row['parameter']}"


def _target_dimensions(value: Any, path: str) -> dict[str, str | None]:
    dimensions = _mapping(value, path)
    missing = CORE_DIMENSIONS - set(dimensions)
    if missing:
        raise ValueError(f"{path} is missing core dimensions: {sorted(missing)}")
    normalized = {}
    for key, item in dimensions.items():
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise ValueError(f"{path}.{key} must be nonempty text or null")
        normalized[key] = item
    return normalized


def _load_target_catalog(
    root: Path,
    selection_value: Any,
    *,
    source_manifest: Mapping[str, Any],
    gaps_by_path: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    selection = _mapping(selection_value, "recipe.constraint_target_catalog")
    _only(
        selection,
        {"path", "sha256"},
        "recipe.constraint_target_catalog",
    )
    relative, path = _resolve_under(
        root,
        selection.get("path"),
        "recipe.constraint_target_catalog.path",
    )
    expected_sha = _expected_sha256(
        selection.get("sha256"),
        "recipe.constraint_target_catalog.sha256",
    )
    raw = _read_checked_file(path, expected_sha, "constraint target catalog")
    document = _json_document(raw, str(path))
    if document.get("format") != MANUFACTURING_TARGET_CATALOG_FORMAT:
        raise ValueError(
            f"constraint target catalog format must be {MANUFACTURING_TARGET_CATALOG_FORMAT}"
        )
    _only(
        document,
        {"format", "scenario_id", "quarter", "targets"},
        "constraint target catalog",
    )
    if document.get("scenario_id") != source_manifest.get("scenario_id"):
        raise ValueError("constraint target catalog scenario does not match source release")
    if document.get("quarter") != source_manifest.get("quarter"):
        raise ValueError("constraint target catalog quarter does not match source release")
    values = document.get("targets")
    if not isinstance(values, list) or not values:
        raise ValueError("constraint target catalog requires at least one target")
    targets = {}
    for index, value in enumerate(values):
        target = _mapping(value, f"constraint target catalog.targets[{index}]")
        _only(
            target,
            {"input_path", "unit", "dimensions", "rationale"},
            f"constraint target catalog.targets[{index}]",
        )
        input_path = _required_text(
            target.get("input_path"),
            f"constraint target catalog.targets[{index}].input_path",
        )
        if input_path in targets:
            raise ValueError(f"duplicate constraint target: {input_path}")
        if input_path not in gaps_by_path:
            raise ValueError(f"constraint target is not a synthetic source input: {input_path}")
        unit = _required_text(
            target.get("unit"),
            f"constraint target catalog.targets[{index}].unit",
        )
        if unit != gaps_by_path[input_path]["unit"]:
            raise ValueError(f"constraint target unit does not match source input: {input_path}")
        targets[input_path] = {
            "input_path": input_path,
            "unit": unit,
            "dimensions": _target_dimensions(
                target.get("dimensions"),
                f"constraint target catalog.targets[{index}].dimensions",
            ),
            "rationale": _required_text(
                target.get("rationale"),
                f"constraint target catalog.targets[{index}].rationale",
            ),
        }
    return {
        "path": relative,
        "sha256": expected_sha,
        "raw": raw,
        "targets": targets,
    }


def _parse_gaps(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("manufacturing evidence_gaps.csv must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = set(reader.fieldnames or [])
    missing = GAP_FIELDS - fields
    if missing:
        raise ValueError(f"manufacturing evidence_gaps.csv missing fields: {sorted(missing)}")
    rows = []
    seen_paths: set[str] = set()
    for index, source in enumerate(reader, start=2):
        path = _input_path(source)
        if path in seen_paths:
            raise ValueError(f"duplicate manufacturing evidence input path: {path}")
        seen_paths.add(path)
        low = _float(source["low"], f"evidence_gaps.csv:{index}.low")
        base = _float(source["base"], f"evidence_gaps.csv:{index}.base")
        high = _float(source["high"], f"evidence_gaps.csv:{index}.high")
        confidence = _float(
            source["confidence"], f"evidence_gaps.csv:{index}.confidence"
        )
        influence = _float(
            source["influence_probability"],
            f"evidence_gaps.csv:{index}.influence_probability",
        )
        priority = _float(
            source["research_priority"],
            f"evidence_gaps.csv:{index}.research_priority",
        )
        if not low <= base <= high:
            raise ValueError(f"evidence_gaps.csv:{index} range is not ordered")
        if not 0 <= confidence <= 1 or not 0 <= influence <= 1 or priority < 0:
            raise ValueError(f"evidence_gaps.csv:{index} has invalid probability or priority")
        if source["conditional_on_current_scenario"] not in {"True", "true", "1"}:
            raise ValueError(
                f"evidence_gaps.csv:{index} must be conditional on the current scenario"
            )
        rows.append(
            {
                "input_path": path,
                "owner_type": source["owner_type"],
                "owner_id": source["owner_id"],
                "parameter": source["parameter"],
                "branch": source["branch"],
                "low": low,
                "base": base,
                "high": high,
                "unit": source["unit"],
                "source_posture": "synthetic",
                "confidence": confidence,
                "last_updated": source["last_updated"],
                "influence_probability": influence,
                "influence_method": source["influence_method"],
                "research_priority": priority,
                "methodology": source["methodology"],
                "evidence_ids": [
                    item for item in source["evidence_ids"].split("|") if item
                ],
                "confirming_evidence": source["confirming_evidence"],
                "falsifying_evidence": source["falsifying_evidence"],
                "conditional_on_current_scenario": True,
            }
        )
    if not rows:
        raise ValueError("manufacturing evidence_gaps.csv contains no rows")
    return sorted(rows, key=lambda item: (-item["research_priority"], item["input_path"]))


def _assessment_status(assessment: Mapping[str, Any]) -> str:
    if not assessment["accepted_for_usage"]:
        return "rejected"
    if assessment["eligible_as_constraint"]:
        return "constraint_eligible"
    return str(assessment["usage"])


def _assessment_row(case_id: str, assessment: Mapping[str, Any]) -> dict[str, Any]:
    dimensions = _mapping(assessment["claim_dimensions"], "assessment.claim_dimensions")
    normalized = assessment.get("normalized_estimate") or {}
    blocking_codes = [item["code"] for item in assessment["blocking_reasons"]]
    return {
        "id": case_id,
        "assessment_status": _assessment_status(assessment),
        "usage": assessment["usage"],
        "accepted_for_usage": assessment["accepted_for_usage"],
        "eligible_as_constraint": assessment["eligible_as_constraint"],
        "target_input_path": assessment["target_input_path"],
        "claim_key": assessment["claim_key"],
        "revision_id": assessment["revision_id"],
        "claim_value": assessment["claim_value"],
        "claim_unit": assessment["claim_unit"],
        "claim_posture": assessment["claim_posture"],
        "claim_period": dimensions["period"],
        "claim_stage": dimensions["stage"],
        "claim_product": dimensions.get("product"),
        "claim_dimensions": dict(dimensions),
        "normalized_low": normalized.get("low"),
        "normalized_base": normalized.get("base"),
        "normalized_high": normalized.get("high"),
        "normalized_unit": normalized.get("unit"),
        "blocking_codes": blocking_codes,
        "blocking_reasons": assessment["blocking_reasons"],
        "nonbinding_rationale": assessment["nonbinding_rationale"],
        "lineage": assessment["lineage"],
    }


def load_manufacturing_evidence_coverage(
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
    if recipe.get("format") != MANUFACTURING_EVIDENCE_RECIPE_FORMAT:
        raise ValueError(
            f"recipe format must be {MANUFACTURING_EVIDENCE_RECIPE_FORMAT}"
        )
    _only(
        recipe,
        {
            "format",
            "id",
            "as_of_date",
            "recorded_at",
            "manufacturing_release",
            "constraint_target_catalog",
            "claim_cases",
        },
        "recipe",
    )
    release_id = _required_text(recipe.get("id"), "recipe.id")
    if not CASE_ID_PATTERN.fullmatch(release_id):
        raise ValueError("recipe.id must use lowercase letters, digits, and hyphens")
    as_of_date = _iso_date(recipe.get("as_of_date"), "recipe.as_of_date")
    recorded_at = _utc_timestamp(recipe.get("recorded_at"), "recipe.recorded_at")
    if as_of_date > recorded_at.date():
        raise ValueError("recipe.as_of_date cannot be after recorded_at")

    release_selection = _mapping(
        recipe.get("manufacturing_release"),
        "recipe.manufacturing_release",
    )
    _only(
        release_selection,
        {"path", "manifest_sha256"},
        "recipe.manufacturing_release",
    )
    release_relative, release_dir = _resolve_under(
        root,
        release_selection.get("path"),
        "recipe.manufacturing_release.path",
    )
    expected_manifest_sha = _expected_sha256(
        release_selection.get("manifest_sha256"),
        "recipe.manufacturing_release.manifest_sha256",
    )
    source_release = _verify_manufacturing_release(
        release_dir,
        expected_manifest_sha,
    )
    gaps = _parse_gaps(source_release["gaps_raw"])
    gaps_by_path = {item["input_path"]: item for item in gaps}
    target_catalog = _load_target_catalog(
        root,
        recipe.get("constraint_target_catalog"),
        source_manifest=source_release["manifest"],
        gaps_by_path=gaps_by_path,
    )

    claim_cases = recipe.get("claim_cases")
    if not isinstance(claim_cases, list) or not claim_cases:
        raise ValueError("recipe.claim_cases requires at least one case")
    cases = []
    assessment_rows = []
    seen_ids: set[str] = set()
    seen_selection_hashes: set[str] = set()
    for index, case_value in enumerate(claim_cases):
        case = _mapping(case_value, f"recipe.claim_cases[{index}]")
        _only(
            case,
            {
                "id",
                "snapshot_path",
                "snapshot_sha256",
                "selection_path",
                "selection_sha256",
            },
            f"recipe.claim_cases[{index}]",
        )
        case_id = _required_text(case.get("id"), f"recipe.claim_cases[{index}].id")
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"invalid claim case id: {case_id}")
        if case_id in seen_ids:
            raise ValueError(f"duplicate claim case id: {case_id}")
        seen_ids.add(case_id)
        snapshot_relative, snapshot_path = _resolve_under(
            root,
            case.get("snapshot_path"),
            f"recipe.claim_cases[{index}].snapshot_path",
        )
        selection_relative, selection_path = _resolve_under(
            root,
            case.get("selection_path"),
            f"recipe.claim_cases[{index}].selection_path",
        )
        snapshot_sha = _expected_sha256(
            case.get("snapshot_sha256"),
            f"recipe.claim_cases[{index}].snapshot_sha256",
        )
        selection_sha = _expected_sha256(
            case.get("selection_sha256"),
            f"recipe.claim_cases[{index}].selection_sha256",
        )
        if selection_sha in seen_selection_hashes:
            raise ValueError(f"duplicate claim selection in recipe: {selection_relative}")
        seen_selection_hashes.add(selection_sha)
        snapshot_raw = _read_checked_file(snapshot_path, snapshot_sha, f"{case_id} snapshot")
        selection_raw = _read_checked_file(
            selection_path,
            selection_sha,
            f"{case_id} selection",
        )
        assessment = assess_manufacturing_claim(snapshot_path, selection_path)
        if _utc_timestamp(
            assessment["lineage"]["known_at"],
            f"{case_id}.lineage.known_at",
        ) > recorded_at:
            raise ValueError(f"claim case {case_id} was not known by recipe.recorded_at")
        if _iso_date(
            assessment["lineage"]["valid_at"],
            f"{case_id}.lineage.valid_at",
        ) > as_of_date:
            raise ValueError(f"claim case {case_id} is not valid by recipe.as_of_date")
        target_path = assessment["target_input_path"]
        if assessment["usage"] == "constraint_input":
            target = target_catalog["targets"].get(target_path)
            if target is None:
                raise ValueError(
                    f"constraint claim case {case_id} targets no cataloged input: {target_path}"
                )
            if assessment["target_dimensions"] != target["dimensions"]:
                raise ValueError(
                    f"constraint claim case {case_id} target dimensions do not match catalog"
                )
            normalized = assessment.get("normalized_estimate")
            if normalized is not None and normalized["unit"] != target["unit"]:
                raise ValueError(
                    f"constraint claim case {case_id} unit does not match target input"
                )
        normalized_assessment = dict(assessment)
        normalized_lineage = dict(assessment["lineage"])
        normalized_lineage.update(
            {
                "snapshot_path": snapshot_relative,
                "selection_path": selection_relative,
                "selection_sha256": selection_sha,
            }
        )
        normalized_assessment["lineage"] = normalized_lineage
        row = _assessment_row(case_id, normalized_assessment)
        assessment_rows.append(row)
        cases.append(
            {
                "id": case_id,
                "snapshot_raw": snapshot_raw,
                "selection_raw": selection_raw,
                "assessment": normalized_assessment,
            }
        )

    input_rows = []
    for gap in gaps:
        matching = [
            item
            for item in assessment_rows
            if item["usage"] == "constraint_input"
            and item["target_input_path"] == gap["input_path"]
        ]
        if any(item["eligible_as_constraint"] for item in matching):
            input_status = "eligible_claim_candidate"
        elif matching and any(
            code.startswith("dimension_mismatch:")
            for item in matching
            for code in item["blocking_codes"]
        ):
            input_status = "scope_rejected_claim"
        elif matching:
            input_status = "rejected_claim"
        else:
            input_status = "no_constraint_claim"
        input_rows.append(
            {
                **gap,
                "input_status": input_status,
                "assessment_ids": [item["id"] for item in matching],
                "blocking_codes": sorted(
                    {
                        code
                        for item in matching
                        for code in item["blocking_codes"]
                    }
                ),
                "source_replaced": False,
            }
        )

    eligible_inputs = [
        item for item in input_rows if item["input_status"] == "eligible_claim_candidate"
    ]
    total_priority = sum(item["research_priority"] for item in input_rows)
    eligible_priority = sum(item["research_priority"] for item in eligible_inputs)
    summary = {
        "synthetic_inputs": len(input_rows),
        "synthetic_inputs_replaced": 0,
        "eligible_claim_candidate_inputs": len(eligible_inputs),
        "scope_rejected_inputs": sum(
            item["input_status"] == "scope_rejected_claim" for item in input_rows
        ),
        "other_rejected_inputs": sum(
            item["input_status"] == "rejected_claim" for item in input_rows
        ),
        "inputs_without_constraint_claim": sum(
            item["input_status"] == "no_constraint_claim" for item in input_rows
        ),
        "accepted_scale_controls": sum(
            item["assessment_status"] == "scale_control" for item in assessment_rows
        ),
        "accepted_directional_signals": sum(
            item["assessment_status"] == "directional_signal"
            for item in assessment_rows
        ),
        "rejected_claim_assessments": sum(
            item["assessment_status"] == "rejected" for item in assessment_rows
        ),
        "eligible_research_priority_share": (
            eligible_priority / total_priority if total_priority else 0.0
        ),
    }
    recipe_relative = recipe_source.relative_to(root).as_posix()
    manifest = source_release["manifest"]
    document = {
        "format": MANUFACTURING_EVIDENCE_COVERAGE_FORMAT,
        "id": release_id,
        "as_of_date": as_of_date.isoformat(),
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "inputs": input_rows,
        "assessments": assessment_rows,
        "lineage": {
            "recipe": {
                "path": recipe_relative,
                "sha256": _sha256_bytes(recipe_raw),
            },
            "manufacturing_release": {
                "path": release_relative,
                "manifest_sha256": expected_manifest_sha,
                "format": manifest["format"],
                "scenario_id": manifest["scenario_id"],
                "quarter": manifest["quarter"],
                "as_of_date": manifest["as_of_date"],
                "recorded_at": manifest["recorded_at"],
                "synthetic": manifest["synthetic"],
                "evidence_gaps_sha256": manifest["files"]["evidence_gaps.csv"]["sha256"],
                "result_sha256": manifest["files"]["result.json"]["sha256"],
            },
            "constraint_target_catalog": {
                "path": target_catalog["path"],
                "sha256": target_catalog["sha256"],
                "target_count": len(target_catalog["targets"]),
            },
        },
        "limitations": [
            "The source manufacturing scenario remains synthetic; this audit applies no replacements.",
            "Directional signals and scale controls cannot constrain quarterly product output.",
            "Research priority is conditional on the frozen scenario and is not a global sensitivity score.",
            "A gate-passing claim would still require an explicit reviewed scenario revision before use.",
        ],
    }
    return {
        "document": document,
        "recipe_raw": recipe_raw,
        "source_release": source_release,
        "target_catalog": target_catalog,
        "cases": cases,
    }


def _input_csv_rows(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "evidence_ids": "|".join(item["evidence_ids"]),
            "assessment_ids": "|".join(item["assessment_ids"]),
            "blocking_codes": "|".join(item["blocking_codes"]),
        }
        for item in document["inputs"]
    ]


def _assessment_csv_rows(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "claim_value": json.dumps(
                item["claim_value"],
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "claim_dimensions": json.dumps(
                item["claim_dimensions"],
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "blocking_codes": "|".join(item["blocking_codes"]),
            "source_snapshot_ids": "|".join(
                item["lineage"]["source_snapshot_ids"]
            ),
            "snapshot_sha256": item["lineage"]["snapshot_sha256"],
            "selection_sha256": item["lineage"]["selection_sha256"],
        }
        for item in document["assessments"]
    ]


def build_manufacturing_evidence_coverage_documents(
    case: Mapping[str, Any],
) -> dict[str, str]:
    document = case["document"]
    source_release = case["source_release"]
    input_fields = [
        "input_path",
        "owner_type",
        "owner_id",
        "parameter",
        "branch",
        "low",
        "base",
        "high",
        "unit",
        "source_posture",
        "confidence",
        "last_updated",
        "influence_probability",
        "influence_method",
        "research_priority",
        "input_status",
        "assessment_ids",
        "blocking_codes",
        "source_replaced",
        "methodology",
        "evidence_ids",
        "confirming_evidence",
        "falsifying_evidence",
        "conditional_on_current_scenario",
    ]
    assessment_fields = [
        "id",
        "assessment_status",
        "usage",
        "accepted_for_usage",
        "eligible_as_constraint",
        "target_input_path",
        "claim_key",
        "revision_id",
        "claim_value",
        "claim_unit",
        "claim_posture",
        "claim_period",
        "claim_stage",
        "claim_product",
        "claim_dimensions",
        "normalized_low",
        "normalized_base",
        "normalized_high",
        "normalized_unit",
        "blocking_codes",
        "nonbinding_rationale",
        "source_snapshot_ids",
        "snapshot_sha256",
        "selection_sha256",
    ]
    documents = {
        "dashboard.html": render_manufacturing_evidence_dashboard(document),
        "coverage.json": _json(document),
        "input_coverage.csv": _csv(input_fields, _input_csv_rows(document)),
        "claim_assessments.csv": _csv(
            assessment_fields,
            _assessment_csv_rows(document),
        ),
        "recipe.json": case["recipe_raw"].decode("utf-8"),
        "sources/manufacturing-manifest.json": source_release[
            "manifest_raw"
        ].decode("utf-8"),
        "sources/manufacturing-evidence-gaps.csv": source_release[
            "gaps_raw"
        ].decode("utf-8"),
        "sources/manufacturing-result.json": source_release["result_raw"].decode(
            "utf-8"
        ),
        "sources/constraint-target-catalog.json": case["target_catalog"][
            "raw"
        ].decode("utf-8"),
        "README.md": (
            f"# {document['id']}\n\n"
            f"As of `{document['as_of_date']}`. Recorded `{document['recorded_at']}`.\n\n"
            "**This is an evidence-coverage audit of a synthetic manufacturing run. "
            "It does not estimate actual Blackwell output and applies no source-input "
            "replacements.**\n\n"
            "Open `dashboard.html` first. `coverage.json` is the complete machine-readable "
            "audit; `input_coverage.csv` preserves the ranked synthetic inputs; "
            "`claim_assessments.csv` separates constraint decisions from nonbinding evidence; "
            "and `sources/` freezes every selected claim snapshot and source manufacturing "
            "artifact used by this release.\n"
        ),
    }
    for claim_case in case["cases"]:
        prefix = f"sources/claim-cases/{claim_case['id']}"
        documents[f"{prefix}/snapshot.json"] = claim_case["snapshot_raw"].decode(
            "utf-8"
        )
        documents[f"{prefix}/selection.json"] = claim_case["selection_raw"].decode(
            "utf-8"
        )
        documents[f"{prefix}/assessment.json"] = _json(
            claim_case["assessment"]
        )
    manifest = {
        "format": MANUFACTURING_EVIDENCE_RELEASE_FORMAT,
        "id": document["id"],
        "as_of_date": document["as_of_date"],
        "recorded_at": document["recorded_at"],
        "source_scenario_id": document["lineage"]["manufacturing_release"][
            "scenario_id"
        ],
        "source_quarter": document["lineage"]["manufacturing_release"]["quarter"],
        "source_synthetic": True,
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_manufacturing_evidence_coverage_release(
    recipe_path: str | Path,
    output_dir: str | Path,
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    case = load_manufacturing_evidence_coverage(
        recipe_path,
        source_root=source_root,
    )
    documents = build_manufacturing_evidence_coverage_documents(case)
    destination = Path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing_files = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing_files != set(documents) or any(
            (destination / name).read_bytes() != text.encode("utf-8")
            for name, text in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
        return {
            "output_dir": str(destination.resolve()),
            **json.loads(documents["manifest.json"]),
            "summary": case["document"]["summary"],
        }
    destination.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
        "summary": case["document"]["summary"],
    }
