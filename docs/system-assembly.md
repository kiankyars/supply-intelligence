# Supplier-resolved system assembly

Status: executable illustrative model, 2026-07-19.

The system-assembly engine converts non-overlapping ODM compute-tray and rack-integration scopes,
plus required component pools, into component-cleared complete racks. It sits after accelerator
package production and before factory qualification, logistics, site installation, and data-center
commissioning.

The checked release is not an estimate of actual GB200 output. Its ODM labels are deliberately
generic because all throughput, yield, qualification, allocation, component-capacity, and demand
ranges are synthetic. Hash-pinned NVIDIA documentation supports only the DGX GB200 NVL72 topology.

## Local ODM conservation

Every ODM declares a unique compute-tray capacity scope and a unique rack-integration capacity
scope. For each draw, the engine applies effective yield, platform qualification, and customer
allocation separately at both stages:

```text
ODM assembly-supported racks
  = minimum(
      customer-allocated compute trays / compute trays per rack,
      customer-allocated rack-integration output
    )
```

Only those local minima are summed. The engine does not transfer spare trays or integration slots
between ODMs. Duplicate capacity-scope IDs fail loading before simulation.

`nameplate_input`, `sellable_output`, and `platform_allocated` capacity bases have different
deduction rules. Sellable output must use an effective yield of one. Platform-allocated output must
also use qualification and allocation shares of one, preventing an already-net capacity from being
discounted again.

## Component-cleared rack output

The checked model includes customer-addressable pools for ConnectX-7 NICs, BlueField-3 DPUs, NVLink
switch trays, management switches, power shelves, and rack-side liquid-cooling integration. Each
pool has a unique scope, capacity basis, yield, qualification share, allocation share, and fixed
per-rack requirement.

```text
component-cleared rack capacity
  = minimum(
      summed local ODM assembly-supported racks,
      each customer-allocated component pool / its units per rack
    )

complete racks
  = minimum(component-cleared rack capacity, rack demand)
```

The release retains unused allocated trays, rack slots, and components as shadow capacity. It also
reports ODM concentration, local tray-versus-rack bottleneck probabilities, top-level component
bottleneck probabilities, a sourcing queue, and every capacity draw.

## Exact coverage handoff

`coverage.complete_rack_output` defines the output as
`component_cleared_complete_racks` and lists absorbed constraints as exact `(stage, resource_kind)`
selectors. Stage scope matters: rack-integration work at the factory does not absorb the later
`installed`-stage site-installation constraint merely because both use a related resource kind.

When this result enters the full-chain linker, one assembly link must require the complete selector
set. The linker verifies an exact match and requires every matching base constraint to be removed.
It fails if a covered NIC, DPU, switch, power, cooling, tray, or rack constraint survives. This is a
double-count guard, not proof that actual capacity is sufficient.

## Checked release

```sh
python3 -m supply_intelligence validate-system-assembly \
  --scenario examples/system-assembly/gb200-nvl72-odm-assembly-illustrative-2026q3.json \
  --source-root examples/system-assembly

python3 -m supply_intelligence reconcile-system-assembly \
  --scenario examples/system-assembly/gb200-nvl72-odm-assembly-illustrative-2026q3.json \
  --source-root examples/system-assembly \
  --output-dir releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative
```

Open the [assembly dashboard](../releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/dashboard.html).
In the checked synthetic run, median complete-rack output is 299, with P10–P90 of 271–328. The
summed ODM branch binds 98.26% of draws, rack-side cooling 1.30%, and NVLink switch trays 0.44%.
Those values describe only the declared demonstration inputs.

`capacity_draws.csv` preserves every local ODM and component handoff. The v2 full-chain linker
hash-pins that file, verifies the `complete_racks` summary against the frozen result, and consumes
every exact draw. Repeated complete-rack links reuse the same permuted tuple, so the downstream site
allocation is applied to the same rack population rather than a second fit.

## Checked exact-draw three-source chain

The current linked recipe imports material-cleared manufacturing, component-cleared assembly, and
site-operational capacity:

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

The [exact-draw chain dashboard](../releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative/dashboard.html)
shows median package-stage capacity of 3,719 rack equivalents, 299 component-cleared racks, 17.85
shipped racks, and 17.56 operational racks after a synthetic six-percent central Abilene allocation.
The allocation binds 92.03% of operational draws and the illustrative operational source binds 7.97%.
Independent deterministic permutations preserve each source marginal and within-source row
structure, but do not establish dependence between manufacturing, assembly, and deployment. This is
a scope-transition demonstration, not an actual shipment or deployment estimate.
