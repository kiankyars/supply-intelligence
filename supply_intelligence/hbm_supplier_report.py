"""Standalone dashboard for supplier-resolved HBM supply and allocation."""

from __future__ import annotations

import html
import re
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value)


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


def _supplier_cards(result: Mapping[str, Any]) -> str:
    cards = []
    for index, supplier in enumerate(result["suppliers"]):
        outputs = supplier["outputs"]
        share = outputs["customer_allocated_stack_share"]["p50"]
        cards.append(
            f"""
            <article class="supplier-card series-{index % 3 + 1}">
              <div class="eyebrow">{_escape(supplier['product'])} · {_escape(supplier['process_node'])}</div>
              <h2>{_escape(supplier['name'])}</h2>
              <div class="supplier-metrics">
                <div><span>Allocated stacks</span><strong>{_number(outputs['customer_allocated_stacks']['p50'])}</strong><small>P10–P90 {_number(outputs['customer_allocated_stacks']['p10'])}–{_number(outputs['customer_allocated_stacks']['p90'])}</small></div>
                <div><span>Supply share</span><strong>{share * 100:.1f}%</strong><small>median customer allocation</small></div>
                <div><span>Criticality</span><strong>{supplier['criticality_probability'] * 100:.1f}%</strong><small>demand uncovered without supplier</small></div>
              </div>
            </article>
            """
        )
    return "".join(cards)


def _allocation_bar(result: Mapping[str, Any]) -> str:
    segments = []
    labels = []
    for index, supplier in enumerate(result["suppliers"]):
        share = supplier["outputs"]["customer_allocated_stack_share"]["p50"]
        segments.append(
            f'<span class="segment series-{index % 3 + 1}" style="width:{share * 100:.5f}%" title="{_escape(supplier["name"])} {share * 100:.1f}%"></span>'
        )
        labels.append(
            f'<div><i class="dot series-{index % 3 + 1}"></i><span>{_escape(supplier["name"])}</span><strong>{share * 100:.1f}%</strong></div>'
        )
    return (
        f'<div class="stacked-bar">{"".join(segments)}</div>'
        f'<div class="legend">{"".join(labels)}</div>'
    )


def _supplier_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for supplier in result["suppliers"]:
        outputs = supplier["outputs"]
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(supplier['name'])}</strong><span>{_escape(supplier['geography'])} · {_escape(supplier['wafer_start_basis'].replace('_', ' '))}</span></td>
              <td><code>{_escape(supplier['capacity_scope_id'])}</code><span>{_escape(supplier['capacity_scope'])}</span></td>
              <td class="mono">{_escape(_interval(outputs['good_stacks']))}</td>
              <td class="mono">{_escape(_interval(outputs['platform_qualified_stacks']))}</td>
              <td class="mono">{_escape(_interval(outputs['customer_allocated_stacks']))}</td>
              <td class="mono">{_escape(_interval(outputs['platform_package_equivalents']))}</td>
            </tr>
            """
        )
    return "".join(rows)


def _gap_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["research_queue"][:12]:
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['owner_id'])}</strong><span>{_escape(item['owner_type'])}</span></td>
              <td><code>{_escape(item['parameter'])}</code></td>
              <td class="mono">{_number(item['low'], 3)} / {_number(item['base'], 3)} / {_number(item['high'], 3)} {_escape(item['unit'])}</td>
              <td class="mono">{item['confidence'] * 100:.0f}%</td>
              <td>{_escape(item['confirming_evidence'])}</td>
            </tr>
            """
        )
    return "".join(rows) or '<tr><td colspan="5">No synthetic estimate remains.</td></tr>'


def _evidence_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["evidence"]:
        links = _escape(item["title"])
        rows.append(
            f"""
            <tr id="source-{_safe_id(item['id'])}">
              <td><code>{_escape(item['id'])}</code></td>
              <td><a href="{_escape(item['source_url'])}">{links}</a><span>{_escape(item['publisher'])}</span></td>
              <td>{_escape(item['kind'].replace('_', ' '))}</td>
              <td class="mono">{_escape(item['published_at'] or 'not supplied')}</td>
              <td class="mono">{_escape(item['retrieved_at'])}</td>
            </tr>
            """
        )
    return "".join(rows)


def render_hbm_supplier_dashboard(result: Mapping[str, Any]) -> str:
    totals = result["totals"]
    limited = result["supply_sufficiency"]["probability_hbm_limited"]
    warning_items = "".join(
        f"<li>{_escape(item)}</li>" for item in result["warnings"]
    )
    posture = (
        "Illustrative supplier portfolio"
        if result["scenario"]["synthetic"]
        else "Evidence-backed supplier portfolio"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{_escape(result['scenario']['name'])}</title>
  <style>
    :root {{ --bg:#f0eee7; --paper:#fffdf8; --ink:#16211d; --muted:#65716b; --line:#d6d4cb; --green:#0d6b55; --mint:#9ed7c1; --orange:#c56b36; --blue:#547698; --warn:#8e4b11; --warn-bg:#fff0d7; --shadow:0 14px 38px rgba(22,33,29,.07); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.48 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:var(--green); }}
    header,main {{ width:min(1480px,calc(100% - 40px)); margin-inline:auto; }}
    header {{ display:flex; justify-content:space-between; gap:28px; align-items:end; padding:38px 0 24px; border-bottom:1px solid var(--line); }}
    h1 {{ max-width:1000px; margin:7px 0; font:600 clamp(38px,5.5vw,70px)/.98 Georgia,serif; letter-spacing:-.04em; }}
    h2,h3 {{ font-family:Georgia,serif; }}
    header p,.muted,.section-head p {{ margin:0; color:var(--muted); }}
    .eyebrow {{ color:var(--green); font:800 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.1em; text-transform:uppercase; }}
    .stamp {{ min-width:190px; text-align:right; }} .stamp span,.stamp strong {{ display:block; }} .stamp strong {{ font-size:21px; }} .stamp span {{ color:var(--muted); }}
    main {{ padding:22px 0 70px; }}
    .notice {{ display:grid; grid-template-columns:210px 1fr; gap:20px; padding:15px 17px; border:1px solid #e1bf89; background:var(--warn-bg); }} .notice strong {{ color:var(--warn); }} .notice ul {{ margin:0; padding-left:18px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:13px; margin:18px 0 28px; }}
    .card,.supplier-card,.panel,.table-wrap {{ border:1px solid var(--line); background:var(--paper); box-shadow:var(--shadow); }}
    .card {{ padding:19px; }} .card span {{ display:block; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }} .card strong {{ display:block; margin:7px 0 2px; font:600 35px/1 Georgia,serif; }} .card small {{ color:var(--muted); }}
    .supplier-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }} .supplier-card {{ padding:19px; border-top:4px solid var(--green); }} .supplier-card.series-2 {{ border-top-color:var(--orange); }} .supplier-card.series-3 {{ border-top-color:var(--blue); }} .supplier-card h2 {{ margin:4px 0 14px; font-size:27px; }} .supplier-metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }} .supplier-metrics div:first-child {{ grid-column:1/-1; }} .supplier-metrics span,.supplier-metrics small {{ display:block; color:var(--muted); font-size:12px; }} .supplier-metrics strong {{ display:block; margin:3px 0; font:600 24px/1.1 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .section-head {{ display:flex; justify-content:space-between; gap:24px; align-items:end; margin:34px 0 12px; }} .section-head h2 {{ margin:4px 0 0; font-size:29px; }} .section-head p {{ max-width:640px; }}
    .two-column {{ display:grid; grid-template-columns:minmax(0,1.1fr) minmax(350px,.9fr); gap:16px; }} .panel {{ padding:22px; }}
    .stacked-bar {{ display:flex; height:30px; overflow:hidden; background:#e2ded4; margin:20px 0 16px; }} .segment {{ height:100%; background:var(--green); }} .segment.series-2 {{ background:var(--orange); }} .segment.series-3 {{ background:var(--blue); }} .legend {{ display:grid; gap:10px; }} .legend div {{ display:grid; grid-template-columns:12px 1fr auto; gap:9px; align-items:center; }} .dot {{ width:9px; height:9px; border-radius:50%; background:var(--green); }} .dot.series-2 {{ background:var(--orange); }} .dot.series-3 {{ background:var(--blue); }}
    .table-wrap {{ overflow-x:auto; }} table {{ width:100%; min-width:1020px; border-collapse:collapse; }} th,td {{ padding:12px 13px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:11px; letter-spacing:.06em; text-transform:uppercase; }} tbody tr:last-child td {{ border-bottom:0; }} td span,td small {{ display:block; margin-top:3px; color:var(--muted); font-size:12px; }} code,.mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums; }} code {{ overflow-wrap:anywhere; }}
    footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media(max-width:1000px) {{ .cards,.supplier-grid {{ grid-template-columns:1fr 1fr; }} .two-column {{ grid-template-columns:1fr; }} }}
    @media(max-width:680px) {{ header,.section-head {{ display:block; }} .stamp {{ margin-top:15px; text-align:left; }} .notice {{ grid-template-columns:1fr; gap:5px; }} .cards,.supplier-grid {{ grid-template-columns:1fr; }} .supplier-metrics {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="eyebrow">Supplier-resolved HBM · {_escape(result['scenario']['quarter'])}</div><h1>{_escape(result['scenario']['name'])}</h1><p>Compatible HBM supply is qualified and allocated by supplier before aggregation for {_escape(result['platform']['name'])}.</p></div>
    <div class="stamp"><span>As of</span><strong>{_escape(result['scenario']['as_of_date'])}</strong><span>{result['scenario']['samples']:,} draws · seed {result['scenario']['seed']}</span></div>
  </header>
  <main>
    <aside class="notice"><strong>{_escape(posture)}</strong><ul>{warning_items}</ul></aside>
    <div class="cards">
      <article class="card"><span>Allocated stacks</span><strong>{_number(totals['customer_allocated_stacks']['p50'])}</strong><small>P10–P90 {_number(totals['customer_allocated_stacks']['p10'])}–{_number(totals['customer_allocated_stacks']['p90'])}</small></article>
      <article class="card"><span>Package equivalents</span><strong>{_number(totals['hbm_package_equivalents']['p50'])}</strong><small>{_escape(result['platform']['name'])}</small></article>
      <article class="card"><span>HBM-limited probability</span><strong>{limited * 100:.1f}%</strong><small>against package demand</small></article>
      <article class="card"><span>Supplier HHI</span><strong>{totals['supplier_concentration_hhi']['p50']:.3f}</strong><small>allocated-stack concentration</small></article>
    </div>
    <section><div class="section-head"><div><div class="eyebrow">Supplier ledger</div><h2>Three scopes, consumed once</h2></div><p>Each supplier owns a unique declared capacity scope. Qualification and customer allocation remain visible deductions.</p></div><div class="supplier-grid">{_supplier_cards(result)}</div></section>
    <section class="two-column"><div><div class="section-head"><div><div class="eyebrow">Allocation mix</div><h2>Who supplies the customer pool</h2></div></div><div class="panel">{_allocation_bar(result)}</div></div><div><div class="section-head"><div><div class="eyebrow">Demand bridge</div><h2>Reserved stacks to packages</h2></div></div><div class="panel"><p><strong>{_escape(_interval(totals['accelerator_package_demand']))}</strong> package demand</p><p><strong>{_escape(_interval(totals['packages_supported']))}</strong> packages supported</p><p><strong>{_escape(_interval(totals['unfilled_package_demand']))}</strong> unfilled demand</p><p class="muted">Values show P10 / P50 / P90.</p></div></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Physical conversion</div><h2>Supplier output audit</h2></div><p>Good stacks are not customer supply until platform qualification and allocation pass.</p></div><div class="table-wrap"><table><thead><tr><th>Supplier</th><th>Capacity scope</th><th>Good stacks</th><th>Qualified</th><th>Customer allocated</th><th>Package equivalents</th></tr></thead><tbody>{_supplier_rows(result)}</tbody></table></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Evidence queue</div><h2>Highest-priority synthetic inputs</h2></div><p>Priority combines median supplier contribution with missing confidence. It is conditional on this illustrative scenario.</p></div><div class="table-wrap"><table><thead><tr><th>Owner</th><th>Input</th><th>Low / base / high</th><th>Confidence</th><th>Evidence needed</th></tr></thead><tbody>{_gap_rows(result)}</tbody></table></div></section>
    <section><div class="section-head"><div><div class="eyebrow">Source lineage</div><h2>Evidence retained with the run</h2></div></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_evidence_rows(result)}</tbody></table></div></section>
    <footer>Capacity-scope uniqueness is enforced inside this scenario. It does not prove that external disclosures are independent, complete, or free of undisclosed overlap.</footer>
  </main>
</body>
</html>
"""
