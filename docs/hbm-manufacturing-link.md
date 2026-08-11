# Supplier HBM to manufacturing link

This link replaces the manufacturing model's aggregate HBM wafer branch with one frozen,
supplier-resolved customer-allocation result. It does not add supplier HBM beside the old branch.
The aggregate flow is removed before package attempts are calculated, so HBM capacity is consumed
once.

The checked link remains illustrative. Supplier capacity, yields, qualification, allocation,
manufacturing process inputs, and demand are synthetic. Its output is not an estimate of actual
Blackwell production or HBM market share.

## Required source agreement

All link versions pin the exact SHA-256 of a manufacturing scenario and an
`ai-supply-hbm-supplier-result.v1` document. Version 2 and later also pin the exact capacity-draw CSV
and expected row count. Loading fails unless:

- both source scenario IDs and quarters match the recipe;
- both sources were known before the linked run's recorded timestamp;
- the selected aggregate HBM wafer-flow ID exists in the manufacturing scenario;
- the supplier result has unique supplier IDs and capacity-scope IDs;
- memory dies per stack, stack capacity, and stacks per accelerator match exactly, including units;
- the imported metric is `customer_allocated_stacks`;
- every draw conserves supplier allocations, stack-to-package conversion, and demand, while
  reproducing the frozen aggregate and per-supplier summaries; and
- no aggregate HBM wafer-start scale reference would survive after its underlying flow is removed.

The lineage records every topology comparison, both source hashes, the removed flow, all declared
supplier capacity scopes, and the one-count guard.

## Package-start coverage

Version 3 can also declare `material_cleared_starts`. In that basis, each sampled package start is
defined as having its required interposer and package substrate issued already. The declaration names
the absorbed resource kinds and carries its own posture, method, and confirmatory and falsifying
tests. The checked declaration is synthetic: it prevents double counting but does not estimate
interposer or substrate capacity.

When the canonical result enters the full-chain linker, `require_source_coverage` must match those
resource kinds. Every base constraint for a covered kind must appear in `replace_constraint_ids` or
loading fails. Tool-slot or theoretical-throughput starts before material issue must not use this
basis; their interposer and substrate pools must remain separate.

## Distribution mapping

The current v3 link reads every source capacity draw. It applies a deterministic permutation before
pairing those draws with manufacturing draws. That preserves the full HBM marginal—including tails—
and each draw's supplier allocation, while avoiding an unsupported relationship between the two
models' original draw indexes. It does not assert dependence between HBM and logic or packaging.

The v1 link remains available for frozen releases that have summaries only. It maps source P10, P50,
and P90 to triangular low, mode, and high parameters, truncating tails and discarding supplier
dependence. The format and lineage always identify which mapping ran.

The linked manufacturing result omits aggregate pre-allocation HBM gross-die, known-good-die, and
raw-stack outputs. Those quantities remain in the frozen supplier result. In the canonical
manufacturing output, `hbm_good_stacks` is explicitly the imported customer-allocated stack pool.
Logic and package branches retain their source estimates, and package attempts are:

```text
minimum(
  logic package equivalents,
  supplier customer-allocated stacks / stacks per accelerator,
  package assembly starts
)
```

The result remains `ai-supply-manufacturing-result.v1`, so the existing earnings, calibration, alert,
and manufacturing-to-site linkers can consume its finished-package or complete-system metrics. Its
embedded `ai-supply-hbm-manufacturing-lineage.v1` distinguishes the replacement from a native
aggregate manufacturing run.

## Checked linked manufacturing run

```sh
python3 -m supply_intelligence validate-hbm-manufacturing-link \
  --manufacturing-scenario releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence/scenario.json \
  --hbm-result releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/result.json \
  --hbm-capacity-draws releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/capacity_draws.csv \
  --link-recipe examples/hbm-suppliers/blackwell-manufacturing-draw-material-cleared-reticle-geometry-link-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-hbm-manufacturing-link \
  --manufacturing-scenario releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence/scenario.json \
  --hbm-result releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/result.json \
  --hbm-capacity-draws releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/capacity_draws.csv \
  --link-recipe examples/hbm-suppliers/blackwell-manufacturing-draw-material-cleared-reticle-geometry-link-illustrative-2026q3.json \
  --include-output-draws \
  --output-dir releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws
```

Open the [material-cleared output-draw manufacturing dashboard](../releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/dashboard.html).
The first generated link release remains frozen because its arrows visually implied a sequential
flow; the v2 revision shows the branches as an explicit minimum. The v3 release adds the exact draw
artifact, the v4 release adds the material-coverage scope and double-count guard, and the v5 artifact
adds `manufacturing_draws.csv` without changing the frozen result. The v6 release propagates the
derived wafer format and bounded reticle-geometry revision through the same exact-draw HBM link. The
output ledger retains all 20,000 logic, supplier-HBM, package, finished-package, and complete-system
draws.

In this synthetic draw-level run, HBM binds package attempts in 96.625% of draws. Median output is
267,777 finished accelerator packages or 3,719 NVL72 equivalents. Those numbers describe only the
checked assumptions; the geometry is derived, while capacity and yield flows remain synthetic.

## Checked package-to-site continuation

The canonical linked result can replace the manufacturing source in the existing full-chain linker:

```sh
python3 -m supply_intelligence reconcile-linked-chain \
  --base-scenario examples/gb200-nvl72-illustrative-2026q3.json \
  --link-recipe examples/gb200-to-abilene-odm-assembly-draw-linked-reticle-geometry-illustrative-2026q3.json \
  --manufacturing-result releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/result.json \
  --manufacturing-draws releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/manufacturing_draws.csv \
  --assembly-result releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/result.json \
  --assembly-draws releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/capacity_draws.csv \
  --operational-result releases/2026-07-19-abilene-operational-illustrative-v2-draws/result.json \
  --operational-draws releases/2026-07-19-abilene-operational-illustrative-v2-draws/capacity_draws.csv \
  --output-dir releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative
```

The [full-chain dashboard](../releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative/dashboard.html)
retains the explicit synthetic site allocation and gross-to-net operational result. The package
stage is constrained by the linked material-cleared manufacturing result. A separate
component-cleared assembly source then limits median rack output to 299 before a synthetic
six-percent central Abilene allocation limits median shipped output to 17.85 and median operational
output to 17.56. This is a bottleneck handoff inside the demonstration, not a real production or
deployment estimate.

The v2 continuation consumes every manufacturing, assembly, and operational draw, verifies each
linked metric against all six frozen summary statistics, and preserves the source files in its
release. One deterministic permutation per engine retains source marginals and within-source row
structure while deliberately avoiding an unsupported relationship among original source indexes.
That independence policy is not an estimated cross-engine dependence model.
