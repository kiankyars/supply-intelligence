"""Deterministic revision and bottleneck-shift alerts for reconciliation results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from math import isclose, isfinite
from typing import Any, Iterable


SUPPORTED_RESULT_FORMATS = {
    "ai-supply-reconciliation.v1",
    "ai-supply-portfolio-reconciliation.v1",
    "ai-supply-manufacturing-result.v1",
    "ai-supply-datacenter-operational-result.v1",
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _identity(value: Any, index: int) -> str:
    if isinstance(value, dict):
        for key in ("id", "stage", "constraint", "resource_id", "platform_id"):
            if key in value:
                return str(value[key])
    return str(index)


def _walk(
    value: Any,
    path: str,
    required_keys: set[str],
) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if required_keys.issubset(value):
            yield path, value
            return
        for key in sorted(value):
            child = value[key]
            child_path = f"{path}.{key}" if path else key
            yield from _walk(child, child_path, required_keys)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(
                child,
                f"{path}[{_identity(child, index)}]",
                required_keys,
            )


def _estimates(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(
        _walk(
            result.get("inputs", {}),
            "inputs",
            {"low", "base", "high", "unit", "posture"},
        )
    )


def _distributions(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    excluded = {"inputs", "evidence", "methodology", "scenario", "warnings"}
    payload = {key: value for key, value in result.items() if key not in excluded}
    return dict(_walk(payload, "", {"p10", "p50", "p90"}))


def _bottlenecks(result: dict[str, Any]) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    flat_stages = {
        "ai-supply-manufacturing-result.v1": "manufacturing",
        "ai-supply-datacenter-operational-result.v1": "operational",
    }
    if result["format"] in flat_stages:
        normalized[flat_stages[result["format"]]] = {
            item["constraint"]: item["probability"]
            for item in result["bottlenecks"]
        }
        return normalized
    source = (
        result["stage_bottlenecks"]
        if result["format"] == "ai-supply-portfolio-reconciliation.v1"
        else result["bottlenecks"]
    )
    for stage in source:
        probabilities = {}
        for item in stage["constraints"]:
            identifier = item.get("constraint_id", item.get("resource_id"))
            probabilities[str(identifier)] = item["probability"]
        normalized[stage["stage"]] = probabilities
    return normalized


def _alert(kind: str, severity: str, path: str, **details: Any) -> dict[str, Any]:
    payload = {
        "type": kind,
        "severity": severity,
        "path": path,
        **details,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {"id": f"alert:{digest}", **payload}


def _relative_change(previous: float, current: float) -> float | None:
    if isclose(previous, 0.0, abs_tol=1e-12):
        return 0.0 if isclose(current, 0.0, abs_tol=1e-12) else None
    return (current - previous) / abs(previous)


def detect_revision_alerts(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    output_relative_threshold: float = 0.10,
    bottleneck_probability_threshold: float = 0.15,
    previous_sha256: str | None = None,
    current_sha256: str | None = None,
) -> dict[str, Any]:
    """Compare two frozen results from the same scenario and emit stable alerts."""

    if not isfinite(output_relative_threshold) or output_relative_threshold < 0:
        raise ValueError("output_relative_threshold must be finite and nonnegative")
    if not 0 <= bottleneck_probability_threshold <= 1:
        raise ValueError(
            "bottleneck_probability_threshold must be between zero and one"
        )
    previous_format = previous.get("format")
    current_format = current.get("format")
    if previous_format not in SUPPORTED_RESULT_FORMATS:
        raise ValueError(f"unsupported previous result format: {previous_format}")
    if current_format != previous_format:
        raise ValueError("result formats must match")
    previous_scenario = previous.get("scenario", {})
    current_scenario = current.get("scenario", {})
    if not isinstance(previous_scenario.get("id"), str):
        raise ValueError("both results require scenario.id")
    if current_scenario.get("id") != previous_scenario.get("id"):
        raise ValueError("result scenario IDs must match")
    previous_recorded = previous_scenario.get("recorded_at")
    current_recorded = current_scenario.get("recorded_at")
    if not isinstance(previous_recorded, str) or not isinstance(current_recorded, str):
        raise ValueError("both results require scenario.recorded_at")
    if _timestamp(current_recorded) < _timestamp(previous_recorded):
        raise ValueError("current result cannot precede previous recorded_at")

    alerts = []
    previous_estimates = _estimates(previous)
    current_estimates = _estimates(current)
    for path in sorted(previous_estimates.keys() | current_estimates.keys()):
        old = previous_estimates.get(path)
        new = current_estimates.get(path)
        if old is None:
            alerts.append(
                _alert(
                    "estimate_added",
                    "info",
                    path,
                    current={key: new[key] for key in ("low", "base", "high", "unit", "posture")},
                )
            )
            continue
        if new is None:
            alerts.append(
                _alert(
                    "estimate_removed",
                    "high",
                    path,
                    previous={key: old[key] for key in ("low", "base", "high", "unit", "posture")},
                )
            )
            continue
        if new["unit"] != old["unit"]:
            alerts.append(
                _alert(
                    "estimate_unit_changed",
                    "critical",
                    path,
                    previous_unit=old["unit"],
                    current_unit=new["unit"],
                )
            )
            continue
        if new["base"] < old["low"] or new["base"] > old["high"]:
            alerts.append(
                _alert(
                    "estimate_range_breach",
                    "high",
                    path,
                    previous_range={key: old[key] for key in ("low", "base", "high")},
                    current_range={key: new[key] for key in ("low", "base", "high")},
                    unit=new["unit"],
                )
            )
        if new["posture"] != old["posture"]:
            alerts.append(
                _alert(
                    "estimate_posture_changed",
                    "medium",
                    path,
                    previous_posture=old["posture"],
                    current_posture=new["posture"],
                )
            )

    previous_distributions = _distributions(previous)
    current_distributions = _distributions(current)
    for path in sorted(previous_distributions.keys() & current_distributions.keys()):
        old_value = previous_distributions[path]["p50"]
        new_value = current_distributions[path]["p50"]
        relative = _relative_change(old_value, new_value)
        if relative is None or abs(relative) >= output_relative_threshold:
            alerts.append(
                _alert(
                    "output_revision",
                    "medium",
                    path,
                    previous_p50=old_value,
                    current_p50=new_value,
                    relative_change=relative,
                )
            )

    previous_bottlenecks = _bottlenecks(previous)
    current_bottlenecks = _bottlenecks(current)
    for stage in sorted(previous_bottlenecks.keys() & current_bottlenecks.keys()):
        old = previous_bottlenecks[stage]
        new = current_bottlenecks[stage]
        old_top = max(old, key=old.get) if old else None
        new_top = max(new, key=new.get) if new else None
        if old_top != new_top:
            alerts.append(
                _alert(
                    "binding_bottleneck_changed",
                    "critical",
                    f"bottlenecks.{stage}",
                    previous_constraint=old_top,
                    current_constraint=new_top,
                    previous_probability=old.get(old_top, 0.0),
                    current_probability=new.get(new_top, 0.0),
                )
            )
        for constraint in sorted(old.keys() | new.keys()):
            delta = new.get(constraint, 0.0) - old.get(constraint, 0.0)
            if abs(delta) >= bottleneck_probability_threshold:
                alerts.append(
                    _alert(
                        "bottleneck_probability_shift",
                        "high",
                        f"bottlenecks.{stage}[{constraint}]",
                        constraint=constraint,
                        previous_probability=old.get(constraint, 0.0),
                        current_probability=new.get(constraint, 0.0),
                        probability_change=delta,
                    )
                )

    alerts.sort(
        key=lambda item: (
            SEVERITY_ORDER[item["severity"]],
            item["type"],
            item["path"],
            item["id"],
        )
    )
    changed_payload = json.dumps(previous, sort_keys=True) != json.dumps(
        current,
        sort_keys=True,
    )
    if changed_payload and current_recorded == previous_recorded:
        raise ValueError("changed result requires a later current recorded_at")
    return {
        "format": "ai-supply-revision-alerts.v1",
        "scenario_id": previous_scenario["id"],
        "result_format": previous_format,
        "previous": {
            "recorded_at": previous_recorded,
            "as_of_date": previous_scenario.get("as_of_date"),
            "sha256": previous_sha256,
        },
        "current": {
            "recorded_at": current_recorded,
            "as_of_date": current_scenario.get("as_of_date"),
            "sha256": current_sha256,
        },
        "thresholds": {
            "output_relative_change": output_relative_threshold,
            "bottleneck_probability_change": bottleneck_probability_threshold,
        },
        "alert_count": len(alerts),
        "alerts": alerts,
    }
