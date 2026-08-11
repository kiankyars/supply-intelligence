# Manufacturing claim-scope gate

The manufacturing claim gate decides whether one frozen ledger claim can serve as a numeric model
input, a nonbinding scale control, or a directional research signal. It does not infer missing scope.
A selection pins the snapshot hash, valid and known cutoffs, revision ID, source dimensions, allowed
postures, unit conversion, and intended target.

## Structured dimensions

Every new claim carries at least six dimensions:

- entity scope;
- geography;
- period;
- production stage;
- capacity basis;
- quantity semantics.

Product, process node, customer, technology, and qualifier fields preserve additional scope when the
source provides it. These dimensions are revision identity: changing one creates a new claim revision.

## Constraint eligibility

For `constraint_input` usage, the claim and target must match every target dimension. The claim must
also use an allowed posture, match the declared source unit, and contain either a numeric point or an
explicit low/base/high range. A low/high guidance range has no automatically invented base.

The checked TSMC assessment intentionally fails:

```sh
python3 -m supply_intelligence assess-manufacturing-claim \
  --snapshot releases/claim-cycles/official-controls/20260719T190000Z-official-controls-9784ceec7b/current_snapshot.json \
  --selection examples/claim-selections/tsmc-2026q2-shipments-as-blackwell-wafer-starts.json
```

TSMC's reported 2Q26 total differs from the Blackwell target on capacity basis, customer, entity
scope, period, process node, product, and stage. It is company-wide wafer shipments across all nodes,
products, and customers in 2026-Q2. The target is NVIDIA Blackwell 4NP wafer starts for 2026-Q3.
The normalized 4,336,000-wafer value remains visible, but `constraint_estimate` is null.

## Nonbinding controls and signals

The same TSMC claim is accepted as a scale control under a selection that states why it is
nonbinding:

```sh
python3 -m supply_intelligence assess-manufacturing-claim \
  --snapshot releases/claim-cycles/official-controls/20260719T190000Z-official-controls-9784ceec7b/current_snapshot.json \
  --selection examples/claim-selections/tsmc-2026q2-shipments-scale-control.json
```

The current manufacturing-signals pack also records primary-source observations that do not disclose
qualified throughput:

- TSMC's USD 60 billion to USD 64 billion 2026 capital-budget range;
- the combined 10% to 20% backend-related capital bucket;
- qualitative backend and tester shortages;
- Micron's HBM4 revenue lower bound and relative ramp-speed statement;
- Micron's HBM4 high-volume shipment status and 2027-H1 Singapore packaging timing.

Those records are useful for change detection and research prioritization. They cannot replace
Blackwell logic wafer starts, HBM3E wafer starts, stack yield, customer allocation, or CoWoS package
starts. A `directional_signal` selection accepts qualitative status without manufacturing a numeric
estimate.

## Current boundary

Checked derived claims now pass for nominal wafer format and bounded reticle-based die geometry.
They are physical-specification estimates and do not establish production.
No checked public claim passes the gate for the remaining synthetic manufacturing-capacity and yield
inputs. A passing replacement still needs exact-quarter product, node, customer, stage, capacity
basis, units, and uncertainty. The gate prevents unsupported substitution; it does not solve the
underlying evidence gap.

The checked [manufacturing evidence-coverage release](manufacturing-evidence-coverage.md) adds an
independently hash-pinned target catalog. A constraint selection must agree with that catalog before
its gate result can be associated with a source-scenario input. This prevents a selection from
weakening the target scope it is supposed to test.
