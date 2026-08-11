"""Standalone dashboard for the supplier-HBM manufacturing replacement."""

from __future__ import annotations

import html
from typing import Any


LABELS = {
    "logic_package_equivalents": "Logic package equivalents",
    "hbm_package_equivalents": "Supplier HBM package equivalents",
    "package_assembly_start_capacity": "Package assembly starts",
    "finished_accelerator_packages": "Finished accelerator packages",
    "complete_system_equivalents": "Complete NVL72 equivalents",
    "hbm_good_stacks": "Customer-allocated HBM stacks",
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _number(value: float, digits: int = 0) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _distribution(result: dict[str, Any], metric: str) -> dict[str, float]:
    return result["conversion_outputs"][metric]


def _metric_card(result: dict[str, Any], metric: str, unit: str) -> str:
    value = _distribution(result, metric)
    return f"""
      <article class="metric-card">
        <span>{_escape(LABELS[metric])}</span>
        <strong>{_number(value['p50'])}</strong>
        <small>{_escape(unit)} · P10 {_number(value['p10'])} · P90 {_number(value['p90'])}</small>
      </article>
    """


def _bottlenecks(result: dict[str, Any]) -> str:
    labels = {
        "logic_binned_dies": "Logic dies",
        "hbm_good_stacks": "Supplier HBM",
        "package_assembly_starts": "Package starts",
    }
    rows = []
    for item in result["bottlenecks"]:
        probability = item["probability"]
        rows.append(
            f"""
            <div class="bar-row">
              <span>{_escape(labels[item['constraint']])}</span>
              <div class="bar"><i style="width:{probability * 100:.4f}%"></i></div>
              <strong>{probability * 100:.1f}%</strong>
            </div>
            """
        )
    return "".join(rows)


def _research_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in result["research_queue"][:10]:
        rows.append(
            f"""
            <tr>
              <td>{_escape(item['owner_id'])}</td>
              <td>{_escape(item['parameter'])}</td>
              <td>{item['influence_probability'] * 100:.1f}%</td>
              <td>{item['confidence'] * 100:.0f}%</td>
              <td>{item['research_priority']:.3f}</td>
            </tr>
            """
        )
    return "".join(rows)


def render_hbm_manufacturing_dashboard(result: dict[str, Any]) -> str:
    scenario = result["scenario"]
    lineage = result["lineage"]
    source = lineage["sources"]["hbm_supplier_result"]
    replacement = lineage["replacement"]
    supplier_names = ", ".join(source["supplier_names"])
    source_range = replacement["source_distribution"]
    package_coverage = lineage.get("package_coverage")
    draw_link = "capacity_draws_sha256" in source
    draw_lineage = (
        f"\n        <dt>Capacity draws</dt><dd><code>{_escape(source['capacity_draws_sha256'])}</code> · {source['capacity_draw_count']:,} rows</dd>"
        if draw_link
        else ""
    )
    footnote = (
        "Every source HBM capacity draw is retained under a deterministic permutation. Supplier allocation within each HBM draw is preserved; dependence with logic and packaging is not asserted."
        if draw_link
        else "The imported source quantiles are triangular endpoints and mode. Source tails and joint dependence are not preserved; inspect the frozen source result and lineage before interpreting this run."
    )
    coverage_lineage = (
        "\n        <dt>Package starts</dt><dd>Material-cleared; absorbs "
        + _escape(", ".join(package_coverage["absorbed_resource_kinds"]))
        + "</dd>"
        if package_coverage
        else ""
    )
    if package_coverage:
        footnote += (
            " Package-start coverage is a synthetic scope declaration, not evidence of "
            "interposer or substrate capacity."
        )
    warning = (
        "Illustrative linked run: manufacturing, supplier capacity, yields, allocation, "
        "and demand contain synthetic inputs. This is not an estimate of actual output."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(scenario['name'])}</title>
  <style>
    :root {{ --ink:#17221d; --muted:#617067; --paper:#f4f1e9; --card:#fffdf7;
      --line:#d8d3c6; --green:#0f6a4d; --amber:#9a5b12; --warn:#fff0d0; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1180px,calc(100% - 40px)); margin:34px auto 60px; }}
    .eyebrow {{ color:var(--green); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ max-width:850px; margin:8px 0 10px; font:700 clamp(34px,5vw,60px)/1.02 Georgia,serif; }}
    h2 {{ margin:0 0 16px; font:700 25px/1.15 Georgia,serif; }}
    p {{ margin:0; }}
    .subtitle {{ color:var(--muted); max-width:850px; font-size:17px; }}
    .warning {{ margin:24px 0; padding:16px 18px; border:1px solid #d39a45; background:var(--warn); font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }}
    .metric-card,.panel {{ background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px #25382b0a; }}
    .metric-card {{ padding:19px; min-width:0; }}
    .metric-card span {{ display:block; color:var(--muted); font-size:13px; font-weight:700; }}
    .metric-card strong {{ display:block; margin:7px 0 3px; font:700 31px/1 Georgia,serif; }}
    .metric-card small {{ color:var(--muted); }}
    .panel {{ margin-top:18px; padding:24px; }}
    .flow {{ display:grid; grid-template-columns:1fr auto 1fr auto 1fr; gap:12px; align-items:center; }}
    .flow-node {{ min-width:0; padding:18px; border:1px solid var(--line); border-radius:10px; background:#fff; }}
    .flow-node span,.flow-node small {{ display:block; color:var(--muted); }}
    .flow-node strong {{ display:block; margin:5px 0; font-size:24px; }}
    .arrow {{ color:var(--green); font-size:14px; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }}
    .boundary {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
    dl {{ display:grid; grid-template-columns:160px 1fr; gap:10px 16px; margin:0; }}
    dt {{ color:var(--muted); font-weight:700; }} dd {{ margin:0; overflow-wrap:anywhere; }}
    code {{ font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .bar-row {{ display:grid; grid-template-columns:160px 1fr 58px; gap:12px; align-items:center; margin:12px 0; }}
    .bar {{ height:11px; overflow:hidden; border-radius:9px; background:#e6e1d6; }}
    .bar i {{ display:block; height:100%; background:var(--green); }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:10px 8px; text-align:left; border-bottom:1px solid var(--line); }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }}
    .foot {{ margin-top:18px; color:var(--muted); font-size:13px; }}
    @media (max-width:800px) {{ .grid,.boundary {{ grid-template-columns:1fr; }} .flow {{ grid-template-columns:1fr; }} .arrow {{ transform:rotate(90deg); text-align:center; }} }}
  </style>
</head>
<body><main>
  <div class="eyebrow">Supplier HBM → manufacturing · {_escape(scenario['quarter'])}</div>
  <h1>{_escape(scenario['name'])}</h1>
  <p class="subtitle">One hash-pinned supplier stack pool replaces the aggregate HBM wafer branch before logic, HBM, and package capacity are reconciled.</p>
  <div class="warning">{_escape(warning)}</div>

  <section class="grid">
    {_metric_card(result, 'hbm_good_stacks', 'allocated stack')}
    {_metric_card(result, 'finished_accelerator_packages', 'package')}
    {_metric_card(result, 'complete_system_equivalents', 'system')}
  </section>

  <section class="panel">
    <h2>Three branches enter one minimum</h2>
    <div class="flow">
      <div class="flow-node"><span>Logic branch</span><strong>{_number(_distribution(result,'logic_package_equivalents')['p50'])}</strong><small>package equivalents · P50</small></div>
      <div class="arrow">min</div>
      <div class="flow-node"><span>Supplier HBM branch</span><strong>{_number(_distribution(result,'hbm_package_equivalents')['p50'])}</strong><small>package equivalents · P50</small></div>
      <div class="arrow">min</div>
      <div class="flow-node"><span>Package starts</span><strong>{_number(_distribution(result,'package_assembly_start_capacity')['p50'])}</strong><small>attempt capacity · P50</small></div>
    </div>
  </section>

  <section class="panel boundary">
    <div>
      <h2>Replacement boundary</h2>
      <dl>
        <dt>Removed flow</dt><dd><code>{_escape(replacement['removed_aggregate_hbm_wafer_flow_id'])}</code></dd>
        <dt>Imported metric</dt><dd><code>{_escape(replacement['imported_metric'])}</code></dd>
        <dt>Source range</dt><dd>{_number(source_range['p10'])} / {_number(source_range['p50'])} / {_number(source_range['p90'])} stacks</dd>
        <dt>Mapping</dt><dd><code>{_escape(replacement['distribution_mapping'])}</code></dd>
        <dt>Suppliers</dt><dd>{_escape(supplier_names)}</dd>{coverage_lineage}
      </dl>
    </div>
    <div>
      <h2>Frozen lineage</h2>
      <dl>
        <dt>HBM result</dt><dd><code>{_escape(source['sha256'])}</code></dd>{draw_lineage}
        <dt>Manufacturing</dt><dd><code>{_escape(lineage['sources']['manufacturing_scenario']['sha256'])}</code></dd>
        <dt>Capacity scopes</dt><dd>{len(source['capacity_scope_ids'])} unique declarations</dd>
        <dt>Double count</dt><dd>Aggregate HBM inputs are removed, not added beside supplier output.</dd>
      </dl>
    </div>
  </section>

  <section class="panel">
    <h2>Binding probability</h2>
    {_bottlenecks(result)}
  </section>

  <section class="panel">
    <h2>Highest-priority evidence gaps</h2>
    <table><thead><tr><th>Owner</th><th>Input</th><th>Influence</th><th>Confidence</th><th>Priority</th></tr></thead>
    <tbody>{_research_rows(result)}</tbody></table>
  </section>

  <p class="foot">{_escape(footnote)}</p>
</main></body></html>
"""
