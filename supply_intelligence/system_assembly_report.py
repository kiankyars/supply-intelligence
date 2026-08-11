"""Audit dashboard for supplier-resolved system assembly."""

from __future__ import annotations

import html
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _number(value: float, digits: int = 0) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _interval(value: Mapping[str, float], digits: int = 0) -> str:
    return (
        f"{_number(value['p10'], digits)} / "
        f"{_number(value['p50'], digits)} / "
        f"{_number(value['p90'], digits)}"
    )


def _odm_cards(result: Mapping[str, Any]) -> str:
    cards = []
    for odm in result["odms"]:
        outputs = odm["outputs"]
        tray_probability = odm["stage_bottleneck_probabilities"].get(
            "compute_trays", 0.0
        )
        cards.append(
            f"""
            <article class="odm-card">
              <div class="eyebrow">{_escape(odm['geography'])}</div>
              <h3>{_escape(odm['name'])}</h3>
              <div class="mini-grid">
                <div><span>Assembly racks</span><strong>{_number(outputs['assembly_supported_racks']['p50'])}</strong></div>
                <div><span>Contribution</span><strong>{outputs['assembly_rack_share']['p50'] * 100:.1f}%</strong></div>
              </div>
              <p>Local bottleneck: compute trays {tray_probability * 100:.1f}% · rack integration {(1 - tray_probability) * 100:.1f}%</p>
              <code>{_escape(odm['tray_capacity_scope_id'])}</code>
              <code>{_escape(odm['rack_capacity_scope_id'])}</code>
            </article>
            """
        )
    return "".join(cards)


def _component_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["components"]:
        outputs = item["outputs"]
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['name'])}</strong><span>{_escape(item['stage'].replace('_', ' '))} · {_escape(item['resource_kind'])}</span></td>
              <td><code>{_escape(item['capacity_scope_id'])}</code></td>
              <td class="mono">{_escape(_interval(outputs['customer_allocated_output']))} {_escape(item['unit'])}</td>
              <td class="mono">{_escape(_interval(outputs['rack_equivalents']))}</td>
              <td class="mono">{item['bottleneck_probability'] * 100:.2f}%</td>
              <td class="mono">{outputs['customer_allocated_utilization']['p50'] * 100:.1f}%</td>
            </tr>
            """
        )
    return "".join(rows)


def _bottleneck_bars(result: Mapping[str, Any]) -> str:
    labels = {"odm_assembly": "ODM tray + rack flow", "rack_demand": "Rack demand"}
    rows = []
    for item in result["bottlenecks"]:
        key = item["constraint"]
        label = labels.get(key, key.removeprefix("component:").replace("-", " "))
        probability = item["probability"]
        rows.append(
            f"""
            <div class="bar-row">
              <span>{_escape(label)}</span>
              <div><i style="width:{probability * 100:.6f}%"></i></div>
              <strong>{probability * 100:.2f}%</strong>
            </div>
            """
        )
    return "".join(rows)


def _gap_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["research_queue"][:14]:
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['owner_id'])}</strong><span>{_escape(item['owner_type'])}</span></td>
              <td><code>{_escape(item['parameter'])}</code></td>
              <td class="mono">{_number(item['low'], 3)} / {_number(item['base'], 3)} / {_number(item['high'], 3)} {_escape(item['unit'])}</td>
              <td class="mono">{item['influence_probability'] * 100:.1f}%</td>
              <td>{_escape(item['confirming_evidence'])}</td>
            </tr>
            """
        )
    return "".join(rows) or '<tr><td colspan="5">No synthetic input remains.</td></tr>'


def _evidence_rows(result: Mapping[str, Any]) -> str:
    return "".join(
        f"""
        <tr>
          <td><code>{_escape(item['id'])}</code></td>
          <td><a href="{_escape(item['source_url'])}">{_escape(item['title'])}</a><span>{_escape(item['publisher'])}</span></td>
          <td>{_escape(item['kind'].replace('_', ' '))}</td>
          <td class="mono">{_escape(item['published_at'] or 'not supplied')}</td>
          <td class="mono">{_escape(item['retrieved_at'])}</td>
        </tr>
        """
        for item in result["evidence"]
    )


def _coverage_chips(result: Mapping[str, Any]) -> str:
    coverage = result["coverage"]["complete_rack_output"]
    return "".join(
        f'<span>{_escape(item["stage"])} · {_escape(item["resource_kind"])}</span>'
        for item in coverage["absorbed_constraints"]
    )


def render_system_assembly_dashboard(result: Mapping[str, Any]) -> str:
    outputs = result["conversion_outputs"]
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in result["warnings"])
    posture = "Illustrative assembly model" if result["scenario"]["synthetic"] else "Evidence-backed assembly model"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{_escape(result['scenario']['name'])}</title>
  <style>
    :root {{ --bg:#f2efe8; --paper:#fffdf8; --ink:#18211f; --muted:#66706d; --line:#d8d3c8; --teal:#126e68; --orange:#c66c3a; --gold:#d7b56d; --warn:#8d4812; --warn-bg:#fff0d7; --shadow:0 14px 38px rgba(24,33,31,.07); }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }} a {{ color:var(--teal); }}
    header,main {{ width:min(1480px,calc(100% - 40px)); margin-inline:auto; }} header {{ display:flex; justify-content:space-between; gap:28px; align-items:end; padding:38px 0 24px; border-bottom:1px solid var(--line); }}
    h1 {{ max-width:980px; margin:7px 0; font:600 clamp(38px,5vw,68px)/.98 Georgia,serif; letter-spacing:-.04em; }} h2,h3 {{ font-family:Georgia,serif; }} header p,.muted,.section-head p {{ color:var(--muted); margin:0; }}
    .eyebrow {{ color:var(--teal); font:800 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.1em; text-transform:uppercase; }} .stamp {{ text-align:right; min-width:200px; }} .stamp span,.stamp strong {{ display:block; }} .stamp strong {{ font-size:21px; }} .stamp span {{ color:var(--muted); }}
    main {{ padding:22px 0 70px; }} .notice {{ display:grid; grid-template-columns:210px 1fr; gap:20px; padding:15px 17px; border:1px solid #e1bf89; background:var(--warn-bg); }} .notice strong {{ color:var(--warn); }} .notice ul {{ margin:0; padding-left:18px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:13px; margin:18px 0 28px; }} .card,.odm-card,.panel,.table-wrap {{ background:var(--paper); border:1px solid var(--line); box-shadow:var(--shadow); }} .card {{ padding:19px; }} .card span {{ display:block; color:var(--muted); font-size:12px; text-transform:uppercase; }} .card strong {{ display:block; margin:7px 0 2px; font:600 35px/1 Georgia,serif; }} .card small {{ color:var(--muted); }}
    .section-head {{ display:flex; justify-content:space-between; gap:24px; align-items:end; margin:34px 0 12px; }} .section-head h2 {{ margin:4px 0 0; font-size:29px; }} .section-head p {{ max-width:650px; }} .odm-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }} .odm-card {{ padding:19px; border-top:4px solid var(--teal); }} .odm-card h3 {{ margin:4px 0 14px; font-size:26px; }} .odm-card p {{ color:var(--muted); }} .odm-card code {{ display:block; margin-top:5px; }} .mini-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }} .mini-grid span {{ display:block; color:var(--muted); font-size:12px; }} .mini-grid strong {{ display:block; font:600 25px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .two-column {{ display:grid; grid-template-columns:minmax(0,1.1fr) minmax(360px,.9fr); gap:16px; }} .panel {{ padding:22px; }} .bar-row {{ display:grid; grid-template-columns:190px 1fr 70px; gap:12px; align-items:center; margin:12px 0; }} .bar-row div {{ height:13px; background:#e5e0d5; overflow:hidden; }} .bar-row i {{ display:block; height:100%; background:var(--teal); }} .bar-row strong {{ text-align:right; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .coverage {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; }} .coverage span {{ padding:6px 9px; border:1px solid var(--line); background:#f7f3ea; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
    .table-wrap {{ overflow-x:auto; }} table {{ width:100%; min-width:1050px; border-collapse:collapse; }} th,td {{ padding:12px 13px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:11px; letter-spacing:.06em; text-transform:uppercase; }} tbody tr:last-child td {{ border-bottom:0; }} td span {{ display:block; margin-top:3px; color:var(--muted); font-size:12px; }} code,.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums; }} code {{ overflow-wrap:anywhere; }} footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media(max-width:1000px) {{ .cards,.odm-grid {{ grid-template-columns:1fr 1fr; }} .two-column {{ grid-template-columns:1fr; }} }} @media(max-width:680px) {{ header,.section-head {{ display:block; }} .stamp {{ margin-top:15px; text-align:left; }} .notice {{ grid-template-columns:1fr; }} .cards,.odm-grid {{ grid-template-columns:1fr; }} .bar-row {{ grid-template-columns:1fr; }} .bar-row strong {{ text-align:left; }} }}
  </style>
</head>
<body>
  <header><div><div class="eyebrow">ODM + rack components · {_escape(result['scenario']['quarter'])}</div><h1>{_escape(result['scenario']['name'])}</h1><p>Each ODM reconciles compute-tray and rack-integration output locally before required component pools are consumed once.</p></div><div class="stamp"><span>As of</span><strong>{_escape(result['scenario']['as_of_date'])}</strong><span>{result['scenario']['samples']:,} draws · seed {result['scenario']['seed']}</span></div></header>
  <main>
    <aside class="notice"><strong>{_escape(posture)}</strong><ul>{warnings}</ul></aside>
    <div class="cards">
      <article class="card"><span>Complete racks</span><strong>{_number(outputs['complete_racks']['p50'])}</strong><small>P10–P90 {_number(outputs['complete_racks']['p10'])}–{_number(outputs['complete_racks']['p90'])}</small></article>
      <article class="card"><span>Accelerator package equivalents</span><strong>{_number(outputs['accelerator_package_equivalents']['p50'])}</strong><small>72 per complete rack</small></article>
      <article class="card"><span>Supply-limited probability</span><strong>{result['demand_sufficiency']['probability_supply_limited'] * 100:.1f}%</strong><small>against illustrative rack demand</small></article>
      <article class="card"><span>ODM concentration HHI</span><strong>{outputs['odm_concentration_hhi']['p50']:.3f}</strong><small>assembly-supported rack contribution</small></article>
    </div>
    <section><div class="section-head"><div><div class="eyebrow">Supplier scopes</div><h2>Tray and rack output meet locally</h2></div><p>No cross-ODM work transfer is assumed. Each declared tray and rack capacity scope is unique.</p></div><div class="odm-grid">{_odm_cards(result)}</div></section>
    <section class="two-column"><div><div class="section-head"><div><div class="eyebrow">Constraint probability</div><h2>What binds complete racks</h2></div></div><div class="panel">{_bottleneck_bars(result)}</div></div><div><div class="section-head"><div><div class="eyebrow">One-count guard</div><h2>Component-cleared output</h2></div></div><div class="panel"><p>{_escape(result['coverage']['complete_rack_output']['methodology'])}</p><div class="coverage">{_coverage_chips(result)}</div><p class="muted">Coverage posture: {_escape(result['coverage']['complete_rack_output']['posture'])}. This is a semantic scope declaration, not capacity evidence.</p></div></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Component ledger</div><h2>Required pools consumed once</h2></div><p>Allocated output becomes rack capacity only after the exact per-rack requirement is applied.</p></div><div class="table-wrap"><table><thead><tr><th>Component</th><th>Capacity scope</th><th>Customer allocated P10 / P50 / P90</th><th>Rack equivalents</th><th>Bind probability</th><th>Median utilization</th></tr></thead><tbody>{_component_rows(result)}</tbody></table></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Evidence queue</div><h2>Highest-priority synthetic inputs</h2></div><p>Influence is conditional on this draw set and ranks sourcing work; it is not causal proof.</p></div><div class="table-wrap"><table><thead><tr><th>Owner</th><th>Input</th><th>Low / base / high</th><th>Influence</th><th>Evidence needed</th></tr></thead><tbody>{_gap_rows(result)}</tbody></table></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Source lineage</div><h2>Topology evidence and synthetic boundaries</h2></div></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_evidence_rows(result)}</tbody></table></div></section>
    <footer>Factory qualification, outbound logistics, site installation, facility-side cooling, transformers, backup power, and commissioning remain outside this complete-rack output.</footer>
  </main>
</body>
</html>
"""
