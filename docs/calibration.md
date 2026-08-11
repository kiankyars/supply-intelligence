# Forecast calibration and backtesting

The calibration layer scores realized outcomes against frozen forecast vintages. It is designed to
answer a narrow question before anyone changes a model range: did the prior distribution cover the
outcome, was its center biased, and did its event probability deserve confidence?

Pre-outcome native forecasts now have a separate
[forecast registry contract](forecast-vintages.md). That registry freezes raw draws, target scopes,
maturity dates, and future evidence requirements without inventing an actual value. A calibration
dataset starts only after a comparable outcome exists. The
[forecast outcome review](forecast-outcomes.md) requires a disposition for every registered metric
and scores only evidence-backed, scope-comparable actuals.

Version 1 accepts `ai-supply-calibration-dataset.v1` and manufacturing results in
`ai-supply-manufacturing-result.v1` format. A dataset may reference several vintages, but each
forecast file is resolved below one explicit source root and pinned by SHA-256, format, scenario ID,
quarter, and recorded timestamp.

## Outcome contract

Each outcome fixes:

- one forecast ID and metric;
- the matching quarter and unit;
- a realized value, posture, and observation date;
- a source family and one or more evidence IDs;
- the measurement method and revision risk;
- an optional `at_least` or `at_most` threshold event.

Evidence retrieval must precede the dataset's recorded timestamp. A non-synthetic quarterly outcome
cannot be observed until the quarter has ended. Its evidence needs a publication date and content
hash, and its posture must be reported or derived. A forecast must be frozen on an earlier date than
the outcome, must predate the dataset, and cannot be synthetic when the dataset is presented as
evidence-backed. Each outcome source family must match every evidence record it cites. These checks
preserve transaction time; they do not prove that the reported outcome is scope-comparable, so the
outcome method and revision risk remain first-class fields.

## Scores

For actual value `y` and frozen forecast quantiles `q10`, `q50`, and `q90`:

```text
inside interval = q10 <= y <= q90
signed error    = q50 - y
absolute error  = abs(q50 - y)
```

Positive signed error means the P50 overforecast the outcome. P10, P50, and P90 also receive standard
quantile, or pinball, loss. Their mean is normalized by the absolute actual value so unlike physical
units can be compared without averaging dies, stacks, packages, and systems together. Absolute error
used for the width diagnostic is divided by the greater of the P10-to-P90 half-width, one percent of
absolute P50, or a numerical epsilon; the chosen denominator is exported with every score.

An optional threshold event receives a Brier score. Version 1 approximates a distribution as
triangular with P10/P50/P90 used as low/mode/high. That is deliberately labeled as lossy: those
quantiles are not true support endpoints, tail mass disappears, and cross-metric dependence is not
preserved. A point forecast is handled as a degenerate point mass.

The scorecard reports overall, metric-class, and source-family summaries. Raw signed and absolute
errors are aggregated only when every row in the group shares one unit. Coverage, relative bias,
normalized pinball loss, and Brier scores remain available for mixed-unit groups. Overall and
source-family summaries are diagnostic only; only an explicitly defined metric class may propose
shared calibration parameters.

## Recalibration guardrail

A metric class needs at least ten outcomes before version 1 estimates parameters. Thin classes
report the additional observations needed. A sufficiently large class exposes:

```text
P50 multiplier       = median(actual / forecast P50)
half-width multiplier = max(1, P80 normalized absolute error)
```

The width rule cannot narrow an interval. Every proposal is marked
`eligible_for_application: false` and `holdout_validation_required`; no scorecard mutates a forecast.
A separate, later holdout must show that the candidate parameters improve calibration without
damaging a different period, metric, or source family. A class containing a zero-P50 forecast is
marked not estimable rather than deriving a multiplier from only part of its history.

## Replayable release

`build-calibration-scorecard` writes:

- `dashboard.html` and the complete `result.json`;
- outcome-level `scores.csv`;
- metric-class and source-family summary CSVs;
- `evidence.csv`;
- the exact `dataset.json`, a path-remapped `replay-dataset.json`, and every frozen forecast under
  `sources/forecasts/`;
- a manifest hashing every byte of those audit surfaces.

An exact replay is idempotent. A different or incomplete non-empty output directory is rejected.
An isolated release can be recomputed by passing its `replay-dataset.json` and release directory as
the dataset and `source_root`; the replay copy changes forecast paths only.

Run the checked contract fixture from `supply_intelligence/`:

```sh
python3 -m supply_intelligence validate-calibration \
  --dataset examples/calibration/blackwell-manufacturing-calibration-synthetic-2026-07-19.json \
  --source-root .

python3 -m supply_intelligence build-calibration-scorecard \
  --dataset examples/calibration/blackwell-manufacturing-calibration-synthetic-2026-07-19.json \
  --source-root . \
  --output-dir releases/calibration/2026-07-19-blackwell-manufacturing-synthetic-scorecard
```

The checked dataset has six synthetic outcomes against one synthetic manufacturing vintage. It
exercises interval misses, bias, pinball loss, Brier scoring, unit-safe grouping, and
insufficient-history gates. It is not a backtest of actual Blackwell production.

## External guidance outcome adapter

The separate `ai-supply-guidance-backtest-case.v1` contract pairs an official pre-period-end company
guidance observation with its later reported result. It validates hashes, entity, fiscal period,
metric, accounting basis, unit, publication order, retrieval time, and capture time. It reports
management-range coverage and midpoint error without treating guidance as a probability
distribution.

The checked Micron FY2026-Q3 case uses real disclosures, but it is not a native-model vintage. The
normalized observation was assembled after the result was known, both records come from the same
company source family, and the release permanently sets `eligible_for_model_calibration` to false.
It proves the historical financial-outcome adapter and audit path, not model skill or physical AI
production. See the [reported-guidance backtest contract](guidance-backtest.md).

## Current boundary

One Q3 linked-chain native vintage is now frozen before period end with all 20,000 raw draws and five
physical outcome contracts. It has not matured and has no realized value. Its source scenario is
synthetic, so it demonstrates forecast-time integrity but remains ineligible for evidence-backed
model calibration.

Calibration version 1 still scores manufacturing conversion outputs only. It does not yet consume
the linked shipment, installation, or commissioning registry; model outcome revisions; exact-draw
event probabilities; or rolling and blocked holdouts. Those require dated, scope-matched outcome
adapters and a later evidence-backed native forecast before any parameter can become eligible.
