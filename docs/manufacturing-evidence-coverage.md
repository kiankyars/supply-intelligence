# Manufacturing evidence coverage

The manufacturing evidence-coverage release joins a frozen synthetic-input research queue to
claim-level scope decisions. It answers three separate questions without collapsing them:

1. Which inputs can move the current manufacturing result?
2. Which public claims are relevant as scale controls or directional signals?
3. Which claims satisfy the exact scope required to become numeric constraint candidates?

The release never edits the source scenario. A gate-passing claim is a candidate for a reviewed
scenario revision, not an automatic replacement.

## Checked release

From `supply_intelligence/`:

```sh
python3 -m supply_intelligence build-manufacturing-evidence-coverage \
  --recipe examples/coverage/blackwell-manufacturing-evidence-coverage-2026-07-19.json \
  --source-root . \
  --output-dir releases/manufacturing-evidence/blackwell-2026q3/20260719T210000Z-blackwell-evidence-coverage
```

The checked result contains 21 synthetic inputs and applies zero replacements. TSMC's company-wide
2Q26 wafer shipments are rejected as a Blackwell wafer-start constraint on seven dimensions, while
the same claim is retained as one nonbinding scale control. Eight TSMC and Micron disclosures are
accepted as directional signals. They identify investment, construction, backend, tester, HBM4
ramp, revenue, and shipment conditions without fabricating throughput.

## Independent target catalog

A claim selection cannot define its own target scope unchecked. The coverage recipe separately
hash-pins `ai-supply-manufacturing-target-catalog.v1`. Each catalog row fixes:

- the source-scenario input path and unit;
- entity, geography, period, production stage, capacity basis, and quantity semantics;
- product, process node, customer, or other optional scope dimensions;
- a human-readable explanation of the intended quantity.

For a `constraint_input` assessment, the selection's target dimensions must exactly match the
catalog, the target must exist in the frozen synthetic-input queue, and the normalized unit must
match the source input. This prevents a selection from relabeling a company shipment claim as a
product wafer-start claim merely by changing its requested target dimensions.

The current catalog contains the assessed Blackwell logic-wafer-start target. Add and review a
catalog row before testing another synthetic input as a constraint.

## Input statuses

`input_coverage.csv` assigns one of four statuses to every frozen source input:

- `eligible_claim_candidate`: at least one numeric claim passes the independent target gate;
- `scope_rejected_claim`: a claim was tested but failed at least one scope dimension;
- `rejected_claim`: a tested claim failed posture, unit, or numeric-range requirements;
- `no_constraint_claim`: no selected constraint claim targets the input.

Every source row remains marked `source_posture: synthetic` and `source_replaced: false`. The file
also preserves the current low/base/high range, influence probability, research priority,
confirmatory evidence, and falsifying evidence.

`claim_assessments.csv` separately records accepted scale controls, accepted directional signals,
eligible constraint candidates, and rejected assessments. This prevents nonbinding evidence from
inflating numeric coverage.

## Frozen lineage and failure rules

The recipe pins the complete manufacturing-release manifest, the independent target catalog, every
claim snapshot, and every claim selection by SHA-256. The loader verifies every file listed in the
source manufacturing manifest before assessing claims. It also rejects:

- paths outside the declared source root;
- duplicate case IDs or duplicate selections;
- claims not valid by the coverage date or not known by its transaction time;
- constraint targets missing from the target catalog or source research queue;
- target-dimension or normalized-unit disagreement with the catalog;
- a source release, snapshot, selection, or target catalog whose bytes drift.

The output bundles the source research queue and result, target catalog, snapshots, selections,
assessments, CSV audits, dashboard, and a manifest covering every emitted byte. An exact replay into
the same directory is idempotent; a different or incomplete pre-existing release is rejected.

## Current boundary

Coverage is zero because no checked public claim establishes exact-quarter Blackwell wafer starts,
HBM3E wafer starts or stack output, advanced-package starts, customer allocation, or process yield.
Current disclosures help identify bottleneck families and proof to seek. They do not resolve the
quantity gaps.
