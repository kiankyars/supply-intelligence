# Manufacturing evidence replacement

The revision layer turns an exact-scope claim into a reviewed manufacturing input without mutating
its frozen predecessor. A gate-passing claim is only a candidate until an
`ai-supply-manufacturing-revision-recipe.v1` document independently pins the source scenario, target
catalog, claim snapshot, and claim selection.

## Workflow

```text
normalized official observations
  -> bitemporal claim snapshot
  -> exact-scope claim selection
  -> independent target catalog
  -> synthetic-only replacement recipe
  -> new manufacturing release
  -> frozen-result comparison alert
```

The recipe supplies a later `as_of_date` and `recorded_at`, one or more replacements, and display
metadata for each source snapshot. Every replacement must pass the manufacturing claim gate as a
`constraint_input`. The claim dimensions and normalized unit must exactly match the independently
pinned target catalog.

The loader then requires the selected source estimate to have `synthetic` posture. It replaces the
estimate's range, posture, methodology, confidence, date, confirm/falsify tests, and evidence IDs.
It preserves the predecessor's correlation group. The revised scenario remains synthetic while any
synthetic estimate remains.

## Failure boundaries

The revision is rejected when:

- any input path escapes `source_root` or any pinned SHA-256 digest drifts;
- the recipe predates the source scenario, the snapshot is not valid on the revision date, or the
  claim was not known by the revision timestamp;
- the claim gate reports a scope, posture, unit, or numeric-range blocker;
- the target path is absent from the catalog or its dimensions differ from the selection;
- the source estimate is already reported, derived, or modeled;
- source-snapshot display metadata is incomplete or collides with existing scenario evidence; or
- an output directory contains an incomplete or different release.

The release retains the exact predecessor, target catalog, claim snapshot, selection, recipe,
revised scenario, revision audit, manufacturing result, dashboard, CSVs, and a hash manifest. An
idempotent replay may reproduce an existing release byte for byte; it cannot overwrite drift.

## Checked Blackwell revision

The checked recipe derives a nominal 300 mm Blackwell logic-wafer format from three official-source
observations: NVIDIA identifies Blackwell's TSMC 4NP process; TSMC identifies 4 nm production on a
12-inch facility; and TSMC labels its 12-inch GIGAFAB profile as 300 mm capacity. The claim does not
identify Blackwell fab location, wafer starts, yield, allocation, or production volume.

Run the validation and release build from the package root:

```sh
python3 -m supply_intelligence validate-manufacturing-revision \
  --recipe examples/revisions/blackwell-wafer-format-2026-07-19.json \
  --source-root .

python3 -m supply_intelligence build-manufacturing-revision \
  --recipe examples/revisions/blackwell-wafer-format-2026-07-19.json \
  --source-root . \
  --output-dir releases/2026-07-19-blackwell-manufacturing-wafer-format-evidence
```

The checked release replaces one of 21 synthetic manufacturing inputs and leaves 20. The numerical
diameter stays 300 mm, so every conversion output remains byte-for-byte numerically identical. The
result comparison emits one `estimate_posture_changed` alert and no output or bottleneck revision.
This is evidence-progress, not evidence of actual Blackwell production.

## Checked reticle-geometry revision

The next checked revision stacks on the wafer-format release. NVIDIA reports that Blackwell uses two
reticle-limit logic dies on TSMC 4NP; ASML reports a 26 mm by 33 mm maximum exposure field for its
standard full-field lithography platform. The derived claim treats those facts as an uncertainty
boundary, not a die measurement: short-axis width is 25.5/26/26 mm and long-axis height is
31/32/33 mm at low/base/high.

```sh
python3 -m supply_intelligence validate-manufacturing-revision \
  --recipe examples/revisions/blackwell-reticle-geometry-2026-07-19.json \
  --source-root .

python3 -m supply_intelligence build-manufacturing-revision \
  --recipe examples/revisions/blackwell-reticle-geometry-2026-07-19.json \
  --source-root . \
  --output-dir releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence
```

The release replaces two more synthetic inputs and leaves 18. Relative to the wafer-format
predecessor, P50 gross logic dies per wafer rises 0.67%, P50 complete-system equivalents rises
0.77%, and logic's binding probability moves from 70.75% to 68.69%. The default alert policy emits
the two posture changes; the output and bottleneck moves stay below its materiality thresholds.

The interval is falsifiable by a public die photo with a calibrated scale, a mask/floorplan report,
or a vendor dimension. Until then, it must not be described as a teardown-measured die size. Wafer
starts, edge exclusion, scribe width, defect density, sort yield, performance binning, and package
throughput remain synthetic.
