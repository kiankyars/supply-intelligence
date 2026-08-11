"""Build the checked synthetic supplier earnings and discrepancy demonstration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


AS_OF = "2026-07-19"
RECORDED_AT = "2026-07-19T22:30:00Z"
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "releases" / "2026-07-17-blackwell-manufacturing-illustrative" / "result.json"
OUTPUT = Path(__file__).with_name(
    "blackwell-supplier-earnings-illustrative-2026q3.json"
)


def synthetic(
    low: float,
    base: float,
    high: float,
    unit: str,
    label: str,
    evidence_id: str,
    *,
    correlation_group: str | None = None,
) -> dict[str, object]:
    return {
        "low": low,
        "base": base,
        "high": high,
        "unit": unit,
        "posture": "synthetic",
        "methodology": f"Illustrative {label}; not a sourced company, consensus, or market estimate.",
        "confidence": 0.3,
        "last_updated": AS_OF,
        "evidence_ids": [evidence_id],
        "confirming_evidence": f"A dated, scope-comparable source supports the {label} range.",
        "falsifying_evidence": f"A dated, scope-comparable source places {label} outside the range.",
        "correlation_group": correlation_group,
    }


def line_item(config: dict[str, object]) -> dict[str, object]:
    component = str(config["component_unit"])
    source_unit = str(config["source_unit"])
    currency = str(config.get("currency", "USD"))
    inventory = config["inventory"]
    assert isinstance(inventory, dict)
    return {
        "id": config["id"],
        "name": config["name"],
        "source_metric": config["source_metric"],
        "source_unit": source_unit,
        "component_unit": component,
        "currency": currency,
        "units_per_source_unit": synthetic(
            *config["units_per_source"],
            f"{component}/{source_unit}",
            f"{config['name']} units per physical source unit",
            "synthetic:earnings-economics",
        ),
        "attributable_share": synthetic(
            *config["attributable_share"],
            "ratio",
            f"{config['name']} supplier attribution",
            "synthetic:earnings-economics",
        ),
        "beginning_inventory_units": synthetic(
            *inventory["beginning"],
            component,
            f"{config['name']} beginning inventory",
            "synthetic:earnings-economics",
        ),
        "ending_inventory_units": synthetic(
            *inventory["ending"],
            component,
            f"{config['name']} ending inventory",
            "synthetic:earnings-economics",
        ),
        "revenue_recognition_share": synthetic(
            *config["recognition_share"],
            "ratio",
            f"{config['name']} current-quarter recognition share",
            "synthetic:earnings-economics",
        ),
        "unit_price_local": synthetic(
            *config["unit_price"],
            f"{currency}/{component}",
            f"{config['name']} unit price",
            "synthetic:earnings-economics",
        ),
        "fx_usd_per_local": synthetic(
            *config.get("fx", (1, 1, 1)),
            f"USD/{currency}",
            f"{config['name']} USD conversion",
            "synthetic:earnings-economics",
        ),
        "gross_margin": synthetic(
            *config["gross_margin"],
            "ratio",
            f"{config['name']} gross margin",
            "synthetic:earnings-economics",
        ),
        "notes": config["notes"],
    }


def company(config: dict[str, object]) -> dict[str, object]:
    ticker = str(config["ticker"])
    return {
        "id": config["id"],
        "name": config["name"],
        "ticker": ticker,
        "reporting_currency": "USD",
        "line_items": [line_item(item) for item in config["line_items"]],
        "rest_of_company_revenue": synthetic(
            *config["rest_revenue"],
            "USD",
            f"{ticker} rest-of-company quarterly revenue",
            "synthetic:earnings-economics",
            correlation_group=f"{ticker.lower()}-company-demand",
        ),
        "rest_of_company_gross_margin": synthetic(
            *config["rest_margin"],
            "ratio",
            f"{ticker} rest-of-company gross margin",
            "synthetic:earnings-economics",
        ),
        "operating_expenses": synthetic(
            *config["opex"],
            "USD",
            f"{ticker} quarterly operating expenses",
            "synthetic:earnings-economics",
        ),
        "net_nonoperating_expense": synthetic(
            *config["nonoperating"],
            "USD",
            f"{ticker} quarterly net nonoperating expense",
            "synthetic:earnings-economics",
        ),
        "tax_rate": synthetic(
            *config["tax_rate"],
            "ratio",
            f"{ticker} effective tax rate",
            "synthetic:earnings-economics",
        ),
        "diluted_shares": synthetic(
            *config["shares"],
            "share",
            f"{ticker} diluted share count",
            "synthetic:earnings-economics",
        ),
        "consensus": {
            "as_of_date": AS_OF,
            "comparable_scope": "Synthetic same-quarter total revenue and diluted EPS comparator; not sell-side consensus.",
            "revenue": synthetic(
                *config["consensus_revenue"],
                "USD",
                f"{ticker} same-quarter consensus revenue comparator",
                "synthetic:consensus-market",
            ),
            "eps": synthetic(
                *config["consensus_eps"],
                "USD/share",
                f"{ticker} same-quarter consensus EPS comparator",
                "synthetic:consensus-market",
            ),
        },
        "market_snapshot": {
            "as_of_date": AS_OF,
            "price": synthetic(
                *config["price"],
                "USD/share",
                f"{ticker} share price",
                "synthetic:consensus-market",
            ),
            "next_twelve_month_eps": synthetic(
                *config["ntm_eps"],
                "USD/share",
                f"{ticker} next-twelve-month EPS",
                "synthetic:consensus-market",
            ),
            "market_cap": synthetic(
                *config["market_cap"],
                "USD",
                f"{ticker} market capitalization",
                "synthetic:consensus-market",
            ),
            "valuation_context": "Synthetic valuation fixture. No live price, multiple, positioning, or ownership data are included.",
        },
        "opportunity": {
            "catalyst_date": config["catalyst_date"],
            "confidence": synthetic(
                *config["confidence"],
                "ratio",
                f"{ticker} research confidence",
                "synthetic:opportunity",
            ),
            "evidence_readiness": synthetic(
                *config["evidence_readiness"],
                "ratio",
                f"{ticker} evidence readiness",
                "synthetic:opportunity",
            ),
            "liquidity": synthetic(
                *config["liquidity"],
                "ratio",
                f"{ticker} liquidity factor",
                "synthetic:opportunity",
            ),
            "catalyst_proximity": synthetic(
                *config["catalyst_proximity"],
                "ratio",
                f"{ticker} catalyst proximity",
                "synthetic:opportunity",
            ),
            "downside_resilience": synthetic(
                *config["downside_resilience"],
                "ratio",
                f"{ticker} downside resilience",
                "synthetic:opportunity",
            ),
            "actionability": "Research queue only; physical, earnings, consensus, and market inputs remain synthetic.",
            "variant_wedge": config["variant_wedge"],
            "what_is_priced_in": "Unknown. The market snapshot and consensus comparator are synthetic.",
            "why_now": config["why_now"],
            "catalyst": config["catalyst"],
            "first_rejection": config["first_rejection"],
            "investable_if": "Exact-scope physical output, supplier attribution, accounting bridge, current consensus, valuation, and downside are all sourced and the discrepancy survives review.",
            "thesis_kill": config["thesis_kill"],
            "next_workflow": config["next_workflow"],
        },
        "notes": config["notes"],
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    companies = [
        {
            "id": "nvidia-illustrative",
            "name": "NVIDIA illustrative Blackwell bridge",
            "ticker": "NVDA",
            "line_items": [
                {
                    "id": "nvidia-blackwell-accelerators",
                    "name": "Illustrative Blackwell accelerator revenue",
                    "source_metric": "finished_accelerator_packages",
                    "source_unit": "package",
                    "component_unit": "accelerator",
                    "units_per_source": (1, 1, 1),
                    "attributable_share": (0.95, 1, 1),
                    "inventory": {
                        "beginning": (20000, 35000, 50000),
                        "ending": (25000, 40000, 60000),
                    },
                    "recognition_share": (0.85, 0.93, 0.98),
                    "unit_price": (25000, 32000, 39000),
                    "gross_margin": (0.65, 0.72, 0.76),
                    "notes": "The physical package count is synthetic and the ASP does not represent disclosed NVIDIA pricing or bundle allocation.",
                }
            ],
            "rest_revenue": (42e9, 48e9, 55e9),
            "rest_margin": (0.68, 0.72, 0.75),
            "opex": (6e9, 6.5e9, 7.2e9),
            "nonoperating": (0, 0.2e9, 0.5e9),
            "tax_rate": (0.15, 0.17, 0.2),
            "shares": (23.5e9, 24e9, 24.5e9),
            "consensus_revenue": (53e9, 56e9, 59e9),
            "consensus_eps": (1, 1.1, 1.2),
            "price": (160, 175, 190),
            "ntm_eps": (5.5, 6.2, 7),
            "market_cap": (3.8e12, 4.2e12, 4.6e12),
            "catalyst_date": "2026-08-26",
            "confidence": (0.2, 0.3, 0.4),
            "evidence_readiness": (0.05, 0.1, 0.2),
            "liquidity": (0.9, 0.95, 1),
            "catalyst_proximity": (0.7, 0.85, 0.95),
            "downside_resilience": (0.2, 0.35, 0.5),
            "variant_wedge": "Illustrative Blackwell accelerator recognition could differ from a synthetic same-quarter comparator.",
            "why_now": "The illustrative earnings date creates a bounded research window.",
            "catalyst": "Illustrative quarterly earnings and platform shipment commentary.",
            "first_rejection": "Source actual Blackwell sell-through, bundle ASP, channel inventory, and comparable consensus.",
            "thesis_kill": "Sourced unit economics or sell-through remove the modeled EPS discrepancy.",
            "next_workflow": "Build a disclosed revenue-segment bridge and reconcile distributor and customer acceptance data.",
            "notes": "Real security name with wholly synthetic economics and market data; not an NVIDIA forecast.",
        },
        {
            "id": "micron-illustrative",
            "name": "Micron illustrative HBM bridge",
            "ticker": "MU",
            "line_items": [
                {
                    "id": "micron-hbm-stacks",
                    "name": "Illustrative HBM stack revenue",
                    "source_metric": "hbm_good_stacks",
                    "source_unit": "stack",
                    "component_unit": "HBM-stack",
                    "units_per_source": (1, 1, 1),
                    "attributable_share": (0.2, 0.3, 0.4),
                    "inventory": {
                        "beginning": (100000, 200000, 350000),
                        "ending": (150000, 250000, 450000),
                    },
                    "recognition_share": (0.8, 0.9, 0.98),
                    "unit_price": (1800, 2400, 3000),
                    "gross_margin": (0.45, 0.55, 0.62),
                    "notes": "The source HBM3E flow is not supplier allocated; the Micron share, stack price, inventory, and recognition inputs are synthetic.",
                }
            ],
            "rest_revenue": (7e9, 9e9, 11e9),
            "rest_margin": (0.38, 0.46, 0.53),
            "opex": (3.2e9, 3.6e9, 4e9),
            "nonoperating": (0.1e9, 0.2e9, 0.35e9),
            "tax_rate": (0.1, 0.14, 0.18),
            "shares": (1.1e9, 1.13e9, 1.16e9),
            "consensus_revenue": (12e9, 14e9, 16e9),
            "consensus_eps": (2.8, 3.4, 4),
            "price": (180, 205, 230),
            "ntm_eps": (12, 15, 18),
            "market_cap": (200e9, 230e9, 260e9),
            "catalyst_date": "2026-09-23",
            "confidence": (0.15, 0.25, 0.35),
            "evidence_readiness": (0.05, 0.1, 0.15),
            "liquidity": (0.8, 0.9, 0.95),
            "catalyst_proximity": (0.55, 0.7, 0.85),
            "downside_resilience": (0.25, 0.4, 0.55),
            "variant_wedge": "Illustrative HBM mix and attribution could create a positive or negative EPS discrepancy.",
            "why_now": "HBM4 disclosures create directional evidence but do not validate the HBM3E quantity bridge.",
            "catalyst": "Illustrative quarterly earnings, HBM mix, and capacity commentary.",
            "first_rejection": "Source HBM3E supplier share, good-stack output, price, inventory, and comparable consensus.",
            "thesis_kill": "Supplier allocation or pricing evidence invalidates the HBM revenue bridge.",
            "next_workflow": "Build supplier-specific HBM BOM, wafer allocation, packaging, price, and revenue-recognition evidence.",
            "notes": "Real security name with wholly synthetic economics and market data; not a Micron forecast.",
        },
        {
            "id": "tsmc-illustrative",
            "name": "TSMC illustrative advanced-packaging bridge",
            "ticker": "TSM",
            "line_items": [
                {
                    "id": "tsmc-blackwell-packaging",
                    "name": "Illustrative advanced-package service revenue",
                    "source_metric": "package_attempts",
                    "source_unit": "package",
                    "component_unit": "package-service",
                    "units_per_source": (1, 1, 1),
                    "attributable_share": (0.8, 0.9, 1),
                    "inventory": {"beginning": (0, 0, 0), "ending": (0, 0, 0)},
                    "recognition_share": (0.9, 0.97, 1),
                    "unit_price": (3500, 5500, 7500),
                    "gross_margin": (0.48, 0.55, 0.6),
                    "notes": "A zero-inventory service bridge is illustrative; package ownership, price, mix, yield accounting, and revenue timing are not sourced.",
                }
            ],
            "rest_revenue": (27e9, 31e9, 35e9),
            "rest_margin": (0.52, 0.57, 0.61),
            "opex": (5e9, 5.8e9, 6.6e9),
            "nonoperating": (0, 0.15e9, 0.35e9),
            "tax_rate": (0.16, 0.19, 0.22),
            "shares": (5.15e9, 5.2e9, 5.25e9),
            "consensus_revenue": (31e9, 34e9, 37e9),
            "consensus_eps": (2, 2.3, 2.6),
            "price": (330, 365, 400),
            "ntm_eps": (9, 10.5, 12),
            "market_cap": (850e9, 950e9, 1.05e12),
            "catalyst_date": "2026-10-15",
            "confidence": (0.15, 0.25, 0.35),
            "evidence_readiness": (0.05, 0.1, 0.15),
            "liquidity": (0.75, 0.85, 0.92),
            "catalyst_proximity": (0.45, 0.6, 0.75),
            "downside_resilience": (0.3, 0.45, 0.6),
            "variant_wedge": "Illustrative advanced-package revenue could differ from a synthetic company comparator.",
            "why_now": "Reported backend and tester shortages identify a bottleneck family without quantifying product throughput.",
            "catalyst": "Illustrative quarterly results and advanced-packaging capacity commentary.",
            "first_rejection": "Source product-specific package starts, service pricing, revenue timing, and comparable consensus.",
            "thesis_kill": "Exact package economics or broader company results remove the modeled EPS discrepancy.",
            "next_workflow": "Map CoWoS technology mix, customer allocation, package pricing, and accounting recognition.",
            "notes": "Real security name with wholly synthetic economics and market data; not a TSMC forecast.",
        },
    ]
    document = {
        "format": "ai-supply-earnings-bridge.v1",
        "id": "blackwell-supplier-earnings-illustrative-2026q3",
        "name": "Illustrative Blackwell supplier earnings and discrepancy bridge",
        "quarter": "2026-Q3",
        "as_of_date": AS_OF,
        "recorded_at": RECORDED_AT,
        "synthetic": True,
        "samples": 20000,
        "seed": 20260719,
        "source_result": {
            "sha256": source_sha,
            "format": source["format"],
            "scenario_id": source["scenario"]["id"],
        },
        "evidence": [
            {
                "id": "synthetic:earnings-economics",
                "kind": "synthetic",
                "title": "Illustrative supplier economics and accounting bridge",
                "source_url": "urn:synthetic:blackwell-supplier-economics",
                "publisher": "AI Supply Intelligence",
                "retrieved_at": RECORDED_AT,
                "published_at": None,
                "source_family": "synthetic-earnings-demo",
                "license": "Internal demonstration",
                "excerpt": "Prices, attribution, inventory, recognition, margins, expenses, tax, and shares are synthetic.",
                "content_hash": None,
            },
            {
                "id": "synthetic:consensus-market",
                "kind": "synthetic",
                "title": "Illustrative consensus and market snapshot",
                "source_url": "urn:synthetic:blackwell-consensus-market",
                "publisher": "AI Supply Intelligence",
                "retrieved_at": RECORDED_AT,
                "published_at": None,
                "source_family": "synthetic-market-demo",
                "license": "Internal demonstration",
                "excerpt": "Revenue, EPS, price, market cap, and valuation comparators are not live or sell-side data.",
                "content_hash": None,
            },
            {
                "id": "synthetic:opportunity",
                "kind": "synthetic",
                "title": "Illustrative opportunity-screen factors",
                "source_url": "urn:synthetic:blackwell-opportunity",
                "publisher": "AI Supply Intelligence",
                "retrieved_at": RECORDED_AT,
                "published_at": None,
                "source_family": "synthetic-opportunity-demo",
                "license": "Internal demonstration",
                "excerpt": "Research confidence, readiness, liquidity, timing, and downside factors are synthetic.",
                "content_hash": None,
            },
        ],
        "companies": [company(item) for item in companies],
        "notes": "Physical output comes from the checked synthetic manufacturing release. Every company and market input remains synthetic.",
    }
    OUTPUT.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
