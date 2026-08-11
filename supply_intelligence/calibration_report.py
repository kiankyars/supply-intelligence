"""Standalone forecast calibration and backtest dashboard."""

from __future__ import annotations

import html
from typing import Any, Mapping


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _breakable(value: object) -> str:
    return _escape(value).replace("_", "_<wbr>").replace("-", "-<wbr>")


def _percent(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"


def _number(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.3g}"


def _score_rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["scores"]:
        coverage = "Inside" if item["inside_p10_p90"] else "Outside"
        coverage_class = "pass" if item["inside_p10_p90"] else "fail"
        event = "<span>—</span>"
        if item["event_score"] is not None:
            event = (
                f"<span>p={item['event_score']['forecast_probability']:.2f}</span>"
                f"<span>realized={str(item['event_score']['realized']).lower()}</span>"
                f"<span>Brier={item['event_score']['brier_score']:.3f}</span>"
            )
        rows.append(
            f"""
            <tr>
              <td><strong>{_breakable(item['forecast_metric'])}</strong><span>{_breakable(item['forecast_id'])} · {_escape(item['period'])}</span></td>
              <td>{_breakable(item['metric_class'])}<span>{_breakable(item['source_family'])}</span></td>
              <td class="mono">{_number(item['forecast_p10'])} / <strong>{_number(item['forecast_p50'])}</strong> / {_number(item['forecast_p90'])}<span>{_escape(item['unit'])}</span></td>
              <td class="mono"><strong>{_number(item['actual_value'])}</strong><span>{_escape(item['actual_posture'])} · {_escape(item['observed_at'])}</span></td>
              <td><span class="pill {coverage_class}">{coverage}</span><span>miss {_number(item['interval_miss'])}</span></td>
              <td class="mono {'negative-text' if item['signed_error'] > 0 else 'positive-text'}">{_number(item['signed_error'])}<span>{_percent(item['signed_error_ratio'], signed=True)} of actual</span></td>
              <td class="mono">{item['normalized_mean_pinball_loss']:.4f}</td>
              <td>{event}</td>
            </tr>
            """
        )
    return "".join(rows)


def _group_rows(groups: Mapping[str, Mapping[str, Any]]) -> str:
    rows = []
    for name, item in groups.items():
        proposal = item["calibration_proposal"]
        parameters = "Not estimated"
        if proposal["p50_multiplier"] is not None:
            parameters = (
                f"P50 × {proposal['p50_multiplier']:.3f}; "
                f"half-width × {proposal['half_width_multiplier']:.3f}"
            )
        rows.append(
            f"""
            <tr>
              <td><strong>{_breakable(name)}</strong></td>
              <td class="mono">{item['count']}</td>
              <td class="mono">{_percent(item['p10_p90_coverage_rate'])}</td>
              <td class="mono">{_percent(item['mean_signed_error_ratio'], signed=True)}</td>
              <td class="mono">{item['mean_normalized_pinball_loss']:.4f}</td>
              <td class="mono">{'N/A' if item['mean_brier_score'] is None else f"{item['mean_brier_score']:.4f}"}</td>
              <td><span class="pill neutral">{_escape(proposal['status'].replace('_', ' '))}</span><span>{_escape(parameters)} · never auto-applied</span></td>
            </tr>
            """
        )
    return "".join(rows)


def render_calibration_dashboard(result: dict[str, Any]) -> str:
    dataset = result["dataset"]
    summary = result["summary"]
    boundary = (
        "<div class=\"warning\"><strong>Boundary:</strong> this checked dataset is "
        "synthetic. It validates the scoring and release contract; it is not evidence "
        "about historical Blackwell forecast accuracy.</div>"
        if dataset["synthetic"]
        else "<div class=\"warning\"><strong>Evidence-backed run:</strong> inspect "
        "outcome definitions, revisions, and source-family dependence before using "
        "these diagnostics.</div>"
    )
    return f"""<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(dataset['id'])}</title>
  <style>
    :root {{ --ink:#14231d; --paper:#f4f2ea; --card:#fffdf8; --line:#d8d7ce; --muted:#66736d; --green:#0f6b4b; --green-soft:#dceee5; --red:#a13d33; --red-soft:#f5ddd9; --amber:#98600a; --amber-soft:#f7e9c6; --shadow:0 18px 50px rgba(20,35,29,.08); }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    main {{ width:min(1500px,calc(100% - 40px)); margin:auto; padding:42px 0 72px; }}
    header {{ display:flex; flex-direction:column; gap:18px; padding:36px; border-radius:24px; color:#fffdf8; background:var(--ink); box-shadow:var(--shadow); }}
    .eyebrow {{ color:#9fd0bd; font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ max-width:1100px; margin:0; font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif; letter-spacing:-.035em; }} header p {{ max-width:960px; margin:0; color:#d2ddd7; font-size:17px; }}
    .warning {{ width:100%; padding:14px 16px; border:1px solid #6c756f; border-radius:14px; color:#fff4cf; background:rgba(255,255,255,.04); }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:20px 0 34px; }}
    .card,section {{ border:1px solid var(--line); border-radius:18px; background:var(--card); box-shadow:var(--shadow); }} .card {{ padding:20px; }}
    .card span {{ display:block; color:var(--muted); font-size:12px; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }} .card strong {{ display:block; margin:6px 0 2px; font:700 32px/1 Georgia,serif; }} .card small {{ color:var(--muted); }}
    section {{ margin-top:20px; padding:26px; overflow:hidden; }} .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:24px; margin-bottom:18px; }} h2 {{ margin:3px 0 0; font:700 29px/1.1 Georgia,serif; }} .section-head p {{ max-width:640px; margin:0; color:var(--muted); }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:14px; }} table {{ width:100%; min-width:0; table-layout:fixed; border-collapse:collapse; }} th {{ padding:11px 13px; background:#ecebe4; color:#58665f; font-size:11px; letter-spacing:.08em; text-align:left; text-transform:uppercase; }} td {{ padding:13px; border-top:1px solid var(--line); vertical-align:top; }} th,td {{ overflow-wrap:anywhere; }} td strong,td span {{ display:block; }} td span {{ margin-top:3px; color:var(--muted); font-size:12px; }}
    .mono {{ font-variant-numeric:tabular-nums; }} .pill {{ display:inline-block; width:fit-content; padding:4px 8px; border-radius:999px; font-size:11px; font-weight:800; }} .pill.pass {{ color:var(--green); background:var(--green-soft); }} .pill.fail {{ color:var(--red); background:var(--red-soft); }} .pill.neutral {{ color:var(--amber); background:var(--amber-soft); }} .positive-text {{ color:var(--green); }} .negative-text {{ color:var(--red); }}
    footer {{ margin-top:24px; color:var(--muted); font-size:12px; }} @media(max-width:950px) {{ .cards {{ grid-template-columns:1fr 1fr; }} .section-head {{ display:block; }} table {{ min-width:1120px; }} }} @media(max-width:600px) {{ main {{ width:calc(100% - 20px); padding-top:10px; }} header,section {{ padding:20px; border-radius:14px; }} .cards {{ grid-template-columns:1fr; }} }}
  </style>
</head><body><main>
  <header><div class="eyebrow">Forecast calibration · {_escape(dataset['as_of_date'])}</div><h1>Score frozen forecasts before changing their ranges.</h1><p>Coverage, bias, quantile loss, event probability, and source-family error stay separate. Recalibration parameters require enough history and a holdout before use.</p>{boundary}</header>
  <div class="cards">
    <article class="card"><span>Scored outcomes</span><strong>{summary['count']}</strong><small>{len(result['forecast_lineage'])} frozen forecast vintage(s)</small></article>
    <article class="card"><span>P10–P90 coverage</span><strong>{_percent(summary['p10_p90_coverage_rate'])}</strong><small>target interpretation: nominal 80%</small></article>
    <article class="card"><span>Mean signed bias</span><strong>{_percent(summary['mean_signed_error_ratio'], signed=True)}</strong><small>positive means overforecast</small></article>
    <article class="card"><span>Mean Brier</span><strong>{'N/A' if summary['mean_brier_score'] is None else f"{summary['mean_brier_score']:.3f}"}</strong><small>{summary['brier_event_count']} scored event(s)</small></article>
  </div>
  <section><div class="section-head"><div><div class="eyebrow">Outcome-level audit</div><h2>Every realized value stays tied to one prior forecast</h2></div><p>Signed error is forecast P50 minus actual. Pinball loss tests quantile placement; Brier scores test threshold-event probabilities under the documented triangular approximation.</p></div><div class="table-wrap"><table><thead><tr><th>Metric</th><th>Class / source</th><th>Forecast P10 / P50 / P90</th><th>Outcome</th><th>Coverage</th><th>Bias</th><th>Normalized pinball</th><th>Event score</th></tr></thead><tbody>{_score_rows(result)}</tbody></table></div></section>
  <section><div class="section-head"><div><div class="eyebrow">Metric-class calibration</div><h2>Do not tune on thin history</h2></div><p>Proposed P50 and width multipliers remain ineligible until the group reaches its minimum and passes holdout validation.</p></div><div class="table-wrap"><table><thead><tr><th>Metric class</th><th>N</th><th>Coverage</th><th>Bias</th><th>Pinball</th><th>Brier</th><th>Proposal</th></tr></thead><tbody>{_group_rows(result['by_metric_class'])}</tbody></table></div></section>
  <section><div class="section-head"><div><div class="eyebrow">Source-family error</div><h2>Find systematic evidence bias</h2></div><p>Syndicated or shared-source observations should retain one family so correlated errors are visible rather than counted as independent confirmation. These aggregates never emit shared parameters.</p></div><div class="table-wrap"><table><thead><tr><th>Source family</th><th>N</th><th>Coverage</th><th>Bias</th><th>Pinball</th><th>Brier</th><th>Treatment</th></tr></thead><tbody>{_group_rows(result['by_source_family'])}</tbody></table></div></section>
  <footer>Recorded {_escape(dataset['recorded_at'])}. Calibration proposals never mutate a forecast automatically and are not investment signals.</footer>
</main></body></html>
"""
