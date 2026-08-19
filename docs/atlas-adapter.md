# Semiconductor Atlas adapter contract

Status: executable consumer contract, 2026-07-17.

The adapter imports one explicitly selected quarterly capacity slice from a hashed Semiconductor
Atlas release. It does not query the atlas database, choose claims, collapse capacity bases, infer
allocation, or convert an end-of-quarter capacity rate into quarterly production.

## Selection file

An `ai-supply-atlas-selection.v1` document pins:

- the atlas `as_of` and `recorded_at` cutoffs;
- the target quarter, metric, unit, and input capacity basis;
- an explicit sorted list of capacity claim IDs;
- either one claim or an explicit sum of non-overlapping claims;
- the attribution basis and aggregation rationale;
- `quarter_total` quantity semantics;
- evidence that would confirm or falsify the imported estimate; and
- for a forecast, its vintage and model-parameter SHA-256.

Example:

```json
{
  "format": "ai-supply-atlas-selection.v1",
  "target_quarter": "2026-Q3",
  "source_mode": "canonical_capacity",
  "input_capacity_basis": "economically_usable",
  "metric": "advanced_packages",
  "unit": "package",
  "quantity_semantics": "quarter_total",
  "claim_ids": ["claim:qualified-output:line-1"],
  "aggregation_policy": "single_claim",
  "aggregation_rationale": "The claim is the complete line total for the selected quarter.",
  "attribution_basis": "full physical output",
  "expected_release_as_of": "2026-07-17",
  "expected_release_recorded_at": "2026-07-17T23:00:00Z",
  "confirming_evidence": "Later audited line output falls inside the selected range.",
  "falsifying_evidence": "The claim is a rate, overlaps another total, or misses the range.",
  "correlation_group": "advanced-packaging",
  "forecast_vintage": null,
  "parameter_fingerprint": null
}
```

The checked contract is self-contained in
[`tests/test_atlas_adapter.py`](../tests/test_atlas_adapter.py). The tests build a minimal temporary
release containing manifest-pinned capacity, claim, evidence, and source-input files, then exercise
the public `import-atlas-capacity` command against that fixture. They require no sibling checkout or
ignored local payload.

This repository does not currently distribute a reusable Semiconductor Atlas release fixture, so it
does not present a copy-and-paste production import command. A real import requires an explicitly
selected release directory whose complete payload is available directly to the caller, plus a
selection document following the contract below. The command emits an `Estimate`, evidence records
suitable for a scenario or portfolio pack, and a lineage block containing the atlas manifest hash,
selected claim IDs, recursive dependency closure, and selected source rows.

## Canonical capacity mode

`canonical_capacity` reads `capacity.csv`. Every selected row must match the requested metric, unit,
and one of the five atlas capacity bases. Its `period_start` and `period_end` must exactly equal the
target calendar quarter. The adapter sums low, base, and high only when the selection names every
claim and declares them non-overlapping.

The exact-quarter check prevents annual nameplate capacity or monthly rates from silently entering a
quarterly production numerator. The selection author remains responsible for proving that the metric
and unit describe total output during that period.

## Quarterly forecast mode

`quarterly_output_forecast` reads a manifest-pinned `quarterly_output_forecast.csv`. Each selected
claim needs exactly one row for the target quarter with these fields:

| Field | Required value or meaning |
| --- | --- |
| `capacity_claim_id` | Atlas capacity claim used by the forecast |
| `forecast_vintage` | Exact vintage pinned by the selection |
| `parameter_fingerprint` | Exact model-parameter SHA-256 |
| `input_basis` | Selected atlas capacity basis |
| `output_basis` | `economically_usable` |
| `quantity_semantics` | `quarter_total` |
| `metric`, `unit`, `quarter` | Exact selection match |
| `p10`, `p50`, `p90` | Ordered quarterly output range |

The current atlas `forecast.csv` reports capacity available by quarter end. It is a point-in-time
capacity view, not output produced during the quarter, so the adapter does not accept it. The atlas
can attach the required quarterly-output file through its release `extra_files` mechanism after a
time-integration method is implemented and reviewed.

## Provenance and failure rules

The adapter verifies the byte count and SHA-256 for `capacity.csv`, `claims.jsonl`, `evidence.csv`,
`source_inputs.json`, and the forecast file when used. It follows claim dependencies recursively and
copies supporting evidence into the reconciliation evidence ledger. A missing claim, dependency,
source document, support link, cutoff match, or file hash fails the import.

Imported confidence is the minimum confidence of the selected capacity claims. Canonical source or
observation claims use `reported` posture; reconciled or derived claims use `derived`; quarterly
forecasts use `modeled`. No imported value is labelled synthetic.
