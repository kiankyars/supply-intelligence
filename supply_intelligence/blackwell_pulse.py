"""Evidence classification and fail-closed gates for the Blackwell weekly pulse."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .upstream_release import (
    REQUIRED_UPSTREAMS,
    VerifiedUpstreamRelease,
    ensure_not_upstream_worktree_path,
)


PULSE_FORMAT = "ai-supply-blackwell-constraint-pulse.v1"
SYNTHETIC_AUDIT_FORMAT = "ai-supply-blackwell-synthetic-input-audit.v1"
UPSTREAM_CLAIMS_FORMAT = "ai-supply-upstream-claims.v1"
NO_EVIDENCE_BACKED_ESTIMATE = "no evidence-backed estimate."
PRODUCT = "blackwell-constraint-pulse"
TARGET_QUARTER = "2026-Q4"
TARGET_QUARTER_START = date(2026, 10, 1)
TARGET_QUARTER_END = date(2026, 12, 31)
MAX_UPSTREAM_RELEASE_AGE = timedelta(days=7)
FROZEN_BASELINE_COMMIT = "6d287e9bae400a54d05f8f8ae15687eb80dedbfb"
FROZEN_BASELINE_QUARTER = "2026-Q3"
FROZEN_ACTIVE_INPUT_COUNT = 107
FROZEN_DIAGNOSTIC_INPUT_IDS = frozenset(
    {"hbm_supplier:platform.accelerator_package_demand"}
)
FROZEN_ACTIVE_INPUT_IDS_SHA256 = (
    "4e4291d3e5fba63b6bf92a448fa4a576ef86e00cf09eb137acb25f47670ce5c2"
)
FROZEN_SYNTHETIC_AUDIT_SEMANTIC_SHA256 = (
    "b01bc728b58d9cc92aa8e36ad184988ad9db32a3a376d6c0879c7e7f26d035f4"
)
REQUIRED_GATE_TARGETS = {
    "gate:energization.q4-operational-nvl72-systems": "energization",
    "gate:manufacture.q4-blackwell-systems": "manufacture",
    "gate:shipment.q4-selected-site-nvl72-systems": "shipment",
}
REQUIRED_CATEGORICAL_GATES = frozenset(
    {
        "categorical:cross-stage.cross-source-dependence",
        "categorical:energization.operational-deduction-non-overlap",
        "categorical:manufacture.hbm-supplier-identity-non-overlap",
        "categorical:manufacture.material-cleared-packages",
        "categorical:shipment.component-cleared-racks",
        "categorical:shipment.component-identity-non-overlap",
        "categorical:shipment.odm-identity-non-overlap",
        "categorical:shipment.site-shipment-attribution",
    }
)
STAGES = ("manufacture", "shipment", "energization")
PARAMETER_CLASSES = {
    "allocation",
    "capacity",
    "conversion",
    "demand",
    "economics",
    "geometry",
    "other",
    "throughput",
    "timing",
    "topology",
    "utilization",
    "yield",
}
PROTECTED_UNKNOWNS = (
    "allocation",
    "capacity",
    "demand",
    "economics",
    "utilization",
    "yield",
)
POSTURES = {"reported", "derived", "modeled", "synthetic"}
EVIDENCE_GATE_POSTURES = {"reported", "derived"}
RANGE_BASES = {"bounded_interval", "exact"}
CLAIM_KINDS = {"numerical", "directional", "missing"}
INTENDED_USES = {"constraint", "scale_control", "signal"}
CHANGE_STATUSES = {"added", "revised", "removed", "unchanged"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9:._-]*$")


class ClaimClassification(StrEnum):
    NUMERICAL_CONSTRAINT = "numerical_constraint"
    SCALE_CONTROL = "scale_control"
    DIRECTIONAL_EVIDENCE = "directional_evidence"
    INCOMPATIBLE = "incompatible"
    MISSING = "missing"


CLASSIFICATIONS = {item.value for item in ClaimClassification}


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    missing = fields - set(value)
    if unexpected or missing:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if unexpected:
            details.append(f"unexpected {sorted(unexpected)}")
        raise ValueError(f"{path} fields are invalid: {'; '.join(details)}")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _identifier(value: Any, path: str) -> str:
    text = _text(value, path)
    if not IDENTIFIER_PATTERN.fullmatch(text):
        raise ValueError(f"{path} must be a stable lowercase identifier")
    return text


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{path} must be boolean")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a nonnegative integer")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{path} must be finite and nonnegative")
    return result


def _date(value: Any, path: str) -> date:
    text = _text(value, path)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _timestamp(value: Any, path: str) -> datetime:
    text = _text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _string_list(value: Any, path: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path} must be an array of strings")
    values = tuple(value)
    if not allow_empty and not values:
        raise ValueError(f"{path} cannot be empty")
    if any(not item.strip() for item in values):
        raise ValueError(f"{path} cannot contain blanks")
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{path} must be unique and sorted")
    return values


def _range(value: Any, path: str, *, expected_unit: str | None = None) -> dict[str, Any]:
    source = _mapping(value, path)
    _only(source, {"low", "base", "high", "unit"}, path)
    low = _number(source["low"], f"{path}.low")
    base = _number(source["base"], f"{path}.base")
    high = _number(source["high"], f"{path}.high")
    if not low <= base <= high:
        raise ValueError(f"{path} must satisfy low <= base <= high")
    unit = _text(source["unit"], f"{path}.unit")
    if expected_unit is not None and unit != expected_unit:
        raise ValueError(f"{path}.unit must be {expected_unit}")
    if unit == "ratio" and high > 1:
        raise ValueError(f"{path} ratio values cannot exceed 1")
    return {"low": low, "base": base, "high": high, "unit": unit}


def _evidence_gate(value: Any, path: str) -> dict[str, Any]:
    source = _mapping(value, path)
    _only(
        source,
        {"required_for_numerical_result", "accepted_postures", "description"},
        path,
    )
    postures = _string_list(source["accepted_postures"], f"{path}.accepted_postures")
    if unexpected := set(postures) - EVIDENCE_GATE_POSTURES:
        raise ValueError(f"{path}.accepted_postures has unsupported values: {sorted(unexpected)}")
    return {
        "required_for_numerical_result": _boolean(
            source["required_for_numerical_result"],
            f"{path}.required_for_numerical_result",
        ),
        "accepted_postures": list(postures),
        "description": _text(source["description"], f"{path}.description"),
    }


def _requirement_fields(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    stage = _text(value["stage"], f"{path}.stage")
    if stage not in STAGES:
        raise ValueError(f"{path}.stage is unsupported")
    upstream = _text(value["required_upstream"], f"{path}.required_upstream")
    if upstream not in REQUIRED_UPSTREAMS:
        raise ValueError(f"{path}.required_upstream is unsupported")
    required_type = _text(value["required_claim_type"], f"{path}.required_claim_type")
    if required_type not in CLASSIFICATIONS:
        raise ValueError(f"{path}.required_claim_type is unsupported")
    accepted_range_bases = _string_list(
        value["accepted_range_bases"],
        f"{path}.accepted_range_bases",
    )
    if unexpected := set(accepted_range_bases) - RANGE_BASES:
        raise ValueError(
            f"{path}.accepted_range_bases has unsupported values: {sorted(unexpected)}"
        )
    return {
        "stage": stage,
        "unit": _text(value["unit"], f"{path}.unit"),
        "required_upstream": upstream,
        "required_claim_type": required_type,
        "accepted_range_bases": list(accepted_range_bases),
        "attribution_basis": _text(value["attribution_basis"], f"{path}.attribution_basis"),
        "time_basis": _text(value["time_basis"], f"{path}.time_basis"),
        "evidence_gate": _evidence_gate(value["evidence_gate"], f"{path}.evidence_gate"),
    }


@dataclass(frozen=True, slots=True)
class SyntheticInputAudit:
    raw: bytes
    sha256: str
    semantic_sha256: str
    document: Mapping[str, Any]
    inputs: tuple[Mapping[str, Any], ...]
    gate_targets: tuple[Mapping[str, Any], ...]
    categorical_gates: tuple[Mapping[str, Any], ...]

    @property
    def requirements(self) -> tuple[Mapping[str, Any], ...]:
        return self.inputs + self.gate_targets

    @property
    def by_id(self) -> dict[str, Mapping[str, Any]]:
        return {item["id"]: item for item in self.requirements}


def synthetic_input_audit_from_dict(
    document: Mapping[str, Any],
    *,
    raw: bytes | None = None,
) -> SyntheticInputAudit:
    _only(
        document,
        {
            "format",
            "product",
            "target_quarter",
            "required_upstreams",
            "baseline",
            "inputs",
            "gate_targets",
            "categorical_gates",
            "protected_unknowns",
        },
        "synthetic audit",
    )
    if document["format"] != SYNTHETIC_AUDIT_FORMAT:
        raise ValueError(f"synthetic audit format must be {SYNTHETIC_AUDIT_FORMAT}")
    if document["product"] != PRODUCT or document["target_quarter"] != TARGET_QUARTER:
        raise ValueError("synthetic audit product or target quarter is incompatible")
    required_upstreams = _string_list(
        document["required_upstreams"],
        "synthetic audit.required_upstreams",
    )
    if required_upstreams != tuple(sorted(REQUIRED_UPSTREAMS)):
        raise ValueError("synthetic audit must require both Atlas upstreams")

    baseline = _mapping(document["baseline"], "synthetic audit.baseline")
    _only(
        baseline,
        {
            "source_commit",
            "source_quarter",
            "active_numeric_input_count",
            "diagnostic_numeric_input_count",
            "active_input_ids_sha256",
            "notes",
        },
        "synthetic audit.baseline",
    )
    source_commit = _text(baseline["source_commit"], "synthetic audit.baseline.source_commit")
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ValueError("synthetic audit baseline source_commit must be a full Git commit")
    if source_commit != FROZEN_BASELINE_COMMIT:
        raise ValueError("synthetic audit baseline source_commit is not the frozen v1 commit")
    source_quarter = _text(baseline["source_quarter"], "synthetic audit.baseline.source_quarter")
    if source_quarter != FROZEN_BASELINE_QUARTER:
        raise ValueError("synthetic audit baseline source_quarter must remain 2026-Q3")
    active_count = _integer(
        baseline["active_numeric_input_count"],
        "synthetic audit.baseline.active_numeric_input_count",
    )
    diagnostic_count = _integer(
        baseline["diagnostic_numeric_input_count"],
        "synthetic audit.baseline.diagnostic_numeric_input_count",
    )
    expected_ids_sha = _text(
        baseline["active_input_ids_sha256"],
        "synthetic audit.baseline.active_input_ids_sha256",
    )
    if not SHA256_PATTERN.fullmatch(expected_ids_sha):
        raise ValueError("synthetic audit baseline active_input_ids_sha256 is invalid")
    if (
        active_count != FROZEN_ACTIVE_INPUT_COUNT
        or diagnostic_count != len(FROZEN_DIAGNOSTIC_INPUT_IDS)
        or expected_ids_sha != FROZEN_ACTIVE_INPUT_IDS_SHA256
    ):
        raise ValueError("synthetic audit baseline does not match the frozen v1 coverage contract")
    _text(baseline["notes"], "synthetic audit.baseline.notes")

    input_values = document["inputs"]
    if not isinstance(input_values, list) or not input_values:
        raise ValueError("synthetic audit.inputs requires at least one row")
    inputs = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(input_values):
        path = f"synthetic audit.inputs[{index}]"
        item = _mapping(raw_item, path)
        _only(
            item,
            {
                "id",
                "current_source",
                "current_range",
                "current_posture",
                "active_for_supply_to_site",
                "parameter_class",
                "stage",
                "unit",
                "required_upstream",
                "required_claim_type",
                "accepted_range_bases",
                "attribution_basis",
                "time_basis",
                "evidence_gate",
            },
            path,
        )
        item_id = _identifier(item["id"], f"{path}.id")
        if item_id in seen_ids:
            raise ValueError(f"duplicate synthetic audit input id: {item_id}")
        seen_ids.add(item_id)
        active = _boolean(
            item["active_for_supply_to_site"],
            f"{path}.active_for_supply_to_site",
        )
        parameter_class = _text(item["parameter_class"], f"{path}.parameter_class")
        if parameter_class not in PARAMETER_CLASSES:
            raise ValueError(f"{path}.parameter_class is unsupported")
        common = _requirement_fields(item, path)
        if item["current_posture"] != "synthetic":
            raise ValueError(f"{path}.current_posture must remain synthetic")
        current_range = _range(
            item["current_range"],
            f"{path}.current_range",
            expected_unit=common["unit"],
        )
        if active and not common["evidence_gate"]["required_for_numerical_result"]:
            raise ValueError(f"active input {item_id} must be required by the numerical gate")
        if (
            active
            and common["required_claim_type"]
            != ClaimClassification.NUMERICAL_CONSTRAINT.value
        ):
            raise ValueError(f"active input {item_id} requires numerical_constraint evidence")
        inputs.append(
            {
                "kind": "synthetic_input",
                "id": item_id,
                "current_source": _text(item["current_source"], f"{path}.current_source"),
                "current_range": current_range,
                "current_posture": "synthetic",
                "active_for_supply_to_site": active,
                "parameter_class": parameter_class,
                **common,
            }
        )

    active_ids = sorted(item["id"] for item in inputs if item["active_for_supply_to_site"])
    diagnostic_ids = sorted(item["id"] for item in inputs if not item["active_for_supply_to_site"])
    if len(active_ids) != active_count or len(diagnostic_ids) != diagnostic_count:
        raise ValueError("synthetic audit input cardinality does not match its frozen baseline")
    actual_ids_sha = hashlib.sha256(
        ("\n".join(active_ids) + "\n").encode("utf-8")
    ).hexdigest()
    if actual_ids_sha != expected_ids_sha:
        raise ValueError("synthetic audit active input ID set does not match its frozen baseline")
    if set(diagnostic_ids) != FROZEN_DIAGNOSTIC_INPUT_IDS:
        raise ValueError("synthetic audit diagnostic input set does not match its frozen baseline")

    gate_values = document["gate_targets"]
    if not isinstance(gate_values, list) or not gate_values:
        raise ValueError("synthetic audit.gate_targets requires stage output targets")
    gate_targets = []
    for index, raw_item in enumerate(gate_values):
        path = f"synthetic audit.gate_targets[{index}]"
        item = _mapping(raw_item, path)
        _only(
            item,
            {
                "id",
                "description",
                "stage",
                "unit",
                "required_upstream",
                "required_claim_type",
                "accepted_range_bases",
                "attribution_basis",
                "time_basis",
                "evidence_gate",
            },
            path,
        )
        target_id = _identifier(item["id"], f"{path}.id")
        if target_id in seen_ids:
            raise ValueError(f"duplicate audit requirement id: {target_id}")
        seen_ids.add(target_id)
        common = _requirement_fields(item, path)
        if common["unit"] != "system":
            raise ValueError(f"{path}.unit must be system for supply-to-site comparison")
        if common["required_claim_type"] != ClaimClassification.NUMERICAL_CONSTRAINT.value:
            raise ValueError(f"{path} must require numerical_constraint evidence")
        if not common["evidence_gate"]["required_for_numerical_result"]:
            raise ValueError(f"{path} must be required by the numerical gate")
        gate_targets.append(
            {
                "kind": "gate_target",
                "id": target_id,
                "description": _text(item["description"], f"{path}.description"),
                **common,
            }
        )
    actual_gate_targets = {item["id"]: item["stage"] for item in gate_targets}
    if actual_gate_targets != REQUIRED_GATE_TARGETS:
        raise ValueError("synthetic audit gate targets do not match the frozen v1 contract")
    if [item["id"] for item in gate_targets] != sorted(actual_gate_targets):
        raise ValueError("synthetic audit.gate_targets must be sorted by stable ID")

    categorical_values = document["categorical_gates"]
    if not isinstance(categorical_values, list):
        raise ValueError("synthetic audit.categorical_gates must be an array")
    categorical_gates = []
    categorical_ids: set[str] = set()
    for index, raw_item in enumerate(categorical_values):
        path = f"synthetic audit.categorical_gates[{index}]"
        item = _mapping(raw_item, path)
        _only(
            item,
            {
                "id",
                "stage",
                "current_source",
                "current_status",
                "required_upstreams",
                "required_for_numerical_result",
                "accepted_postures",
                "time_basis",
                "attribution_basis",
                "description",
            },
            path,
        )
        gate_id = _identifier(item["id"], f"{path}.id")
        if gate_id in categorical_ids:
            raise ValueError(f"duplicate categorical gate id: {gate_id}")
        categorical_ids.add(gate_id)
        stage = _text(item["stage"], f"{path}.stage")
        if stage not in (*STAGES, "cross_stage"):
            raise ValueError(f"{path}.stage is unsupported")
        upstreams = _string_list(item["required_upstreams"], f"{path}.required_upstreams")
        if unexpected := set(upstreams) - REQUIRED_UPSTREAMS:
            raise ValueError(f"{path}.required_upstreams is unsupported: {sorted(unexpected)}")
        if item["current_status"] != "synthetic":
            raise ValueError(f"{path}.current_status must remain synthetic")
        accepted_postures = _string_list(
            item["accepted_postures"],
            f"{path}.accepted_postures",
        )
        if unexpected := set(accepted_postures) - EVIDENCE_GATE_POSTURES:
            raise ValueError(
                f"{path}.accepted_postures has unsupported values: {sorted(unexpected)}"
            )
        categorical_gates.append(
            {
                "id": gate_id,
                "stage": stage,
                "current_source": _text(item["current_source"], f"{path}.current_source"),
                "current_status": "synthetic",
                "required_upstreams": list(upstreams),
                "required_for_numerical_result": _boolean(
                    item["required_for_numerical_result"],
                    f"{path}.required_for_numerical_result",
                ),
                "accepted_postures": list(accepted_postures),
                "time_basis": _text(item["time_basis"], f"{path}.time_basis"),
                "attribution_basis": _text(
                    item["attribution_basis"],
                    f"{path}.attribution_basis",
                ),
                "description": _text(item["description"], f"{path}.description"),
            }
        )
    if categorical_ids != REQUIRED_CATEGORICAL_GATES:
        raise ValueError("synthetic audit categorical gates do not match the frozen v1 contract")
    if [item["id"] for item in categorical_gates] != sorted(categorical_ids):
        raise ValueError("synthetic audit.categorical_gates must be sorted by stable ID")
    if not all(item["required_for_numerical_result"] for item in categorical_gates):
        raise ValueError("all frozen v1 categorical gates are required for a numerical result")

    protected_values = document["protected_unknowns"]
    if not isinstance(protected_values, list):
        raise ValueError("synthetic audit.protected_unknowns must be an array")
    protected = []
    for index, raw_item in enumerate(protected_values):
        path = f"synthetic audit.protected_unknowns[{index}]"
        item = _mapping(raw_item, path)
        _only(item, {"dimension", "policy"}, path)
        protected.append(
            {
                "dimension": _text(item["dimension"], f"{path}.dimension"),
                "policy": _text(item["policy"], f"{path}.policy"),
            }
        )
    if tuple(item["dimension"] for item in protected) != PROTECTED_UNKNOWNS:
        raise ValueError("synthetic audit must preserve all protected unknown dimensions in order")

    semantic_sha256 = hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if semantic_sha256 != FROZEN_SYNTHETIC_AUDIT_SEMANTIC_SHA256:
        raise ValueError("synthetic audit semantics do not match the frozen v1 catalog")

    canonical_raw = raw if raw is not None else (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    normalized = dict(document)
    normalized["baseline"] = dict(baseline)
    normalized["inputs"] = inputs
    normalized["gate_targets"] = gate_targets
    normalized["categorical_gates"] = categorical_gates
    normalized["protected_unknowns"] = protected
    return SyntheticInputAudit(
        raw=canonical_raw,
        sha256=hashlib.sha256(canonical_raw).hexdigest(),
        semantic_sha256=semantic_sha256,
        document=normalized,
        inputs=tuple(inputs),
        gate_targets=tuple(gate_targets),
        categorical_gates=tuple(categorical_gates),
    )


def load_synthetic_input_audit(path: str | Path) -> SyntheticInputAudit:
    source = ensure_not_upstream_worktree_path(path, "synthetic audit")
    raw = source.read_bytes()
    try:
        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON field in synthetic input audit: {key}")
                result[key] = value
            return result

        document = json.loads(raw, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in synthetic input audit {source}: {exc}") from exc
    return synthetic_input_audit_from_dict(_mapping(document, "synthetic audit"), raw=raw)


def _claim_evidence(
    value: Any,
    path: str,
    *,
    release_recorded_at: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path} requires at least one evidence record")
    result = []
    ids: set[str] = set()
    for index, raw_item in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _mapping(raw_item, item_path)
        _only(
            item,
            {"id", "source_url", "publisher", "published_at", "retrieved_at", "content_sha256"},
            item_path,
        )
        evidence_id = _identifier(item["id"], f"{item_path}.id")
        if evidence_id in ids:
            raise ValueError(f"duplicate evidence id in {path}: {evidence_id}")
        ids.add(evidence_id)
        url = _text(item["source_url"], f"{item_path}.source_url")
        parsed_url = urlsplit(url)
        try:
            parsed_port = parsed_url.port
        except ValueError as exc:
            raise ValueError(f"{item_path}.source_url must be a valid HTTPS URL") from exc
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_port not in {None, 443}
        ):
            raise ValueError(f"{item_path}.source_url must be a valid HTTPS URL")
        published_at = _timestamp(item["published_at"], f"{item_path}.published_at")
        retrieved_at = _timestamp(item["retrieved_at"], f"{item_path}.retrieved_at")
        if published_at > retrieved_at or retrieved_at > release_recorded_at:
            raise ValueError(f"{item_path} publication/retrieval order is invalid")
        digest = _text(item["content_sha256"], f"{item_path}.content_sha256")
        if not SHA256_PATTERN.fullmatch(digest):
            raise ValueError(f"{item_path}.content_sha256 must be a lowercase SHA-256")
        result.append(
            {
                "id": evidence_id,
                "source_url": url,
                "publisher": _text(item["publisher"], f"{item_path}.publisher"),
                "published_at": published_at.isoformat().replace("+00:00", "Z"),
                "retrieved_at": retrieved_at.isoformat().replace("+00:00", "Z"),
                "content_sha256": digest,
            }
        )
    return result


def _claim_gate_supports(
    value: Any,
    path: str,
    *,
    evidence_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    supports = []
    seen_gate_ids: set[str] = set()
    for index, raw_item in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _mapping(raw_item, item_path)
        _only(
            item,
            {
                "gate_id",
                "assertion",
                "period",
                "time_basis",
                "attribution_basis",
                "posture",
                "evidence_ids",
            },
            item_path,
        )
        gate_id = _identifier(item["gate_id"], f"{item_path}.gate_id")
        if gate_id in seen_gate_ids:
            raise ValueError(f"duplicate categorical gate support in {path}: {gate_id}")
        seen_gate_ids.add(gate_id)
        posture = _text(item["posture"], f"{item_path}.posture")
        if posture not in POSTURES:
            raise ValueError(f"{item_path}.posture is unsupported")
        support_evidence_ids = _string_list(
            item["evidence_ids"],
            f"{item_path}.evidence_ids",
        )
        if unknown := set(support_evidence_ids) - evidence_ids:
            raise ValueError(
                f"{item_path}.evidence_ids are not present on the parent claim: "
                f"{sorted(unknown)}"
            )
        supports.append(
            {
                "gate_id": gate_id,
                "assertion": _text(item["assertion"], f"{item_path}.assertion"),
                "period": _text(item["period"], f"{item_path}.period"),
                "time_basis": _text(
                    item["time_basis"],
                    f"{item_path}.time_basis",
                ),
                "attribution_basis": _text(
                    item["attribution_basis"],
                    f"{item_path}.attribution_basis",
                ),
                "posture": posture,
                "evidence_ids": list(support_evidence_ids),
            }
        )
    if [item["gate_id"] for item in supports] != sorted(seen_gate_ids):
        raise ValueError(f"{path} must be sorted by gate_id")
    return supports


def _claims_from_release(release: VerifiedUpstreamRelease) -> list[dict[str, Any]]:
    document = _mapping(release.claims, f"{release.entry.upstream_id} claims")
    _only(document, {"format", "claims"}, f"{release.entry.upstream_id} claims")
    if document["format"] != UPSTREAM_CLAIMS_FORMAT:
        raise ValueError(
            f"{release.entry.upstream_id} claims format must be "
            f"{UPSTREAM_CLAIMS_FORMAT}"
        )
    values = document["claims"]
    if not isinstance(values, list):
        raise ValueError(f"{release.entry.upstream_id} claims must be an array")
    release_recorded_at = _timestamp(
        release.manifest["recorded_at"],
        f"{release.entry.upstream_id} manifest.recorded_at",
    )
    comparison = release.manifest["comparison"]
    claims = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(values):
        path = f"{release.entry.upstream_id} claims[{index}]"
        item = _mapping(raw_item, path)
        _only(
            item,
            {
                "id",
                "target_id",
                "claim_kind",
                "intended_use",
                "change_status",
                "summary",
                "value",
                "range_basis",
                "posture",
                "period",
                "time_basis",
                "attribution_basis",
                "gate_supports",
                "evidence",
            },
            path,
        )
        claim_id = _identifier(item["id"], f"{path}.id")
        if claim_id in seen_ids:
            raise ValueError(f"duplicate upstream claim id: {claim_id}")
        seen_ids.add(claim_id)
        claim_kind = _text(item["claim_kind"], f"{path}.claim_kind")
        intended_use = _text(item["intended_use"], f"{path}.intended_use")
        change_status = _text(item["change_status"], f"{path}.change_status")
        if claim_kind not in CLAIM_KINDS:
            raise ValueError(f"{path}.claim_kind is unsupported")
        if intended_use not in INTENDED_USES:
            raise ValueError(f"{path}.intended_use is unsupported")
        if change_status not in CHANGE_STATUSES:
            raise ValueError(f"{path}.change_status is unsupported")
        if comparison is None and change_status not in {"added", "unchanged"}:
            raise ValueError(
                f"{path}.change_status requires a producer-declared comparison release"
            )
        posture = item["posture"]
        if posture is not None and posture not in POSTURES:
            raise ValueError(f"{path}.posture is unsupported")
        period = _text(item["period"], f"{path}.period")
        time_basis = _text(item["time_basis"], f"{path}.time_basis")
        attribution_basis = _text(
            item["attribution_basis"],
            f"{path}.attribution_basis",
        )
        value = item["value"]
        range_basis = item["range_basis"]
        evidence = item["evidence"]
        if claim_kind == "missing" or change_status == "removed":
            if value is not None or evidence != []:
                raise ValueError(f"{path} missing/removed claims cannot carry value or evidence")
            if range_basis is not None:
                raise ValueError(f"{path} missing/removed claims must use a null range_basis")
            if claim_kind == "missing" and posture is not None:
                raise ValueError(f"{path} missing claims must use a null posture")
            parsed_value = None
            parsed_evidence: list[dict[str, Any]] = []
            parsed_gate_supports: list[dict[str, Any]] = []
            if item["gate_supports"] != []:
                raise ValueError(f"{path} missing/removed claims cannot support categorical gates")
        else:
            if posture is None:
                raise ValueError(f"{path} non-missing claims require an evidence posture")
            parsed_evidence = _claim_evidence(
                evidence,
                f"{path}.evidence",
                release_recorded_at=release_recorded_at,
            )
            if claim_kind == "numerical":
                parsed_value = _range(value, f"{path}.value")
                parsed_range_basis = _text(range_basis, f"{path}.range_basis")
                if parsed_range_basis not in RANGE_BASES:
                    raise ValueError(f"{path}.range_basis is unsupported")
                if parsed_range_basis == "exact" and not (
                    parsed_value["low"]
                    == parsed_value["base"]
                    == parsed_value["high"]
                ):
                    raise ValueError(f"{path} exact range_basis requires one repeated value")
            elif value is not None:
                raise ValueError(f"{path} directional claims cannot carry a numeric value")
            else:
                parsed_value = None
                if range_basis is not None:
                    raise ValueError(f"{path} directional claims must use a null range_basis")
                parsed_range_basis = None
            parsed_gate_supports = _claim_gate_supports(
                item["gate_supports"],
                f"{path}.gate_supports",
                evidence_ids={item["id"] for item in parsed_evidence},
            )
        claims.append(
            {
                "upstream_id": release.entry.upstream_id,
                "release_tag": release.entry.release_tag,
                "comparison": comparison,
                "id": claim_id,
                "target_id": _identifier(item["target_id"], f"{path}.target_id"),
                "claim_kind": claim_kind,
                "intended_use": intended_use,
                "change_status": change_status,
                "summary": _text(item["summary"], f"{path}.summary"),
                "value": parsed_value,
                "range_basis": (
                    None
                    if claim_kind == "missing" or change_status == "removed"
                    else parsed_range_basis
                ),
                "posture": posture,
                "period": period,
                "time_basis": time_basis,
                "attribution_basis": attribution_basis,
                "gate_supports": parsed_gate_supports,
                "evidence": parsed_evidence,
            }
        )
    return claims


def _classify_claim(
    claim: Mapping[str, Any],
    requirement: Mapping[str, Any] | None,
    *,
    release_is_fresh: bool,
) -> tuple[ClaimClassification, list[str]]:
    if claim["claim_kind"] == "missing" or claim["change_status"] == "removed":
        return ClaimClassification.MISSING, ["source_reports_missing_or_removed"]
    if requirement is None:
        return ClaimClassification.INCOMPATIBLE, ["unknown_target_id"]
    if claim["claim_kind"] == "directional" or claim["intended_use"] == "signal":
        return ClaimClassification.DIRECTIONAL_EVIDENCE, ["qualitative_or_directional_only"]
    if claim["intended_use"] == "scale_control":
        return ClaimClassification.SCALE_CONTROL, ["explicitly_nonbinding_scale_control"]

    reasons = []
    if claim["upstream_id"] != requirement["required_upstream"]:
        reasons.append("wrong_upstream")
    if claim["value"] is None:
        reasons.append("missing_numeric_range")
    elif claim["value"]["unit"] != requirement["unit"]:
        reasons.append("incompatible_unit")
    if claim["range_basis"] not in requirement["accepted_range_bases"]:
        reasons.append("incompatible_range_basis")
    if claim["period"] != TARGET_QUARTER:
        reasons.append("incompatible_period")
    if claim["time_basis"] != requirement["time_basis"]:
        reasons.append("incompatible_time_basis")
    if claim["attribution_basis"] != requirement["attribution_basis"]:
        reasons.append("unsupported_attribution")
    if claim["posture"] not in requirement["evidence_gate"]["accepted_postures"]:
        reasons.append("unsupported_posture")
    if not claim["evidence"]:
        reasons.append("missing_suitable_evidence")
    if not release_is_fresh:
        reasons.append("stale_upstream_release")
    if reasons:
        return ClaimClassification.INCOMPATIBLE, reasons
    return ClaimClassification.NUMERICAL_CONSTRAINT, ["all_scope_and_evidence_gates_pass"]


def _minimum_range(
    values: Iterable[Mapping[str, Any]],
    *,
    range_bases: Iterable[str],
) -> dict[str, Any]:
    ranges = list(values)
    bases = list(range_bases)
    if not ranges:
        raise ValueError("cannot calculate a stage estimate without ranges")
    if len(ranges) != len(bases) or not set(bases) <= RANGE_BASES:
        raise ValueError("stage gate ranges require one supported basis each")
    units = {item["unit"] for item in ranges}
    if len(units) != 1:
        raise ValueError("stage gate ranges must use one unit")
    return {
        "low": min(item["low"] for item in ranges),
        "base": min(item["base"] for item in ranges),
        "high": min(item["high"] for item in ranges),
        "unit": ranges[0]["unit"],
        "range_basis": (
            "exact" if set(bases) == {"exact"} else "bounded_interval"
        ),
    }


def _categorical_support_reasons(
    support: Mapping[str, Any],
    gate: Mapping[str, Any],
    assessment: Mapping[str, Any],
    resolved_assessment_ids: set[str],
) -> list[str]:
    reasons = []
    if assessment["assessment_id"] not in resolved_assessment_ids:
        reasons.append("parent_claim_not_unique_numerical_constraint")
    if support["assertion"] != gate["description"]:
        reasons.append("unsupported_gate_assertion")
    if support["period"] != TARGET_QUARTER:
        reasons.append("incompatible_gate_period")
    if support["time_basis"] != gate["time_basis"]:
        reasons.append("incompatible_gate_time_basis")
    if support["attribution_basis"] != gate["attribution_basis"]:
        reasons.append("unsupported_gate_attribution")
    if support["posture"] not in gate["accepted_postures"]:
        reasons.append("unsupported_gate_posture")
    if support["posture"] != assessment["posture"]:
        reasons.append("gate_posture_differs_from_parent_claim")
    if not support["evidence_ids"]:
        reasons.append("missing_gate_evidence")
    return reasons


def build_blackwell_pulse(
    audit: SyntheticInputAudit,
    releases: Sequence[VerifiedUpstreamRelease],
    *,
    week_ending: str,
    recorded_at: str,
    lock_sha256: str,
) -> dict[str, Any]:
    week = _date(week_ending, "week_ending")
    if week.weekday() != 6:
        raise ValueError("week_ending must be a Sunday")
    if not TARGET_QUARTER_START <= week <= TARGET_QUARTER_END:
        raise ValueError("week_ending must fall in 2026-Q4")
    recorded = _timestamp(recorded_at, "recorded_at")
    if recorded.date() < week:
        raise ValueError("recorded_at cannot precede week_ending")
    if not SHA256_PATTERN.fullmatch(lock_sha256):
        raise ValueError("lock_sha256 must be a lowercase SHA-256")

    releases_by_upstream = {item.entry.upstream_id: item for item in releases}
    if len(releases_by_upstream) != len(releases):
        raise ValueError("duplicate verified upstream release")
    if unexpected := set(releases_by_upstream) - REQUIRED_UPSTREAMS:
        raise ValueError(f"unexpected verified upstream releases: {sorted(unexpected)}")
    release_freshness: dict[str, dict[str, Any]] = {}
    for release in releases:
        if _timestamp(release.manifest["recorded_at"], "upstream recorded_at") > recorded:
            raise ValueError("upstream release was recorded after the pulse cutoff")
        as_of = _date(release.manifest["as_of_date"], "upstream as_of_date")
        if as_of > week:
            raise ValueError("upstream release as_of_date is after the weekly cutoff")
        age = week - as_of
        release_freshness[release.entry.upstream_id] = {
            "fresh_for_week": (
                as_of >= TARGET_QUARTER_START
                and timedelta(0) <= age <= MAX_UPSTREAM_RELEASE_AGE
            ),
            "age_days": age.days,
        }

    claims = [
        claim
        for upstream_id in sorted(releases_by_upstream)
        for claim in _claims_from_release(releases_by_upstream[upstream_id])
    ]
    known_categorical_gate_ids = {item["id"] for item in audit.categorical_gates}
    for claim in claims:
        declared_gate_ids = {item["gate_id"] for item in claim["gate_supports"]}
        if unexpected := declared_gate_ids - known_categorical_gate_ids:
            raise ValueError(
                f"upstream claim {claim['id']} names unknown categorical gates: "
                f"{sorted(unexpected)}"
            )
    requirement_by_id = audit.by_id
    assessments = []
    actual_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        requirement = requirement_by_id.get(claim["target_id"])
        classification, reasons = _classify_claim(
            claim,
            requirement,
            release_is_fresh=release_freshness[claim["upstream_id"]][
                "fresh_for_week"
            ],
        )
        assessment = {
            "assessment_id": f"claim:{claim['upstream_id']}:{claim['id']}",
            "claim_id": claim["id"],
            "upstream_id": claim["upstream_id"],
            "release_tag": claim["release_tag"],
            "comparison": claim["comparison"],
            "target_id": claim["target_id"],
            "classification": classification.value,
            "reason_codes": reasons,
            "change_status": claim["change_status"],
            "summary": claim["summary"],
            "value": claim["value"],
            "range_basis": claim["range_basis"],
            "posture": claim["posture"],
            "period": claim["period"],
            "time_basis": claim["time_basis"],
            "attribution_basis": claim["attribution_basis"],
            "gate_supports": claim["gate_supports"],
            "evidence": claim["evidence"],
        }
        assessments.append(assessment)
        if requirement is not None:
            actual_by_target[claim["target_id"]].append(assessment)

    for requirement in audit.requirements:
        if requirement["id"] in actual_by_target:
            continue
        assessments.append(
            {
                "assessment_id": f"missing:{requirement['id']}",
                "claim_id": None,
                "upstream_id": requirement["required_upstream"],
                "release_tag": None,
                "comparison": None,
                "target_id": requirement["id"],
                "classification": ClaimClassification.MISSING.value,
                "reason_codes": [
                    "upstream_release_missing"
                    if requirement["required_upstream"] not in releases_by_upstream
                    else "no_claim_for_required_input"
                ],
                "change_status": "unchanged",
                "summary": "No compatible upstream claim is available for this required target.",
                "value": None,
                "range_basis": None,
                "posture": None,
                "period": None,
                "time_basis": None,
                "attribution_basis": None,
                "gate_supports": [],
                "evidence": [],
            }
        )
        actual_by_target[requirement["id"]].append(assessments[-1])
    assessments.sort(key=lambda item: item["assessment_id"])

    resolved_numerical_by_target: dict[str, Mapping[str, Any]] = {}
    for target_id, target_assessments in actual_by_target.items():
        if (
            len(target_assessments) == 1
            and target_assessments[0]["classification"]
            == ClaimClassification.NUMERICAL_CONSTRAINT.value
        ):
            resolved_numerical_by_target[target_id] = target_assessments[0]
    resolved_assessment_ids = {
        assessment["assessment_id"]
        for assessment in resolved_numerical_by_target.values()
    }

    replacements = []
    unknowns = []
    for item in audit.inputs:
        candidate = resolved_numerical_by_target.get(item["id"])
        target_assessments = actual_by_target.get(item["id"], [])
        if candidate is not None:
            replacements.append(
                {
                    "input_id": item["id"],
                    "stage": item["stage"],
                    "parameter_class": item["parameter_class"],
                    "current_posture": "synthetic",
                    "replacement_status": "eligible_candidate_not_applied",
                    "claim_id": candidate["claim_id"],
                    "upstream_id": candidate["upstream_id"],
                    "evidence_value": candidate["value"],
                    "evidence_range_basis": candidate["range_basis"],
                }
            )
        else:
            classifications = sorted(
                {entry["classification"] for entry in actual_by_target.get(item["id"], [])}
            )
            unknowns.append(
                {
                    "id": item["id"],
                    "kind": "synthetic_input",
                    "stage": item["stage"],
                    "parameter_class": item["parameter_class"],
                    "active_for_supply_to_site": item["active_for_supply_to_site"],
                    "classifications": classifications or [ClaimClassification.MISSING.value],
                    "reason": (
                        "conflicting_or_multiple_claims"
                        if len(target_assessments) > 1
                        else "no_single_evidence_backed_replacement"
                    ),
                }
            )
    replacements.sort(key=lambda item: item["input_id"])

    for item in audit.gate_targets:
        candidate = resolved_numerical_by_target.get(item["id"])
        target_assessments = actual_by_target.get(item["id"], [])
        if candidate is None:
            classifications = sorted(
                {entry["classification"] for entry in actual_by_target.get(item["id"], [])}
            )
            unknowns.append(
                {
                    "id": item["id"],
                    "kind": "gate_target",
                    "stage": item["stage"],
                    "parameter_class": "throughput",
                    "active_for_supply_to_site": True,
                    "classifications": classifications or [ClaimClassification.MISSING.value],
                    "reason": (
                        "conflicting_or_multiple_claims"
                        if len(target_assessments) > 1
                        else "no_single_evidence_backed_stage_total"
                    ),
                }
            )

    categorical_results = []
    for gate in audit.categorical_gates:
        support_evaluations = []
        for assessment in assessments:
            for support in assessment["gate_supports"]:
                if support["gate_id"] != gate["id"]:
                    continue
                reasons = _categorical_support_reasons(
                    support,
                    gate,
                    assessment,
                    resolved_assessment_ids,
                )
                if assessment["upstream_id"] not in gate["required_upstreams"]:
                    reasons.append("upstream_not_required_for_gate")
                support_evaluations.append(
                    {
                        "upstream_id": assessment["upstream_id"],
                        "claim_id": assessment["claim_id"],
                        "assessment_id": assessment["assessment_id"],
                        "evidence_ids": support["evidence_ids"],
                        "passed": not reasons,
                        "reason_codes": reasons or ["exact_gate_support_contract_passes"],
                    }
                )
        invalid_supports = [item for item in support_evaluations if not item["passed"]]
        supporting_upstreams = sorted(
            {
                item["upstream_id"]
                for item in support_evaluations
                if item["passed"]
            }
        )
        missing_upstreams = sorted(set(gate["required_upstreams"]) - set(supporting_upstreams))
        passed = not missing_upstreams and not invalid_supports
        categorical_results.append(
            {
                "id": gate["id"],
                "stage": gate["stage"],
                "passed": passed,
                "required_upstreams": gate["required_upstreams"],
                "supporting_upstreams": supporting_upstreams,
                "supporting_claim_ids": sorted(
                    item["claim_id"]
                    for item in support_evaluations
                    if item["passed"] and item["claim_id"] is not None
                ),
                "missing_upstreams": missing_upstreams,
                "support_evaluations": support_evaluations,
                "current_status": "synthetic",
            }
        )
        if gate["required_for_numerical_result"] and not passed:
            unknowns.append(
                {
                    "id": gate["id"],
                    "kind": "categorical_gate",
                    "stage": gate["stage"],
                    "parameter_class": "other",
                    "active_for_supply_to_site": True,
                    "classifications": [
                        (
                            ClaimClassification.INCOMPATIBLE.value
                            if support_evaluations
                            else ClaimClassification.MISSING.value
                        )
                    ],
                    "reason": "unsupported_categorical_assumption",
                }
            )

    stage_results = []
    overall_blockers = []
    for stage in STAGES:
        required_inputs = [
            item
            for item in audit.inputs
            if item["stage"] == stage
            and item["active_for_supply_to_site"]
            and item["evidence_gate"]["required_for_numerical_result"]
        ]
        targets = [item for item in audit.gate_targets if item["stage"] == stage]
        unresolved_inputs = sorted(
            item["id"]
            for item in required_inputs
            if item["id"] not in resolved_numerical_by_target
        )
        unresolved_targets = sorted(
            item["id"]
            for item in targets
            if item["id"] not in resolved_numerical_by_target
        )
        unresolved_categories = sorted(
            item["id"]
            for item in categorical_results
            if item["stage"] in {stage, "cross_stage"} and not item["passed"]
        )
        passed = not (unresolved_inputs or unresolved_targets or unresolved_categories)
        if passed:
            target_assessments = [
                resolved_numerical_by_target[item["id"]] for item in targets
            ]
            stage_estimate: Mapping[str, Any] | str = _minimum_range(
                (assessment["value"] for assessment in target_assessments),
                range_bases=(
                    assessment["range_basis"] for assessment in target_assessments
                ),
            )
        else:
            stage_estimate = NO_EVIDENCE_BACKED_ESTIMATE
            overall_blockers.extend(
                f"{stage}:{kind}:{identifier}"
                for kind, identifiers in (
                    ("input", unresolved_inputs),
                    ("target", unresolved_targets),
                    ("categorical", unresolved_categories),
                )
                for identifier in identifiers
            )
        stage_results.append(
            {
                "stage": stage,
                "passed": passed,
                "required_input_ids": [item["id"] for item in required_inputs],
                "gate_target_ids": [item["id"] for item in targets],
                "unresolved_input_ids": unresolved_inputs,
                "unresolved_gate_target_ids": unresolved_targets,
                "unresolved_categorical_gate_ids": unresolved_categories,
                "estimate": stage_estimate,
            }
        )

    both_releases_locked = set(releases_by_upstream) == REQUIRED_UPSTREAMS
    if not both_releases_locked:
        for upstream_id in sorted(REQUIRED_UPSTREAMS - set(releases_by_upstream)):
            overall_blockers.append(f"upstream:missing:{upstream_id}")
    for upstream_id, freshness in sorted(release_freshness.items()):
        if not freshness["fresh_for_week"]:
            overall_blockers.append(f"upstream:stale:{upstream_id}")
    passed = both_releases_locked and all(item["passed"] for item in stage_results)
    if passed:
        passing_stage_estimates = [
            item["estimate"]
            for item in stage_results
            if isinstance(item["estimate"], dict)
        ]
        supply_to_site: Mapping[str, Any] | str = _minimum_range(
            passing_stage_estimates,
            range_bases=(item["range_basis"] for item in passing_stage_estimates),
        )
    else:
        supply_to_site = NO_EVIDENCE_BACKED_ESTIMATE

    changed = [
        {
            "claim_id": assessment["claim_id"],
            "upstream_id": assessment["upstream_id"],
            "target_id": assessment["target_id"],
            "stage": requirement_by_id.get(assessment["target_id"], {}).get(
                "stage",
                "unmapped",
            ),
            "change_basis": (
                "upstream_reported_against_declared_comparison"
                if assessment["comparison"] is not None
                else "upstream_reported_initial_release"
            ),
            "comparison_verification": "producer_asserted_not_locally_replayed",
            "comparison": assessment["comparison"],
            "change_status": assessment["change_status"],
            "classification": assessment["classification"],
            "summary": assessment["summary"],
        }
        for assessment in assessments
        if assessment["claim_id"] is not None and assessment["change_status"] != "unchanged"
    ]
    changed.sort(key=lambda item: (item["upstream_id"], item["claim_id"] or ""))

    upstream_lineage = []
    for upstream_id in sorted(REQUIRED_UPSTREAMS):
        release = releases_by_upstream.get(upstream_id)
        if release is None:
            upstream_lineage.append(
                {"upstream_id": upstream_id, "status": "missing", "release": None}
            )
        else:
            upstream_lineage.append(
                {
                    "upstream_id": upstream_id,
                    "status": (
                        "verified"
                        if release_freshness[upstream_id]["fresh_for_week"]
                        else "verified_stale"
                    ),
                    "release": {
                        "repository": release.entry.repository,
                        "tag": release.entry.release_tag,
                        "asset_name": release.entry.asset.name,
                        "asset_url": release.entry.asset.url,
                        "asset_bytes": release.entry.asset.bytes,
                        "asset_sha256": release.entry.asset.sha256,
                        "schema_version": release.entry.manifest.schema_version,
                        "manifest_sha256": release.entry.manifest.sha256,
                        "manifest_as_of_date": release.manifest["as_of_date"],
                        "manifest_recorded_at": release.manifest["recorded_at"],
                        "claims_sha256": release.claims_sha256,
                        "comparison": release.manifest["comparison"],
                        **release_freshness[upstream_id],
                        "content_address": f"sha256:{release.entry.asset.sha256}",
                    },
                }
            )

    protected_unknowns = [
        {
            **item,
            "status": "unknown_unless_suitable_evidence_is_gated",
        }
        for item in audit.document["protected_unknowns"]
    ]
    unknowns.sort(key=lambda item: (item["kind"], item["id"]))
    return {
        "format": PULSE_FORMAT,
        "id": f"blackwell-constraint-pulse:{week.isoformat()}",
        "product": PRODUCT,
        "target_quarter": TARGET_QUARTER,
        "week_ending": week.isoformat(),
        "recorded_at": recorded.isoformat().replace("+00:00", "Z"),
        "upstreams": upstream_lineage,
        "baseline": {
            **audit.document["baseline"],
            "synthetic_input_posture_preserved": True,
        },
        "questions": {
            "what_changed": changed,
            "what_changed_basis": {
                "status": "upstream_reported",
                "comparison_assets_locally_replayed": False,
                "limitation": (
                    "The locked current release carries the producer's change status "
                    "and declared prior hashes; v1 does not fetch or replay the prior asset."
                ),
            },
            "synthetic_inputs_now_replaceable": replacements,
            "what_remains_unknowable": unknowns,
            "protected_unknowns": protected_unknowns,
        },
        "claim_assessments": assessments,
        "evidence_gates": {
            "both_upstream_releases_locked_and_verified": both_releases_locked,
            "stages": stage_results,
            "categorical": categorical_results,
            "supply_to_site_passed": passed,
            "blockers": sorted(set(overall_blockers)),
        },
        "supply_to_site_estimate": supply_to_site,
        "lineage": {
            "upstream_lock_sha256": lock_sha256,
            "synthetic_input_audit_sha256": audit.sha256,
            "synthetic_input_audit_semantic_sha256": audit.semantic_sha256,
        },
        "limitations": [
            (
                "No synthetic input is mutated or promoted by this pulse; eligible "
                "claims remain candidates until an explicit reviewed revision."
            ),
            (
                "Scale controls and directional evidence can explain change but cannot "
                "pass a numerical gate."
            ),
            (
                "Integrity failures abort before a pulse release is written; missing or "
                "incompatible evidence produces the exact non-estimate string."
            ),
            (
                "The frozen 2026-Q3 synthetic ranges are an audit baseline and are not "
                "2026-Q4 facts."
            ),
            (
                "Change statuses are upstream-reported assertions; v1 does not "
                "independently replay prior release assets."
            ),
        ],
    }
