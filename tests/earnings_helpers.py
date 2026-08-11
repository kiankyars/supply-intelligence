from __future__ import annotations

import json
import hashlib
from pathlib import Path

from supply_intelligence.earnings_engine import _company_inputs
from supply_intelligence.earnings_loader import LoadedEarningsCase
from supply_intelligence.earnings_models import (
    CompanyEarningsBridge,
    EarningsBridgeScenario,
    EarningsConsensus,
    EarningsLineItem,
    MarketSnapshot,
    OpportunityFrame,
)
from supply_intelligence.models import (
    Estimate,
    EstimatePosture,
    Evidence,
    EvidenceKind,
)


def estimate(
    low: float,
    base: float,
    high: float,
    unit: str,
    *,
    evidence_id: str = "synthetic:earnings",
) -> Estimate:
    return Estimate(
        low=low,
        base=base,
        high=high,
        unit=unit,
        posture=EstimatePosture.SYNTHETIC,
        methodology="Deterministic or bounded synthetic fixture for earnings bridge tests.",
        confidence=0.4,
        last_updated="2026-07-19",
        evidence_ids=(evidence_id,),
        confirming_evidence="A sourced physical, accounting, consensus, or market record supports the value.",
        falsifying_evidence="A sourced record places the value outside the range.",
    )


def _line_item(identifier: str, price: tuple[float, float, float]) -> EarningsLineItem:
    return EarningsLineItem(
        id=identifier,
        name=f"{identifier} accelerator-linked revenue",
        source_metric="finished_accelerator_packages",
        source_unit="package",
        component_unit="unit",
        currency="USD",
        units_per_source_unit=estimate(1, 1, 1, "unit/package"),
        attributable_share=estimate(1, 1, 1, "ratio"),
        beginning_inventory_units=estimate(10, 10, 10, "unit"),
        ending_inventory_units=estimate(20, 20, 20, "unit"),
        revenue_recognition_share=estimate(1, 1, 1, "ratio"),
        unit_price_local=estimate(*price, "USD/unit"),
        fx_usd_per_local=estimate(1, 1, 1, "USD/USD"),
        gross_margin=estimate(0.5, 0.5, 0.5, "ratio"),
    )


def _opportunity(identifier: str, readiness: float) -> OpportunityFrame:
    return OpportunityFrame(
        catalyst_date="2026-08-20",
        confidence=estimate(0.4, 0.5, 0.6, "ratio"),
        evidence_readiness=estimate(readiness, readiness, readiness, "ratio"),
        liquidity=estimate(0.8, 0.8, 0.8, "ratio"),
        catalyst_proximity=estimate(0.7, 0.7, 0.7, "ratio"),
        downside_resilience=estimate(0.5, 0.5, 0.5, "ratio"),
        actionability="Research only while fixture inputs remain synthetic.",
        variant_wedge=f"{identifier} modeled EPS differs from the frozen comparator.",
        what_is_priced_in="Synthetic market snapshot; no live priced-in conclusion.",
        why_now="A dated synthetic catalyst exercises timing fields.",
        catalyst="Illustrative earnings release.",
        first_rejection="Replace physical and consensus fixtures with sourced values.",
        investable_if="Every material input is sourced and downside survives review.",
        thesis_kill="Sourced earnings bridge removes the discrepancy.",
        next_workflow="Acquire comparable consensus and reconcile segment attribution.",
    )


def _company(
    identifier: str,
    ticker: str,
    price: tuple[float, float, float],
    rest_revenue: tuple[float, float, float],
    consensus_revenue: float,
    consensus_eps: float,
    readiness: float,
) -> CompanyEarningsBridge:
    return CompanyEarningsBridge(
        id=identifier,
        name=f"{identifier} supplier",
        ticker=ticker,
        reporting_currency="USD",
        line_items=(_line_item(f"{identifier}-line", price),),
        rest_of_company_revenue=estimate(*rest_revenue, "USD"),
        rest_of_company_gross_margin=estimate(0.4, 0.4, 0.4, "ratio"),
        operating_expenses=estimate(200, 200, 200, "USD"),
        net_nonoperating_expense=estimate(0, 0, 0, "USD"),
        tax_rate=estimate(0.2, 0.2, 0.2, "ratio"),
        diluted_shares=estimate(100, 100, 100, "share"),
        consensus=EarningsConsensus(
            as_of_date="2026-07-19",
            comparable_scope="Illustrative same-quarter total company revenue and EPS.",
            revenue=estimate(
                consensus_revenue,
                consensus_revenue,
                consensus_revenue,
                "USD",
            ),
            eps=estimate(consensus_eps, consensus_eps, consensus_eps, "USD/share"),
        ),
        market_snapshot=MarketSnapshot(
            as_of_date="2026-07-19",
            price=estimate(20, 20, 20, "USD/share"),
            next_twelve_month_eps=estimate(2, 2, 2, "USD/share"),
            market_cap=estimate(2000, 2000, 2000, "USD"),
            valuation_context="Synthetic 10x NTM P/E fixture.",
        ),
        opportunity=_opportunity(identifier, readiness),
    )


def earnings_case(*, samples: int = 2000) -> LoadedEarningsCase:
    evidence = Evidence(
        id="synthetic:earnings",
        kind=EvidenceKind.SYNTHETIC,
        title="Synthetic earnings fixture",
        source_url="urn:synthetic:earnings-fixture",
        publisher="AI Supply Intelligence",
        retrieved_at="2026-07-19T22:00:00Z",
    )
    scenario = EarningsBridgeScenario(
        id="earnings-fixture-2026q3",
        name="Synthetic supplier earnings bridge fixture",
        quarter="2026-Q3",
        as_of_date="2026-07-19",
        recorded_at="2026-07-19T22:00:00Z",
        synthetic=True,
        samples=samples,
        seed=20260719,
        source_result_sha256="a" * 64,
        source_result_format="ai-supply-manufacturing-result.v1",
        source_scenario_id="manufacturing-fixture-2026q3",
        evidence=(evidence,),
        companies=(
            _company(
                "positive",
                "POS",
                (8, 10, 12),
                (80, 100, 120),
                900,
                2,
                0.6,
            ),
            _company(
                "negative",
                "NEG",
                (3, 5, 7),
                (40, 50, 60),
                700,
                1.5,
                0.3,
            ),
        ),
    )
    source_result = {
        "format": "ai-supply-manufacturing-result.v1",
        "scenario": {
            "id": "manufacturing-fixture-2026q3",
            "quarter": "2026-Q3",
            "recorded_at": "2026-07-19T21:00:00Z",
            "synthetic": True,
        },
        "conversion_outputs": {
            "finished_accelerator_packages": {
                "p10": 100,
                "p50": 100,
                "p90": 100,
                "mean": 100,
                "minimum": 100,
                "maximum": 100,
            }
        },
    }
    source_document = json.dumps(source_result, indent=2, sort_keys=True) + "\n"
    return LoadedEarningsCase(
        scenario=scenario,
        source_result=source_result,
        source_result_sha256="a" * 64,
        source_result_document=source_document,
        scenario_document="{}\n",
        source_metrics={
            "finished_accelerator_packages": {
                "p10": 100.0,
                "p50": 100.0,
                "p90": 100.0,
                "unit": "package",
            }
        },
        source_synthetic=True,
    )


def earnings_documents(root: Path) -> tuple[Path, Path, dict[str, object]]:
    case = earnings_case(samples=500)
    source_path = root / "source-result.json"
    source_path.write_text(case.source_result_document, encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    evidence = case.scenario.evidence[0]
    scenario_document: dict[str, object] = {
        "format": "ai-supply-earnings-bridge.v1",
        "id": case.scenario.id,
        "name": case.scenario.name,
        "quarter": case.scenario.quarter,
        "as_of_date": case.scenario.as_of_date,
        "recorded_at": case.scenario.recorded_at,
        "synthetic": True,
        "samples": 500,
        "seed": case.scenario.seed,
        "source_result": {
            "sha256": source_sha,
            "format": case.scenario.source_result_format,
            "scenario_id": case.scenario.source_scenario_id,
        },
        "evidence": [
            {
                "id": evidence.id,
                "kind": evidence.kind.value,
                "title": evidence.title,
                "source_url": evidence.source_url,
                "publisher": evidence.publisher,
                "retrieved_at": evidence.retrieved_at,
                "published_at": evidence.published_at,
                "source_family": evidence.source_family,
                "license": evidence.license,
                "excerpt": evidence.excerpt,
                "content_hash": evidence.content_hash,
            }
        ],
        "companies": [_company_inputs(company) for company in case.scenario.companies],
        "notes": "Synthetic loader fixture.",
    }
    scenario_path = root / "earnings-scenario.json"
    scenario_path.write_text(
        json.dumps(scenario_document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return scenario_path, source_path, scenario_document
