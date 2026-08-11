# Frozen-result linked chain

Status: executable illustrative link, 2026-07-19.

The linker joins frozen manufacturing and site-operational results, and optionally a frozen
system-assembly result, to the complete-system reconciliation without representing the same capacity
twice. It is a bridge between independently audited engines, not a substitute for source-backed
inputs.

## Recipe contract

An `ai-supply-chain-link.v1` or `ai-supply-chain-link.v2` recipe pins:

- the base scenario, manufacturing result, operational result, and optional system-assembly result
  by SHA-256 and scenario ID;
- a later linked-scenario transaction time and a common quarter;
- each imported metric, target stage, resource kind, capacity basis, and unit conversion;
- the exact base constraints replaced by each frozen result;
- any source-coverage kinds that the manufacturing result must absorb;
- exact stage-and-resource coverage selectors for component-cleared assembly output;
- any extra platform or site allocation estimate;
- the source and target scope explanation; and
- whether customer, supplier, consensus, and opportunity views remain valid.

Version 2 additionally pins one capacity-draw CSV and expected row count for every configured
source. Missing draw files, hash drift, non-contiguous indexes, wrong row counts, non-finite values,
or a draw metric that does not reproduce the frozen result's P10, P50, P90, mean, minimum, and
maximum all fail loading.

The current checked recipe imports manufacturing `complete_system_equivalents`, assembly
`complete_racks`, and operational `operational_racks`. It rejects a manufacturing result whose
accelerators per system differ from the base platform, an assembly result whose packages per rack
differ, and an operational result whose racks per system differ. Constraints cannot be replaced
twice.

The checked manufacturing source defines package assembly starts as material-cleared and declares
silicon interposers and ABF substrates as absorbed resources. Its recipe therefore requires that
coverage and replaces the corresponding base constraints. The linker fails if the source omits a
required coverage kind or if any covered base constraint survives. This is a one-count semantic
guard, not evidence that actual interposer or substrate capacity is sufficient.

The checked assembly source defines component-cleared complete racks. Its coverage uses exact
`(stage, resource_kind)` selectors for compute-tray assembly, factory rack integration, NICs, DPUs,
switches, power shelves, and rack-side cooling. The recipe must require the complete selector set and
remove every matching base constraint. A later `installed`-stage site-installation constraint
survives because stage scope is part of the identity. A configured assembly source without one exact
coverage handoff is rejected.

## Scope transition

A one-site operational result cannot cap a broader production flow without an allocation boundary.
The checked recipe therefore adds a shipped-stage constraint:

```text
site-target shipped systems
  = frozen component-cleared complete-rack capacity
  × synthetic site allocation share
```

Package stages retain the selected illustrative manufacturing scope. Rack integration uses the
selected illustrative assembly scope. Shipped, installed, and operational stages represent the
synthetic Abilene-target subset. The release clears market and customer views because a site-scoped
output cannot support global supplier revenue or customer-allocation conclusions.

## Distribution mapping

Version 2 consumes every exact hash-pinned source draw. It creates one deterministic permutation per
source engine, then reuses that permutation for every link to the same source. Repeated uses of
assembly `complete_racks` therefore start from an identical raw draw tuple; the shipped-stage link
then applies its explicit site-allocation estimate. A source's marginal distribution, point masses,
tails, and dependence among fields in the same source row survive exactly.

Permutations differ across manufacturing, assembly, and operational sources. This avoids treating
unrelated row indexes as a shared random state, but it is an independence assumption—not evidence of
cross-source causal dependence. Common causal drivers or an estimated dependence model are still
needed for that. The remaining base constraints continue to use their declared triangular estimates.

Version 1 remains replayable for summary-only releases. It maps source P10, P50, and P90 to
triangular low, mode, and high parameters and coordinates repeated metrics with a correlation group.
That mapping preserves only a central range, not tails, point masses, or full dependence. The recipe,
lineage, and release format identify which policy ran.

## Release contents

The linked release preserves byte-identical copies of the base scenario, link recipe, manufacturing
result, operational result, and optional assembly result. A v2 release also preserves every source
draw file byte for byte and writes `chain_draws.csv` with every linked constraint, stage, and physical
output draw. The generated scenario, link lineage, audit CSVs, dashboard, and manifest hash every
payload. Writing to a populated output directory succeeds only for an exact replay.

The current checked v2 release is a method demonstration. The manufacturing capacity and yield inputs,
material-cleared package scope, ODM and component inputs, component-cleared rack scope, operational
deductions and commissioning inputs, site allocation, and remaining base constraints are synthetic.
Its latest P10/P50/P90 flow is 3,227/3,719/4,255 package-equivalent systems, 271/299/328 complete racks,
14.34/17.85/21.73 Abilene-target shipped racks, and 12.83/17.56/21.60 operational racks. The
synthetic site allocation binds 92.03% of operational draws; the exact illustrative operational
source binds 7.97%, including its zero-capacity tail. Wafer format and reticle-bounded die geometry
are derived, but the geometry is not a teardown measurement. This is neither a global production
estimate nor an estimate of actual Abilene shipments or deployments.
