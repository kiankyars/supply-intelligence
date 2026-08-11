# Forecast outcome reviews

The outcome review attaches later evidence to an immutable native forecast registry. It closes a
selection-bias loophole: every frozen metric must receive exactly one disposition, including metrics
for which no comparable public outcome exists.

## Dispositions

`ai-supply-forecast-outcome-review.v1` accepts four states:

- `pending`: the observation window is not complete; an overdue row cannot remain pending;
- `observed`: a scope-matched reported or derived actual with hash-pinned evidence;
- `not_comparable`: candidate evidence exists, but one or more frozen scope dimensions differ;
- `unobservable`: the expected evidence date passed without a scope-matched public outcome.

`not_comparable` requires evidence plus explicit mismatch dimensions such as product, geography,
stage, period, aggregation, unit, or quantity semantics. `unobservable` is allowed only after the
forecast's frozen expected-evidence date and requires a reason code and search summary. Neither state
receives a numeric value or score.

An `observed` row must use the frozen unit, occur after the outcome window opens, cite retrieved and
publication-dated source bytes, use reported or derived posture, and match the evidence source
family. The review records measurement method and revision risk. Candidate capacity announcements,
construction progress, and directional language fail comparability unless the forecast explicitly
targets those quantities.

## Scoring boundary

Observed rows receive P10-to-P90 coverage, P50 error, interval miss, and pinball loss. A frozen event
uses the exact raw-draw probability stored by the native registry, so the Brier score does not
reconstruct a distribution from three quantiles. Other dispositions emit no score and do not enter
the coverage denominator.

`ai-supply-forecast-outcome-review-result.v1` always reports disposition and score counts separately.
No review auto-calibrates the model. A synthetic source forecast remains ineligible for
evidence-backed scoring and calibration even if a later actual is attached for diagnostics.

## Checked pre-period review

From `supply_intelligence/`:

```sh
python3 -m supply_intelligence validate-forecast-outcome-review \
  --review examples/calibration/blackwell-linked-chain-outcome-review-preperiod-2026q3.json \
  --source-root .

python3 -m supply_intelligence build-forecast-outcome-review \
  --review examples/calibration/blackwell-linked-chain-outcome-review-preperiod-2026q3.json \
  --source-root . \
  --output-dir releases/forecast-outcome-reviews/2026-07-19-blackwell-linked-chain-preperiod
```

The checked review covers all five native Q3 metrics. Because the period has not ended, all five are
pending and the release contains zero evidence records and zero scores. This is the correct
pre-period state, not an incomplete backtest.

`ai-supply-forecast-outcome-review-release.v1` preserves the review, registry release manifest,
registry recipe and result, source evidence bytes, disposition and score CSVs, dashboard, and a
byte-and-hash manifest. `replay-review.json` remaps only preserved source paths for isolated
validation.

After the frozen evidence dates, create a new review rather than editing this one. Retain
scope-mismatched candidates, explicitly close unobservable rows, and add observed outcomes only when
the original target dimensions survive comparison.
