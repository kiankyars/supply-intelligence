"""Standalone dashboard for gross-to-net power and commissioning reconciliation."""

from __future__ import annotations

import html
import re
from typing import Any

from .datacenter_operational_engine import OUTPUT_UNITS


OUTPUT_LABELS = {
    "gross_critical_it_power": "Gross critical IT envelope",
    "current_critical_it_load": "Current critical IT load",
    "contracted_reservations": "Contracted reservations",
    "other_platform_commitments": "Other platform commitments",
    "rack_incompatible_capacity": "Rack-incompatible capacity",
    "total_deductions": "Total explicit deductions",
    "net_uncommitted_compatible_power": "Net uncommitted compatible power",
    "other_unallocated_compatible_power": "Compatible power not allocated to target",
    "target_allocatable_power": "Target-platform allocatable power",
    "power_limited_racks": "Power-supported racks",
    "commissioning_slots": "Target-quarter commissioning slots",
    "commissioning_completed_capacity": "Completed commissioning capacity",
    "operational_racks": "Operational racks",
    "operational_rack_power": "Operational rack power",
    "shadow_allocatable_power": "Power held back by commissioning",
    "shadow_commissioning_capacity": "Commissioning held back by power",
    "oversubscribed_deductions": "Deductions above gross envelope",
    "gross_power_utilization": "Gross envelope used by target racks",
    "target_power_utilization": "Target allocatable power utilization",
    "commissioning_utilization": "Completed commissioning utilization",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value)


def _number(value: float, digits: int = 1) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _range(distribution: dict[str, float], digits: int = 1) -> str:
    return (
        f"{_number(distribution['p10'], digits)} to "
        f"{_number(distribution['p90'], digits)}"
    )


def _metric(result: dict[str, Any], key: str) -> dict[str, float]:
    return result["conversion_outputs"][key]


def _flow_node(
    result: dict[str, Any],
    key: str,
    *,
    deduction: bool = False,
    digits: int = 1,
) -> str:
    value = _metric(result, key)
    prefix = "−" if deduction else ""
    return f"""
      <article class="flow-node{' deduction' if deduction else ''}">
        <span>{_escape(OUTPUT_LABELS[key])}</span>
        <strong>{prefix}{_number(value['p50'], digits)}</strong>
        <small>{_escape(OUTPUT_UNITS[key])} · P10–P90 {_range(value, digits)}</small>
      </article>
    """


def _bottleneck_chart(result: dict[str, Any]) -> str:
    labels = {"power": "Allocatable power", "commissioning": "Commissioning"}
    rows = []
    for item in result["bottlenecks"]:
        probability = item["probability"]
        rows.append(
            f"""
            <div class="bar-row">
              <span>{_escape(labels[item['constraint']])}</span>
              <div class="bar-track"><i style="width:{probability * 100:.4f}%"></i></div>
              <strong>{probability * 100:.1f}%</strong>
            </div>
            """
        )
    return "".join(rows)


def _research_rows(result: dict[str, Any]) -> str:
    if not result["research_queue"]:
        return '<tr><td colspan="5">No synthetic operational inputs remain.</td></tr>'
    return "".join(
        f"""
        <tr>
          <td><strong>{_escape(item['parameter'])}</strong><span>{_escape(item['branch'])} branch</span></td>
          <td class="mono">{_number(item['low'], 2)} / {_number(item['base'], 2)} / {_number(item['high'], 2)} {_escape(item['unit'])}</td>
          <td class="mono">{item['influence_probability'] * 100:.1f}%</td>
          <td class="mono">{item['confidence'] * 100:.0f}%</td>
          <td class="mono"><strong>{item['research_priority']:.3f}</strong></td>
        </tr>
        """
        for item in result["research_queue"]
    )


def _source_rows(result: dict[str, Any]) -> str:
    return "".join(
        f"""
        <tr id="source-{_safe_id(item['id'])}">
          <td class="mono">{_escape(item['id'])}</td>
          <td><a href="{_escape(item['source_url'])}" target="_blank" rel="noreferrer">{_escape(item['title'])}</a><span>{_escape(item['publisher'])}</span></td>
          <td>{_escape(item['kind'])}</td>
          <td class="mono">{_escape(item['published_at'] or 'Not supplied')}</td>
          <td class="mono">{_escape(item['retrieved_at'])}</td>
        </tr>
        """
        for item in result["evidence"]
    )


def _audit_row(label: str, estimate: dict[str, Any]) -> str:
    sources = " ".join(
        f'<a href="#source-{_safe_id(source_id)}">{_escape(source_id)}</a>'
        for source_id in estimate["evidence_ids"]
    )
    return f"""
      <tr>
        <td><strong>{_escape(label)}</strong><span>{_escape(estimate['methodology'])}</span></td>
        <td class="mono">{_number(estimate['low'], 3)} / {_number(estimate['base'], 3)} / {_number(estimate['high'], 3)} {_escape(estimate['unit'])}</td>
        <td>{_escape(estimate['posture'])}<span>confidence {estimate['confidence']:.0%} · updated {_escape(estimate['last_updated'])}</span></td>
        <td>{sources}<span><b>Confirms:</b> {_escape(estimate['confirming_evidence'])}</span><span><b>Falsifies:</b> {_escape(estimate['falsifying_evidence'])}</span></td>
      </tr>
    """


def _input_audit(result: dict[str, Any]) -> str:
    inputs = result["inputs"]
    rows = [
        _audit_row("Gross critical IT envelope", inputs["gross_power"]["estimate"])
    ]
    deduction_labels = {
        "current_critical_it_load": "Current critical IT load",
        "contracted_reservations": "Contracted reservations",
        "other_platform_commitments": "Other platform commitments",
        "rack_incompatible_capacity": "Rack-incompatible capacity",
    }
    rows.extend(
        _audit_row(label, inputs["deductions"][key])
        for key, label in deduction_labels.items()
    )
    rows.extend(
        (
            _audit_row("Target-platform share", inputs["target_platform_share"]),
            _audit_row("Rack critical IT load", inputs["rack_it_load"]),
            _audit_row("Commissioning slots", inputs["commissioning_slots"]),
            _audit_row(
                "Commissioning completion ratio",
                inputs["commissioning_completion_ratio"],
            ),
        )
    )
    return "".join(rows)


def render_datacenter_operational_dashboard(result: dict[str, Any]) -> str:
    scenario = result["scenario"]
    net_power = _metric(result, "target_allocatable_power")
    operational = _metric(result, "operational_racks")
    shadow_power = _metric(result, "shadow_allocatable_power")
    shadow_commissioning = _metric(result, "shadow_commissioning_capacity")
    top = result["bottlenecks"][0]
    top_label = {
        "power": "Allocatable power",
        "commissioning": "Commissioning",
    }[top["constraint"]]
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in result["warnings"])
    posture = (
        "Illustrative operational run"
        if scenario["synthetic"]
        else "Evidence-backed operational run"
    )
    manifest_hash = result["inputs"]["gross_power"]["datacenter_manifest_sha256"]
    import_hash = result["inputs"]["gross_power"]["source_sha256"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{_escape(scenario['name'])}</title>
  <style>
    :root {{ color-scheme:light dark; --bg:#edf1ef; --paper:#fafcfb; --ink:#17201c; --muted:#5f6d66; --line:#cbd4cf; --soft:#e0e7e3; --teal:#006d67; --teal-soft:#cae7e1; --red:#a94e3d; --warning:#734918; --warning-bg:#fff0d3; }}
    @media (prefers-color-scheme:dark) {{ :root {{ --bg:#121816; --paper:#1d2522; --ink:#edf3f0; --muted:#a6b2ac; --line:#36423c; --soft:#2b3732; --teal:#67cfc4; --teal-soft:#274943; --red:#ed947f; --warning:#ffd299; --warning-bg:#3a2b1c; }} }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:var(--teal); overflow-wrap:anywhere; }}
    header,main {{ width:min(1380px,calc(100% - 40px)); margin-inline:auto; }}
    header {{ display:flex; justify-content:space-between; align-items:end; gap:28px; padding:34px 0 22px; border-bottom:1px solid var(--line); }}
    h1,h2,h3 {{ font-family:Georgia,"Times New Roman",serif; font-weight:500; }}
    h1 {{ margin:7px 0 5px; max-width:900px; font-size:clamp(34px,5vw,62px); line-height:.98; letter-spacing:-.035em; }}
    h2 {{ margin:4px 0 0; font-size:28px; }}
    h3 {{ margin:0; font-size:20px; }}
    p {{ margin:0; }}
    .kicker,.section-label {{ color:var(--teal); font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.09em; text-transform:uppercase; }}
    .muted,.section-head p,small,td span,.stamp span {{ color:var(--muted); }}
    .stamp {{ min-width:190px; text-align:right; }} .stamp strong,.stamp span {{ display:block; }} .stamp strong {{ font-size:20px; }}
    main {{ padding:24px 0 70px; }}
    .notice {{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:20px; padding:14px 16px; background:var(--warning-bg); border-left:4px solid var(--red); }}
    .notice strong {{ color:var(--warning); }} .notice ul {{ margin:0; padding-left:18px; }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin-top:20px; }}
    .summary-card,.flow-node,.panel {{ min-width:0; background:var(--paper); border:1px solid var(--line); padding:18px; }}
    .summary-card span,.summary-card small,.flow-node span,.flow-node small {{ display:block; color:var(--muted); }}
    .summary-card strong {{ display:block; margin:5px 0; font:500 36px/1.05 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:24px; margin:34px 0 12px; }}
    .section-head p {{ max-width:610px; text-align:right; }}
    .bridge {{ display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; }}
    .flow-node {{ position:relative; border-top:3px solid var(--teal); }}
    .flow-node.deduction {{ border-top-color:var(--red); }}
    .flow-node strong {{ display:block; margin:7px 0 4px; font:500 25px/1 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .flow-node:not(:last-child)::after {{ content:"→"; position:absolute; z-index:2; right:-9px; top:50%; color:var(--muted); transform:translate(50%,-50%); }}
    .convergence {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }}
    .convergence .flow-node:nth-child(3) {{ border-top-color:var(--ink); }}
    .two-column {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:22px; }}
    .bar-row {{ display:grid; grid-template-columns:minmax(150px,1fr) 1.7fr 60px; gap:10px; align-items:center; margin:14px 0; }}
    .bar-track {{ height:13px; background:var(--soft); overflow:hidden; }} .bar-track i {{ display:block; height:100%; background:var(--teal); }} .bar-row strong {{ text-align:right; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .shadow-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }} .shadow-grid strong {{ font-size:30px; }}
    .table-wrap {{ min-width:0; max-width:100%; overflow-x:auto; background:var(--paper); border:1px solid var(--line); }}
    table {{ width:100%; min-width:720px; border-collapse:collapse; }}
    th,td {{ padding:12px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }} tbody tr:last-child td {{ border-bottom:0; }}
    td span {{ display:block; max-width:680px; margin-top:4px; font-size:12px; }} .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums; }}
    details {{ border-block:1px solid var(--line); }} summary {{ display:flex; justify-content:space-between; gap:18px; padding:14px 5px; cursor:pointer; }} details .table-wrap {{ margin-bottom:14px; }} .audit-table {{ min-width:1000px; }}
    .lineage {{ overflow-wrap:anywhere; }} .lineage p + p {{ margin-top:8px; }}
    footer {{ margin-top:36px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media (max-width:1080px) {{ .bridge {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} .flow-node:nth-child(3)::after {{ content:none; }} }}
    @media (max-width:760px) {{ .summary-grid,.two-column,.shadow-grid {{ grid-template-columns:minmax(0,1fr); }} .section-head {{ display:block; }} .section-head p {{ margin-top:6px; text-align:left; }} }}
    @media (max-width:560px) {{ header,main {{ width:min(1380px,calc(100% - 24px)); }} header {{ display:block; }} .stamp {{ margin-top:16px; text-align:left; }} .notice {{ grid-template-columns:minmax(0,1fr); gap:5px; }} .bridge,.convergence {{ grid-template-columns:minmax(0,1fr); }} .flow-node:not(:last-child)::after,.flow-node:nth-child(3)::after {{ content:"↓"; top:auto; right:50%; bottom:-14px; transform:translate(50%,50%); }} .bar-row {{ grid-template-columns:minmax(0,1fr) 55px; }} .bar-track {{ grid-column:1/-1; grid-row:2; }} summary {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="kicker">Gross power to operational racks · {_escape(scenario['quarter'])}</div><h1>{_escape(scenario['name'])}</h1><p class="muted">{_escape(scenario['scope_description'])}</p></div>
    <div class="stamp"><span>As of</span><strong>{_escape(scenario['as_of_date'])}</strong><span>{scenario['samples']:,} draws · seed {scenario['seed']}</span></div>
  </header>
  <main>
    <aside class="notice"><strong>{_escape(posture)}</strong><ul>{warnings}</ul></aside>
    <section class="summary-grid" aria-label="Operational capacity summary">
      <article class="summary-card"><span>Target-platform allocatable power</span><strong>{_number(net_power['p50'])}</strong><small>MW · P10–P90 {_range(net_power)}</small></article>
      <article class="summary-card"><span>Operational racks in target quarter</span><strong>{_number(operational['p50'], 0)}</strong><small>racks · P10–P90 {_range(operational, 0)}</small></article>
      <article class="summary-card"><span>Most frequent constraint</span><strong>{top['probability'] * 100:.1f}%</strong><small>{_escape(top_label)}</small></article>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Gross-to-net bridge</div><h2>Every unavailable MW is removed before allocation</h2></div><p>The medians below are marginal summaries; they do not form a deterministic arithmetic bridge because each value is sampled jointly.</p></div>
      <div class="bridge">{_flow_node(result, 'gross_critical_it_power')}{_flow_node(result, 'current_critical_it_load', deduction=True)}{_flow_node(result, 'contracted_reservations', deduction=True)}{_flow_node(result, 'other_platform_commitments', deduction=True)}{_flow_node(result, 'rack_incompatible_capacity', deduction=True)}{_flow_node(result, 'net_uncommitted_compatible_power')}</div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Operational convergence</div><h2>Power support meets commissioning throughput</h2></div><p>The rack critical-IT input converts compatible MW to rack capacity before the target-quarter commissioning limit is applied.</p></div>
      <div class="convergence">{_flow_node(result, 'power_limited_racks', digits=0)}{_flow_node(result, 'commissioning_completed_capacity', digits=0)}{_flow_node(result, 'operational_racks', digits=0)}</div>
    </section>

    <section class="two-column">
      <div><div class="section-head"><div><div class="section-label">Constraint risk</div><h2>Binding probability</h2></div></div><div class="panel"><p class="muted">Share of draws in which each branch limits operational racks.</p>{_bottleneck_chart(result)}</div></div>
      <div><div class="section-head"><div><div class="section-label">Double-count guard</div><h2>Deduction contract</h2></div></div><div class="panel"><p>{_escape(result['diagnostics']['deduction_non_overlap_rationale'])}</p><p class="muted" style="margin-top:12px">Probability that sampled deductions consume the entire gross envelope: {result['diagnostics']['zero_residual_probability']:.1%}.</p></div></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Shadow capacity</div><h2>Identify what prevents available resources from operating</h2></div><p>Only one shadow metric is positive in a given draw: commissioning can strand power, or power can strand commissioning throughput.</p></div>
      <div class="shadow-grid">
        <article class="summary-card"><span>Allocatable power held back by commissioning</span><strong>{_number(shadow_power['p50'])}</strong><small>MW · P10–P90 {_range(shadow_power)}</small></article>
        <article class="summary-card"><span>Completed commissioning held back by power</span><strong>{_number(shadow_commissioning['p50'], 0)}</strong><small>racks · P10–P90 {_range(shadow_commissioning, 0)}</small></article>
      </div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Evidence replacement queue</div><h2>Source the assumptions on the binding branch first</h2></div><p>Priority equals current-run branch influence times one minus confidence. It is a triage score, not causal proof.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Synthetic input</th><th>Low / base / high</th><th>Influence</th><th>Confidence</th><th>Priority</th></tr></thead><tbody>{_research_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Input audit</div><h2>Ranges, methods, posture, and falsification</h2></div><p>The imported gross envelope remains blocked from direct use; only this explicit subtraction and commissioning model creates the illustrative operational output.</p></div>
      <details><summary><strong>Open all numerical assumptions</strong><span>9 estimates</span></summary><div class="table-wrap"><table class="audit-table"><thead><tr><th>Input and method</th><th>Low / base / high</th><th>Posture</th><th>Evidence and tests</th></tr></thead><tbody>{_input_audit(result)}</tbody></table></div></details>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Source ledger</div><h2>Evidence used by this run</h2></div><p>A rack-power record supports the MW conversion only. It does not support site load, reservations, allocation, compatibility, or commissioning.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Evidence ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_source_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Pinned lineage</div><h2>Gross envelope cannot drift silently</h2></div></div>
      <div class="panel lineage"><p><b>Gross import SHA-256:</b> <span class="mono">{_escape(import_hash)}</span></p><p><b>Data Center Atlas manifest SHA-256:</b> <span class="mono">{_escape(manifest_hash)}</span></p></div>
    </section>

    <footer>{_escape(result['methodology']['gross_to_net'])} {_escape(result['methodology']['operational_throughput'])}</footer>
  </main>
</body>
</html>
"""
