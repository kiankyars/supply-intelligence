"""Standalone manufacturing evidence-coverage dashboard."""

from __future__ import annotations

import html
import json
from typing import Any


STATUS_LABELS = {
    "eligible_claim_candidate": "Eligible claim candidate",
    "scope_rejected_claim": "Scope-rejected claim",
    "rejected_claim": "Rejected claim",
    "no_constraint_claim": "No constraint claim",
    "constraint_eligible": "Constraint eligible",
    "scale_control": "Scale control",
    "directional_signal": "Directional signal",
    "rejected": "Rejected",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:,.3g}"


def _status(value: str) -> str:
    label = STATUS_LABELS.get(value, value.replace("_", " ").title())
    return f'<span class="status status-{_escape(value)}">{_escape(label)}</span>'


def _input_rows(document: dict[str, Any]) -> str:
    rows = []
    for item in document["inputs"]:
        assessment_text = "None"
        if item["assessment_ids"]:
            assessment_text = ", ".join(item["assessment_ids"])
        blockers = ", ".join(item["blocking_codes"]) or "—"
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['input_path'])}</strong><span>{_escape(item['owner_type'])} · {_escape(item['owner_id'])}</span></td>
              <td>{_status(item['input_status'])}<span>{_escape(assessment_text)}</span></td>
              <td class="mono"><strong>{item['research_priority']:.3f}</strong><span>{_percentage(item['influence_probability'])} modeled influence</span></td>
              <td class="mono">{_number(item['low'])} / <strong>{_number(item['base'])}</strong> / {_number(item['high'])}<span>{_escape(item['unit'])}</span></td>
              <td><span>{_escape(blockers)}</span><small>{_escape(item['confirming_evidence'])}</small></td>
            </tr>
            """
        )
    return "".join(rows)


def _assessment_rows(document: dict[str, Any]) -> str:
    rows = []
    for item in document["assessments"]:
        claim_value = json.dumps(
            item["claim_value"], sort_keys=True, ensure_ascii=False
        )
        blockers = ", ".join(item["blocking_codes"]) or "None"
        rationale = item["nonbinding_rationale"] or blockers
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['id'])}</strong><span>{_escape(item['claim_key'])}</span></td>
              <td>{_status(item['assessment_status'])}<span>{_escape(item['usage'])}</span></td>
              <td><strong>{_escape(claim_value)}</strong><span>{_escape(item['claim_unit'])}</span></td>
              <td><strong>{_escape(item['claim_stage'])}</strong><span>{_escape(item['claim_period'])} · {_escape(item['claim_product'])}</span></td>
              <td><span>{_escape(rationale)}</span><small>Target: {_escape(item['target_input_path'])}</small></td>
            </tr>
            """
        )
    return "".join(rows)


def render_manufacturing_evidence_dashboard(document: dict[str, Any]) -> str:
    summary = document["summary"]
    source = document["lineage"]["manufacturing_release"]
    eligible = summary["eligible_claim_candidate_inputs"]
    total = summary["synthetic_inputs"]
    headline = (
        f"{eligible} of {total} synthetic inputs have a gate-passing constraint claim; "
        "zero replacements were applied."
    )
    priority_coverage = summary["eligible_research_priority_share"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(document['id'])}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #14231d;
      --muted: #607069;
      --paper: #f4f2ea;
      --card: #fffdf8;
      --line: #d8d7ce;
      --green: #0f6b4b;
      --green-soft: #dceee5;
      --amber: #98600a;
      --amber-soft: #f7e9c6;
      --red: #a13d33;
      --red-soft: #f5ddd9;
      --slate-soft: #e7ebe8;
      --shadow: 0 18px 50px rgba(20, 35, 29, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(1500px, calc(100% - 40px)); margin: 0 auto; padding: 42px 0 72px; }}
    header {{ background: var(--ink); color: #fffdf8; border-radius: 24px; padding: 36px; box-shadow: var(--shadow); }}
    .eyebrow {{ color: #a7d5c2; font-size: 12px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }}
    h1 {{ max-width: 980px; margin: 10px 0 12px; font: 700 clamp(32px, 5vw, 60px)/1.02 Georgia, serif; letter-spacing: -.035em; }}
    header p {{ max-width: 920px; margin: 0; color: #d4ddd8; font-size: 17px; }}
    .warning {{ margin-top: 22px; padding: 14px 16px; border: 1px solid #6c756f; border-radius: 14px; color: #fff4cf; background: rgba(255, 255, 255, .04); }}
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
    .progress {{ height: 14px; overflow: hidden; border-radius: 999px; background: #e2e3dd; }}
    .progress i {{ display: block; height: 100%; width: {priority_coverage * 100:.4f}%; background: var(--green); }}
    .progress-note {{ display: flex; justify-content: space-between; margin-top: 7px; color: var(--muted); font-size: 13px; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }}
    table {{ width: 100%; min-width: 1050px; border-collapse: collapse; }}
    th {{ padding: 11px 13px; background: #ecebe4; color: #58665f; font-size: 11px; letter-spacing: .08em; text-align: left; text-transform: uppercase; }}
    td {{ padding: 13px; border-top: 1px solid var(--line); vertical-align: top; }}
    td strong, td span, td small {{ display: block; }}
    td span, td small {{ margin-top: 3px; color: var(--muted); font-size: 12px; }}
    td small {{ max-width: 420px; }}
    .mono {{ font-variant-numeric: tabular-nums; }}
    .status {{ display: inline-block; width: fit-content; margin: 0 0 3px; padding: 4px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; letter-spacing: .02em; }}
    .status-constraint_eligible, .status-eligible_claim_candidate {{ color: var(--green); background: var(--green-soft); }}
    .status-scale_control, .status-directional_signal {{ color: var(--amber); background: var(--amber-soft); }}
    .status-rejected, .status-scope_rejected_claim, .status-rejected_claim {{ color: var(--red); background: var(--red-soft); }}
    .status-no_constraint_claim {{ color: #56635d; background: var(--slate-soft); }}
    .lineage {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
    .lineage div {{ padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: #f7f6f0; }}
    .lineage span {{ display: block; color: var(--muted); font-size: 12px; }}
    .lineage code {{ overflow-wrap: anywhere; font-size: 12px; }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 950px) {{ .cards {{ grid-template-columns: 1fr 1fr; }} .section-head, .lineage {{ display: block; }} .section-head p, .lineage div + div {{ margin-top: 12px; }} }}
    @media (max-width: 560px) {{ main {{ width: min(100% - 20px, 1500px); padding-top: 10px; }} header, section {{ border-radius: 14px; padding: 20px; }} .cards {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">Manufacturing evidence coverage · {_escape(document['as_of_date'])}</div>
    <h1>{_escape(headline)}</h1>
    <p>This release joins a frozen manufacturing research queue to claim-level scope decisions. Accepted directional evidence informs what to investigate; it does not become throughput.</p>
    <div class="warning"><strong>Boundary:</strong> the source manufacturing run remains entirely synthetic. A gate decision does not mutate its inputs, and no public claim in this release qualifies as Blackwell quarterly capacity.</div>
  </header>

  <div class="cards">
    <article class="card"><span>Synthetic inputs</span><strong>{total}</strong><small>All remain unreplaced</small></article>
    <article class="card"><span>Eligible claim candidates</span><strong>{eligible}</strong><small>{_percentage(priority_coverage)} of research priority</small></article>
    <article class="card"><span>Scope-rejected inputs</span><strong>{summary['scope_rejected_inputs']}</strong><small>Claim found, target mismatch</small></article>
    <article class="card"><span>Nonbinding evidence</span><strong>{summary['accepted_directional_signals'] + summary['accepted_scale_controls']}</strong><small>{summary['accepted_directional_signals']} signals · {summary['accepted_scale_controls']} scale control</small></article>
  </div>

  <section>
    <div class="section-head"><div><div class="eyebrow">Coverage weighted by modeled influence</div><h2>Gate-passing evidence still covers {_percentage(priority_coverage)}</h2></div><p>Research priority equals the current branch influence multiplied by evidence weakness. It is a sourcing order, not a causal sensitivity estimate.</p></div>
    <div class="progress" role="img" aria-label="Eligible claim candidates cover {_percentage(priority_coverage)} of research priority"><i></i></div>
    <div class="progress-note"><span>0%</span><span>{_percentage(priority_coverage)} eligible</span><span>100%</span></div>
  </section>

  <section>
    <div class="section-head"><div><div class="eyebrow">Constraint-input audit</div><h2>Source the assumptions that can move output first</h2></div><p>Every row preserves its low/base/high range, current-run influence, confirmation test, and any claim-gate blockers.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Input</th><th>Evidence status</th><th>Priority</th><th>Source range</th><th>What is missing</th></tr></thead><tbody>{_input_rows(document)}</tbody></table></div>
  </section>

  <section>
    <div class="section-head"><div><div class="eyebrow">Claim-level decisions</div><h2>Signals stay separate from capacity</h2></div><p>Each assessment pins a ledger revision and snapshot. Nonbinding claims can sharpen research without changing the production estimate.</p></div>
    <div class="table-wrap"><table><thead><tr><th>Assessment</th><th>Decision</th><th>Claim value</th><th>Claim scope</th><th>Boundary</th></tr></thead><tbody>{_assessment_rows(document)}</tbody></table></div>
  </section>

  <section>
    <div class="section-head"><div><div class="eyebrow">Frozen lineage</div><h2>Reproduce the exact evidence view</h2></div><p>The release includes the source research queue, claim snapshots, selections, assessments, and hashes.</p></div>
    <div class="lineage">
      <div><span>Manufacturing release</span><code>{_escape(source['path'])}</code></div>
      <div><span>Manufacturing manifest SHA-256</span><code>{_escape(source['manifest_sha256'])}</code></div>
      <div><span>Scenario</span><code>{_escape(source['scenario_id'])} · {_escape(source['quarter'])}</code></div>
      <div><span>Coverage recipe SHA-256</span><code>{_escape(document['lineage']['recipe']['sha256'])}</code></div>
    </div>
  </section>
  <footer>Recorded {_escape(document['recorded_at'])}. This dashboard is an evidence audit, not an estimate of actual Blackwell output or an investment recommendation.</footer>
</main>
</body>
</html>
"""
