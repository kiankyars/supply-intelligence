# Gross-to-net power and commissioning

Status: executable illustrative conversion, 2026-07-19.

The operational engine turns a gross critical-IT power envelope into target-platform racks that can
be brought online in one quarter. It does not treat campus nameplate or modeled site capacity as
vacant power.

## Input boundary

An `ai-supply-datacenter-operational.v1` scenario pins the exact gross-import JSON by SHA-256, the
selected site IDs, and the upstream Data Center Atlas manifest hash. The imported record must retain
both `gross_site_critical_it_envelope` semantics and `not_net_incremental_capacity` availability.

The scenario supplies eight estimates:

1. current critical IT load;
2. contracted reservations not already in current load;
3. other-platform commitments not in the first two categories;
4. otherwise-uncommitted MW that lacks target-rack electrical density or cooling compatibility;
5. the target platform's share of residual compatible MW;
6. critical-IT MW per target rack;
7. rack commissioning slots in the target quarter; and
8. the share of scheduled slots that reaches operational acceptance in that quarter.

The four deductions require a written non-overlap rationale. This does not prove the categories are
disjoint; it exposes the partition that must be tested against operator records.

## Conversion

For every Monte Carlo draw:

```text
residual compatible MW
  = max(0, gross critical IT MW
           - current load
           - contracted reservations
           - other-platform commitments
           - rack-incompatible capacity)

target allocatable MW = residual compatible MW × target-platform share
power-supported racks = target allocatable MW ÷ critical-IT MW per rack
completed commissioning capacity = commissioning slots × completion ratio
operational racks = min(power-supported racks, completed commissioning capacity)
```

If commissioning binds, unused target MW is reported as shadow power. If power binds, unused
completed commissioning throughput is reported as shadow commissioning capacity. The result also
reports the probability that deductions consume the full gross envelope.

## Checked run

Run from `supply_intelligence`:

```sh
python3 -m supply_intelligence reconcile-datacenter-operational \
  --gross-import examples/datacenter-openai-abilene-operational-2026q3-import.json \
  --scenario examples/datacenter-openai-abilene-net-operational-illustrative-2026q3.json \
  --include-capacity-draws \
  --output-dir releases/2026-07-19-abilene-operational-illustrative-v2-draws
```

The gross Abilene envelope comes from the pinned open Data Center Atlas release. NVIDIA's rack guide
supports the approximately 120 kW NVL72 rack conversion. All site load, reservation, other-platform,
compatibility, target-share, and commissioning values are synthetic. The release therefore sets
`usable_as_operational_capacity` to `false` and must not be read as actual OpenAI, Oracle, NVIDIA, or
site-operator capacity.

The v2 release contains the exact scenario and gross-import JSON, full result JSON, output and input
CSVs, selected sites, a ranked evidence-replacement queue, source records, dashboard, and a manifest
that hashes every payload. `capacity_draws.csv` retains all 20,000 gross-to-net power,
commissioning, and operational-rack draws for the v2 full-chain linker. It includes the checked
illustrative zero-capacity tail rather than replacing it with a fitted triangle.
