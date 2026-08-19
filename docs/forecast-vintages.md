# Native forecast vintages

The forecast registry freezes a model output before its target period ends. It is deliberately
separate from the calibration dataset: the registry contains forecasts and future outcome
definitions, while calibration requires realized values and evidence.

## Contract

`ai-supply-forecast-registry.v1` pins one `ai-supply-linked-chain-release.v2` source by release
manifest, result, and raw-draw SHA-256. Version 1 accepts linked-chain physical outputs only. Every
forecast fixes:

- a metric, metric class, quarter, unit, and exact raw-draw column;
- entity, product, geography, quantity semantics, aggregation, and quarter-end cutoff;
- the earliest outcome date, expected evidence date, and revision window;
- acceptable reported or derived posture and the required evidence and measurement method;
- confirming, falsifying, and known-unobservable evidence conditions;
- an optional threshold event and its pre-outcome rationale.

The loader recomputes P10, P50, P90, mean, minimum, and maximum from every selected raw-draw column.
All six values must exactly match the frozen result. A threshold probability is the exact share of
source draws satisfying the event; it is not inferred from three quantiles.

The registry recording must follow the source recording, remain before quarter end, and predate the
earliest possible outcome observation. Paths are confined below one `source_root`. Source files must
match both the registry and the source release manifest.

## Maturity and scoring

Maturity is evaluated at the registry's explicit as-of date, never from the wall clock:

- `pending_period_end`: the target quarter has not ended;
- `pending_observation_window`: the quarter ended but the defined observation window has not opened;
- `awaiting_outcome`: the window is open and the expected evidence date has not passed;
- `outcome_overdue`: the expected evidence date passed without an attached outcome.

These are calendar states, not evidence states. `validate-forecast-registry --status-as-of
YYYY-MM-DD` can evaluate a later date without changing the frozen release. The registry cannot emit
`eligible_to_score` merely because time passed. A later artifact must attach a realized value, prove
publication and retrieval order, and pass the frozen scope contract. Until then, the release exposes
zero outcomes and zero scores.

A native forecast can still be synthetic. The checked Q3 source contains synthetic wafer starts,
yields, HBM, assembly throughput, site allocation, and commissioning assumptions. Its registry is a
valid pre-outcome timestamped model vintage, but it remains ineligible for evidence-backed model
calibration and is not a market estimate.

## Checked release

From `supply_intelligence/`:

```sh
python3 -m supply_intelligence validate-forecast-registry \
  --registry examples/calibration/blackwell-linked-chain-native-forecast-registry-2026q3.json \
  --source-root .

python3 -m supply_intelligence build-forecast-registry \
  --registry examples/calibration/blackwell-linked-chain-native-forecast-registry-2026q3.json \
  --source-root . \
  --output-dir releases/forecast-vintages/2026-07-19-blackwell-linked-chain-native-vintage-v2
```

The release freezes five Q3 metrics across production, rack integration, shipment, installation,
and operation. It preserves the complete 20,000-row source draw ledger byte for byte. All five
forecasts are `pending_period_end`; no actual or score is present.

`dashboard.html` is the first-read view. `forecasts.csv` contains the distributions, threshold
events, and maturity gates. `outcome_contracts.csv` contains every later comparability requirement.
`registry.json` is the original recipe, and `sources/source-release/` contains the exact manifest,
result, and draw ledger. `replay-registry.json` remaps only the source-release path for isolated
validation and deterministic rebuilding. A different or incomplete non-empty output directory is
rejected.

## Boundary

Version 1 does not attach outcomes, advance maturity in place, or score forecasts. It does not make
an unobservable synthetic scope observable. The next release after quarter end should reference
this immutable vintage, capture any scope-matched evidence without revising the forecast, and state
clearly when a metric remains unobservable. Only then should the calibration layer be extended to
linked-chain metrics and exact-draw event probabilities.

The separate [forecast outcome review](forecast-outcomes.md) now enforces that later lifecycle. It
requires one disposition per frozen metric and forbids scores for pending, scope-mismatched, or
unobservable rows.

The [canonical forecast release index](forecast-release-index.md) identifies the accepted v2 vintage,
its exact-draw source, the retained historical predecessor, and the immutable pre-period review.
