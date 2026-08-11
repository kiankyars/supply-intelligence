"""Standalone dashboard for wafer-to-package manufacturing reconciliation."""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from .manufacturing_engine import OUTPUT_UNITS


OUTPUT_LABELS = {
    "logic_gross_dies_per_wafer": "Gross logic dies per wafer",
    "logic_defect_yield": "Logic defect yield",
    "logic_effective_known_good_yield": "Logic known-good yield",
    "logic_binned_yield": "Logic binned yield",
    "logic_gross_dies": "Gross logic dies",
    "logic_known_good_dies": "Known-good logic dies",
    "logic_binned_dies": "Binned logic dies",
    "logic_package_equivalents": "Logic package equivalents",
    "hbm_gross_dies_per_wafer": "Gross HBM dies per wafer",
    "hbm_gross_dies": "Gross HBM memory dies",
    "hbm_known_good_dies": "Known-good HBM dies",
    "hbm_raw_stacks": "Raw HBM stacks",
    "hbm_good_stacks": "Good HBM stacks",
    "hbm_package_equivalents": "HBM package equivalents",
    "hbm_gb_per_accelerator": "HBM per accelerator",
    "hbm_memory_dies_per_accelerator": "HBM dies per accelerator",
    "package_assembly_start_capacity": "Assembly starts",
    "package_attempts": "Attempted packages",
    "package_assembly_yield": "Package assembly yield",
    "finished_accelerator_packages": "Finished accelerator packages",
    "complete_system_equivalents": "Complete system equivalents",
    "surplus_binned_logic_dies": "Surplus binned logic dies",
    "surplus_good_hbm_stacks": "Surplus good HBM stacks",
    "logic_die_utilization": "Binned logic die utilization",
    "hbm_stack_utilization": "Good HBM stack utilization",
    "assembly_start_utilization": "Assembly start utilization",
}

CONSTRAINT_LABELS = {
    "logic_binned_dies": "Binned logic dies",
    "hbm_good_stacks": "Good HBM stacks",
    "package_assembly_starts": "Package assembly starts",
}


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


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _distribution_text(distribution: dict[str, float], digits: int = 0) -> str:
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
    digits: int = 0,
) -> str:
    distribution = _metric(result, key)
    unit = OUTPUT_UNITS[key]
    return f"""
      <div class="flow-node">
        <span>{_escape(OUTPUT_LABELS[key])}</span>
        <strong>{_number(distribution['p50'], digits)}</strong>
        <small>{_escape(unit)} · P10 to P90 {_distribution_text(distribution, digits)}</small>
      </div>
    """


def _topology_card(label: str, estimate: dict[str, Any], context: str) -> str:
    return f"""
      <article class="topology-card">
        <span>{_escape(label)}</span>
        <strong>{_number(estimate['base'], 0)}</strong>
        <small>{_escape(estimate['unit'])}</small>
        <p>{_escape(context)}</p>
      </article>
    """


def _bottleneck_rows(result: dict[str, Any]) -> str:
    rows = []
    for item in result["bottlenecks"]:
        probability = item["probability"]
        rows.append(
            f"""
            <div class="bar-row">
              <span>{_escape(CONSTRAINT_LABELS[item['constraint']])}</span>
              <div class="bar-track" aria-hidden="true"><i style="width:{probability * 100:.4f}%"></i></div>
              <strong>{probability * 100:.1f}%</strong>
            </div>
            """
        )
    summary = ", ".join(
        f"{CONSTRAINT_LABELS[item['constraint']]} {item['probability'] * 100:.1f}%"
        for item in result["bottlenecks"]
    )
    return f'<div class="bar-chart" role="img" aria-label="Bottleneck probability: {_escape(summary)}">{"".join(rows)}</div>'


def _yield_rows(result: dict[str, Any]) -> str:
    keys = (
        "logic_defect_yield",
        "logic_effective_known_good_yield",
        "logic_binned_yield",
        "package_assembly_yield",
        "logic_die_utilization",
        "hbm_stack_utilization",
        "assembly_start_utilization",
    )
    rows = []
    for key in keys:
        distribution = _metric(result, key)
        value = distribution["p50"]
        rows.append(
            f"""
            <div class="bar-row">
              <span>{_escape(OUTPUT_LABELS[key])}</span>
              <div class="bar-track" aria-hidden="true"><i style="width:{value * 100:.4f}%"></i></div>
              <strong>{_percentage(value)}</strong>
            </div>
            """
        )
    summary = ", ".join(
        f"{OUTPUT_LABELS[key]} {_percentage(_metric(result, key)['p50'])}"
        for key in keys
    )
    return f'<div class="bar-chart yield-chart" role="img" aria-label="Median yields and utilization: {_escape(summary)}">{"".join(rows)}</div>'


def _inventory_rows(result: dict[str, Any]) -> str:
    keys = ("surplus_binned_logic_dies", "surplus_good_hbm_stacks")
    return "".join(
        f"""
        <tr>
          <td>{_escape(OUTPUT_LABELS[key])}</td>
          <td class="mono"><strong>{_number(_metric(result, key)['p50'])}</strong></td>
          <td class="mono">{_distribution_text(_metric(result, key))}</td>
          <td>{_escape(OUTPUT_UNITS[key])}</td>
        </tr>
        """
        for key in keys
    )


def _reference_section(result: dict[str, Any]) -> str:
    comparisons = result["reference_comparisons"]
    if not comparisons:
        return ""
    rows = []
    for item in comparisons:
        role = (
            "Product capacity input"
            if item["usable_as_product_capacity"]
            else "Scale control only"
        )
        rows.append(
            f"""
            <tr>
              <td><strong>{_escape(item['name'])}</strong><span>{_escape(item['period'])} · {_escape(role)}</span><span>{_escape(item['notes'])}</span></td>
              <td class="mono"><strong>{_number(item['reference_value']['p50'])}</strong><span>{_distribution_text(item['reference_value'])} {_escape(item['unit'])}</span></td>
              <td class="mono"><strong>{_number(item['modeled_target']['p50'])}</strong><span>{_distribution_text(item['modeled_target'])} {_escape(item['unit'])}</span></td>
              <td class="mono"><strong>{_percentage(item['target_share']['p50'])}</strong><span>{_percentage(item['target_share']['p10'])} to {_percentage(item['target_share']['p90'])}</span></td>
            </tr>
            """
        )
    return f"""
    <section>
      <div class="section-head"><div><div class="section-label">External scale controls</div><h2>Reported totals bound, but do not allocate, product supply</h2></div><p>A company-wide or prior-period total cannot be substituted for product-specific wafer starts.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Reference</th><th>Reported total</th><th>Modeled target</th><th>Target share</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
    </section>
    """


def _research_rows(result: dict[str, Any]) -> str:
    return "".join(
        f"""
        <tr>
          <td><strong>{_escape(item['parameter'])}</strong><span>{_escape(item['owner_type'])} · {_escape(item['owner_id'])}</span></td>
          <td>{_escape(CONSTRAINT_LABELS.get(item['branch'], item['branch']))}<span>{_escape(item['influence_method'])}</span></td>
          <td class="mono">{_percentage(item['influence_probability'])}</td>
          <td class="mono">{_percentage(item['confidence'])}</td>
          <td class="mono"><strong>{item['research_priority']:.3f}</strong></td>
        </tr>
        """
        for item in result["research_queue"]
    )


def _input_groups(result: dict[str, Any]) -> Iterable[tuple[str, str, dict[str, Any]]]:
    inputs = result["inputs"]
    yield (
        "logic_wafer",
        inputs["logic"]["wafer"]["name"],
        {
            key: value
            for key, value in inputs["logic"]["wafer"].items()
            if isinstance(value, dict) and "low" in value
        },
    )
    yield (
        "logic_yield",
        "Logic yield and binning",
        {
            key: value
            for key, value in inputs["logic"].items()
            if isinstance(value, dict) and "low" in value
        },
    )
    yield (
        "hbm_wafer",
        inputs["hbm"]["wafer"]["name"],
        {
            key: value
            for key, value in inputs["hbm"]["wafer"].items()
            if isinstance(value, dict) and "low" in value
        },
    )
    yield (
        "hbm_stack",
        "HBM die and stack flow",
        {
            key: value
            for key, value in inputs["hbm"].items()
            if isinstance(value, dict) and "low" in value
        },
    )
    yield (
        "package",
        "Advanced package assembly",
        {
            key: value
            for key, value in inputs["package"].items()
            if isinstance(value, dict) and "low" in value
        },
    )
    references = {
        item["id"]: item["estimate"] for item in inputs["references"]
    }
    if references:
        yield "reference", "External scale controls", references


def _input_audit(result: dict[str, Any]) -> str:
    groups = []
    for group_id, label, estimates in _input_groups(result):
        rows = []
        for parameter, estimate in estimates.items():
            source_links = " ".join(
                f'<a href="#source-{_safe_id(source_id)}">{_escape(source_id)}</a>'
                for source_id in estimate["evidence_ids"]
            )
            rows.append(
                f"""
                <tr>
                  <td><strong>{_escape(parameter)}</strong><span>{_escape(estimate['methodology'])}</span><span><b>Confirms:</b> {_escape(estimate['confirming_evidence'])}</span><span><b>Falsifies:</b> {_escape(estimate['falsifying_evidence'])}</span></td>
                  <td class="mono">{_number(estimate['low'], 3)} / {_number(estimate['base'], 3)} / {_number(estimate['high'], 3)} {_escape(estimate['unit'])}</td>
                  <td>{_escape(estimate['posture'])}<span>confidence {estimate['confidence']:.0%}</span><span>updated {_escape(estimate['last_updated'])}</span></td>
                  <td>{source_links}</td>
                </tr>
                """
            )
        groups.append(
            f"""
            <details id="input-{_escape(group_id)}">
              <summary><strong>{_escape(label)}</strong><span>{len(estimates)} estimates</span></summary>
              <div class="table-wrap"><table class="audit-table"><thead><tr><th>Parameter and method</th><th>Low / base / high</th><th>Posture</th><th>Evidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
            </details>
            """
        )
    return "".join(groups)


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


def render_manufacturing_dashboard(result: dict[str, Any]) -> str:
    scenario = result["scenario"]
    topology = result["topology"]
    finished = _metric(result, "finished_accelerator_packages")
    systems = _metric(result, "complete_system_equivalents")
    top_constraint = result["bottlenecks"][0]
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in result["warnings"])
    posture = "Illustrative manufacturing run" if scenario["synthetic"] else "Evidence-backed manufacturing run"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{_escape(scenario['name'])}</title>
  <style>
    :root {{ color-scheme:light dark; --bg:#f2efe8; --paper:#fbfaf6; --ink:#171a18; --muted:#62675f; --line:#d4cfc3; --soft:#e7e2d8; --green:#006b5d; --green-soft:#cfe4df; --orange:#b45b2d; --warning:#7b4717; --warning-bg:#fff0d8; }}
    @media (prefers-color-scheme:dark) {{ :root {{ --bg:#151816; --paper:#202421; --ink:#f1efe8; --muted:#adb3aa; --line:#3d443e; --soft:#303630; --green:#68c7b4; --green-soft:#294a43; --orange:#e59a70; --warning:#ffd29a; --warning-bg:#3a2c1d; }} }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.48 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    a {{ color:var(--green); overflow-wrap:anywhere; }}
    header,main {{ width:min(1420px,calc(100% - 40px)); margin-inline:auto; }}
    header {{ display:flex; justify-content:space-between; align-items:end; gap:28px; padding:34px 0 22px; border-bottom:1px solid var(--line); }}
    h1,h2,h3 {{ font-family:Georgia,"Times New Roman",serif; font-weight:500; }}
    h1 {{ margin:7px 0 5px; font-size:clamp(34px,5vw,64px); line-height:.98; letter-spacing:-.035em; }}
    h2 {{ margin:4px 0 0; font-size:28px; }}
    h3 {{ margin:0 0 4px; font-size:21px; }}
    p {{ margin:0; }}
    .kicker,.section-label {{ color:var(--green); font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.09em; text-transform:uppercase; }}
    .muted,.section-head p,small,td span,summary span,.stamp span {{ color:var(--muted); }}
    .stamp {{ text-align:right; }} .stamp strong,.stamp span {{ display:block; }} .stamp strong {{ font-size:20px; }}
    main {{ padding:24px 0 70px; }}
    .notice {{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:20px; padding:14px 16px; margin-bottom:20px; background:var(--warning-bg); border-left:4px solid var(--orange); }}
    .notice strong {{ color:var(--warning); }} .notice ul {{ margin:0; padding-left:18px; }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }}
    .summary-card,.topology-card {{ min-width:0; background:var(--paper); border:1px solid var(--line); padding:18px; }}
    .summary-card span,.summary-card small,.topology-card span,.topology-card small {{ display:block; color:var(--muted); }}
    .summary-card strong {{ display:block; margin:5px 0; font:500 36px/1.05 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .section-head {{ display:flex; justify-content:space-between; align-items:end; gap:24px; margin:34px 0 12px; }}
    .section-head p {{ max-width:560px; text-align:right; }}
    .topology-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }}
    .topology-card strong {{ display:inline-block; margin:5px 6px 0 0; font:500 28px/1 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .topology-card small {{ display:inline; }} .topology-card p {{ margin-top:10px; color:var(--muted); }}
    .flow {{ min-width:0; }}
    .flow-lane {{ display:grid; grid-template-columns:110px repeat(4,minmax(0,1fr)); gap:12px; align-items:stretch; margin-bottom:12px; }}
    .lane-label {{ display:flex; align-items:center; color:var(--green); font-weight:700; border-top:3px solid var(--green); }}
    .flow-lane.hbm .lane-label {{ color:var(--orange); border-color:var(--orange); }}
    .flow-node {{ min-width:0; position:relative; padding:13px; background:var(--paper); border-top:3px solid var(--green); }}
    .hbm .flow-node {{ border-color:var(--orange); }}
    .flow-node:not(:last-child)::after {{ content:"→"; position:absolute; right:-10px; top:50%; z-index:2; color:var(--muted); transform:translate(50%,-50%); }}
    .flow-node span,.flow-node small {{ display:block; }} .flow-node span {{ min-height:42px; }}
    .flow-node strong {{ display:block; margin:3px 0; font:500 23px/1.08 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .convergence {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:16px 0 0 122px; padding-top:18px; border-top:1px solid var(--line); }}
    .convergence .flow-node {{ border-color:var(--ink); }}
    .two-column {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:22px; }}
    .panel {{ min-width:0; background:var(--paper); padding:18px; border:1px solid var(--line); }}
    .bar-chart {{ margin-top:18px; }}
    .bar-row {{ display:grid; grid-template-columns:minmax(145px,1.1fr) 1.6fr 58px; gap:10px; align-items:center; margin:13px 0; }}
    .bar-track {{ height:13px; background:var(--soft); overflow:hidden; }} .bar-track i {{ display:block; height:100%; background:var(--green); }}
    .yield-chart .bar-track i {{ background:var(--orange); }} .bar-row strong {{ text-align:right; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .table-wrap {{ min-width:0; max-width:100%; overflow-x:auto; background:var(--paper); border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; min-width:640px; }}
    th,td {{ padding:12px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.06em; }} tbody tr:last-child td {{ border-bottom:0; }}
    td span {{ display:block; max-width:660px; margin-top:3px; font-size:12px; }} .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums; }}
    details {{ border-top:1px solid var(--line); }} details:last-child {{ border-bottom:1px solid var(--line); }}
    summary {{ display:flex; justify-content:space-between; gap:16px; padding:14px 5px; cursor:pointer; }} details .table-wrap {{ margin-bottom:14px; }} .audit-table {{ min-width:900px; }}
    footer {{ margin-top:36px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media (max-width:960px) {{ .flow-lane {{ grid-template-columns:90px repeat(2,minmax(0,1fr)); }} .lane-label {{ grid-row:1/3; }} .flow-node:nth-of-type(3)::after {{ content:none; }} .convergence {{ margin-left:102px; }} }}
    @media (max-width:760px) {{ .summary-grid,.topology-grid,.two-column {{ grid-template-columns:minmax(0,1fr); }} .section-head {{ display:block; }} .section-head p {{ margin-top:6px; text-align:left; }} }}
    @media (max-width:560px) {{ header,main {{ width:min(1420px,calc(100% - 24px)); }} header {{ display:block; }} .stamp {{ margin-top:16px; text-align:left; }} .notice {{ grid-template-columns:minmax(0,1fr); gap:5px; }} .flow-lane {{ grid-template-columns:minmax(0,1fr); }} .lane-label {{ grid-row:auto; min-height:30px; }} .flow-node:not(:last-child)::after {{ content:"↓"; right:50%; top:auto; bottom:-14px; transform:translate(50%,50%); }} .convergence {{ grid-template-columns:minmax(0,1fr); margin-left:0; }} .convergence .flow-node:not(:last-child)::after {{ content:"↓"; }} .bar-row {{ grid-template-columns:minmax(0,1fr) 52px; }} .bar-track {{ grid-column:1/-1; grid-row:2; }} summary {{ display:block; }} }}
  </style>
</head>
<body>
  <header>
    <div><div class="kicker">Wafer to finished package · {_escape(scenario['quarter'])}</div><h1>{_escape(scenario['name'])}</h1><p class="muted">Physical conversion of logic wafers, HBM memory dies, stacks, and advanced-package starts.</p></div>
    <div class="stamp"><span>As of</span><strong>{_escape(scenario['as_of_date'])}</strong><span>{scenario['samples']:,} draws · seed {scenario['seed']}</span></div>
  </header>
  <main>
    <aside class="notice"><strong>{_escape(posture)}</strong><ul>{warnings}</ul></aside>
    <section class="summary-grid" aria-label="Manufacturing output summary">
      <article class="summary-card"><span>Finished accelerator packages</span><strong>{_number(finished['p50'])}</strong><small>P10 to P90 {_distribution_text(finished)}</small></article>
      <article class="summary-card"><span>Complete system equivalents</span><strong>{_number(systems['p50'])}</strong><small>P10 to P90 {_distribution_text(systems)}</small></article>
      <article class="summary-card"><span>Most frequent bottleneck</span><strong>{top_constraint['probability'] * 100:.1f}%</strong><small>{_escape(CONSTRAINT_LABELS[top_constraint['constraint']])}</small></article>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Product topology</div><h2>Audited conversion factors</h2></div><p>Reported and derived product structure is kept separate from synthetic manufacturing assumptions.</p></div>
      <div class="topology-grid">
        {_topology_card('Logic dies per accelerator', topology['logic_dies_per_accelerator'], 'NVIDIA reports two reticle-limit dies in one Blackwell GPU.')}
        {_topology_card('HBM placements per accelerator', topology['hbm_stacks_per_accelerator'], f"{_number(topology['hbm_stack_capacity_gb']['base'])} GB per reference placement, {_number(_metric(result, 'hbm_gb_per_accelerator')['p50'])} GB total.")}
        {_topology_card('Accelerators per complete system', topology['accelerators_per_system'], 'The system unit is one GB200 NVL72 rack-scale system.')}
      </div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Physical flow</div><h2>Two upstream branches converge at package assembly</h2></div><p>Every node shows the median and P10 to P90 output for the quarter.</p></div>
      <div class="flow" aria-label="Logic and HBM manufacturing flow">
        <div class="flow-lane logic"><div class="lane-label">Logic</div>{_flow_node(result, 'logic_gross_dies')}{_flow_node(result, 'logic_known_good_dies')}{_flow_node(result, 'logic_binned_dies')}{_flow_node(result, 'logic_package_equivalents')}</div>
        <div class="flow-lane hbm"><div class="lane-label">HBM</div>{_flow_node(result, 'hbm_gross_dies')}{_flow_node(result, 'hbm_known_good_dies')}{_flow_node(result, 'hbm_good_stacks')}{_flow_node(result, 'hbm_package_equivalents')}</div>
        <div class="convergence">{_flow_node(result, 'package_attempts')}{_flow_node(result, 'finished_accelerator_packages')}{_flow_node(result, 'complete_system_equivalents')}</div>
      </div>
    </section>

    <section class="two-column">
      <div><div class="section-head"><div><div class="section-label">Constraint risk</div><h2>Binding probability</h2></div></div><div class="panel"><p class="muted">Share of Monte Carlo draws in which each upstream branch sets package attempts.</p>{_bottleneck_rows(result)}</div></div>
      <div><div class="section-head"><div><div class="section-label">Process retention</div><h2>Yields and utilization</h2></div></div><div class="panel"><p class="muted">Median sampled yield and utilization. These values do not measure source confidence.</p>{_yield_rows(result)}</div></div>
    </section>

    {_reference_section(result)}

    <section>
      <div class="section-head"><div><div class="section-label">Evidence replacement queue</div><h2>Source the assumptions that can move output first</h2></div><p>Priority equals current-run influence multiplied by one minus input confidence. It is conditional on this scenario.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Synthetic input</th><th>Output path</th><th>Influence</th><th>Confidence</th><th>Priority</th></tr></thead><tbody>{_research_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Shadow capacity</div><h2>Usable upstream inventory held back</h2></div><p>Surplus is measured after the binding package-attempt limit, before final package yield.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Inventory</th><th>P50</th><th>P10 to P90</th><th>Unit</th></tr></thead><tbody>{_inventory_rows(result)}</tbody></table></div>
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Input audit</div><h2>Ranges, methods, posture, and evidence</h2></div><p>Open a group to trace each numerical assumption to its source record and falsification method.</p></div>
      {_input_audit(result)}
    </section>

    <section>
      <div class="section-head"><div><div class="section-label">Source ledger</div><h2>Evidence used by this run</h2></div><p>The Micron HBM3E record is a generic stack reference. It does not identify the GB200 memory supplier.</p></div>
      <div class="table-wrap"><table><thead><tr><th>Evidence ID</th><th>Source</th><th>Kind</th><th>Published</th><th>Retrieved</th></tr></thead><tbody>{_source_rows(result)}</tbody></table></div>
    </section>

    <footer>{_escape(result['methodology']['gross_dies_per_wafer'])} {_escape(result['methodology']['package_output'])}</footer>
  </main>
</body>
</html>
"""
