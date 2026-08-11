"""Standalone dashboard for reconciliation revision alerts."""

from __future__ import annotations

import html
import json
from typing import Any


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _alert_rows(report: dict[str, Any]) -> str:
    if not report["alerts"]:
        return '<p class="empty">No changes crossed the configured alert thresholds.</p>'
    rows = []
    for alert in report["alerts"]:
        details = {
            key: value
            for key, value in alert.items()
            if key not in {"id", "type", "severity", "path"}
        }
        rows.append(
            f"""
            <details class="alert alert-{_escape(alert['severity'])}">
              <summary><span class="severity">{_escape(alert['severity'])}</span><strong>{_escape(alert['type'].replace('_', ' '))}</strong><code>{_escape(alert['path'])}</code></summary>
              <div class="alert-body"><span>{_escape(alert['id'])}</span><pre>{_escape(json.dumps(details, indent=2, sort_keys=True, ensure_ascii=False))}</pre></div>
            </details>
            """
        )
    return "".join(rows)


def render_alert_dashboard(report: dict[str, Any]) -> str:
    counts = {
        severity: sum(item["severity"] == severity for item in report["alerts"])
        for severity in ("critical", "high", "medium", "info")
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Revision alerts · {_escape(report['scenario_id'])}</title>
  <style>
    :root {{ color-scheme:light dark; --bg:#f2efe8; --paper:#fbfaf6; --ink:#171a18; --muted:#62675f; --line:#d4cfc3; --green:#006b5d; --critical:#a7352a; --high:#b45b2d; --medium:#90731f; --info:#476b8e; }}
    @media (prefers-color-scheme:dark) {{ :root {{ --bg:#151816; --paper:#202421; --ink:#f1efe8; --muted:#adb3aa; --line:#3d443e; --green:#68c7b4; --critical:#ff8c82; --high:#e59a70; --medium:#d7c06c; --info:#90b5d9; }} }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    header,main {{ width:min(1180px,calc(100% - 40px)); margin-inline:auto; }} header {{ display:flex; justify-content:space-between; align-items:end; gap:28px; padding:34px 0 22px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:7px 0 5px; font:500 clamp(34px,5vw,60px)/.98 Georgia,"Times New Roman",serif; letter-spacing:-.035em; }} p {{ margin:0; }}
    .kicker {{ color:var(--green); font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.09em; text-transform:uppercase; }} .muted,.stamp span,.alert-body>span {{ color:var(--muted); }}
    .stamp {{ text-align:right; }} .stamp strong,.stamp span {{ display:block; }} .stamp strong {{ font-size:18px; }} main {{ padding:24px 0 70px; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:28px; }} .stat {{ min-width:0; padding:16px; background:var(--paper); border:1px solid var(--line); }} .stat span {{ display:block; color:var(--muted); }} .stat strong {{ display:block; margin-top:5px; font:500 30px/1 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .alert {{ border-top:1px solid var(--line); }} .alert:last-child {{ border-bottom:1px solid var(--line); }} summary {{ display:grid; grid-template-columns:78px minmax(180px,.7fr) minmax(0,1.3fr); gap:14px; align-items:center; padding:14px 5px; cursor:pointer; }}
    summary code {{ overflow-wrap:anywhere; color:var(--muted); }} .severity {{ font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; text-transform:uppercase; }} .alert-critical .severity {{ color:var(--critical); }} .alert-high .severity {{ color:var(--high); }} .alert-medium .severity {{ color:var(--medium); }} .alert-info .severity {{ color:var(--info); }}
    .alert-body {{ margin:0 0 14px 92px; padding:14px; background:var(--paper); border-left:3px solid var(--line); }} pre {{ max-width:100%; margin:8px 0 0; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }} .empty {{ padding:24px; background:var(--paper); border:1px solid var(--line); color:var(--muted); }}
    footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line); color:var(--muted); }}
    @media (max-width:720px) {{ .summary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} summary {{ grid-template-columns:68px minmax(0,1fr); }} summary code {{ grid-column:1/-1; }} .alert-body {{ margin-left:0; }} }}
    @media (max-width:480px) {{ header,main {{ width:min(1180px,calc(100% - 24px)); }} header {{ display:block; }} .stamp {{ margin-top:16px; text-align:left; }} }}
  </style>
</head>
<body>
  <header><div><div class="kicker">Frozen result comparison</div><h1>Revision alerts</h1><p class="muted">{_escape(report['scenario_id'])} · {_escape(report['result_format'])}</p></div><div class="stamp"><span>Previous</span><strong>{_escape(report['previous']['recorded_at'])}</strong><span>Current</span><strong>{_escape(report['current']['recorded_at'])}</strong></div></header>
  <main>
    <section class="summary" aria-label="Alert counts"><article class="stat"><span>Critical</span><strong>{counts['critical']}</strong></article><article class="stat"><span>High</span><strong>{counts['high']}</strong></article><article class="stat"><span>Medium</span><strong>{counts['medium']}</strong></article><article class="stat"><span>Total</span><strong>{report['alert_count']}</strong></article></section>
    <section aria-label="Revision alert details">{_alert_rows(report)}</section>
    <footer>Output threshold: {report['thresholds']['output_relative_change']:.0%}. Bottleneck probability threshold: {report['thresholds']['bottleneck_probability_change']:.0%}. Alerts are deterministic comparisons of frozen inputs and outputs, not trading signals.</footer>
  </main>
</body>
</html>
"""
