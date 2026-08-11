"""Standalone dashboard for reported-guidance backtests."""

from __future__ import annotations

import html
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _number(value: float, unit: str) -> str:
    if unit == "ratio":
        return _percentage(value)
    if unit == "USD billion":
        return f"${value:,.3f}B"
    if unit == "USD/share":
        return f"${value:,.2f}"
    return f"{value:,.3g} {unit}"


def _score_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["scores"]:
        guidance = (
            _number(item["guidance_midpoint"], item["unit"])
            if item["range_semantics"] == "approximate_point"
            else (
                f"{_number(item['guidance_low'], item['unit'])} – "
                f"{_number(item['guidance_high'], item['unit'])}"
            )
        )
        midpoint_ratio = item["actual_to_guidance_midpoint_ratio"]
        surprise = (
            "—"
            if midpoint_ratio is None
            else _percentage(midpoint_ratio - 1.0)
        )
        status = item["surprise_direction"].replace("_", " ").title()
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['label'])}</strong><span>{_escape(item['basis'])} · {_escape(item['metric_class'])}</span></td>
              <td class="mono"><strong>{_escape(guidance)}</strong><span>{_escape(item['range_semantics'].replace('_', ' '))}</span></td>
              <td class="mono"><strong>{_escape(_number(item['actual_value'], item['unit']))}</strong></td>
              <td class="mono"><strong>{_escape(surprise)}</strong><span>actual vs midpoint</span></td>
              <td><span class="status status-{_escape(item['surprise_direction'])}">{_escape(status)}</span><small>normalized error {_escape(f"{item['normalized_absolute_error']:.2f}x")}</small></td>
            </tr>
            """
        )
    return "".join(rows)


def _evidence_rows(result: Mapping[str, Any]) -> str:
    return "".join(
        f"""
        <div>
          <span>{_escape(item['role'])} · {_escape(item['published_at'])}</span>
          <strong>{_escape(item['title'])}</strong>
          <a href="{_escape(item['source_url'])}">{_escape(item['publisher'])}</a>
          <code>{_escape(item['content_hash'])}</code>
        </div>
        """
        for item in result["evidence"]
    )


def render_guidance_backtest_dashboard(result: Mapping[str, Any]) -> str:
    case = result["case"]
    summary = result["summary"]
    largest = max(
        result["scores"],
        key=lambda item: abs(
            (item["actual_to_guidance_midpoint_ratio"] or 1.0) - 1.0
        ),
    )
    largest_surprise = abs(
        (largest["actual_to_guidance_midpoint_ratio"] or 1.0) - 1.0
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(case['id'])}</title>
  <style>
    :root {{ color-scheme: light; --ink: #16211c; --muted: #66716c; --paper: #f3f1e9; --card: #fffdf8; --line: #d7d6cc; --green: #12684d; --green-soft: #dceee5; --red: #9b4035; --red-soft: #f4ddd8; --amber: #93620d; --amber-soft: #f6e9c8; --shadow: 0 18px 48px rgba(22, 33, 28, .08); }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(1440px, calc(100% - 40px)); margin: 0 auto; padding: 42px 0 72px; }}
    header {{ padding: 36px; border-radius: 24px; background: var(--ink); color: #fffdf8; box-shadow: var(--shadow); }}
    .eyebrow {{ color: #9ed6bf; font-size: 12px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    h1 {{ max-width: 1050px; margin: 10px 0 12px; font: 700 clamp(34px, 5vw, 62px)/1.02 Georgia, serif; letter-spacing: -.035em; }}
    header p {{ max-width: 960px; margin: 0; color: #d5ddd9; font-size: 17px; }}
    .warning {{ margin-top: 22px; padding: 14px 16px; border: 1px solid #68736d; border-radius: 14px; color: #fff2c9; background: rgba(255,255,255,.04); }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 20px 0 34px; }}
    .card, section {{ background: var(--card); border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow); }}
    .card {{ padding: 20px; }}
    .card span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 750; letter-spacing: .07em; text-transform: uppercase; }}
    .card strong {{ display: block; margin: 6px 0 2px; font: 700 34px/1 Georgia, serif; }}
    .card small {{ color: var(--muted); }}
    section {{ margin-top: 20px; padding: 26px; overflow: hidden; }}
    .section-head {{ display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }}
    .section-head h2 {{ margin: 2px 0 0; font: 700 28px/1.1 Georgia, serif; }}
    .section-head p {{ max-width: 620px; margin: 0; color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }}
    table {{ width: 100%; min-width: 980px; border-collapse: collapse; }}
    th {{ padding: 11px 13px; background: #ecebe4; color: #58655f; font-size: 11px; letter-spacing: .08em; text-align: left; text-transform: uppercase; }}
    td {{ padding: 14px 13px; border-top: 1px solid var(--line); vertical-align: top; }}
    td strong, td span, td small {{ display: block; }}
    td span, td small {{ margin-top: 3px; color: var(--muted); font-size: 12px; }}
    .mono {{ font-variant-numeric: tabular-nums; }}
    .status {{ width: fit-content; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }}
    .status-inside_range {{ color: var(--green); background: var(--green-soft); }}
    .status-above_range {{ color: var(--red); background: var(--red-soft); }}
    .status-below_range {{ color: var(--amber); background: var(--amber-soft); }}
    .evidence {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .evidence div {{ padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: #f7f6f0; }}
    .evidence span, .evidence strong, .evidence a, .evidence code {{ display: block; }}
    .evidence span {{ color: var(--muted); font-size: 12px; text-transform: capitalize; }}
    .evidence a {{ margin: 5px 0; color: var(--green); }}
    .evidence code {{ overflow-wrap: anywhere; color: var(--muted); font-size: 11px; }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 900px) {{ .cards {{ grid-template-columns: 1fr 1fr; }} .section-head, .evidence {{ display: block; }} .section-head p, .evidence div + div {{ margin-top: 12px; }} }}
    @media (max-width: 560px) {{ main {{ width: min(100% - 20px, 1440px); padding-top: 10px; }} header, section {{ border-radius: 14px; padding: 20px; }} .cards {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Reported guidance backtest · {_escape(case['period']['label'])}</div>
    <h1>{_escape(case['entity']['name'])}: actual results cleared {summary['above_range_count']} of {summary['metric_count']} guidance ranges.</h1>
    <p>This evidence-backed benchmark scores management's pre-period-end guidance against the later reported quarter, preserving basis, units, source dates, and normalized source hashes.</p>
    <div class="warning"><strong>Boundary:</strong> reconstructed external benchmark, not a native model forecast. The source guidance was public before the outcome, but this normalized artifact was captured afterward and is never eligible for model calibration.</div>
  </header>

  <div class="cards">
    <article class="card"><span>Metrics scored</span><strong>{summary['metric_count']}</strong><small>same entity and fiscal period</small></article>
    <article class="card"><span>Inside range</span><strong>{_percentage(summary['inside_guidance_range_rate'])}</strong><small>{summary['inside_guidance_range_count']} reported outcomes</small></article>
    <article class="card"><span>Largest midpoint surprise</span><strong>{_percentage(largest_surprise)}</strong><small>{_escape(largest['label'])}</small></article>
    <article class="card"><span>Calibration eligibility</span><strong>None</strong><small>external reconstruction</small></article>
  </div>

  <section>
    <div class="section-head"><div><div class="eyebrow">Guidance versus reported result</div><h2>Range misses stay descriptive</h2></div><p>Management ranges are not probability quantiles. The benchmark reports coverage and midpoint error without inventing P10/P90, pinball, or Brier scores.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Metric</th><th>Guidance</th><th>Actual</th><th>Midpoint surprise</th><th>Result</th></tr></thead><tbody>{_score_rows(result)}</tbody></table></div>
  </section>

  <section>
    <div class="section-head"><div><div class="eyebrow">Frozen source lineage</div><h2>Two observations, one dependent source family</h2></div><p>The guidance and outcome are both Micron disclosures. Their dates establish order, but they do not provide independent confirmation.</p></div>
    <div class="evidence">{_evidence_rows(result)}</div>
  </section>
  <footer>Recorded {_escape(case['recorded_at'])}. This dashboard is a historical evidence benchmark, not an investment recommendation or evidence of native model skill.</footer>
</main>
</body>
</html>
"""
