"""Strict claim-scope gate for manufacturing inputs and controls."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .claim_ledger import CLAIM_SNAPSHOT_FORMAT


MANUFACTURING_CLAIM_SELECTION_FORMAT = "ai-supply-manufacturing-claim-selection.v1"
MANUFACTURING_CLAIM_ASSESSMENT_FORMAT = "ai-supply-manufacturing-claim-assessment.v1"
USAGES = {"constraint_input", "scale_control", "directional_signal"}
CORE_DIMENSIONS = {
    "entity_scope",
    "geography",
    "period",
    "stage",
    "capacity_basis",
    "quantity_semantics",
}


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


def _json_file(path: Path, label: str) -> tuple[bytes, Mapping[str, Any]]:
    raw = path.read_bytes()
    try:
        document = _mapping(json.loads(raw), label)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    return raw, document


def _iso_timestamp(value: str, path: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _dimension_map(value: Any, path: str) -> dict[str, str | None]:
    dimensions = _mapping(value, path)
    if not CORE_DIMENSIONS <= set(dimensions):
        missing = sorted(CORE_DIMENSIONS - set(dimensions))
        raise ValueError(f"{path} is missing core dimensions: {missing}")
    normalized: dict[str, str | None] = {}
    for key, item in dimensions.items():
        if item is not None and not isinstance(item, str):
            raise ValueError(f"{path}.{key} must be text or null")
        if isinstance(item, str) and not item.strip():
            raise ValueError(f"{path}.{key} cannot be empty")
        normalized[key] = item
    return normalized


def _numeric(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _normalized_range(
    value: Any,
    *,
    multiplier: float,
    target_unit: str,
    source_posture: str,
    methodology: str,
    confidence: float,
    recorded_at: str,
    evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    blockers = []
    if _numeric(value):
        low = base = high = float(value) * multiplier
    elif isinstance(value, dict) and set(value) == {"low", "base", "high"}:
        if not all(_numeric(value[key]) for key in ("low", "base", "high")):
            blockers.append(
                {
                    "code": "nonnumeric_range",
                    "message": "claim range values must be numeric",
                }
            )
            return None, blockers
        low = float(value["low"]) * multiplier
        base = float(value["base"]) * multiplier
        high = float(value["high"]) * multiplier
    elif isinstance(value, dict) and set(value) == {"low", "high"}:
        blockers.append(
            {
                "code": "range_has_no_base",
                "message": "a reported low/high range needs an explicit sourced base before it can become a model estimate",
            }
        )
        return None, blockers
    else:
        blockers.append(
            {
                "code": "value_is_not_numeric_capacity",
                "message": "claim value is not a numeric point or low/base/high range",
            }
        )
        return None, blockers
    if not low <= base <= high:
        blockers.append(
            {
                "code": "range_is_not_ordered",
                "message": "normalized claim range is not ordered low <= base <= high",
            }
        )
        return None, blockers
    posture = source_posture if multiplier == 1 else "derived"
    return (
        {
            "low": low,
            "base": base,
            "high": high,
            "unit": target_unit,
            "posture": posture,
            "source_posture": source_posture,
            "methodology": methodology,
            "confidence": confidence,
            "last_updated": recorded_at[:10],
            "source_snapshot_ids": [item["snapshot_id"] for item in evidence],
        },
        blockers,
    )


def assess_manufacturing_claim(
    snapshot_path: str | Path,
    selection_path: str | Path,
) -> dict[str, Any]:
    snapshot_source = Path(snapshot_path)
    selection_source = Path(selection_path)
    snapshot_raw, snapshot = _json_file(snapshot_source, "snapshot")
    _, selection = _json_file(selection_source, "selection")
    if snapshot.get("format") != CLAIM_SNAPSHOT_FORMAT:
        raise ValueError(f"snapshot format must be {CLAIM_SNAPSHOT_FORMAT}")
    if selection.get("format") != MANUFACTURING_CLAIM_SELECTION_FORMAT:
        raise ValueError(
            f"selection format must be {MANUFACTURING_CLAIM_SELECTION_FORMAT}"
        )
    _only(
        selection,
        {
            "format",
            "snapshot_sha256",
            "expected_valid_at",
            "expected_known_at",
            "claim_key",
            "expected_revision_id",
            "usage",
            "target_input_path",
            "allowed_postures",
            "expected_claim_dimensions",
            "target_dimensions",
            "conversion",
            "nonbinding_rationale",
        },
        "selection",
    )
    snapshot_sha256 = hashlib.sha256(snapshot_raw).hexdigest()
    if snapshot_sha256 != _required_text(
        selection.get("snapshot_sha256"),
        "selection.snapshot_sha256",
    ):
        raise ValueError("claim snapshot SHA-256 mismatch")
    expected_valid_at = _required_text(
        selection.get("expected_valid_at"),
        "selection.expected_valid_at",
    )
    try:
        expected_valid_at = date.fromisoformat(expected_valid_at).isoformat()
    except ValueError as exc:
        raise ValueError("selection.expected_valid_at must be an ISO date") from exc
    if snapshot.get("valid_at") != expected_valid_at:
        raise ValueError("claim snapshot valid_at does not match selection")
    expected_known_at = _required_text(
        selection.get("expected_known_at"),
        "selection.expected_known_at",
    )
    if _iso_timestamp(expected_known_at, "selection.expected_known_at") != _iso_timestamp(
        _required_text(snapshot.get("known_at"), "snapshot.known_at"),
        "snapshot.known_at",
    ):
        raise ValueError("claim snapshot known_at does not match selection")
    claim_key = _required_text(selection.get("claim_key"), "selection.claim_key")
    claims = snapshot.get("claims")
    if not isinstance(claims, list):
        raise ValueError("snapshot.claims must be an array")
    matches = [item for item in claims if isinstance(item, dict) and item.get("claim_key") == claim_key]
    if len(matches) != 1:
        raise ValueError(f"claim snapshot must contain exactly one {claim_key} claim")
    claim = matches[0]
    expected_revision = _required_text(
        selection.get("expected_revision_id"),
        "selection.expected_revision_id",
    )
    if claim.get("revision_id") != expected_revision:
        raise ValueError("claim revision does not match selection")
    expected_claim_dimensions = _dimension_map(
        selection.get("expected_claim_dimensions"),
        "selection.expected_claim_dimensions",
    )
    claim_dimensions = _dimension_map(claim.get("dimensions"), "claim.dimensions")
    if claim_dimensions != expected_claim_dimensions:
        raise ValueError("claim dimensions do not match selection expectations")
    usage = _required_text(selection.get("usage"), "selection.usage")
    if usage not in USAGES:
        raise ValueError(f"unsupported manufacturing claim usage: {usage}")
    target_input_path = _required_text(
        selection.get("target_input_path"),
        "selection.target_input_path",
    )
    postures = selection.get("allowed_postures")
    if not isinstance(postures, list) or not postures:
        raise ValueError("selection.allowed_postures requires at least one posture")
    if not all(item in {"reported", "derived", "modeled", "synthetic"} for item in postures):
        raise ValueError("selection.allowed_postures contains an unsupported posture")
    if len(postures) != len(set(postures)):
        raise ValueError("selection.allowed_postures contains duplicates")
    target_dimensions_value = selection.get("target_dimensions")
    if usage == "constraint_input":
        target_dimensions = _dimension_map(
            target_dimensions_value,
            "selection.target_dimensions",
        )
    else:
        target_dimensions_mapping = _mapping(
            target_dimensions_value,
            "selection.target_dimensions",
        )
        if target_dimensions_mapping:
            raise ValueError("nonbinding usage requires empty target_dimensions")
        target_dimensions = {}
    conversion_value = selection.get("conversion")
    if usage == "directional_signal":
        if conversion_value is not None:
            raise ValueError("directional_signal usage requires null conversion")
        conversion = None
    else:
        conversion = _mapping(conversion_value, "selection.conversion")
        _only(
            conversion,
            {"source_unit", "target_unit", "multiplier"},
            "selection.conversion",
        )
        source_unit = _required_text(
            conversion.get("source_unit"),
            "selection.conversion.source_unit",
        )
        target_unit = _required_text(
            conversion.get("target_unit"),
            "selection.conversion.target_unit",
        )
        multiplier = conversion.get("multiplier")
        if not _numeric(multiplier) or multiplier <= 0:
            raise ValueError("selection.conversion.multiplier must be positive")
        conversion = {
            "source_unit": source_unit,
            "target_unit": target_unit,
            "multiplier": float(multiplier),
        }
    nonbinding_rationale = _optional_text(
        selection.get("nonbinding_rationale"),
        "selection.nonbinding_rationale",
    )
    if usage == "constraint_input" and nonbinding_rationale is not None:
        raise ValueError("constraint_input usage cannot set nonbinding_rationale")
    if usage != "constraint_input" and not nonbinding_rationale:
        raise ValueError("nonbinding usage requires nonbinding_rationale")

    blockers = []
    if claim.get("posture") not in postures:
        blockers.append(
            {
                "code": "posture_not_allowed",
                "message": f"claim posture {claim.get('posture')} is not allowed",
            }
        )
    if usage == "constraint_input":
        for field in sorted(target_dimensions):
            if claim_dimensions.get(field) != target_dimensions[field]:
                blockers.append(
                    {
                        "code": f"dimension_mismatch:{field}",
                        "message": (
                            f"claim {field} is {claim_dimensions.get(field)!r}; "
                            f"target requires {target_dimensions[field]!r}"
                        ),
                    }
                )
    normalized_estimate = None
    if conversion is not None:
        if claim.get("unit") != conversion["source_unit"]:
            blockers.append(
                {
                    "code": "source_unit_mismatch",
                    "message": (
                        f"claim unit {claim.get('unit')!r} does not match "
                        f"selection source unit {conversion['source_unit']!r}"
                    ),
                }
            )
        else:
            normalized_estimate, range_blockers = _normalized_range(
                claim.get("value"),
                multiplier=conversion["multiplier"],
                target_unit=conversion["target_unit"],
                source_posture=claim["posture"],
                methodology=(
                    f"Claim gate conversion: {claim['methodology']} "
                    f"Applied multiplier {conversion['multiplier']:g} from "
                    f"{conversion['source_unit']} to {conversion['target_unit']}."
                ),
                confidence=float(claim["confidence"]),
                recorded_at=claim["recorded_at"],
                evidence=claim["evidence"],
            )
            blockers.extend(range_blockers)
    accepted_for_usage = not blockers
    eligible_as_constraint = usage == "constraint_input" and accepted_for_usage
    if not eligible_as_constraint:
        constraint_estimate = None
    else:
        constraint_estimate = normalized_estimate
    return {
        "format": MANUFACTURING_CLAIM_ASSESSMENT_FORMAT,
        "usage": usage,
        "accepted_for_usage": accepted_for_usage,
        "eligible_as_constraint": eligible_as_constraint,
        "target_input_path": target_input_path,
        "claim_key": claim_key,
        "revision_id": claim["revision_id"],
        "claim_value": claim["value"],
        "claim_unit": claim["unit"],
        "claim_posture": claim["posture"],
        "claim_dimensions": claim_dimensions,
        "target_dimensions": target_dimensions,
        "conversion": conversion,
        "normalized_estimate": normalized_estimate,
        "constraint_estimate": constraint_estimate,
        "blocking_reasons": blockers,
        "nonbinding_rationale": nonbinding_rationale,
        "lineage": {
            "snapshot_path": str(snapshot_source.resolve()),
            "snapshot_sha256": snapshot_sha256,
            "valid_at": snapshot["valid_at"],
            "known_at": snapshot["known_at"],
            "source_snapshot_ids": [item["snapshot_id"] for item in claim["evidence"]],
        },
    }
