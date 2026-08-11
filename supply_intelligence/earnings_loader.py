"""Strict loader for supplier earnings bridges and frozen physical results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .earnings_models import (
    CompanyEarningsBridge,
    EarningsBridgeScenario,
    EarningsConsensus,
    EarningsLineItem,
    MarketSnapshot,
    OpportunityFrame,
)
from .loader import _estimate as common_estimate
from .loader import _evidence as common_evidence
from .manufacturing_engine import OUTPUT_UNITS


EARNINGS_BRIDGE_FORMAT = "ai-supply-earnings-bridge.v1"
MANUFACTURING_RESULT_FORMAT = "ai-supply-manufacturing-result.v1"
ESTIMATE_FIELDS = {
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
EVIDENCE_FIELDS = {
    "id",
    "kind",
    "title",
    "source_url",
    "publisher",
    "retrieved_at",
    "published_at",
    "source_family",
    "license",
    "excerpt",
    "content_hash",
}


@dataclass(frozen=True, slots=True)
class LoadedEarningsCase:
    scenario: EarningsBridgeScenario
    source_result: dict[str, Any]
    source_result_sha256: str
    source_result_document: str
    scenario_document: str
    source_metrics: dict[str, dict[str, Any]]
    source_synthetic: bool


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    unexpected = set(value) - fields
    if unexpected:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _value(value: Mapping[str, Any], field: str, path: str) -> Any:
    if field not in value:
        raise ValueError(f"{path}.{field} is required")
    return value[field]


def _text(
    value: Mapping[str, Any],
    field: str,
    path: str,
    *,
    default: str | None = None,
) -> str:
    if field not in value and default is not None:
        return default
    item = _value(value, field, path)
    if not isinstance(item, str):
        raise ValueError(f"{path}.{field} must be text")
    return item


def _boolean(value: Mapping[str, Any], field: str, path: str) -> bool:
    item = _value(value, field, path)
    if not isinstance(item, bool):
        raise ValueError(f"{path}.{field} must be boolean")
    return item


def _integer(value: Mapping[str, Any], field: str, path: str) -> int:
    item = _value(value, field, path)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{path}.{field} must be an integer")
    return item


def _estimate(value: Any, path: str):
    data = _mapping(value, path)
    _only(data, ESTIMATE_FIELDS, path)
    return common_estimate(data, path)


def _evidence(value: Any, path: str):
    data = _mapping(value, path)
    _only(data, EVIDENCE_FIELDS, path)
    return common_evidence(data, path)


def _line_item(value: Any, path: str) -> EarningsLineItem:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "source_metric",
            "source_unit",
            "component_unit",
            "currency",
            "units_per_source_unit",
            "attributable_share",
            "beginning_inventory_units",
            "ending_inventory_units",
            "revenue_recognition_share",
            "unit_price_local",
            "fx_usd_per_local",
            "gross_margin",
            "notes",
        },
        path,
    )
    return EarningsLineItem(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        source_metric=_text(data, "source_metric", path),
        source_unit=_text(data, "source_unit", path),
        component_unit=_text(data, "component_unit", path),
        currency=_text(data, "currency", path),
        units_per_source_unit=_estimate(
            _value(data, "units_per_source_unit", path),
            f"{path}.units_per_source_unit",
        ),
        attributable_share=_estimate(
            _value(data, "attributable_share", path),
            f"{path}.attributable_share",
        ),
        beginning_inventory_units=_estimate(
            _value(data, "beginning_inventory_units", path),
            f"{path}.beginning_inventory_units",
        ),
        ending_inventory_units=_estimate(
            _value(data, "ending_inventory_units", path),
            f"{path}.ending_inventory_units",
        ),
        revenue_recognition_share=_estimate(
            _value(data, "revenue_recognition_share", path),
            f"{path}.revenue_recognition_share",
        ),
        unit_price_local=_estimate(
            _value(data, "unit_price_local", path),
            f"{path}.unit_price_local",
        ),
        fx_usd_per_local=_estimate(
            _value(data, "fx_usd_per_local", path),
            f"{path}.fx_usd_per_local",
        ),
        gross_margin=_estimate(
            _value(data, "gross_margin", path),
            f"{path}.gross_margin",
        ),
        notes=_text(data, "notes", path, default=""),
    )


def _consensus(value: Any, path: str) -> EarningsConsensus:
    data = _mapping(value, path)
    _only(data, {"as_of_date", "comparable_scope", "revenue", "eps"}, path)
    return EarningsConsensus(
        as_of_date=_text(data, "as_of_date", path),
        comparable_scope=_text(data, "comparable_scope", path),
        revenue=_estimate(_value(data, "revenue", path), f"{path}.revenue"),
        eps=_estimate(_value(data, "eps", path), f"{path}.eps"),
    )


def _market_snapshot(value: Any, path: str) -> MarketSnapshot:
    data = _mapping(value, path)
    _only(
        data,
        {
            "as_of_date",
            "price",
            "next_twelve_month_eps",
            "market_cap",
            "valuation_context",
        },
        path,
    )
    return MarketSnapshot(
        as_of_date=_text(data, "as_of_date", path),
        price=_estimate(_value(data, "price", path), f"{path}.price"),
        next_twelve_month_eps=_estimate(
            _value(data, "next_twelve_month_eps", path),
            f"{path}.next_twelve_month_eps",
        ),
        market_cap=_estimate(
            _value(data, "market_cap", path),
            f"{path}.market_cap",
        ),
        valuation_context=_text(data, "valuation_context", path),
    )


def _opportunity(value: Any, path: str) -> OpportunityFrame:
    data = _mapping(value, path)
    _only(
        data,
        {
            "catalyst_date",
            "confidence",
            "evidence_readiness",
            "liquidity",
            "catalyst_proximity",
            "downside_resilience",
            "actionability",
            "variant_wedge",
            "what_is_priced_in",
            "why_now",
            "catalyst",
            "first_rejection",
            "investable_if",
            "thesis_kill",
            "next_workflow",
        },
        path,
    )
    return OpportunityFrame(
        catalyst_date=_text(data, "catalyst_date", path),
        confidence=_estimate(_value(data, "confidence", path), f"{path}.confidence"),
        evidence_readiness=_estimate(
            _value(data, "evidence_readiness", path),
            f"{path}.evidence_readiness",
        ),
        liquidity=_estimate(_value(data, "liquidity", path), f"{path}.liquidity"),
        catalyst_proximity=_estimate(
            _value(data, "catalyst_proximity", path),
            f"{path}.catalyst_proximity",
        ),
        downside_resilience=_estimate(
            _value(data, "downside_resilience", path),
            f"{path}.downside_resilience",
        ),
        actionability=_text(data, "actionability", path),
        variant_wedge=_text(data, "variant_wedge", path),
        what_is_priced_in=_text(data, "what_is_priced_in", path),
        why_now=_text(data, "why_now", path),
        catalyst=_text(data, "catalyst", path),
        first_rejection=_text(data, "first_rejection", path),
        investable_if=_text(data, "investable_if", path),
        thesis_kill=_text(data, "thesis_kill", path),
        next_workflow=_text(data, "next_workflow", path),
    )


def _company(value: Any, path: str) -> CompanyEarningsBridge:
    data = _mapping(value, path)
    _only(
        data,
        {
            "id",
            "name",
            "ticker",
            "reporting_currency",
            "line_items",
            "rest_of_company_revenue",
            "rest_of_company_gross_margin",
            "operating_expenses",
            "net_nonoperating_expense",
            "tax_rate",
            "diluted_shares",
            "consensus",
            "market_snapshot",
            "opportunity",
            "notes",
        },
        path,
    )
    line_items = _list(_value(data, "line_items", path), f"{path}.line_items")
    return CompanyEarningsBridge(
        id=_text(data, "id", path),
        name=_text(data, "name", path),
        ticker=_text(data, "ticker", path),
        reporting_currency=_text(data, "reporting_currency", path),
        line_items=tuple(
            _line_item(item, f"{path}.line_items[{index}]")
            for index, item in enumerate(line_items)
        ),
        rest_of_company_revenue=_estimate(
            _value(data, "rest_of_company_revenue", path),
            f"{path}.rest_of_company_revenue",
        ),
        rest_of_company_gross_margin=_estimate(
            _value(data, "rest_of_company_gross_margin", path),
            f"{path}.rest_of_company_gross_margin",
        ),
        operating_expenses=_estimate(
            _value(data, "operating_expenses", path),
            f"{path}.operating_expenses",
        ),
        net_nonoperating_expense=_estimate(
            _value(data, "net_nonoperating_expense", path),
            f"{path}.net_nonoperating_expense",
        ),
        tax_rate=_estimate(_value(data, "tax_rate", path), f"{path}.tax_rate"),
        diluted_shares=_estimate(
            _value(data, "diluted_shares", path),
            f"{path}.diluted_shares",
        ),
        consensus=_consensus(_value(data, "consensus", path), f"{path}.consensus"),
        market_snapshot=_market_snapshot(
            _value(data, "market_snapshot", path),
            f"{path}.market_snapshot",
        ),
        opportunity=_opportunity(
            _value(data, "opportunity", path),
            f"{path}.opportunity",
        ),
        notes=_text(data, "notes", path, default=""),
    )


def _parse_timestamp(value: str, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _source_metrics(source: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = _mapping(source.get("conversion_outputs"), "source conversion_outputs")
    metrics = {}
    for name, value in values.items():
        if name not in OUTPUT_UNITS:
            raise ValueError(f"source result contains unsupported manufacturing metric: {name}")
        distribution = _mapping(value, f"source conversion_outputs.{name}")
        for field in ("p10", "p50", "p90", "mean", "minimum", "maximum"):
            number = distribution.get(field)
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError(f"source metric {name}.{field} must be numeric")
            if not isfinite(number):
                raise ValueError(f"source metric {name}.{field} must be finite")
        if not 0 <= distribution["p10"] <= distribution["p50"] <= distribution["p90"]:
            raise ValueError(f"source metric {name} has an invalid P10/P50/P90 range")
        metrics[name] = {
            "p10": float(distribution["p10"]),
            "p50": float(distribution["p50"]),
            "p90": float(distribution["p90"]),
            "unit": OUTPUT_UNITS[name],
        }
    return metrics


def load_earnings_case(
    scenario_path: str | Path,
    source_result_path: str | Path,
) -> LoadedEarningsCase:
    scenario_source = Path(scenario_path)
    source_result_source = Path(source_result_path)
    scenario_raw = scenario_source.read_bytes()
    source_result_raw = source_result_source.read_bytes()
    try:
        scenario_document = scenario_raw.decode("utf-8")
        source_result_document = source_result_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("earnings scenario and source result must be UTF-8") from exc
    try:
        document = _mapping(json.loads(scenario_document), "earnings scenario")
        source_result = dict(
            _mapping(json.loads(source_result_document), "source result")
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if document.get("format") != EARNINGS_BRIDGE_FORMAT:
        raise ValueError(f"earnings scenario format must be {EARNINGS_BRIDGE_FORMAT}")
    _only(
        document,
        {
            "format",
            "id",
            "name",
            "quarter",
            "as_of_date",
            "recorded_at",
            "synthetic",
            "samples",
            "seed",
            "source_result",
            "evidence",
            "companies",
            "notes",
        },
        "earnings scenario",
    )
    source_selection = _mapping(
        _value(document, "source_result", "earnings scenario"),
        "earnings scenario.source_result",
    )
    _only(
        source_selection,
        {"sha256", "format", "scenario_id"},
        "earnings scenario.source_result",
    )
    source_sha = hashlib.sha256(source_result_raw).hexdigest()
    if source_sha != _text(source_selection, "sha256", "source_result"):
        raise ValueError("source earnings result SHA-256 mismatch")
    expected_format = _text(source_selection, "format", "source_result")
    if expected_format != MANUFACTURING_RESULT_FORMAT:
        raise ValueError(
            f"earnings bridge v1 supports only {MANUFACTURING_RESULT_FORMAT}"
        )
    if source_result.get("format") != expected_format:
        raise ValueError("source earnings result format mismatch")
    source_scenario = _mapping(source_result.get("scenario"), "source result.scenario")
    source_scenario_id = _text(source_selection, "scenario_id", "source_result")
    if source_scenario.get("id") != source_scenario_id:
        raise ValueError("source earnings result scenario ID mismatch")

    evidence_values = _list(_value(document, "evidence", "earnings scenario"), "evidence")
    company_values = _list(_value(document, "companies", "earnings scenario"), "companies")
    scenario = EarningsBridgeScenario(
        id=_text(document, "id", "earnings scenario"),
        name=_text(document, "name", "earnings scenario"),
        quarter=_text(document, "quarter", "earnings scenario"),
        as_of_date=_text(document, "as_of_date", "earnings scenario"),
        recorded_at=_text(document, "recorded_at", "earnings scenario"),
        synthetic=_boolean(document, "synthetic", "earnings scenario"),
        samples=_integer(document, "samples", "earnings scenario"),
        seed=_integer(document, "seed", "earnings scenario"),
        source_result_sha256=source_sha,
        source_result_format=expected_format,
        source_scenario_id=source_scenario_id,
        evidence=tuple(
            _evidence(value, f"evidence[{index}]")
            for index, value in enumerate(evidence_values)
        ),
        companies=tuple(
            _company(value, f"companies[{index}]")
            for index, value in enumerate(company_values)
        ),
        notes=_text(document, "notes", "earnings scenario", default=""),
    )
    if source_scenario.get("quarter") != scenario.quarter:
        raise ValueError("source result quarter does not match earnings scenario")
    source_recorded_at = source_scenario.get("recorded_at")
    if not isinstance(source_recorded_at, str):
        raise ValueError("source result scenario.recorded_at is required")
    if _parse_timestamp(source_recorded_at, "source result recorded_at") > _parse_timestamp(
        scenario.recorded_at,
        "earnings scenario recorded_at",
    ):
        raise ValueError("earnings scenario cannot precede its source result")
    source_synthetic = source_scenario.get("synthetic")
    if not isinstance(source_synthetic, bool):
        raise ValueError("source result scenario.synthetic must be boolean")
    if source_synthetic and not scenario.synthetic:
        raise ValueError("a synthetic source result requires a synthetic earnings scenario")
    metrics = _source_metrics(source_result)
    for company in scenario.companies:
        for line_item in company.line_items:
            metric = metrics.get(line_item.source_metric)
            if metric is None:
                raise ValueError(
                    f"{company.ticker} line item references missing source metric: "
                    f"{line_item.source_metric}"
                )
            if metric["unit"] != line_item.source_unit:
                raise ValueError(
                    f"{company.ticker} line item source unit does not match "
                    f"{line_item.source_metric}"
                )
    return LoadedEarningsCase(
        scenario=scenario,
        source_result=source_result,
        source_result_sha256=source_sha,
        source_result_document=source_result_document,
        scenario_document=scenario_document,
        source_metrics=metrics,
        source_synthetic=source_synthetic,
    )
