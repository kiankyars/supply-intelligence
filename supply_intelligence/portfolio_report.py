"""Standalone dashboard for shared-resource portfolio reconciliation."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from .report import STAGE_LABELS


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value)


def _number(value: float, digits: int = 0) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _interval(distribution: dict[str, float]) -> str:
    return (
        f"{_number(distribution['p10'], 1)} / "
        f"{_number(distribution['p50'], 1)} / "
        f"{_number(distribution['p90'], 1)}"
    )


def _platform_cards(result: dict[str, Any]) -> str:
    cards = []
    for index, item in enumerate(result["platforms"]):
        operational = item["physical_outputs"]["systems_operational"]
        packages = item["physical_outputs"]["accelerator_packages_produced"]
        unfilled = item["unfilled_quarterly_demand"]
        cards.append(
            f"""
            <article class="platform-card series-{index % 4 + 1}">
              <div><span class="kicker">{_escape(item['vendor'])}</span><h2>{_escape(item['name'])}</h2></div>
              <div class="platform-metrics">
                <div><span>Operational systems</span><strong>{_number(operational['p50'])}</strong><small>P10–P90 {_number(operational['p10'])}–{_number(operational['p90'])}</small></div>
                <div><span>Packages produced</span><strong>{_number(packages['p50'])}</strong><small>P10–P90 {_number(packages['p10'])}–{_number(packages['p90'])}</small></div>
                <div><span>Unfilled demand</span><strong>{_number(unfilled['p50'])}</strong><small>P10–P90 {_number(unfilled['p10'])}–{_number(unfilled['p90'])}</small></div>
              </div>
            </article>
            """
        )
    return "".join(cards)


def _stage_matrix(result: dict[str, Any]) -> str:
    platforms = result["platforms"]
    headers = "".join(f"<th>{_escape(item['name'])}</th>" for item in platforms)
    stages = [item["stage"] for item in platforms[0]["stage_outputs"]]
    by_platform = {
        item["id"]: {
            row["stage"]: row["system_equivalents"] for row in item["stage_outputs"]
        }
        for item in platforms
    }
    rows = []
    for stage in stages:
        cells = "".join(
            f"<td class='mono'><strong>{_number(by_platform[item['id']][stage]['p50'])}</strong><span>{_number(by_platform[item['id']][stage]['p10'])}–{_number(by_platform[item['id']][stage]['p90'])}</span></td>"
            for item in platforms
        )
        rows.append(f"<tr><td>{_escape(STAGE_LABELS[stage])}</td>{cells}</tr>")
    return f"<table><thead><tr><th>Stage</th>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _allocation_bars(result: dict[str, Any]) -> str:
    platforms = result["platforms"]
    stages = [item["stage"] for item in platforms[0]["stage_outputs"]]
    lookup = {
        item["id"]: {
            row["stage"]: row["system_equivalents"]["p50"]
            for row in item["stage_outputs"]
        }
        for item in platforms
    }
    rows = []
    for stage in stages:
        total = sum(lookup[item["id"]][stage] for item in platforms)
        segments = "".join(
            f'<span class="segment series-{index % 4 + 1}" style="width:{(lookup[item["id"]][stage] / total * 100 if total else 0):.4f}%" aria-label="{_escape(item["name"])} {_number(lookup[item["id"]][stage])}"></span>'
            for index, item in enumerate(platforms)
        )
        labels = " · ".join(
            f"{item['name']} {_number(lookup[item['id']][stage])}" for item in platforms
        )
        rows.append(
            f"""
            <div class="allocation-bar-row">
              <div><strong>{_escape(STAGE_LABELS[stage])}</strong><span>{_escape(labels)}</span></div>
              <div class="stacked-bar">{segments}</div>
              <strong class="mono">{_number(total)}</strong>
            </div>
            """
        )
    return "".join(rows)


def _resource_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in sorted(
        result["resource_pools"],
        key=lambda row: (-row["binding_probability"], -row["utilization"]["p50"]),
    ):
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['resource_name'])}</strong><span>{_escape(item['resource_kind'])}</span></td>
              <td>{_escape(STAGE_LABELS[item['stage']])}</td>
              <td class="mono">{_interval(item['effective_capacity'])} {_escape(item['unit'])}</td>
              <td class="mono">{_interval(item['consumption'])}</td>
              <td class="mono">{item['utilization']['p50'] * 100:.1f}%</td>
              <td class="mono">{item['binding_probability'] * 100:.1f}%</td>
            </tr>
            """
        )
    return "".join(rows)


def _inventory_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in sorted(
        result["inventory"],
        key=lambda row: -row["systems_held_back"]["p50"],
    ):
        if item["systems_held_back"]["p90"] <= 1e-9:
            continue
        rows.append(
            f"""
            <tr>
              <td>{_escape(item['platform_name'])}</td>
              <td>{_escape(STAGE_LABELS[item['from_stage']])} → {_escape(STAGE_LABELS[item['to_stage']])}</td>
              <td class="mono">{_interval(item['systems_held_back'])}</td>
            </tr>
            """
        )
    return "".join(rows) or '<tr><td colspan="3" class="empty">No material stage inventory.</td></tr>'


def _requirement_rows(result: dict[str, Any]) -> str:
    platform_names = {item["id"]: item["name"] for item in result["inputs"]["platforms"]}
    resource_names = {
        item["id"]: item["resource_name"] for item in result["inputs"]["resource_pools"]
    }
    rows = []
    for item in result["inputs"]["requirements"]:
        estimate = item["units_per_system"]
        links = " ".join(
            f'<a href="#source-{_safe_id(source_id)}">{_escape(source_id)}</a>'
            for source_id in estimate["evidence_ids"]
        )
        rows.append(
            f"""
            <tr>
              <td>{_escape(platform_names[item['platform_id']])}</td>
              <td>{_escape(resource_names[item['resource_pool_id']])}</td>
              <td class="mono">{_number(estimate['low'], 2)} / {_number(estimate['base'], 2)} / {_number(estimate['high'], 2)} {_escape(estimate['unit'])}</td>
              <td>{_escape(estimate['posture'])}<span>confidence {estimate['confidence']:.0%}</span></td>
              <td>{links}</td>
            </tr>
            """
        )
    return "".join(rows)


def _resource_audit(result: dict[str, Any]) -> str:
    rows = []
    for item in result["inputs"]["resource_pools"]:
        estimate = item["capacity"]
        yield_estimate = item["effective_yield"]
        sources = " ".join(
            f'<a href="#source-{_safe_id(source_id)}">{_escape(source_id)}</a>'
            for source_id in estimate["evidence_ids"]
        )
        rows.append(
            f"""
            <details>
              <summary><div><strong>{_escape(item['resource_name'])}</strong><span>{_escape(STAGE_LABELS[item['stage']])} · {_escape(item['capacity_basis'])}</span></div><span class="mono">{_number(estimate['low'], 1)} / {_number(estimate['base'], 1)} / {_number(estimate['high'], 1)} {_escape(estimate['unit'])}</span></summary>
              <div class="audit-body">
                <p><b>Capacity method:</b> {_escape(estimate['methodology'])}</p>
                <p><b>Effective yield:</b> {_number(yield_estimate['low'], 3)} / {_number(yield_estimate['base'], 3)} / {_number(yield_estimate['high'], 3)}. {_escape(yield_estimate['methodology'])}</p>
                <p><b>Sources:</b> {sources} · <b>Updated:</b> {_escape(estimate['last_updated'])}</p>
                <p><b>Confirms:</b> {_escape(estimate['confirming_evidence'])}</p>
                <p><b>Falsifies:</b> {_escape(estimate['falsifying_evidence'])}</p>
              </div>
            </details>
            """
        )
    return "".join(rows)


def _source_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in result["evidence"]:
        rows.append(
            f"""
            <tr id="source-{_safe_id(item['id'])}">
              <td class="mono">{_escape(item['id'])}</td>
              <td><a href="{_escape(item['source_url'])}" target="_blank" rel="noreferrer">{_escape(item['title'])}</a><span>{_escape(item['publisher'])}</span></td>
              <td>{_escape(item['kind'])}</td>
              <td class="mono">{_escape(item['published_at'] or 'Not supplied')}</td>
              <td class="mono">{_escape(item['retrieved_at'])}</td>
            </tr>
            """
        )
    return "".join(rows)


def render_portfolio_dashboard(result: dict[str, Any]) -> str:
    bottleneck_json = json.dumps(
        {item["stage"]: item["constraints"] for item in result["stage_bottlenecks"]},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    stage_options = "".join(
        f'<option value="{item["stage"]}" {"selected" if item["stage"] == "operational" else ""}>{_escape(STAGE_LABELS[item["stage"]])}</option>'
        for item in result["stage_bottlenecks"]
    )
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in result["warnings"])
    synthetic_class = "synthetic" if result["scenario"]["synthetic"] else "evidence-backed"
    posture = "Illustrative portfolio" if result["scenario"]["synthetic"] else "Evidence-backed portfolio"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{_escape(result['scenario']['name'])}</title>
  <style>
    :root {{ --bg:#f2efe8; --paper:#fbfaf6; --ink:#181b19; --muted:#62675f; --line:#d7d2c7; --green:#006b5d; --green-soft:#cfe4df; --orange:#b85c2d; --blue:#476b8e; --gold:#9d812a; --warning:#8b4d12; --warning-bg:#fff0d8; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.48 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:var(--green); }}
    header,main {{ width:min(1440px,calc(100% - 40px)); margin-inline:auto; }}
    header {{ padding:34px 0 22px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:end; gap:24px; }}
    h1 {{ margin:7px 0 4px; font:500 clamp(34px,5vw,64px)/.98 Georgia,"Times New Roman",serif; letter-spacing:-.035em; }}
    h2,h3 {{ font-family:Georgia,"Times New Roman",serif; font-weight:500; }}
    header p,.muted,.section-head p {{ color:var(--muted); margin:0; }}
    .kicker,.section-label {{ color:var(--green); font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.09em; text-transform:uppercase; }}
    .stamp {{ text-align:right; }} .stamp strong,.stamp span {{ display:block; }} .stamp strong {{ font-size:20px; }} .stamp span {{ color:var(--muted); }}
    main {{ padding:24px 0 70px; }}
    .notice {{ display:grid; grid-template-columns:190px 1fr; gap:20px; padding:14px 16px; background:var(--warning-bg); border:1px solid #e4c28e; margin-bottom:20px; }}
    .notice strong {{ color:var(--warning); }} .notice ul {{ margin:0; padding-left:18px; }}
    .platform-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin-bottom:26px; }}
    .platform-card {{ background:var(--paper); border:1px solid var(--line); border-top:4px solid var(--green); padding:18px; }}
    .platform-card.series-2 {{ border-top-color:var(--orange); }} .platform-card.series-3 {{ border-top-color:var(--blue); }} .platform-card.series-4 {{ border-top-color:var(--gold); }}
    .platform-card h2 {{ font-size:27px; margin:4px 0 16px; }}
    .platform-metrics {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }}
    .platform-metrics span,.platform-metrics small {{ display:block; color:var(--muted); }}
    .platform-metrics strong {{ display:block; font:500 30px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace; margin:4px 0; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:24px; margin:34px 0 12px; }}
    .section-head h2 {{ font-size:27px; margin:5px 0 0; }}
    .two-column {{ display:grid; grid-template-columns:minmax(0,1.2fr) minmax(330px,.8fr); gap:18px; }}
    .panel,.table-wrap {{ min-width:0; max-width:100%; background:var(--paper); border:1px solid var(--line); }} .panel {{ padding:20px; }}
    .table-wrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; min-width:720px; }}
    th,td {{ padding:12px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }} tbody tr:last-child td {{ border-bottom:0; }}
    td span,.mono span,summary span {{ display:block; color:var(--muted); font-size:12px; }} .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums; }}
    .allocation-bar-row {{ display:grid; grid-template-columns:230px 1fr 65px; align-items:center; gap:12px; margin:15px 0; }} .allocation-bar-row div:first-child span {{ display:block; color:var(--muted); font-size:12px; }}
    .stacked-bar,.track {{ height:14px; background:#e5e0d7; display:flex; overflow:hidden; }} .segment {{ height:100%; background:var(--green); }} .segment.series-2 {{ background:var(--orange); }} .segment.series-3 {{ background:var(--blue); }} .segment.series-4 {{ background:var(--gold); }}
    label {{ display:block; color:var(--muted); margin:12px 0 6px; }} select {{ width:100%; padding:9px; background:var(--paper); color:var(--ink); border:1px solid var(--line); font:inherit; }}
    .bottleneck-row {{ display:grid; grid-template-columns:minmax(130px,1fr) 1.6fr 58px; gap:10px; align-items:center; margin:12px 0; }} .bottleneck-row .label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .track {{ position:relative; }} .track span {{ display:block; background:var(--green); }}
    details {{ background:var(--paper); border-top:1px solid var(--line); }} details:last-child {{ border-bottom:1px solid var(--line); }} summary {{ display:flex; justify-content:space-between; gap:16px; cursor:pointer; padding:14px 5px; }} .audit-body {{ padding:0 14px 14px; border-left:3px solid var(--green-soft); }} .audit-body p {{ margin:7px 0; color:var(--muted); }} .audit-body b {{ color:var(--ink); }}
    .empty {{ color:var(--muted); padding:20px; }} footer {{ margin-top:36px; border-top:1px solid var(--line); padding-top:18px; color:var(--muted); }}
    @media (max-width:900px) {{ .platform-grid,.two-column {{ grid-template-columns:minmax(0,1fr); }} }}
    @media (max-width:640px) {{ header,main {{ width:min(1440px,calc(100% - 24px)); }} header,.section-head {{ display:block; }} .stamp {{ text-align:left; margin-top:16px; }} .notice {{ grid-template-columns:1fr; gap:5px; }} .platform-metrics {{ grid-template-columns:1fr; }} .allocation-bar-row {{ grid-template-columns:1fr 55px; }} .allocation-bar-row .stacked-bar {{ grid-column:1/-1; grid-row:2; }} .bottleneck-row {{ grid-template-columns:minmax(90px,1fr) 1.2fr 50px; }} summary {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="kicker">Shared-resource allocation · {_escape(result['scenario']['quarter'])}</div><h1>{_escape(result['scenario']['name'])}</h1><p>One capacity pool per resource, allocated across competing accelerator platforms.</p></div>
    <div class="stamp"><span>As of</span><strong>{_escape(result['scenario']['as_of_date'])}</strong><span>{result['scenario']['samples']:,} draws · seed {result['scenario']['seed']}</span></div>
  </header>
  <main>
    <aside class="notice {synthetic_class}"><strong>{_escape(posture)}</strong><ul>{warnings}</ul></aside>
    <div class="platform-grid">{_platform_cards(result)}</div>
    <section>
      <div class="section-head"><div><div class="section-label">Production flow</div><h2>Platform output by stage</h2></div><p>Median systems with P10–P90 beneath each value.</p></div>
      <div class="two-column">
        <div class="table-wrap">{_stage_matrix(result)}</div>
        <div class="panel"><div class="section-label">Allocation mix</div><h3>Who consumes shared capacity</h3><p class="muted">Median platform systems at each stage.</p>{_allocation_bars(result)}</div>
      </div>
    </section>
    <section>
      <div class="section-head"><div><div class="section-label">Resource ledger</div><h2>Capacity is consumed once</h2></div><p>Capacity and consumption show P10 / P50 / P90.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Resource</th><th>Stage</th><th>Effective capacity</th><th>Consumption</th><th>Utilization</th><th>Binding</th></tr></thead><tbody>{_resource_rows(result)}</tbody></table></div>
    </section>
    <section class="two-column">
      <div>
        <div class="section-head"><div><div class="section-label">Inventory</div><h2>Stage holdbacks</h2></div></div>
        <div class="table-wrap"><table><thead><tr><th>Platform</th><th>Transition</th><th>Systems held back</th></tr></thead><tbody>{_inventory_rows(result)}</tbody></table></div>
      </div>
      <div>
        <div class="section-head"><div><div class="section-label">Constraint risk</div><h2>Binding probability</h2></div></div>
        <div class="panel"><label for="portfolio-bottleneck-stage">Production stage</label><select id="portfolio-bottleneck-stage">{stage_options}</select><div id="portfolio-bottleneck-chart" aria-live="polite"></div></div>
      </div>
    </section>
    <section>
      <div class="section-head"><div><div class="section-label">BOM ledger</div><h2>Platform requirements by shared pool</h2></div><p>Each row links the range to its source record.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Platform</th><th>Resource</th><th>Units per system</th><th>Posture</th><th>Evidence</th></tr></thead><tbody>{_requirement_rows(result)}</tbody></table></div>
    </section>
    <section>
      <div class="section-head"><div><div class="section-label">Input audit</div><h2>Resource methods and falsifiers</h2></div><p>Open a pool to inspect its capacity and yield assumptions.</p></div>
      {_resource_audit(result)}
    </section>
    <section>
      <div class="section-head"><div><div class="section-label">Source ledger</div><h2>Evidence used by this run</h2></div><p>Direct URLs, source posture, and retrieval time.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Evidence ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_source_rows(result)}</tbody></table></div>
    </section>
    <footer>{_escape(result['methodology']['allocation'])} {_escape(result['methodology']['stage_flow'])}</footer>
  </main>
  <script>
    const bottlenecks = {bottleneck_json};
    const select = document.getElementById('portfolio-bottleneck-stage');
    const chart = document.getElementById('portfolio-bottleneck-chart');
    function escapeText(value) {{ const node=document.createElement('span'); node.textContent=value; return node.innerHTML; }}
    function render() {{
      const rows=(bottlenecks[select.value]||[]).filter(row=>row.probability>0.0001).slice(0,10);
      chart.innerHTML=rows.map(row=>`<div class="bottleneck-row"><span class="label">${{escapeText(row.resource_name)}}</span><div class="track"><span style="width:${{(row.probability*100).toFixed(3)}}%"></span></div><strong class="mono">${{(row.probability*100).toFixed(1)}}%</strong></div>`).join('')||'<p class="empty">No binding resource at this stage.</p>';
    }}
    select.addEventListener('change',render); render();
  </script>
</body>
</html>
"""
