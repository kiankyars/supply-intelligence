"""Hash-complete releases for supplier earnings bridges."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .earnings_engine import reconcile_earnings
from .earnings_loader import LoadedEarningsCase
from .earnings_report import render_earnings_dashboard
from .release import _csv, _json, _sha256


EARNINGS_RELEASE_FORMAT = "ai-supply-earnings-release.v1"
DISTRIBUTION_FIELDS = ["p10", "p50", "p90", "mean", "minimum", "maximum"]


def _distribution_columns(prefix: str, distribution: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{field}": distribution[field] for field in DISTRIBUTION_FIELDS}


def _company_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for company in result["companies"]:
        rows.append(
            {
                "rank": company["research_rank"],
                "company_id": company["id"],
                "name": company["name"],
                "ticker": company["ticker"],
                "direction": company["direction"],
                "status": company["status"],
                **_distribution_columns(
                    "ai_chain_revenue_usd",
                    company["metrics"]["ai_chain_revenue_usd"],
                ),
                **_distribution_columns(
                    "total_revenue_usd",
                    company["metrics"]["total_revenue_usd"],
                ),
                **_distribution_columns("eps_usd", company["metrics"]["eps_usd"]),
                **_distribution_columns(
                    "consensus_revenue_usd",
                    company["comparisons"]["consensus_revenue_usd"],
                ),
                **_distribution_columns(
                    "consensus_eps_usd",
                    company["comparisons"]["consensus_eps_usd"],
                ),
                **_distribution_columns(
                    "revenue_revision_pct",
                    company["comparisons"]["revenue_revision_pct"],
                ),
                **_distribution_columns(
                    "eps_revision_pct",
                    company["comparisons"]["eps_revision_pct"],
                ),
                **_distribution_columns(
                    "forward_pe",
                    company["comparisons"]["forward_pe"],
                ),
                **_distribution_columns(
                    "market_cap_usd",
                    company["comparisons"]["market_cap_usd"],
                ),
                **_distribution_columns(
                    "screen_score",
                    company["comparisons"]["screen_score"],
                ),
                "catalyst_date": company["opportunity"]["catalyst_date"],
                "first_rejection": company["opportunity"]["first_rejection"],
                "thesis_kill": company["opportunity"]["thesis_kill"],
            }
        )
    return rows


def _line_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for company in result["companies"]:
        for line in company["line_items"]:
            row = {
                "company_id": company["id"],
                "ticker": company["ticker"],
                "line_id": line["id"],
                "line_name": line["name"],
                "source_metric": line["source_metric"],
                "source_unit": line["source_unit"],
                "component_unit": line["component_unit"],
            }
            for metric in (
                "source_units",
                "produced_units",
                "available_units",
                "shipped_units",
                "recognized_units",
                "revenue_usd",
                "gross_profit_usd",
            ):
                row.update(_distribution_columns(metric, line[metric]))
            rows.append(row)
    return rows


def _case_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    fields = (
        "ai_chain_revenue_usd",
        "ai_chain_gross_profit_usd",
        "rest_of_company_revenue_usd",
        "total_revenue_usd",
        "gross_profit_usd",
        "gross_margin",
        "operating_income_usd",
        "pretax_income_usd",
        "tax_expense_usd",
        "net_income_usd",
        "diluted_shares",
        "eps_usd",
        "ai_chain_revenue_share",
        "consensus_revenue_usd",
        "consensus_eps_usd",
        "revenue_revision_pct",
        "eps_revision_pct",
    )
    for company in result["companies"]:
        for case_name in ("bear", "base", "bull"):
            case = company["named_cases"][case_name]
            rows.append(
                {
                    "company_id": company["id"],
                    "ticker": company["ticker"],
                    "case": case_name,
                    **{field: case[field] for field in fields},
                }
            )
    return rows


def _ranking_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in result["rankings"]:
        rows.append(
            {
                "rank": item["rank"],
                "company_id": item["company_id"],
                "name": item["name"],
                "ticker": item["ticker"],
                "direction": item["direction"],
                "status": item["status"],
                **_distribution_columns(
                    "revenue_revision_pct", item["revenue_revision_pct"]
                ),
                **_distribution_columns(
                    "eps_revision_pct", item["eps_revision_pct"]
                ),
                **_distribution_columns("screen_score", item["screen_score"]),
                "catalyst_date": item["catalyst_date"],
                "first_rejection": item["first_rejection"],
                "thesis_kill": item["thesis_kill"],
            }
        )
    return rows


def _estimate_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []

    def append(owner_type: str, owner_id: str, parameter: str, value: Any) -> None:
        if not isinstance(value, dict) or "low" not in value:
            return
        rows.append(
            {
                "owner_type": owner_type,
                "owner_id": owner_id,
                "parameter": parameter,
                "low": value["low"],
                "base": value["base"],
                "high": value["high"],
                "unit": value["unit"],
                "posture": value["posture"],
                "confidence": value["confidence"],
                "last_updated": value["last_updated"],
                "methodology": value["methodology"],
                "evidence_ids": "|".join(value["evidence_ids"]),
                "confirming_evidence": value["confirming_evidence"],
                "falsifying_evidence": value["falsifying_evidence"],
                "correlation_group": value["correlation_group"] or "",
            }
        )

    for company in result["inputs"]["companies"]:
        company_id = company["id"]
        for line in company["line_items"]:
            for parameter, value in line.items():
                append("line_item", f"{company_id}:{line['id']}", parameter, value)
        for parameter in (
            "rest_of_company_revenue",
            "rest_of_company_gross_margin",
            "operating_expenses",
            "net_nonoperating_expense",
            "tax_rate",
            "diluted_shares",
        ):
            append("company", company_id, parameter, company[parameter])
        for parameter, value in company["consensus"].items():
            append("consensus", company_id, parameter, value)
        for parameter, value in company["market_snapshot"].items():
            append("market_snapshot", company_id, parameter, value)
        for parameter, value in company["opportunity"].items():
            append("opportunity", company_id, parameter, value)
    return rows


def build_earnings_release_documents(case: LoadedEarningsCase) -> dict[str, str]:
    result = reconcile_earnings(case)
    company_fields = [
        "rank",
        "company_id",
        "name",
        "ticker",
        "direction",
        "status",
        *[
            f"{metric}_{field}"
            for metric in (
                "ai_chain_revenue_usd",
                "total_revenue_usd",
                "eps_usd",
                "consensus_revenue_usd",
                "consensus_eps_usd",
                "revenue_revision_pct",
                "eps_revision_pct",
                "forward_pe",
                "market_cap_usd",
                "screen_score",
            )
            for field in DISTRIBUTION_FIELDS
        ],
        "catalyst_date",
        "first_rejection",
        "thesis_kill",
    ]
    line_fields = [
        "company_id",
        "ticker",
        "line_id",
        "line_name",
        "source_metric",
        "source_unit",
        "component_unit",
        *[
            f"{metric}_{field}"
            for metric in (
                "source_units",
                "produced_units",
                "available_units",
                "shipped_units",
                "recognized_units",
                "revenue_usd",
                "gross_profit_usd",
            )
            for field in DISTRIBUTION_FIELDS
        ],
    ]
    case_fields = [
        "company_id",
        "ticker",
        "case",
        "ai_chain_revenue_usd",
        "ai_chain_gross_profit_usd",
        "rest_of_company_revenue_usd",
        "total_revenue_usd",
        "gross_profit_usd",
        "gross_margin",
        "operating_income_usd",
        "pretax_income_usd",
        "tax_expense_usd",
        "net_income_usd",
        "diluted_shares",
        "eps_usd",
        "ai_chain_revenue_share",
        "consensus_revenue_usd",
        "consensus_eps_usd",
        "revenue_revision_pct",
        "eps_revision_pct",
    ]
    ranking_fields = [
        "rank",
        "company_id",
        "name",
        "ticker",
        "direction",
        "status",
        *[
            f"{metric}_{field}"
            for metric in (
                "revenue_revision_pct",
                "eps_revision_pct",
                "screen_score",
            )
            for field in DISTRIBUTION_FIELDS
        ],
        "catalyst_date",
        "first_rejection",
        "thesis_kill",
    ]
    estimate_fields = [
        "owner_type",
        "owner_id",
        "parameter",
        "low",
        "base",
        "high",
        "unit",
        "posture",
        "confidence",
        "last_updated",
        "methodology",
        "evidence_ids",
        "confirming_evidence",
        "falsifying_evidence",
        "correlation_group",
    ]
    evidence_fields = [
        "id",
        "kind",
        "title",
        "source_url",
        "publisher",
        "published_at",
        "retrieved_at",
        "source_family",
        "license",
        "excerpt",
        "content_hash",
    ]
    documents = {
        "dashboard.html": render_earnings_dashboard(result),
        "result.json": _json(result),
        "company_summary.csv": _csv(company_fields, _company_rows(result)),
        "line_items.csv": _csv(line_fields, _line_rows(result)),
        "named_cases.csv": _csv(case_fields, _case_rows(result)),
        "rankings.csv": _csv(ranking_fields, _ranking_rows(result)),
        "input_estimates.csv": _csv(estimate_fields, _estimate_rows(result)),
        "evidence.csv": _csv(evidence_fields, result["evidence"]),
        "scenario.json": case.scenario_document.rstrip() + "\n",
        "source_result.json": case.source_result_document.rstrip() + "\n",
        "README.md": (
            f"# {case.scenario.name}\n\n"
            f"Quarter: `{case.scenario.quarter}`. As of: `{case.scenario.as_of_date}`. "
            f"Monte Carlo draws: `{case.scenario.samples:,}`.\n\n"
            "**This checked release uses a synthetic physical source and synthetic earnings, "
            "consensus, market, and opportunity inputs. Every ranked security remains "
            "`wait_for_proof`; nothing is an investment recommendation or price target.**\n\n"
            "Open `dashboard.html` first. `result.json` retains the complete model, named cases, "
            "comparators, rankings, inputs, evidence, and source lineage. The CSV files separate "
            "company summaries, physical-to-revenue line items, named cases, rankings, and every "
            "estimate.\n"
        ),
    }
    manifest = {
        "format": EARNINGS_RELEASE_FORMAT,
        "scenario_id": case.scenario.id,
        "quarter": case.scenario.quarter,
        "as_of_date": case.scenario.as_of_date,
        "recorded_at": case.scenario.recorded_at,
        "synthetic": case.scenario.synthetic,
        "source_result_sha256": case.source_result_sha256,
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_earnings_release(
    case: LoadedEarningsCase,
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_earnings_release_documents(case)
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
            (destination / name).write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
