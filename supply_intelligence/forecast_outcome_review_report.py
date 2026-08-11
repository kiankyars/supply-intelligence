"""Dashboard for forecast outcome dispositions and comparable scores."""

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


def _rows(result: Mapping[str, Any]) -> str:
    rows = []
    for item in result["dispositions"]:
        score = item["score"]
        forecast = "—"
        actual = "—"
        coverage = "Not scored"
        event = "—"
        if score is not None:
            forecast = (
                f"{_number(score['forecast_p10'])} / "
                f"{_number(score['forecast_p50'])} / {_number(score['forecast_p90'])}"
            )
            actual = _number(score["actual_value"])
            coverage = "Inside" if score["inside_p10_p90"] else "Outside"
            if score["event_score"] is not None:
                event = (
                    f"p={score['event_score']['forecast_probability']:.3f} · "
                    f"Brier={score['event_score']['brier_score']:.3f}"
                )
        rows.append(
            f"""
            <tr>
              <td><strong>{_breakable(item['metric'])}</strong><span>{_breakable(item['forecast_id'])}</span></td>
              <td><span class="pill {item['status']}">{_escape(item['status'].replace('_', ' '))}</span><span>{_escape(item['calendar_status'].replace('_', ' '))}</span></td>
              <td class="mono">{_escape(forecast)}<span>{_escape(item['unit'])}</span></td>
              <td class="mono">{_escape(actual)}<span>{_escape(coverage)}</span></td>
              <td>{_escape(event)}</td>
              <td>{_escape(item['rationale'])}<span>{_escape(item['reviewer'])} · {_escape(item['reviewed_at'])}</span></td>
            </tr>
            """
        )
    return "".join(rows)


def render_forecast_outcome_review_dashboard(result: Mapping[str, Any]) -> str:
    review = result["review"]
    summary = result["summary"]
    statuses = ", ".join(
        f"{name.replace('_', ' ')} {count}"
        for name, count in summary["disposition_status_counts"].items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(review['id'])}</title>
<style>
:root{{--ink:#17241f;--paper:#f4f1e8;--card:#fffdf7;--line:#d8d5ca;--muted:#66716c;--amber:#96610d;--amber-soft:#f5e7c4;--green:#126448;--green-soft:#dceee5;--red:#9f4037;--red-soft:#f4ded9;--shadow:0 18px 48px rgba(23,36,31,.08)}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{width:min(1500px,calc(100% - 40px));margin:auto;padding:42px 0 72px}}header{{display:flex;flex-direction:column;gap:17px;padding:36px;border-radius:24px;color:#fffdf8;background:linear-gradient(135deg,#17241f,#3d4d43);box-shadow:var(--shadow)}}.eyebrow{{color:#afd3c4;font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}}h1{{max-width:1100px;margin:0;font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif;letter-spacing:-.035em}}header p{{max-width:970px;margin:0;color:#d7dfdb;font-size:17px}}.warning{{padding:14px 16px;border:1px solid #77867e;border-radius:14px;color:#fff2c9;background:rgba(255,255,255,.04)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0 34px}}.card,section{{border:1px solid var(--line);border-radius:18px;background:var(--card);box-shadow:var(--shadow)}}.card{{padding:20px}}.card span{{display:block;color:var(--muted);font-size:12px;font-weight:750;letter-spacing:.07em;text-transform:uppercase}}.card strong{{display:block;margin:6px 0 2px;font:700 31px/1 Georgia,serif;overflow-wrap:anywhere}}.card small{{color:var(--muted)}}section{{padding:26px;overflow:hidden}}.section-head{{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:18px}}h2{{margin:3px 0 0;font:700 29px/1.1 Georgia,serif}}.section-head p{{max-width:650px;margin:0;color:var(--muted)}}.table-wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:14px}}table{{width:100%;table-layout:fixed;border-collapse:collapse}}th{{padding:11px 13px;background:#ece9df;color:#58655f;font-size:11px;letter-spacing:.08em;text-align:left;text-transform:uppercase}}td{{padding:13px;border-top:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}}td strong,td span{{display:block}}td span{{margin-top:3px;color:var(--muted);font-size:12px}}.mono{{font-variant-numeric:tabular-nums}}.pill{{display:inline-block;width:fit-content;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:800}}.pill.pending{{color:var(--amber);background:var(--amber-soft)}}.pill.observed{{color:var(--green);background:var(--green-soft)}}.pill.not_comparable,.pill.unobservable{{color:var(--red);background:var(--red-soft)}}footer{{margin-top:24px;color:var(--muted);font-size:12px;overflow-wrap:anywhere}}@media(max-width:950px){{.cards{{grid-template-columns:1fr 1fr}}.section-head{{display:block}}table{{min-width:1180px}}}}@media(max-width:600px){{main{{width:calc(100% - 20px);padding-top:10px}}header,section{{padding:20px;border-radius:14px}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div class="eyebrow">Forecast outcome review · {_escape(review['as_of_date'])}</div><h1>Score only what the evidence actually measures.</h1><p>Every frozen metric receives a disposition. Comparable observed outcomes may be scored; pending, mismatched, and unobservable rows remain visible without numeric backfill.</p><div class="warning"><strong>Boundary:</strong> the source forecast is synthetic. This review audits lifecycle discipline and cannot establish model skill or an investment signal.</div></header>
<div class="cards"><article class="card"><span>Frozen forecasts</span><strong>{summary['forecast_count']}</strong><small>all require disposition</small></article><article class="card"><span>Dispositions</span><strong>{summary['disposition_count']}</strong><small>{_escape(statuses)}</small></article><article class="card"><span>Scores</span><strong>{summary['score_count']}</strong><small>observed and comparable only</small></article><article class="card"><span>Coverage</span><strong>{'N/A' if summary['interval_coverage_rate'] is None else f"{summary['interval_coverage_rate'] * 100:.1f}%"}</strong><small>no score means no denominator</small></article></div>
<section><div class="section-head"><div><div class="eyebrow">Complete disposition ledger</div><h2>No convenient-outcome selection</h2></div><p>An overdue forecast cannot remain pending. Scope-mismatched and unobservable outcomes close explicitly and never receive a fabricated value.</p></div><div class="table-wrap"><table><thead><tr><th>Metric</th><th>Disposition</th><th>Forecast P10 / P50 / P90</th><th>Actual / coverage</th><th>Event</th><th>Review rationale</th></tr></thead><tbody>{_rows(result)}</tbody></table></div></section><footer>Recorded {_escape(review['recorded_at'])}. Registry {_breakable(result['registry']['registry_sha256'])}. Calibration remains separately gated.</footer></main></body></html>"""
