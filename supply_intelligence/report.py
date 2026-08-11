"""Standalone audit dashboard rendering."""

from __future__ import annotations

import html
import json
import re
from typing import Any


STAGE_LABELS = {
    "accelerator_package": "Packages",
    "server_assembly": "Servers",
    "rack_integration": "Racks",
    "shipped": "Shipped",
    "installed": "Installed",
    "operational": "Operational",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value)


def _number(value: float, digits: int = 0) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _usd(value: float) -> str:
    return f"${_number(value, 1)}"


def _interval(distribution: dict[str, float], unit: str = "") -> str:
    suffix = f" {unit}" if unit else ""
    return (
        f"{_number(distribution['p10'], 1)} / "
        f"{_number(distribution['p50'], 1)} / "
        f"{_number(distribution['p90'], 1)}{suffix}"
    )


def _metric(label: str, distribution: dict[str, float], unit: str) -> str:
    return f"""
      <article class="metric">
        <p>{_escape(label)}</p>
        <strong>{_number(distribution['p50'], 0)}</strong>
        <span>P10–P90 {_number(distribution['p10'], 0)}–{_number(distribution['p90'], 0)} {_escape(unit)}</span>
      </article>
    """


def _stage_rows(result: dict[str, Any]) -> str:
    rows = result["stage_outputs"]
    maximum = max(row["system_equivalents"]["p90"] for row in rows) or 1
    rendered = []
    for row in rows:
        distribution = row["system_equivalents"]
        width = max(1.5, distribution["p50"] / maximum * 100)
        uncertainty_left = distribution["p10"] / maximum * 100
        uncertainty_width = max(
            0.5, (distribution["p90"] - distribution["p10"]) / maximum * 100
        )
        rendered.append(
            f"""
            <div class="stage-row">
              <div class="stage-label">
                <span>{_escape(STAGE_LABELS[row['stage']])}</span>
                <strong>{_number(distribution['p50'], 0)}</strong>
              </div>
              <div class="track" aria-label="{_escape(STAGE_LABELS[row['stage']])}: {_interval(distribution, row['unit'])}">
                <span class="uncertainty" style="left:{uncertainty_left:.3f}%;width:{uncertainty_width:.3f}%"></span>
                <span class="bar" style="width:{width:.3f}%"></span>
              </div>
              <span class="range">P10–P90 {_number(distribution['p10'], 0)}–{_number(distribution['p90'], 0)}</span>
            </div>
            """
        )
    return "".join(rendered)


def _allocation_rows(result: dict[str, Any]) -> str:
    rows = result["customer_allocations"]
    if not rows:
        return '<p class="empty">No customer allocation rules in this scenario.</p>'
    maximum = max(row["systems_shipped"]["p90"] for row in rows) or 1
    rendered = []
    for row in rows:
        distribution = row["systems_shipped"]
        width = max(0, distribution["p50"] / maximum * 100)
        rendered.append(
            f"""
            <div class="allocation-row">
              <div><strong>{_escape(row['customer'])}</strong><span>{_escape(row['category'])}</span></div>
              <div class="track"><span class="bar secondary" style="width:{width:.3f}%"></span></div>
              <div class="numeric">{_number(distribution['p50'], 0)}<span>{_number(distribution['p10'], 0)}–{_number(distribution['p90'], 0)}</span></div>
            </div>
            """
        )
    return "".join(rendered)


def _constraint_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in sorted(
        result["constraints"],
        key=lambda row: (
            -row["bottleneck_probability"].get("operational", 0),
            row["resource_name"],
        ),
    ):
        probability = item["bottleneck_probability"].get("operational", 0)
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['resource_name'])}</strong><span>{_escape(item['resource_kind'])}</span></td>
              <td>{_escape(STAGE_LABELS[item['stage']])}</td>
              <td class="mono">{_interval(item['equivalent_system_capacity'])}</td>
              <td class="mono">{item['utilization']['p50'] * 100:.1f}%</td>
              <td class="mono">{probability * 100:.1f}%</td>
            </tr>
            """
        )
    return "".join(rows)


def _supplier_rows(result: dict[str, Any]) -> str:
    if not result["supplier_estimates"]:
        return '<tr><td colspan="5" class="empty">No supplier economics in this scenario.</td></tr>'
    rows = []
    for item in result["supplier_estimates"]:
        consensus = item.get("consensus_revenue_usd")
        revision = item.get("expected_revenue_revision_pct")
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['ticker'])}</strong><span>{_escape(item['supplier'])}</span></td>
              <td class="mono">{_usd(item['bottom_up_revenue_usd']['p50'])}</td>
              <td class="mono">{_usd(item['bottom_up_gross_profit_usd']['p50'])}</td>
              <td class="mono">{_usd(consensus['p50']) if consensus else 'N/A'}</td>
              <td class="mono {'positive' if revision and revision['p50'] >= 0 else 'negative'}">{f"{revision['p50']:+.1f}%" if revision else 'N/A'}</td>
            </tr>
            """
        )
    return "".join(rows)


def _opportunity_rows(result: dict[str, Any]) -> str:
    if not result["opportunity_candidates"]:
        return '<tr><td colspan="7" class="empty">No consensus-linked research candidates in this scenario.</td></tr>'
    rows = []
    for item in result["opportunity_candidates"]:
        rows.append(
            f"""
            <tr>
              <td class="mono">#{item['rank']}</td>
              <td><strong>{_escape(item['ticker'])}</strong><span>{_escape(item['supplier'])}</span></td>
              <td>{_escape(item['direction'].replace('_', ' '))}<span>{_escape(item['status'].replace('_', ' '))}</span></td>
              <td class="mono {'positive' if item['expected_revenue_revision_pct']['p50'] >= 0 else 'negative'}">{item['expected_revenue_revision_pct']['p50']:+.1f}%</td>
              <td class="mono">{item['screen_score']['p50']:.3f}</td>
              <td>{_escape(item['catalyst'])}</td>
              <td>{_escape(item['first_rejection'])}</td>
            </tr>
            """
        )
    return "".join(rows)


def _opportunity_cards(result: dict[str, Any]) -> str:
    cards = []
    for item in result["opportunity_candidates"][:3]:
        fields = (
            ("Actionability", item["actionability"]),
            ("Variant wedge", item["variant_wedge"]),
            ("What is priced in", item["what_is_priced_in"]),
            ("Why now", item["why_now"]),
            ("First rejection", item["first_rejection"]),
            ("What would make it investable", item["investable_if"]),
            ("What would kill it", item["thesis_kill"]),
            ("Next research step", item["next_workflow"]),
        )
        details = "".join(
            f"<div><strong>{_escape(label)}</strong><p>{_escape(value)}</p></div>"
            for label, value in fields
        )
        cards.append(
            f"""
            <article class="candidate-card">
              <div class="candidate-head">
                <div><span class="section-label">#{item['rank']} · {_escape(item['status'].replace('_', ' '))}</span><h3>{_escape(item['ticker'])} · {_escape(item['supplier'])}</h3></div>
                <div class="candidate-revision"><strong>{item['expected_revenue_revision_pct']['p50']:+.1f}%</strong><span>modeled revision</span></div>
              </div>
              <div class="candidate-grid">{details}</div>
            </article>
            """
        )
    return "".join(cards)


def _source_ledger(result: dict[str, Any]) -> str:
    rows = []
    for item in result["evidence"]:
        source_id = _safe_id(item["id"])
        published = item["published_at"] or "Not supplied"
        rows.append(
            f"""
            <tr id="source-{source_id}">
              <td class="mono">{_escape(item['id'])}</td>
              <td><a href="{_escape(item['source_url'])}" target="_blank" rel="noreferrer">{_escape(item['title'])}</a><span>{_escape(item['publisher'])}</span></td>
              <td>{_escape(item['kind'])}</td>
              <td class="mono">{_escape(published)}</td>
              <td class="mono">{_escape(item['retrieved_at'])}</td>
            </tr>
            """
        )
    return "".join(rows)


def _estimate_audit(label: str, estimate: dict[str, Any]) -> str:
    sources = " ".join(
        f'<a class="source-ref" href="#source-{_safe_id(source_id)}">{_escape(source_id)}</a>'
        for source_id in estimate["evidence_ids"]
    )
    return f"""
      <div class="estimate-audit">
        <div><strong>{_escape(label)}</strong><span>{_escape(estimate['posture'])} · confidence {estimate['confidence']:.0%}</span></div>
        <div class="mono">{_number(estimate['low'], 2)} / {_number(estimate['base'], 2)} / {_number(estimate['high'], 2)} {_escape(estimate['unit'])}</div>
        <p><b>Method:</b> {_escape(estimate['methodology'])}</p>
        <p><b>Updated:</b> {_escape(estimate['last_updated'])} · <b>Sources:</b> {sources}</p>
        <p><b>Confirms:</b> {_escape(estimate['confirming_evidence'])}</p>
        <p><b>Falsifies:</b> {_escape(estimate['falsifying_evidence'])}</p>
      </div>
    """


def _input_audit(result: dict[str, Any]) -> str:
    rows = []
    for constraint in result["inputs"]["constraints"]:
        details = "".join(
            _estimate_audit(label, constraint[key])
            for label, key in (
                ("Nominal capacity", "capacity"),
                ("Effective yield", "effective_yield"),
                ("Platform allocation", "platform_allocation"),
                ("BOM requirement", "units_per_system"),
            )
        )
        rows.append(
            f"""
            <details>
              <summary><strong>{_escape(constraint['resource_name'])}</strong><span>{_escape(STAGE_LABELS[constraint['stage']])} · {_escape(constraint['capacity_basis'])}</span></summary>
              <div class="audit-grid">{details}</div>
            </details>
            """
        )
    return "".join(rows)


def render_dashboard(result: dict[str, Any]) -> str:
    operational = result["physical_outputs"]["systems_operational"]
    shipped = result["physical_outputs"]["systems_shipped"]
    packages = result["physical_outputs"]["accelerator_packages_produced"]
    stage_options = "".join(
        f'<option value="{_escape(item["stage"])}" {"selected" if item["stage"] == "operational" else ""}>{_escape(STAGE_LABELS[item["stage"]])}</option>'
        for item in result["bottlenecks"]
    )
    bottleneck_json = json.dumps(
        {item["stage"]: item["constraints"] for item in result["bottlenecks"]},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in result["warnings"])
    caveat_class = "synthetic" if result["scenario"]["synthetic"] else "live"
    caveat_title = "Illustrative scenario" if result["scenario"]["synthetic"] else "Evidence-backed scenario"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(result['platform']['name'])} supply reconciliation</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f3f0e9;
      --paper: #fbfaf6;
      --ink: #171a18;
      --muted: #626760;
      --line: #d8d4ca;
      --accent: #006b5c;
      --accent-soft: #cfe5df;
      --secondary: #b45b31;
      --warning: #8a4c12;
      --warning-bg: #fff0d8;
      --warning-border: #e6c38f;
      --live-border: #9fc8bd;
      --track: #e5e1d8;
      --audit-bg: rgba(255,255,255,.38);
      --positive: #08755e;
      --negative: #a33e32;
      --shadow: 0 12px 40px rgba(33, 40, 35, .08);
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #151916;
        --paper: #202622;
        --ink: #f0f2ed;
        --muted: #aab2ab;
        --line: #3b453e;
        --accent: #68c8b5;
        --accent-soft: #294b43;
        --secondary: #e39a71;
        --warning: #ffd29a;
        --warning-bg: #3a2c1d;
        --warning-border: #6c5131;
        --live-border: #3f7167;
        --track: #303832;
        --audit-bg: rgba(255,255,255,.025);
        --positive: #70d2bc;
        --negative: #f39a8e;
        --shadow: none;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    a {{ color: var(--accent); }}
    header, main {{ width: min(1440px, calc(100% - 40px)); margin-inline: auto; }}
    header {{ padding: 34px 0 22px; display: flex; justify-content: space-between; gap: 24px; align-items: end; border-bottom: 1px solid var(--line); }}
    .eyebrow, .section-label {{ color: var(--accent); font: 700 11px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; text-transform: uppercase; }}
    h1 {{ max-width: 850px; margin: 8px 0 5px; font-family: Georgia, "Times New Roman", serif; font-size: clamp(32px, 5vw, 62px); line-height: .98; letter-spacing: -.035em; font-weight: 500; }}
    header p {{ color: var(--muted); margin: 0; }}
    .stamp {{ text-align: right; min-width: 170px; }}
    .stamp strong, .stamp span {{ display: block; }}
    .stamp strong {{ font-size: 20px; }}
    .stamp span {{ color: var(--muted); }}
    main {{ padding: 24px 0 72px; }}
    .notice {{ background: var(--warning-bg); border: 1px solid var(--warning-border); padding: 14px 16px; display: grid; grid-template-columns: minmax(130px, .22fr) 1fr; gap: 20px; margin-bottom: 22px; }}
    .notice.live {{ background: var(--accent-soft); border-color: var(--live-border); }}
    .notice strong {{ color: var(--warning); }}
    .notice.live strong {{ color: var(--accent); }}
    .notice ul {{ margin: 0; padding-left: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 28px; }}
    .metric {{ background: var(--paper); border: 1px solid var(--line); padding: 18px; box-shadow: var(--shadow); }}
    .metric p, .metric span {{ color: var(--muted); margin: 0; }}
    .metric strong {{ display: block; margin: 6px 0 2px; font: 500 clamp(30px, 5vw, 48px)/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -.05em; }}
    .layout {{ display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(330px, .65fr); gap: 22px; margin-bottom: 34px; }}
    section {{ min-width: 0; }}
    .panel {{ background: var(--paper); border: 1px solid var(--line); padding: 20px; }}
    .panel h2, .section-head h2 {{ font: 500 24px/1.1 Georgia, "Times New Roman", serif; margin: 5px 0 4px; }}
    .panel > p, .section-head p {{ margin: 0 0 18px; color: var(--muted); }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 24px; margin: 34px 0 12px; }}
    .stage-row {{ display: grid; grid-template-columns: 125px minmax(140px, 1fr) 120px; gap: 12px; align-items: center; margin: 15px 0; }}
    .stage-label {{ display: flex; justify-content: space-between; gap: 8px; }}
    .stage-label strong, .numeric, .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-variant-numeric: tabular-nums; }}
    .track {{ position: relative; height: 13px; background: var(--track); overflow: hidden; }}
    .bar, .uncertainty {{ position: absolute; inset-block: 0; left: 0; }}
    .bar {{ background: var(--accent); z-index: 2; }}
    .bar.secondary {{ background: var(--secondary); }}
    .uncertainty {{ background: var(--accent-soft); z-index: 1; }}
    .range {{ color: var(--muted); text-align: right; font-size: 12px; }}
    label {{ display: block; color: var(--muted); margin-bottom: 6px; }}
    select {{ width: 100%; border: 1px solid var(--line); background: var(--paper); color: var(--ink); padding: 9px 10px; font: inherit; }}
    #bottleneck-chart {{ margin-top: 18px; }}
    .bottleneck-row {{ display: grid; grid-template-columns: minmax(130px, 1fr) 2fr 56px; gap: 10px; align-items: center; margin: 12px 0; }}
    .bottleneck-row .label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .allocation-row {{ display: grid; grid-template-columns: minmax(170px, .7fr) 1fr 90px; gap: 12px; align-items: center; margin: 13px 0; }}
    .allocation-row div:first-child span, td span, summary span, .estimate-audit span {{ display: block; color: var(--muted); font-size: 12px; }}
    .numeric {{ text-align: right; }}
    .numeric span {{ display: block; color: var(--muted); font: 12px/1.2 ui-sans-serif, system-ui, sans-serif; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); background: var(--paper); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 760px; }}
    th {{ text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    .positive {{ color: var(--positive); }}
    .negative {{ color: var(--negative); }}
    .empty {{ color: var(--muted); padding: 20px; }}
    .candidate-card {{ margin-top: 14px; background: var(--paper); border: 1px solid var(--line); padding: 20px; }}
    .candidate-head {{ display: flex; justify-content: space-between; gap: 20px; align-items: start; padding-bottom: 14px; border-bottom: 1px solid var(--line); }}
    .candidate-head h3 {{ font: 500 23px/1.1 Georgia, "Times New Roman", serif; margin: 5px 0 0; }}
    .candidate-revision {{ text-align: right; }}
    .candidate-revision strong, .candidate-revision span {{ display: block; }}
    .candidate-revision strong {{ font: 500 26px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .candidate-revision span {{ color: var(--muted); font-size: 12px; }}
    .candidate-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; padding-top: 16px; }}
    .candidate-grid strong {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .candidate-grid p {{ margin: 3px 0 0; color: var(--muted); }}
    details {{ border-top: 1px solid var(--line); background: var(--paper); }}
    details:last-child {{ border-bottom: 1px solid var(--line); }}
    summary {{ cursor: pointer; padding: 15px 4px; display: flex; justify-content: space-between; gap: 14px; }}
    .audit-grid {{ min-width: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 0 0 16px; }}
    .estimate-audit {{ min-width: 0; overflow-wrap: anywhere; border-left: 3px solid var(--accent-soft); padding: 10px 12px; background: var(--audit-bg); }}
    .estimate-audit > div:first-child {{ min-width: 0; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; }}
    .estimate-audit p {{ margin: 7px 0 0; color: var(--muted); font-size: 12px; }}
    .estimate-audit b {{ color: var(--ink); }}
    .source-ref {{ display: inline-block; max-width: 100%; margin-right: 5px; overflow-wrap: anywhere; }}
    footer {{ margin-top: 40px; border-top: 1px solid var(--line); padding-top: 18px; color: var(--muted); }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .audit-grid {{ grid-template-columns: 1fr; }}
      .candidate-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 640px) {{
      header, main {{ width: min(100% - 24px, 1440px); }}
      header, .section-head {{ display: block; }}
      .stamp {{ text-align: left; margin-top: 16px; }}
      .metrics {{ grid-template-columns: 1fr; }}
      .notice {{ grid-template-columns: 1fr; gap: 6px; }}
      .stage-row {{ grid-template-columns: 100px 1fr; }}
      .stage-row .range {{ grid-column: 2; text-align: left; }}
      .allocation-row {{ grid-template-columns: 1fr 70px; }}
      .allocation-row .track {{ grid-column: 1 / -1; grid-row: 2; }}
      .bottleneck-row {{ grid-template-columns: minmax(100px, 1fr) 1.4fr 50px; }}
      .candidate-head {{ display: block; }}
      .candidate-revision {{ text-align: left; margin-top: 12px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <div class="eyebrow">AI supply intelligence · {_escape(result['scenario']['quarter'])}</div>
      <h1>{_escape(result['platform']['name'])}</h1>
      <p>Complete-system output reconciled to the minimum feasible supply-chain constraint.</p>
    </div>
    <div class="stamp"><span>As of</span><strong>{_escape(result['scenario']['as_of_date'])}</strong><span>{result['scenario']['samples']:,} draws · seed {result['scenario']['seed']}</span></div>
  </header>
  <main>
    <aside class="notice {caveat_class}">
      <strong>{_escape(caveat_title)}</strong>
      <ul>{warnings}</ul>
    </aside>

    <div class="metrics">
      {_metric('Accelerator packages produced', packages, 'packages')}
      {_metric('Complete systems shipped', shipped, result['platform']['system_unit'])}
      {_metric('Systems operational', operational, result['platform']['system_unit'])}
    </div>

    <div class="layout">
      <section class="panel">
        <div class="section-label">Stage attrition</div>
        <h2>From packages to commissioned systems</h2>
        <p>Bars show median system-equivalent output; the pale interval is P10–P90.</p>
        {_stage_rows(result)}
      </section>
      <section class="panel">
        <div class="section-label">Constraint risk</div>
        <h2>Bottleneck probability</h2>
        <p>Probability that each resource is the binding constraint in a Monte Carlo draw.</p>
        <label for="bottleneck-stage">Production stage</label>
        <select id="bottleneck-stage">{stage_options}</select>
        <div id="bottleneck-chart" aria-live="polite"></div>
      </section>
    </div>

    <section>
      <div class="section-head"><div><div class="section-label">Customer allocation</div><h2>Who receives shipped systems</h2></div><p>Sampled share with demand caps and proportional redistribution.</p></div>
      <div class="panel">{_allocation_rows(result)}</div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Chain audit</div><h2>Constraint capacity, utilization, and risk</h2></div><p>Capacity values are P10 / P50 / P90 system equivalents.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Resource</th><th>First required</th><th>System capacity</th><th>Median utilization</th><th>Operational bottleneck</th></tr></thead><tbody>{_constraint_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Supplier read-through</div><h2>Bottom-up economics versus consensus</h2></div><p>Illustrative unless the underlying inputs are explicitly non-synthetic.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Supplier</th><th>Bottom-up revenue</th><th>Gross profit</th><th>Consensus revenue</th><th>Revision</th></tr></thead><tbody>{_supplier_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Research queue</div><h2>Consensus-discrepancy candidates</h2></div><p>Research prioritization. This table does not recommend or approve a position.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Security</th><th>Direction</th><th>Revision</th><th>Score</th><th>Catalyst</th><th>First rejection</th></tr></thead><tbody>{_opportunity_rows(result)}</tbody></table></div>
      {_opportunity_cards(result)}
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Input ledger</div><h2>Methods, ranges, provenance, and falsifiers</h2></div><p>Open a resource to inspect every numeric input used in reconciliation.</p></div>
      {_input_audit(result)}
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Source ledger</div><h2>Evidence used by this run</h2></div><p>Direct links, publication posture, and retrieval timestamps.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Evidence ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_source_ledger(result)}</tbody></table></div>
    </section>

    <footer>
      <strong>Method:</strong> {_escape(result['methodology']['constraint_reconciliation'])}
      {_escape(result['methodology']['bottleneck_probability'])}
    </footer>
  </main>
  <script>
    const bottlenecks = {bottleneck_json};
    const stageSelect = document.getElementById('bottleneck-stage');
    const chart = document.getElementById('bottleneck-chart');
    function renderBottlenecks() {{
      const rows = (bottlenecks[stageSelect.value] || []).filter(row => row.probability > 0.0001).slice(0, 10);
      if (!rows.length) {{ chart.innerHTML = '<p class="empty">No probabilistic bottleneck in this stage.</p>'; return; }}
      chart.innerHTML = rows.map(row => `
        <div class="bottleneck-row">
          <span class="label">${{escapeText(row.resource_name)}}</span>
          <div class="track"><span class="bar" style="width:${{(row.probability * 100).toFixed(3)}}%"></span></div>
          <strong class="mono">${{(row.probability * 100).toFixed(1)}}%</strong>
        </div>`).join('');
    }}
    function escapeText(value) {{
      const element = document.createElement('span');
      element.textContent = value;
      return element.innerHTML;
    }}
    stageSelect.addEventListener('change', renderBottlenecks);
    renderBottlenecks();
  </script>
</body>
</html>
"""
