# Data Center Atlas power bridge

Status: executable gross-envelope import with a clean-clone fixture, 2026-08-18.

The bridge imports site-level critical IT MW and readiness fields from a hashed Data Center Atlas
release. It keeps a gross site power envelope separate from incremental MW available to new racks.

## What the bridge accepts

An `ai-supply-datacenter-selection.v1` document pins:

- the target quarter and either `operational` or `forecast` capacity stage;
- explicit resolved entity IDs;
- release `as_of` and `recorded_at` cutoffs;
- a minimum observation date;
- optional exact country and user labels;
- a single-site or explicit non-overlapping-site aggregation policy; and
- confirming and falsifying evidence for the selected envelope.

Version 1 accepts only `critical_it_mw` in `MW`. The capacity semantics must be
`gross_site_critical_it_envelope`, and availability must be
`not_net_incremental_capacity`.

Operational rows must have no future target date. Forecast rows must have a target date before the
exclusive end of the selected quarter. Every site must have exactly one matching capacity row and,
for operational imports, a status evidence record.

Run the checked Abilene selection from the repository root:

```sh
python3 -m supply_intelligence import-datacenter-power \
  --release-dir examples/fixtures/datacenter-atlas/2026-07-17-openai-abilene \
  --selection examples/datacenter-openai-abilene-operational-2026q3-selection.json
```

The checked output is
[`examples/datacenter-openai-abilene-operational-2026q3-import.json`](../examples/datacenter-openai-abilene-operational-2026q3-import.json).
It imports a 300.7–589.4 MW site envelope with a 421 MW base from the pinned release. The atlas row is
modeled from Epoch AI data. It is not metered load or evidence of unused capacity.

The directly versioned fixture contains only the selected capacity, entity, and evidence rows. Its
own manifest hashes those bytes and retains the historical upstream manifest hash, `as_of`, and
`recorded_at` values. It is not a complete or current Data Center Atlas release. The adapter still
accepts a canonical `datacenter-atlas-release-v1` directory when all manifest-pinned payloads are
present, but the checked command does not depend on a sibling checkout or ignored generated files.
Replaying through the fixture deliberately preserves the existing checked import bytes, so downstream
immutable releases do not need to be rewritten. The retained upstream hash records lineage; without
the full upstream payload, this repository alone cannot prove selected-row membership in that release.

## Why the result is not a portfolio power pool

The import always emits `usable_as_incremental_power_pool: false`. Four inputs remain necessary:

1. current critical IT load;
2. contracted and reserved capacity;
3. platform-specific allocation; and
4. rack-compatible cooling and power-density headroom.

Only the residual after those deductions can constrain additional operational racks. Treating total
campus MW as vacant MW would overstate deployment capacity and misattribute a site shared across
customers or hardware generations.

The import itself has no commissioning-throughput metric. Site lifecycle evidence can show that a
campus is operational, expanding, or under construction, but it cannot produce a number of racks
commissioned per quarter. The separate [operational conversion](datacenter-operational.md) now
accepts explicit load, commitment, compatibility, allocation, rack-power, and commissioning inputs.
Those site-specific values are synthetic in the checked run, so neither its power nor commissioning
output is eligible for the portfolio solver.

## Provenance rules

The bridge verifies the byte count and SHA-256 of `capacity_estimates.csv`, `entities.csv`, and
`evidence.csv`. The fixture's own manifest records its selected-row scope and historical source
release; the import preserves that historical source-release hash in its existing lineage contract.
It copies the capacity and status evidence records, preserves site identity and scope labels, and
records the selected source rows in the lineage object. Any hash, cutoff, entity, scope, freshness,
range, target-date, or evidence mismatch fails the import.
