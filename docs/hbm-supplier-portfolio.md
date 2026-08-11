# Supplier-resolved HBM portfolio

The supplier HBM portfolio keeps front-end capacity, platform qualification, and customer allocation
separate for each supplier. It is an upstream physical model: it converts supplier wafer starts into
customer-allocated HBM stacks and accelerator-package equivalents without treating public product
topology as proof of supplier capacity or allocation.

The checked Blackwell scenario names SK hynix, Micron, and Samsung to exercise this topology. All
supplier wafer starts, die geometry, yields, qualification shares, allocation shares, and platform
demand are synthetic. The release is therefore a reproducible demonstration, not an estimate of
actual supplier share, Blackwell output, or HBM tightness.

## Capacity and allocation boundaries

Each supplier flow has a unique `capacity_scope_id`. The loader rejects duplicate scope IDs so the
same wafer-start pool cannot be counted for two suppliers or products. A flow also declares one of
two wafer-start bases:

- `supplier_hbm3e_compatible`: starts cover the supplier's compatible HBM3E pool. The engine applies
  platform-qualification and customer-allocation shares separately.
- `platform_allocated`: starts are already qualified and allocated to the modeled platform. Both
  downstream shares must be fixed at one, preventing a second qualification or allocation discount.

Supplier participation is not inferred from a platform specification. Every flow, including a named
supplier, must carry its own evidence posture and source scope.

## Conversion

The engine uses the same circular-wafer approximation as the aggregate manufacturing model, then
keeps each supplier's flow independent:

```text
gross dies
  = wafer starts × gross dies per wafer

known-good dies
  = gross dies × known-good-die yield

good stacks
  = known-good dies ÷ memory dies per stack
  × stack-assembly yield
  × stack final-test yield

platform-qualified stacks
  = good stacks × platform-qualification share

customer-allocated stacks
  = platform-qualified stacks × customer-allocation share

HBM package equivalents
  = total customer-allocated stacks ÷ placements per accelerator
```

Demand consumes the allocated pool once. The result retains unqualified stacks, qualified stacks
allocated elsewhere, and unconsumed customer-reserved stacks as separate shadow quantities.

## Portfolio diagnostics

Supplier share is calculated from customer-allocated stacks in each draw. The release reports the
Herfindahl-Hirschman Index (`sum(share²)`), the largest supplier share, and per-supplier criticality.
Criticality is the probability that modeled package demand would be uncovered if that supplier were
removed while every other draw value stayed fixed. When the full portfolio is already short, more
than one supplier can be critical in the same draw; the metric is a counterfactual dependency test,
not a probability distribution across suppliers.

`probability_hbm_limited` is the share of draws where customer-allocated stacks support fewer
packages than modeled demand. It is only as credible as the capacity, qualification, allocation, and
demand inputs.

## Evidence and release integrity

Every non-synthetic evidence record must name at least one local source document below the selected
source root. The loader recomputes SHA-256 from the exact bytes and rejects missing files, path
escapes, or hash drift. The release copies those normalized source bytes under `sources/` and hashes
the scenario, result, dashboard, audit tables, and sources in `manifest.json`.

The checked observations support only narrow facts: NVIDIA's Blackwell HBM capacity and stack-height
descriptions, Micron's 24 GB 8-high HBM3E reference product, and Micron's own 300 mm wafer statement.
The Micron wafer fact is not applied to SK hynix or Samsung. NVIDIA's current GB200 page also reports
372 GB across two GPUs, so the checked scenario preserves the resulting topology ambiguity instead
of silently treating every published capacity figure as identical.

## Checked run

From the package directory:

```sh
python3 -m supply_intelligence validate-hbm-suppliers \
  --scenario examples/hbm-suppliers/blackwell-supplier-portfolio-illustrative-2026q3.json \
  --source-root .

python3 -m supply_intelligence reconcile-hbm-suppliers \
  --scenario examples/hbm-suppliers/blackwell-supplier-portfolio-illustrative-2026q3.json \
  --source-root . \
  --include-capacity-draws \
  --output-dir releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws
```

The [draw-preserving release](../releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/dashboard.html)
is current. Its `capacity_draws.csv` retains all 20,000 aggregate and per-supplier allocation draws.
The original generated release remains frozen because its long supplier labels exposed a card-layout
defect; the v2 release corrected that presentation, and the v3 release adds draws without changing
the supplier result JSON or numerical summaries.

The frozen result now feeds the [supplier HBM to manufacturing link](hbm-manufacturing-link.md),
which removes the aggregate HBM branch before importing this portfolio's customer-allocated stacks.
