"""Monte Carlo and named-case supplier earnings bridge."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from random import Random
from typing import Any, Callable

from .earnings_loader import LoadedEarningsCase
from .earnings_models import CompanyEarningsBridge, EarningsLineItem
from .engine import EstimateSampler, summarize
from .models import Estimate


def _triangular(low: float, mode: float, high: float, draw: float) -> float:
    if low == high:
        return low
    mode_fraction = (mode - low) / (high - low)
    if draw < mode_fraction:
        return low + sqrt(draw * (high - low) * (mode - low))
    return high - sqrt((1 - draw) * (high - low) * (high - mode))


def _estimate_payload(value: Estimate) -> dict[str, Any]:
    return {
        "low": value.low,
        "base": value.base,
        "high": value.high,
        "unit": value.unit,
        "posture": value.posture.value,
        "methodology": value.methodology,
        "confidence": value.confidence,
        "last_updated": value.last_updated,
        "evidence_ids": list(value.evidence_ids),
        "confirming_evidence": value.confirming_evidence,
        "falsifying_evidence": value.falsifying_evidence,
        "correlation_group": value.correlation_group,
    }


def _safe_revision(modeled: float, comparator: float) -> float:
    return 0.0 if comparator == 0 else (modeled - comparator) / comparator


def _line_calculation(
    line_item: EarningsLineItem,
    source_units: float,
    estimate: Callable[[Estimate], float],
) -> dict[str, float]:
    produced_units = (
        source_units
        * estimate(line_item.units_per_source_unit)
        * estimate(line_item.attributable_share)
    )
    available_units = estimate(line_item.beginning_inventory_units) + produced_units
    shipped_units = max(
        0.0,
        available_units - estimate(line_item.ending_inventory_units),
    )
    recognized_units = shipped_units * estimate(line_item.revenue_recognition_share)
    revenue_usd = (
        recognized_units
        * estimate(line_item.unit_price_local)
        * estimate(line_item.fx_usd_per_local)
    )
    gross_profit_usd = revenue_usd * estimate(line_item.gross_margin)
    return {
        "source_units": source_units,
        "produced_units": produced_units,
        "available_units": available_units,
        "shipped_units": shipped_units,
        "recognized_units": recognized_units,
        "revenue_usd": revenue_usd,
        "gross_profit_usd": gross_profit_usd,
    }


def _company_calculation(
    company: CompanyEarningsBridge,
    line_results: list[dict[str, float]],
    estimate: Callable[[Estimate], float],
) -> dict[str, float]:
    ai_chain_revenue = sum(item["revenue_usd"] for item in line_results)
    ai_chain_gross_profit = sum(item["gross_profit_usd"] for item in line_results)
    rest_revenue = estimate(company.rest_of_company_revenue)
    rest_gross_profit = rest_revenue * estimate(company.rest_of_company_gross_margin)
    total_revenue = ai_chain_revenue + rest_revenue
    gross_profit = ai_chain_gross_profit + rest_gross_profit
    operating_income = gross_profit - estimate(company.operating_expenses)
    pretax_income = operating_income - estimate(company.net_nonoperating_expense)
    tax_expense = max(0.0, pretax_income) * estimate(company.tax_rate)
    net_income = pretax_income - tax_expense
    diluted_shares = estimate(company.diluted_shares)
    eps = net_income / diluted_shares
    return {
        "ai_chain_revenue_usd": ai_chain_revenue,
        "ai_chain_gross_profit_usd": ai_chain_gross_profit,
        "rest_of_company_revenue_usd": rest_revenue,
        "total_revenue_usd": total_revenue,
        "gross_profit_usd": gross_profit,
        "gross_margin": 0.0 if total_revenue == 0 else gross_profit / total_revenue,
        "operating_income_usd": operating_income,
        "pretax_income_usd": pretax_income,
        "tax_expense_usd": tax_expense,
        "net_income_usd": net_income,
        "diluted_shares": diluted_shares,
        "eps_usd": eps,
        "ai_chain_revenue_share": (
            0.0 if total_revenue == 0 else ai_chain_revenue / total_revenue
        ),
    }


def _named_estimate(value: Estimate, case_name: str, *, adverse: bool = False) -> float:
    index = {"bear": "low", "base": "base", "bull": "high"}[case_name]
    if adverse:
        index = {"bear": "high", "base": "base", "bull": "low"}[case_name]
    return float(getattr(value, index))


def _named_case(
    company: CompanyEarningsBridge,
    source_metrics: dict[str, dict[str, Any]],
    case_name: str,
) -> dict[str, Any]:
    source_field = {"bear": "p10", "base": "p50", "bull": "p90"}[case_name]
    line_rows = []
    for line_item in company.line_items:
        source_value = source_metrics[line_item.source_metric][source_field]

        def line_estimate(value: Estimate) -> float:
            return _named_estimate(
                value,
                case_name,
                adverse=value is line_item.ending_inventory_units,
            )

        line_rows.append(
            {
                "id": line_item.id,
                "name": line_item.name,
                "source_metric": line_item.source_metric,
                **_line_calculation(line_item, source_value, line_estimate),
            }
        )

    adverse_company_estimates = {
        id(company.operating_expenses),
        id(company.net_nonoperating_expense),
        id(company.tax_rate),
        id(company.diluted_shares),
    }

    def company_estimate(value: Estimate) -> float:
        return _named_estimate(
            value,
            case_name,
            adverse=id(value) in adverse_company_estimates,
        )

    company_values = _company_calculation(company, line_rows, company_estimate)
    consensus_revenue = company.consensus.revenue.base
    consensus_eps = company.consensus.eps.base
    return {
        "case": case_name,
        "line_items": line_rows,
        **company_values,
        "consensus_revenue_usd": consensus_revenue,
        "consensus_eps_usd": consensus_eps,
        "revenue_revision_pct": _safe_revision(
            company_values["total_revenue_usd"], consensus_revenue
        )
        * 100,
        "eps_revision_pct": _safe_revision(company_values["eps_usd"], consensus_eps)
        * 100,
    }


def _company_inputs(company: CompanyEarningsBridge) -> dict[str, Any]:
    return {
        "id": company.id,
        "name": company.name,
        "ticker": company.ticker,
        "reporting_currency": company.reporting_currency,
        "line_items": [
            {
                "id": line.id,
                "name": line.name,
                "source_metric": line.source_metric,
                "source_unit": line.source_unit,
                "component_unit": line.component_unit,
                "currency": line.currency,
                "units_per_source_unit": _estimate_payload(
                    line.units_per_source_unit
                ),
                "attributable_share": _estimate_payload(line.attributable_share),
                "beginning_inventory_units": _estimate_payload(
                    line.beginning_inventory_units
                ),
                "ending_inventory_units": _estimate_payload(
                    line.ending_inventory_units
                ),
                "revenue_recognition_share": _estimate_payload(
                    line.revenue_recognition_share
                ),
                "unit_price_local": _estimate_payload(line.unit_price_local),
                "fx_usd_per_local": _estimate_payload(line.fx_usd_per_local),
                "gross_margin": _estimate_payload(line.gross_margin),
                "notes": line.notes,
            }
            for line in company.line_items
        ],
        "rest_of_company_revenue": _estimate_payload(
            company.rest_of_company_revenue
        ),
        "rest_of_company_gross_margin": _estimate_payload(
            company.rest_of_company_gross_margin
        ),
        "operating_expenses": _estimate_payload(company.operating_expenses),
        "net_nonoperating_expense": _estimate_payload(
            company.net_nonoperating_expense
        ),
        "tax_rate": _estimate_payload(company.tax_rate),
        "diluted_shares": _estimate_payload(company.diluted_shares),
        "consensus": {
            "as_of_date": company.consensus.as_of_date,
            "comparable_scope": company.consensus.comparable_scope,
            "revenue": _estimate_payload(company.consensus.revenue),
            "eps": _estimate_payload(company.consensus.eps),
        },
        "market_snapshot": {
            "as_of_date": company.market_snapshot.as_of_date,
            "price": _estimate_payload(company.market_snapshot.price),
            "next_twelve_month_eps": _estimate_payload(
                company.market_snapshot.next_twelve_month_eps
            ),
            "market_cap": _estimate_payload(company.market_snapshot.market_cap),
            "valuation_context": company.market_snapshot.valuation_context,
        },
        "opportunity": {
            "catalyst_date": company.opportunity.catalyst_date,
            "confidence": _estimate_payload(company.opportunity.confidence),
            "evidence_readiness": _estimate_payload(
                company.opportunity.evidence_readiness
            ),
            "liquidity": _estimate_payload(company.opportunity.liquidity),
            "catalyst_proximity": _estimate_payload(
                company.opportunity.catalyst_proximity
            ),
            "downside_resilience": _estimate_payload(
                company.opportunity.downside_resilience
            ),
            "actionability": company.opportunity.actionability,
            "variant_wedge": company.opportunity.variant_wedge,
            "what_is_priced_in": company.opportunity.what_is_priced_in,
            "why_now": company.opportunity.why_now,
            "catalyst": company.opportunity.catalyst,
            "first_rejection": company.opportunity.first_rejection,
            "investable_if": company.opportunity.investable_if,
            "thesis_kill": company.opportunity.thesis_kill,
            "next_workflow": company.opportunity.next_workflow,
        },
        "notes": company.notes,
    }


def reconcile_earnings(case: LoadedEarningsCase) -> dict[str, Any]:
    scenario = case.scenario
    random = Random(scenario.seed)
    company_samples: dict[str, dict[str, list[float]]] = {
        company.id: defaultdict(list) for company in scenario.companies
    }
    line_samples: dict[tuple[str, str], dict[str, list[float]]] = {
        (company.id, line.id): defaultdict(list)
        for company in scenario.companies
        for line in company.line_items
    }
    comparator_samples: dict[str, dict[str, list[float]]] = {
        company.id: defaultdict(list) for company in scenario.companies
    }

    for _ in range(scenario.samples):
        sampler = EstimateSampler(random)
        source_draws = {
            name: _triangular(
                metric["p10"],
                metric["p50"],
                metric["p90"],
                random.random(),
            )
            for name, metric in case.source_metrics.items()
        }
        for company in scenario.companies:
            line_results = []
            for line_item in company.line_items:
                values = _line_calculation(
                    line_item,
                    source_draws[line_item.source_metric],
                    sampler.estimate,
                )
                line_results.append(values)
                for metric, value in values.items():
                    line_samples[(company.id, line_item.id)][metric].append(value)
            values = _company_calculation(company, line_results, sampler.estimate)
            for metric, value in values.items():
                company_samples[company.id][metric].append(value)
            consensus_revenue = sampler.estimate(company.consensus.revenue)
            consensus_eps = sampler.estimate(company.consensus.eps)
            price = sampler.estimate(company.market_snapshot.price)
            ntm_eps = sampler.estimate(company.market_snapshot.next_twelve_month_eps)
            market_cap = sampler.estimate(company.market_snapshot.market_cap)
            revenue_revision = _safe_revision(
                values["total_revenue_usd"], consensus_revenue
            )
            eps_revision = _safe_revision(values["eps_usd"], consensus_eps)
            score = (
                abs(eps_revision)
                * sampler.estimate(company.opportunity.confidence)
                * sampler.estimate(company.opportunity.evidence_readiness)
                * sampler.estimate(company.opportunity.liquidity)
                * sampler.estimate(company.opportunity.catalyst_proximity)
                * sampler.estimate(company.opportunity.downside_resilience)
            )
            comparisons = comparator_samples[company.id]
            comparisons["consensus_revenue_usd"].append(consensus_revenue)
            comparisons["consensus_eps_usd"].append(consensus_eps)
            comparisons["revenue_revision_pct"].append(revenue_revision * 100)
            comparisons["eps_revision_pct"].append(eps_revision * 100)
            comparisons["price_usd"].append(price)
            comparisons["next_twelve_month_eps_usd"].append(ntm_eps)
            comparisons["market_cap_usd"].append(market_cap)
            comparisons["forward_pe"].append(price / ntm_eps)
            comparisons["screen_score"].append(score)

    company_results = []
    ranking_rows = []
    for company in scenario.companies:
        metrics = {
            name: summarize(values).as_dict()
            for name, values in company_samples[company.id].items()
        }
        comparisons = {
            name: summarize(values).as_dict()
            for name, values in comparator_samples[company.id].items()
        }
        line_results = []
        for line_item in company.line_items:
            line_results.append(
                {
                    "id": line_item.id,
                    "name": line_item.name,
                    "source_metric": line_item.source_metric,
                    "source_unit": line_item.source_unit,
                    "component_unit": line_item.component_unit,
                    **{
                        name: summarize(values).as_dict()
                        for name, values in line_samples[
                            (company.id, line_item.id)
                        ].items()
                    },
                }
            )
        named_cases = {
            name: _named_case(company, case.source_metrics, name)
            for name in ("bear", "base", "bull")
        }
        status = (
            "wait_for_proof"
            if scenario.synthetic or case.source_synthetic
            else "deeper_research_candidate"
        )
        eps_revision = comparisons["eps_revision_pct"]
        direction = (
            "long_research_candidate"
            if eps_revision["p50"] >= 0
            else "short_research_candidate"
        )
        company_results.append(
            {
                "id": company.id,
                "name": company.name,
                "ticker": company.ticker,
                "reporting_currency": company.reporting_currency,
                "metrics": metrics,
                "line_items": line_results,
                "comparisons": comparisons,
                "named_cases": named_cases,
                "direction": direction,
                "status": status,
                "opportunity": {
                    "catalyst_date": company.opportunity.catalyst_date,
                    "actionability": company.opportunity.actionability,
                    "variant_wedge": company.opportunity.variant_wedge,
                    "what_is_priced_in": company.opportunity.what_is_priced_in,
                    "why_now": company.opportunity.why_now,
                    "catalyst": company.opportunity.catalyst,
                    "first_rejection": company.opportunity.first_rejection,
                    "investable_if": company.opportunity.investable_if,
                    "thesis_kill": company.opportunity.thesis_kill,
                    "next_workflow": company.opportunity.next_workflow,
                },
                "market_context": {
                    "as_of_date": company.market_snapshot.as_of_date,
                    "valuation_context": company.market_snapshot.valuation_context,
                },
                "consensus_context": {
                    "as_of_date": company.consensus.as_of_date,
                    "comparable_scope": company.consensus.comparable_scope,
                },
                "notes": company.notes,
            }
        )
        ranking_rows.append(
            {
                "company_id": company.id,
                "name": company.name,
                "ticker": company.ticker,
                "direction": direction,
                "status": status,
                "eps_revision_pct": eps_revision,
                "revenue_revision_pct": comparisons["revenue_revision_pct"],
                "screen_score": comparisons["screen_score"],
                "catalyst_date": company.opportunity.catalyst_date,
                "first_rejection": company.opportunity.first_rejection,
                "thesis_kill": company.opportunity.thesis_kill,
            }
        )
    ranking_rows.sort(key=lambda item: (-item["screen_score"]["p50"], item["ticker"]))
    for index, item in enumerate(ranking_rows, start=1):
        item["rank"] = index
    rank_by_company = {item["company_id"]: item["rank"] for item in ranking_rows}
    for item in company_results:
        item["research_rank"] = rank_by_company[item["id"]]
    company_results.sort(key=lambda item: item["research_rank"])

    evidence = [
        {
            "id": item.id,
            "kind": item.kind.value,
            "title": item.title,
            "source_url": item.source_url,
            "publisher": item.publisher,
            "published_at": item.published_at,
            "retrieved_at": item.retrieved_at,
            "source_family": item.source_family,
            "license": item.license,
            "excerpt": item.excerpt,
            "content_hash": item.content_hash,
        }
        for item in scenario.evidence
    ]
    warnings = [
        "Source P10/P50/P90 values are approximated as triangular draws; raw manufacturing draws and cross-engine dependence are not preserved.",
        "Named bear/base/bull cases use directional endpoints for model inputs while holding consensus at its base value.",
        "The ranking is a research queue, not a recommendation, price target, or portfolio-sizing rule.",
    ]
    if scenario.synthetic or case.source_synthetic:
        warnings.insert(
            0,
            "The physical source and earnings, consensus, market, or opportunity inputs are synthetic; every candidate remains wait_for_proof.",
        )
    return {
        "format": "ai-supply-earnings-result.v1",
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "quarter": scenario.quarter,
            "as_of_date": scenario.as_of_date,
            "recorded_at": scenario.recorded_at,
            "synthetic": scenario.synthetic,
            "samples": scenario.samples,
            "seed": scenario.seed,
            "notes": scenario.notes,
        },
        "source_result": {
            "format": scenario.source_result_format,
            "scenario_id": scenario.source_scenario_id,
            "sha256": case.source_result_sha256,
            "synthetic": case.source_synthetic,
            "metric_distributions": case.source_metrics,
        },
        "companies": company_results,
        "rankings": ranking_rows,
        "inputs": {
            "companies": [_company_inputs(company) for company in scenario.companies]
        },
        "evidence": evidence,
        "methodology": {
            "physical_source": "Each source metric reuses one sampled triangular P10/P50/P90 draw across every line item in that Monte Carlo iteration.",
            "inventory_bridge": "Recognized units equal max(0, beginning inventory plus attributable production minus ending inventory), multiplied by the recognition share.",
            "earnings_bridge": "AI-chain gross profit plus rest-of-company gross profit, less operating and nonoperating expense and positive-income tax, divided by diluted shares.",
            "named_cases": "Bear and bull cases use adverse and favorable model endpoints respectively; consensus remains frozen at base to avoid manufacturing a moving comparator.",
            "ranking": "Absolute EPS discrepancy times confidence, evidence readiness, liquidity, catalyst proximity, and downside resilience. Direction follows the median EPS discrepancy.",
        },
        "warnings": warnings,
    }
