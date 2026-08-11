"""Auditable supplier earnings, consensus, and opportunity inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from .models import (
    Estimate,
    EstimatePosture,
    Evidence,
    QUARTER_PATTERN,
    _iso_date,
    _iso_timestamp,
    _required,
)


CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _unit(estimate: Estimate, expected: str, field_name: str) -> None:
    if estimate.unit != expected:
        raise ValueError(f"{field_name} must use {expected}")


def _positive(estimate: Estimate, field_name: str) -> None:
    if estimate.low <= 0:
        raise ValueError(f"{field_name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class EarningsLineItem:
    id: str
    name: str
    source_metric: str
    source_unit: str
    component_unit: str
    currency: str
    units_per_source_unit: Estimate
    attributable_share: Estimate
    beginning_inventory_units: Estimate
    ending_inventory_units: Estimate
    revenue_recognition_share: Estimate
    unit_price_local: Estimate
    fx_usd_per_local: Estimate
    gross_margin: Estimate
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "source_metric",
            "source_unit",
            "component_unit",
            "currency",
        ):
            _required(getattr(self, field_name), field_name)
        if not CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("line-item currency must use a three-letter uppercase code")
        _unit(
            self.units_per_source_unit,
            f"{self.component_unit}/{self.source_unit}",
            "units_per_source_unit",
        )
        _positive(self.units_per_source_unit, "units_per_source_unit")
        _unit(self.attributable_share, "ratio", "attributable_share")
        _unit(
            self.beginning_inventory_units,
            self.component_unit,
            "beginning_inventory_units",
        )
        _unit(
            self.ending_inventory_units,
            self.component_unit,
            "ending_inventory_units",
        )
        _unit(
            self.revenue_recognition_share,
            "ratio",
            "revenue_recognition_share",
        )
        _unit(
            self.unit_price_local,
            f"{self.currency}/{self.component_unit}",
            "unit_price_local",
        )
        _positive(self.unit_price_local, "unit_price_local")
        _unit(
            self.fx_usd_per_local,
            f"USD/{self.currency}",
            "fx_usd_per_local",
        )
        _positive(self.fx_usd_per_local, "fx_usd_per_local")
        _unit(self.gross_margin, "ratio", "gross_margin")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.units_per_source_unit
        yield self.attributable_share
        yield self.beginning_inventory_units
        yield self.ending_inventory_units
        yield self.revenue_recognition_share
        yield self.unit_price_local
        yield self.fx_usd_per_local
        yield self.gross_margin


@dataclass(frozen=True, slots=True)
class EarningsConsensus:
    as_of_date: str
    comparable_scope: str
    revenue: Estimate
    eps: Estimate

    def __post_init__(self) -> None:
        _iso_date(self.as_of_date, "consensus.as_of_date")
        _required(self.comparable_scope, "consensus.comparable_scope")
        _unit(self.revenue, "USD", "consensus.revenue")
        _unit(self.eps, "USD/share", "consensus.eps")
        _positive(self.revenue, "consensus.revenue")
        _positive(self.eps, "consensus.eps")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.revenue
        yield self.eps


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    as_of_date: str
    price: Estimate
    next_twelve_month_eps: Estimate
    market_cap: Estimate
    valuation_context: str

    def __post_init__(self) -> None:
        _iso_date(self.as_of_date, "market_snapshot.as_of_date")
        _required(self.valuation_context, "market_snapshot.valuation_context")
        _unit(self.price, "USD/share", "market_snapshot.price")
        _positive(self.price, "market_snapshot.price")
        _unit(
            self.next_twelve_month_eps,
            "USD/share",
            "market_snapshot.next_twelve_month_eps",
        )
        _positive(
            self.next_twelve_month_eps,
            "market_snapshot.next_twelve_month_eps",
        )
        _unit(self.market_cap, "USD", "market_snapshot.market_cap")
        _positive(self.market_cap, "market_snapshot.market_cap")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.price
        yield self.next_twelve_month_eps
        yield self.market_cap


@dataclass(frozen=True, slots=True)
class OpportunityFrame:
    catalyst_date: str
    confidence: Estimate
    evidence_readiness: Estimate
    liquidity: Estimate
    catalyst_proximity: Estimate
    downside_resilience: Estimate
    actionability: str
    variant_wedge: str
    what_is_priced_in: str
    why_now: str
    catalyst: str
    first_rejection: str
    investable_if: str
    thesis_kill: str
    next_workflow: str

    def __post_init__(self) -> None:
        _iso_date(self.catalyst_date, "opportunity.catalyst_date")
        for field_name in (
            "actionability",
            "variant_wedge",
            "what_is_priced_in",
            "why_now",
            "catalyst",
            "first_rejection",
            "investable_if",
            "thesis_kill",
            "next_workflow",
        ):
            _required(getattr(self, field_name), f"opportunity.{field_name}")
        for field_name in (
            "confidence",
            "evidence_readiness",
            "liquidity",
            "catalyst_proximity",
            "downside_resilience",
        ):
            _unit(getattr(self, field_name), "ratio", f"opportunity.{field_name}")

    def iter_estimates(self) -> Iterable[Estimate]:
        yield self.confidence
        yield self.evidence_readiness
        yield self.liquidity
        yield self.catalyst_proximity
        yield self.downside_resilience


@dataclass(frozen=True, slots=True)
class CompanyEarningsBridge:
    id: str
    name: str
    ticker: str
    reporting_currency: str
    line_items: tuple[EarningsLineItem, ...]
    rest_of_company_revenue: Estimate
    rest_of_company_gross_margin: Estimate
    operating_expenses: Estimate
    net_nonoperating_expense: Estimate
    tax_rate: Estimate
    diluted_shares: Estimate
    consensus: EarningsConsensus
    market_snapshot: MarketSnapshot
    opportunity: OpportunityFrame
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "ticker", "reporting_currency"):
            _required(getattr(self, field_name), field_name)
        if self.reporting_currency != "USD":
            raise ValueError("earnings bridge v1 requires USD reporting currency")
        if not self.line_items:
            raise ValueError("company earnings bridge requires at least one line item")
        line_ids = [item.id for item in self.line_items]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError(f"duplicate line-item id for {self.ticker}")
        _unit(self.rest_of_company_revenue, "USD", "rest_of_company_revenue")
        _unit(
            self.rest_of_company_gross_margin,
            "ratio",
            "rest_of_company_gross_margin",
        )
        _unit(self.operating_expenses, "USD", "operating_expenses")
        _unit(
            self.net_nonoperating_expense,
            "USD",
            "net_nonoperating_expense",
        )
        _unit(self.tax_rate, "ratio", "tax_rate")
        _unit(self.diluted_shares, "share", "diluted_shares")
        _positive(self.diluted_shares, "diluted_shares")

    def iter_estimates(self) -> Iterable[Estimate]:
        for line_item in self.line_items:
            yield from line_item.iter_estimates()
        yield self.rest_of_company_revenue
        yield self.rest_of_company_gross_margin
        yield self.operating_expenses
        yield self.net_nonoperating_expense
        yield self.tax_rate
        yield self.diluted_shares
        yield from self.consensus.iter_estimates()
        yield from self.market_snapshot.iter_estimates()
        yield from self.opportunity.iter_estimates()


@dataclass(frozen=True, slots=True)
class EarningsBridgeScenario:
    id: str
    name: str
    quarter: str
    as_of_date: str
    recorded_at: str
    synthetic: bool
    samples: int
    seed: int
    source_result_sha256: str
    source_result_format: str
    source_scenario_id: str
    evidence: tuple[Evidence, ...]
    companies: tuple[CompanyEarningsBridge, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "name",
            "quarter",
            "as_of_date",
            "recorded_at",
            "source_result_sha256",
            "source_result_format",
            "source_scenario_id",
        ):
            _required(getattr(self, field_name), field_name)
        if not QUARTER_PATTERN.fullmatch(self.quarter):
            raise ValueError("earnings quarter must use YYYY-QN form")
        _iso_date(self.as_of_date, "as_of_date")
        _iso_timestamp(self.recorded_at, "recorded_at")
        if not SHA256_PATTERN.fullmatch(self.source_result_sha256):
            raise ValueError("source_result_sha256 must be a lowercase SHA-256 digest")
        if self.samples < 100:
            raise ValueError("earnings scenario samples must be at least 100")
        if not self.companies:
            raise ValueError("earnings scenario requires at least one company")
        company_ids = [item.id for item in self.companies]
        tickers = [item.ticker for item in self.companies]
        if len(company_ids) != len(set(company_ids)):
            raise ValueError("duplicate company id")
        if len(tickers) != len(set(tickers)):
            raise ValueError("duplicate company ticker")
        if any(
            item.opportunity.catalyst_date < self.as_of_date
            for item in self.companies
        ):
            raise ValueError("opportunity catalyst_date cannot precede scenario as_of_date")
        if any(
            date.fromisoformat(item.consensus.as_of_date)
            > date.fromisoformat(self.as_of_date)
            or date.fromisoformat(item.market_snapshot.as_of_date)
            > date.fromisoformat(self.as_of_date)
            for item in self.companies
        ):
            raise ValueError("consensus and market snapshots cannot be after scenario as_of_date")
        self._validate_evidence()
        if not self.synthetic and any(
            estimate.posture is EstimatePosture.SYNTHETIC
            for estimate in self.iter_estimates()
        ):
            raise ValueError("an evidence-backed earnings scenario cannot use synthetic estimates")

    def _validate_evidence(self) -> None:
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate earnings evidence id")
        available = set(evidence_ids)
        for estimate in self.iter_estimates():
            missing = set(estimate.evidence_ids) - available
            if missing:
                raise ValueError(
                    f"earnings estimate references missing evidence: {sorted(missing)}"
                )

    def iter_estimates(self) -> Iterable[Estimate]:
        for company in self.companies:
            yield from company.iter_estimates()
