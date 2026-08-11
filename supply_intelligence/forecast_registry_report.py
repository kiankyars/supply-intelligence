"""Standalone dashboard for a pre-outcome native forecast registry."""

from __future__ import annotations

import html
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _breakable(value: object) -> str:
    return _escape(value).replace("_", "_<wbr>").replace("-", "-<wbr>")


def _number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.3g}"


def _forecast_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["forecasts"]:
        distribution = item["distribution"]
        maturity = item["maturity"]
        event = item["event"]
        event_text = "Not registered"
        if event is not None:
            event_text = (
                f"{event['operator'].replace('_', ' ')} {_number(event['threshold'])} "
                f"· p={event['forecast_probability']:.3f}"
            )
        rows.append(
            f"""
            <tr>
              <td><strong>{_breakable(item['metric'])}</strong><span>{_breakable(item['id'])}</span></td>
              <td class="mono">{_number(distribution['p10'])} / <strong>{_number(distribution['p50'])}</strong> / {_number(distribution['p90'])}<span>{_escape(item['unit'])}</span></td>
              <td>{_escape(item['target']['entity'])}<span>{_escape(item['target']['geography'])} · {_escape(item['target']['quantity_semantics'])}</span></td>
              <td><span class="pill pending">{_escape(maturity['status'].replace('_', ' '))}</span><span>earliest {_escape(item['outcome_contract']['earliest_observed_at'])}</span></td>
              <td>{_escape(event_text)}<span>{'exact frozen draws' if event is not None else 'no post-hoc threshold'}</span></td>
            </tr>
            """
        )
    return "".join(rows)


def _contract_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["forecasts"]:
        target = item["target"]
        contract = item["outcome_contract"]
        rows.append(
            f"""
            <tr>
              <td><strong>{_breakable(item['metric'])}</strong><span>{_escape(item['period'])} · cutoff {_escape(target['cutoff_date'])}</span></td>
              <td>{_escape(target['scope_definition'])}</td>
              <td>{_escape(contract['measurement_method'])}<span>Accepted posture: {_escape(', '.join(contract['acceptable_postures']))}</span></td>
              <td>{_escape(contract['required_evidence'])}<span>Expected by {_escape(contract['expected_evidence_by'])} · revisions through {_escape(contract['revision_window_end'])}</span></td>
              <td>{_escape(contract['known_observability_gap'])}</td>
            </tr>
            """
        )
    return "".join(rows)


def render_forecast_registry_dashboard(result: Mapping[str, Any]) -> str:
    registry = result["registry"]
    source = result["source"]
    summary = result["summary"]
    boundary = (
        "This is a real pre-outcome native-model freeze, but the underlying scenario is synthetic. "
        "It is not an estimate of actual production, shipments, or deployments and cannot calibrate the model."
        if source["synthetic"]
        else "This is a pre-outcome native-model freeze. It contains no actuals or scores; later evidence still needs scope review."
    )
    return f"""<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(registry['id'])}</title>
  <style>
    :root {{ --ink:#13251f; --paper:#f4f1e8; --card:#fffdf7; --line:#d8d5ca; --muted:#65716c; --green:#11684d; --amber:#96610d; --amber-soft:#f5e7c4; --shadow:0 18px 48px rgba(19,37,31,.08); }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1500px,calc(100% - 40px)); margin:auto; padding:42px 0 72px; }}
    header {{ display:flex; flex-direction:column; gap:17px; padding:36px; border-radius:24px; color:#fffdf8; background:linear-gradient(135deg,#13251f,#24493d); box-shadow:var(--shadow); }}
    .eyebrow {{ color:#9ed1bd; font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ max-width:1050px; margin:0; font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif; letter-spacing:-.035em; }} header p {{ max-width:980px; margin:0; color:#d4dfda; font-size:17px; }}
    .warning {{ padding:14px 16px; border:1px solid #71877d; border-radius:14px; color:#fff2c9; background:rgba(255,255,255,.04); }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:20px 0 34px; }}
    .card,section {{ border:1px solid var(--line); border-radius:18px; background:var(--card); box-shadow:var(--shadow); }} .card {{ padding:20px; }}
    .card span {{ display:block; color:var(--muted); font-size:12px; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }} .card strong {{ display:block; margin:6px 0 2px; font:700 31px/1 Georgia,serif; overflow-wrap:anywhere; }} .card small {{ color:var(--muted); }}
    section {{ margin-top:20px; padding:26px; overflow:hidden; }} .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:24px; margin-bottom:18px; }} h2 {{ margin:3px 0 0; font:700 29px/1.1 Georgia,serif; }} .section-head p {{ max-width:650px; margin:0; color:var(--muted); }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:14px; }} table {{ width:100%; table-layout:fixed; border-collapse:collapse; }} th {{ padding:11px 13px; background:#ece9df; color:#58655f; font-size:11px; letter-spacing:.08em; text-align:left; text-transform:uppercase; }} td {{ padding:13px; border-top:1px solid var(--line); vertical-align:top; overflow-wrap:anywhere; }} td strong,td span {{ display:block; }} td span {{ margin-top:3px; color:var(--muted); font-size:12px; }}
    .mono {{ font-variant-numeric:tabular-nums; }} .pill {{ display:inline-block; width:fit-content; padding:4px 8px; border-radius:999px; font-size:11px; font-weight:800; }} .pill.pending {{ color:var(--amber); background:var(--amber-soft); }}
    footer {{ margin-top:24px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }} @media(max-width:950px) {{ .cards {{ grid-template-columns:1fr 1fr; }} .section-head {{ display:block; }} table {{ min-width:1100px; }} }} @media(max-width:600px) {{ main {{ width:calc(100% - 20px); padding-top:10px; }} header,section {{ padding:20px; border-radius:14px; }} .cards {{ grid-template-columns:1fr; }} }}
  </style>
</head><body><main>
  <header><div class="eyebrow">Native forecast registry · {_escape(registry['as_of_date'])}</div><h1>Freeze the forecast before the outcome exists.</h1><p>The source release, all raw draws, metric scopes, maturity dates, and later evidence tests are fixed now. Actuals and scores remain absent by design.</p><div class="warning"><strong>Boundary:</strong> {_escape(boundary)}</div></header>
  <div class="cards">
    <article class="card"><span>Registered metrics</span><strong>{summary['forecast_count']}</strong><small>one immutable source vintage</small></article>
    <article class="card"><span>Frozen raw draws</span><strong>{summary['raw_draw_count']:,}</strong><small>summary fields replay exactly</small></article>
    <article class="card"><span>Current status</span><strong>{_escape(next(iter(summary['maturity_status_counts'])).replace('_', ' '))}</strong><small>evaluated at {_escape(registry['as_of_date'])}</small></article>
    <article class="card"><span>Scores emitted</span><strong>{summary['scores_emitted']}</strong><small>no outcome, no backfill</small></article>
  </div>
  <section><div class="section-head"><div><div class="eyebrow">Frozen distributions</div><h2>Native outputs retain their full draw history</h2></div><p>Each summary is recomputed from its selected draw column. Optional threshold probabilities use the exact frozen draws and cannot be chosen after an outcome.</p></div><div class="table-wrap"><table><thead><tr><th>Metric</th><th>P10 / P50 / P90</th><th>Target scope</th><th>Maturity</th><th>Frozen event</th></tr></thead><tbody>{_forecast_rows(result)}</tbody></table></div></section>
  <section><div class="section-head"><div><div class="eyebrow">Outcome contract</div><h2>Later evidence must match the scope fixed today</h2></div><p>A publication date alone is not enough. Product, entity, geography, quantity semantics, cutoff, and measurement method must remain comparable.</p></div><div class="table-wrap"><table><thead><tr><th>Metric / period</th><th>Exact scope</th><th>Measurement</th><th>Required evidence</th><th>Known gap</th></tr></thead><tbody>{_contract_rows(result)}</tbody></table></div></section>
  <footer>Registry recorded {_escape(registry['recorded_at'])}. Source result {_breakable(source['result_sha256'])}. No realized values or investment signals are present.</footer>
</main></body></html>
"""
