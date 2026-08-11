"""Standalone supplier earnings and discrepancy dashboard."""

from __future__ import annotations

import html
from typing import Any


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{sign}${absolute / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{sign}${absolute / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{sign}${absolute:,.0f}"
    return f"{sign}${absolute:,.2f}"


def _number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _direction(value: str) -> str:
    label = "Long research" if value.startswith("long") else "Short research"
    css = "positive" if value.startswith("long") else "negative"
    return f'<span class="pill {css}">{label}</span>'


def _ranking_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in result["rankings"]:
        rows.append(
            f"""
            <tr>
              <td class="rank">{item['rank']}</td>
              <td><strong>{_escape(item['ticker'])}</strong><span>{_escape(item['name'])}</span></td>
              <td>{_direction(item['direction'])}<span>{_escape(item['status'].replace('_', ' '))}</span></td>
              <td class="mono {'positive-text' if item['revenue_revision_pct']['p50'] >= 0 else 'negative-text'}">{_pct(item['revenue_revision_pct']['p50'])}<span>P10/P90 {_pct(item['revenue_revision_pct']['p10'])} / {_pct(item['revenue_revision_pct']['p90'])}</span></td>
              <td class="mono {'positive-text' if item['eps_revision_pct']['p50'] >= 0 else 'negative-text'}"><strong>{_pct(item['eps_revision_pct']['p50'])}</strong><span>P10/P90 {_pct(item['eps_revision_pct']['p10'])} / {_pct(item['eps_revision_pct']['p90'])}</span></td>
              <td class="mono">{item['screen_score']['p50']:.4f}<span>research priority only</span></td>
              <td>{_escape(item['catalyst_date'])}<span>{_escape(item['first_rejection'])}</span></td>
            </tr>
            """
        )
    return "".join(rows)


def _company_sections(result: dict[str, Any]) -> str:
    sections = []
    for company in result["companies"]:
        case_rows = []
        for name in ("bear", "base", "bull"):
            case = company["named_cases"][name]
            case_rows.append(
                f"""
                <tr>
                  <td><strong>{name.title()}</strong></td>
                  <td class="mono">{_usd(case['ai_chain_revenue_usd'])}<span>{case['ai_chain_revenue_share'] * 100:.1f}% of total</span></td>
                  <td class="mono">{_usd(case['total_revenue_usd'])}<span>{_pct(case['revenue_revision_pct'])} vs consensus</span></td>
                  <td class="mono">{_usd(case['gross_profit_usd'])}<span>{case['gross_margin'] * 100:.1f}% margin</span></td>
                  <td class="mono"><strong>{_usd(case['eps_usd'])}</strong><span>{_pct(case['eps_revision_pct'])} vs consensus</span></td>
                </tr>
                """
            )
        line_rows = []
        for line in company["line_items"]:
            line_rows.append(
                f"""
                <tr>
                  <td><strong>{_escape(line['name'])}</strong><span>{_escape(line['source_metric'])}</span></td>
                  <td class="mono">{_number(line['source_units']['p50'])}<span>{_escape(line['source_unit'])}</span></td>
                  <td class="mono">{_number(line['produced_units']['p50'])}<span>{_escape(line['component_unit'])}</span></td>
                  <td class="mono">{_number(line['recognized_units']['p50'])}<span>{_escape(line['component_unit'])}</span></td>
                  <td class="mono">{_usd(line['revenue_usd']['p50'])}</td>
                  <td class="mono">{_usd(line['gross_profit_usd']['p50'])}</td>
                </tr>
                """
            )
        opportunity = company["opportunity"]
        sections.append(
            f"""
            <section>
              <div class="section-head"><div><div class="eyebrow">#{company['research_rank']} · {_escape(company['status'].replace('_', ' '))}</div><h2>{_escape(company['ticker'])} · {_escape(company['name'])}</h2></div><div class="company-meta">{_direction(company['direction'])}<span>{company['comparisons']['forward_pe']['p50']:.1f}x synthetic NTM P/E · {_usd(company['comparisons']['market_cap_usd']['p50'])} market cap</span></div></div>
              <div class="table-wrap"><table><thead><tr><th>Case</th><th>AI-chain revenue</th><th>Total revenue</th><th>Gross profit</th><th>EPS</th></tr></thead><tbody>{''.join(case_rows)}</tbody></table></div>
              <h3>Physical-to-revenue lines</h3>
              <div class="table-wrap"><table><thead><tr><th>Line</th><th>Physical source</th><th>Attributed production</th><th>Recognized units</th><th>Revenue</th><th>Gross profit</th></tr></thead><tbody>{''.join(line_rows)}</tbody></table></div>
              <div class="thesis-grid">
                <article><span>Variant wedge</span><p>{_escape(opportunity['variant_wedge'])}</p></article>
                <article><span>What is priced in</span><p>{_escape(opportunity['what_is_priced_in'])}</p></article>
                <article><span>First rejection</span><p>{_escape(opportunity['first_rejection'])}</p></article>
                <article><span>Thesis kill</span><p>{_escape(opportunity['thesis_kill'])}</p></article>
              </div>
            </section>
            """
        )
    return "".join(sections)


def render_earnings_dashboard(result: dict[str, Any]) -> str:
    scenario = result["scenario"]
    source = result["source_result"]
    top = result["rankings"][0]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(scenario['name'])}</title>
  <style>
    :root {{ --ink:#14231d; --paper:#f4f2ea; --card:#fffdf8; --line:#d8d7ce; --muted:#66736d; --green:#0f6b4b; --green-soft:#dceee5; --red:#a13d33; --red-soft:#f5ddd9; --amber:#98600a; --shadow:0 18px 50px rgba(20,35,29,.08); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1500px,calc(100% - 40px)); margin:auto; padding:42px 0 72px; }}
    header {{ display:flex; flex-direction:column; align-items:flex-start; gap:18px; padding:36px; border-radius:24px; background:var(--ink); color:#fffdf8; box-shadow:var(--shadow); }}
    .eyebrow {{ color:#9fd0bd; font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ max-width:1100px; margin:0; font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif; letter-spacing:-.035em; }}
    header p {{ max-width:960px; margin:0; color:#d2ddd7; font-size:17px; }}
    .warning {{ width:100%; padding:14px 16px; border:1px solid #6c756f; border-radius:14px; background:rgba(255,255,255,.04); color:#fff4cf; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:20px 0 34px; }}
    .card, section {{ border:1px solid var(--line); border-radius:18px; background:var(--card); box-shadow:var(--shadow); }}
    .card {{ padding:20px; }} .card span {{ display:block; color:var(--muted); font-size:12px; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }}
    .card strong {{ display:block; margin:6px 0 2px; font:700 32px/1 Georgia,serif; }} .card small {{ color:var(--muted); }} .source-card strong {{ overflow-wrap:anywhere; font-size:22px; line-height:1.05; }}
    section {{ margin-top:20px; padding:26px; overflow:hidden; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:18px; }}
    h2 {{ margin:3px 0 0; font:700 30px/1.1 Georgia,serif; }} h3 {{ margin:26px 0 12px; font:700 20px/1.1 Georgia,serif; }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:14px; }}
    table {{ width:100%; min-width:1050px; border-collapse:collapse; }}
    th {{ padding:11px 13px; background:#ecebe4; color:#58665f; font-size:11px; letter-spacing:.08em; text-align:left; text-transform:uppercase; }}
    td {{ padding:13px; border-top:1px solid var(--line); vertical-align:top; }} td strong,td span {{ display:block; }} td span {{ margin-top:3px; color:var(--muted); font-size:12px; }}
    .rank {{ font:700 24px/1 Georgia,serif; }} .mono {{ font-variant-numeric:tabular-nums; }}
    .pill {{ display:inline-block; width:fit-content; padding:4px 8px; border-radius:999px; font-size:11px; font-weight:800; }}
    .pill.positive {{ color:var(--green); background:var(--green-soft); }} .pill.negative {{ color:var(--red); background:var(--red-soft); }}
    .company-meta span {{ display:block; margin-top:6px; color:var(--muted); font-size:12px; text-align:right; }}
    .positive-text {{ color:var(--green); }} .negative-text {{ color:var(--red); }}
    .thesis-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:20px; }}
    .thesis-grid article {{ padding:16px; border:1px solid var(--line); border-radius:12px; background:#f7f6f0; }}
    .thesis-grid span {{ color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }} .thesis-grid p {{ margin:5px 0 0; }}
    footer {{ margin-top:24px; color:var(--muted); font-size:12px; }}
    @media(max-width:950px) {{ .cards {{ grid-template-columns:1fr 1fr; }} .section-head {{ display:block; }} .section-head>div+div {{ margin-top:12px; }} }}
    @media(max-width:600px) {{ main {{ width:calc(100% - 20px); padding-top:10px; }} header,section {{ padding:20px; border-radius:14px; }} .cards,.thesis-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header>
    <div class="eyebrow">Supplier earnings bridge · {_escape(scenario['quarter'])}</div>
    <h1>Physical output now reaches revenue, EPS, consensus discrepancy, and a research ranking.</h1>
    <p>Inventory and recognition timing stay explicit. Named cases hold the comparator fixed, and every opportunity exposes its first rejection and thesis kill.</p>
    <div class="warning"><strong>Boundary:</strong> this checked run is synthetic and the physical source is synthetic. Every security remains <code>wait_for_proof</code>; no row is a recommendation or price target.</div>
  </header>
  <div class="cards">
    <article class="card"><span>Companies</span><strong>{len(result['companies'])}</strong><small>public-company bridges</small></article>
    <article class="card source-card"><span>Physical source</span><strong>{_escape(source['scenario_id'])}</strong><small>{_escape(source['format'])}</small></article>
    <article class="card"><span>Top research queue</span><strong>#{top['rank']} {_escape(top['ticker'])}</strong><small>{_escape(top['status'].replace('_', ' '))}</small></article>
    <article class="card"><span>Monte Carlo draws</span><strong>{scenario['samples']:,}</strong><small>P10 / P50 / P90 reported</small></article>
  </div>
  <section>
    <div class="section-head"><div><div class="eyebrow">Long / short research queue</div><h2>Rank discrepancy only after evidence-readiness penalties</h2></div><p>Direction follows median EPS discrepancy. Score also requires confidence, liquidity, catalyst proximity, evidence readiness, and downside resilience.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Security</th><th>Direction</th><th>Revenue gap</th><th>EPS gap</th><th>Score</th><th>Catalyst / first rejection</th></tr></thead><tbody>{_ranking_rows(result)}</tbody></table></div>
  </section>
  {_company_sections(result)}
  <section>
    <div class="section-head"><div><div class="eyebrow">Frozen lineage</div><h2>One physical result, one earnings vintage</h2></div></div>
    <div class="thesis-grid"><article><span>Source result SHA-256</span><p class="mono">{_escape(source['sha256'])}</p></article><article><span>Recorded at</span><p>{_escape(scenario['recorded_at'])}</p></article><article><span>Source approximation</span><p>P10, P50, and P90 become triangular low, mode, and high values.</p></article><article><span>Current status</span><p>Research workflow only; all candidates wait for sourced proof.</p></article></div>
  </section>
  <footer>As of {_escape(scenario['as_of_date'])}. Synthetic capacity, earnings, consensus, price, valuation, and ranking inputs are demonstration data.</footer>
</main></body></html>
"""
