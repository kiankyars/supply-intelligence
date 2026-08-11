# Reported-guidance historical benchmark

This adapter compares a company's public guidance with its later reported result while preserving
the exact disclosure dates, accounting basis, units, normalized source bytes, and hashes. It gives
the platform a non-synthetic historical outcome path without pretending that management guidance was
an AI Supply Intelligence forecast.

## Hard boundary

Every result is labeled:

- `type: reconstructed_external_company_guidance`;
- `native_model_forecast: false`;
- `eligible_for_model_calibration: false`.

The normalized artifact may be assembled after the outcome, provided the underlying guidance was
published before period end. That transaction-time distinction is retained in the result. The case
cannot be used to claim native model skill, train a calibration multiplier, or validate physical AI
production.

## Input contracts

`ai-supply-guidance-backtest-case.v1` fixes:

- entity, ticker, fiscal period, as-of date, and recorded timestamp;
- a guidance observation path and SHA-256;
- an outcome observation path and SHA-256;
- the ordered metrics to compare;
- notes stating the benchmark boundary.

`ai-supply-reported-guidance-observation.v1` records each management range or approximate point.
`ai-supply-reported-outcome-observation.v1` records the later reported value and its revision risk.
Both observations carry publisher, URL, publication date, retrieval timestamp, source family,
license note, excerpt, capture timestamp, and limitations.

The loader rejects path escape, hash drift, unexpected fields, identity mismatch, duplicate or
missing metrics, and mismatched label, metric class, accounting basis, or unit. It also requires:

```text
guidance publication < period end < outcome publication <= case as-of date
publication <= retrieval <= capture <= case recorded timestamp
```

These checks prove ordering and reproducibility. They do not make two disclosures from one company
independent evidence.

## Scores

For reported result `y`, guidance low `l`, midpoint `m`, and high `h`:

```text
inside range       = l <= y <= h
signed error       = m - y
midpoint surprise  = y / m - 1, when m is nonzero
interval miss      = max(l - y, y - h, 0)
normalization      = max((h - l) / 2, abs(m) * 1%, epsilon)
normalized error   = abs(m - y) / normalization
```

Positive midpoint surprise means the actual exceeded guidance. Approximate-point guidance has zero
stated width and is normalized against one percent of its midpoint. This is a scale diagnostic, not
a probabilistic score.

Management ranges do not define P10, P50, or P90. The adapter therefore does not compute interval
calibration, quantile loss, pinball loss, Brier scores, or recalibration parameters.

## Replayable release

`build-guidance-backtest` writes:

- `dashboard.html` and complete `result.json`;
- `scores.csv` and `evidence.csv`;
- the exact `case.json`;
- the exact guidance and outcome observations under `sources/`;
- `README.md` with the boundary warning;
- `manifest.json` with every file's byte count and SHA-256.

An exact replay is idempotent. A different or incomplete non-empty destination is rejected.

Run the checked case from `supply_intelligence/`:

```sh
python3 -m supply_intelligence validate-guidance-backtest \
  --case examples/backtests/micron-fy2026q3-guidance-backtest.json \
  --source-root .

python3 -m supply_intelligence build-guidance-backtest \
  --case examples/backtests/micron-fy2026q3-guidance-backtest.json \
  --source-root . \
  --output releases/backtests/2026-07-19-micron-fy2026q3-guidance
```

The checked case pairs Micron's [March 18 FY2026-Q3 guidance](https://investors.micron.com/static-files/0cf459c6-1c96-49d1-982a-3a890f43dd77)
with its [June 24 reported results](https://investors.micron.com/node/50671). It scores revenue,
GAAP and non-GAAP gross margin, GAAP and non-GAAP operating expenses, and GAAP and non-GAAP diluted
EPS. All seven actuals were above their guidance ranges or approximate points; the largest midpoint
surprise was 31.1% for non-GAAP diluted EPS.

This is one company-quarter from one source family. It establishes a real, replayable financial
outcome adapter and nothing broader. Native forecast backtesting must wait for a genuinely frozen
pre-outcome model vintage and a later scope-matched realized outcome.
