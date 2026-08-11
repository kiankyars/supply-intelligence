from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.atlas_adapter import (
    ATLAS_RELEASE_FORMAT,
    QUARTERLY_FORECAST_FILE,
    AtlasAggregationPolicy,
    AtlasCapacityBasis,
    AtlasCapacitySelection,
    AtlasSourceMode,
    load_atlas_capacity,
    load_atlas_selection,
)
from supply_intelligence.cli import main


RECORDED_AT = "2026-07-17T23:00:00Z"
FORECAST_VINTAGE = "2026-07-17T22:00:00Z"
PARAMETER_FINGERPRINT = "a" * 64
CAPACITY_FIELDS = (
    "claim_id",
    "entity_id",
    "predicate",
    "claim_kind",
    "metric",
    "basis",
    "unit",
    "low",
    "base",
    "high",
    "period_start",
    "period_end",
    "valid_from",
    "recorded_at",
    "method",
    "confidence",
    "evidence_link_count",
    "dependency_count",
)
EVIDENCE_FIELDS = (
    "claim_id",
    "entity_id",
    "predicate",
    "role",
    "evidence_link_id",
    "source_document_id",
    "source_record_id",
    "source_family",
    "publisher",
    "source_record_observed_at",
    "source_record_sha256",
    "document_url",
    "published_at",
    "retrieved_at",
    "content_sha256",
    "license",
    "locator",
    "excerpt",
)
FORECAST_FIELDS = (
    "capacity_claim_id",
    "forecast_vintage",
    "parameter_fingerprint",
    "input_basis",
    "output_basis",
    "quantity_semantics",
    "metric",
    "unit",
    "quarter",
    "p10",
    "p50",
    "p90",
)


def _csv_bytes(fields: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _build_release(root: Path, *, wrong_period: bool = False) -> Path:
    release = root / "atlas-release"
    release.mkdir()
    capacity_rows = []
    claims = []
    evidence_rows = []
    forecast_rows = []
    for suffix, values, confidence in (
        ("a", (80, 100, 125), 0.82),
        ("b", (40, 50, 65), 0.71),
    ):
        source_claim = f"claim-source-{suffix}"
        capacity_claim = f"claim-capacity-{suffix}"
        capacity_rows.append(
            {
                "claim_id": capacity_claim,
                "entity_id": f"production-unit-{suffix}",
                "predicate": "quarterly_advanced_package_output",
                "claim_kind": "derived_estimate",
                "metric": "advanced_packages",
                "basis": "economically_usable",
                "unit": "package",
                "low": values[0],
                "base": values[1],
                "high": values[2],
                "period_start": "2026-07-01",
                "period_end": "2027-01-01" if wrong_period else "2026-10-01",
                "valid_from": "2026-07-01",
                "recorded_at": RECORDED_AT,
                "method": "fixture derived output",
                "confidence": confidence,
                "evidence_link_count": 0,
                "dependency_count": 1,
            }
        )
        claims.extend(
            [
                {
                    "id": source_claim,
                    "claim_kind": "source_statement",
                    "value_kind": "scalar",
                    "dependencies": [],
                },
                {
                    "id": capacity_claim,
                    "claim_kind": "derived_estimate",
                    "value_kind": "capacity",
                    "dependencies": [
                        {
                            "depends_on_claim_version_id": source_claim,
                            "dependency_kind": "derived_from",
                        }
                    ],
                },
            ]
        )
        evidence_rows.append(
            {
                "claim_id": source_claim,
                "entity_id": f"production-unit-{suffix}",
                "predicate": "reported_output",
                "role": "support",
                "evidence_link_id": f"evidence-{suffix}",
                "source_document_id": "document-1",
                "source_record_id": "",
                "source_family": "company-primary",
                "publisher": "Fixture Semiconductor",
                "source_record_observed_at": "",
                "source_record_sha256": "",
                "document_url": "https://example.com/official-capacity",
                "published_at": "2026-07-10",
                "retrieved_at": RECORDED_AT,
                "content_sha256": "b" * 64,
                "license": "fixture terms",
                "locator": f"table-{suffix}",
                "excerpt": f"Fixture capacity statement {suffix}",
            }
        )
        forecast_rows.append(
            {
                "capacity_claim_id": capacity_claim,
                "forecast_vintage": FORECAST_VINTAGE,
                "parameter_fingerprint": PARAMETER_FINGERPRINT,
                "input_basis": "economically_usable",
                "output_basis": "economically_usable",
                "quantity_semantics": "quarter_total",
                "metric": "advanced_packages",
                "unit": "package",
                "quarter": "2026-Q3",
                "p10": values[0] + 5,
                "p50": values[1] + 5,
                "p90": values[2] + 5,
            }
        )
    source_inputs = [
        {
            "id": "document-1",
            "title": "Official quarterly capacity statement",
            "document_url": "https://example.com/official-capacity",
            "publisher": "Fixture Semiconductor",
        }
    ]
    files = {
        "capacity.csv": _csv_bytes(CAPACITY_FIELDS, capacity_rows),
        "claims.jsonl": (
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in claims
            )
        ).encode("utf-8"),
        "evidence.csv": _csv_bytes(EVIDENCE_FIELDS, evidence_rows),
        "source_inputs.json": (
            json.dumps(source_inputs, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        QUARTERLY_FORECAST_FILE: _csv_bytes(FORECAST_FIELDS, forecast_rows),
    }
    manifest = {
        "format": ATLAS_RELEASE_FORMAT,
        "as_of": "2026-07-17",
        "recorded_at": RECORDED_AT,
        "files": {
            name: {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            for name, raw in sorted(files.items())
        },
    }
    for name, raw in files.items():
        (release / name).write_bytes(raw)
    (release / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return release


def _selection(source_mode: AtlasSourceMode) -> AtlasCapacitySelection:
    forecast = source_mode is AtlasSourceMode.QUARTERLY_OUTPUT_FORECAST
    return AtlasCapacitySelection(
        target_quarter="2026-Q3",
        source_mode=source_mode,
        input_capacity_basis=AtlasCapacityBasis.ECONOMICALLY_USABLE,
        metric="advanced_packages",
        unit="package",
        quantity_semantics="quarter_total",
        claim_ids=("claim-capacity-a", "claim-capacity-b"),
        aggregation_policy=(
            AtlasAggregationPolicy.SUM_EXPLICIT_NONOVERLAPPING_CLAIMS
        ),
        aggregation_rationale=(
            "The selected claims cover separate production units and the same quarter."
        ),
        attribution_basis="full physical output",
        expected_release_as_of="2026-07-17",
        expected_release_recorded_at=RECORDED_AT,
        confirming_evidence="Later audited output supports both selected ranges.",
        falsifying_evidence="A selected unit overlaps another claim or output misses the range.",
        correlation_group="advanced-packaging",
        forecast_vintage=FORECAST_VINTAGE if forecast else None,
        parameter_fingerprint=PARAMETER_FINGERPRINT if forecast else None,
    )


class AtlasAdapterTests(unittest.TestCase):
    def test_canonical_import_sums_explicit_claims_and_traces_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            result = load_atlas_capacity(
                release,
                _selection(AtlasSourceMode.CANONICAL_CAPACITY),
            )
        self.assertEqual((120, 150, 190), (
            result.estimate.low,
            result.estimate.base,
            result.estimate.high,
        ))
        self.assertEqual("derived", result.estimate.posture.value)
        self.assertEqual(0.71, result.estimate.confidence)
        self.assertEqual(2, len(result.evidence))
        self.assertEqual(
            [
                "claim-capacity-a",
                "claim-capacity-b",
                "claim-source-a",
                "claim-source-b",
            ],
            result.lineage["claim_dependency_closure"],
        )
        self.assertIn("without capacity-basis conversion", result.estimate.methodology)

    def test_quarter_total_forecast_pins_vintage_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            result = load_atlas_capacity(
                release,
                _selection(AtlasSourceMode.QUARTERLY_OUTPUT_FORECAST),
            )
        self.assertEqual((130, 160, 200), (
            result.estimate.low,
            result.estimate.base,
            result.estimate.high,
        ))
        self.assertEqual("modeled", result.estimate.posture.value)
        self.assertEqual("quarter_total", result.lineage["quantity_semantics"])
        self.assertEqual(
            PARAMETER_FINGERPRINT,
            result.lineage["selection"]["parameter_fingerprint"],
        )

    def test_canonical_import_rejects_non_exact_quarter_period(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary), wrong_period=True)
            with self.assertRaisesRegex(ValueError, "does not exactly cover 2026-Q3"):
                load_atlas_capacity(
                    release,
                    _selection(AtlasSourceMode.CANONICAL_CAPACITY),
                )

    def test_import_rejects_release_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            with (release / "capacity.csv").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ValueError, "byte count mismatch"):
                load_atlas_capacity(
                    release,
                    _selection(AtlasSourceMode.CANONICAL_CAPACITY),
                )

    def test_selection_round_trip_is_strict(self) -> None:
        selection = _selection(AtlasSourceMode.QUARTERLY_OUTPUT_FORECAST)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.json"
            path.write_text(
                json.dumps(selection.as_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
            loaded = load_atlas_selection(path)
        self.assertEqual(selection, loaded)
        document = selection.as_dict()
        document["unexpected"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected selection fields"):
                load_atlas_selection(path)

    def test_import_cli_emits_reusable_estimate_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = _build_release(root)
            selection_path = root / "selection.json"
            selection_path.write_text(
                json.dumps(
                    _selection(AtlasSourceMode.CANONICAL_CAPACITY).as_dict()
                ),
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "import-atlas-capacity",
                        "--release-dir",
                        str(release),
                        "--selection",
                        str(selection_path),
                    ]
                )
        self.assertEqual(0, status)
        document = json.loads(output.getvalue())
        self.assertEqual("ai-supply-atlas-capacity-import.v1", document["format"])
        self.assertEqual(150, document["estimate"]["base"])
        self.assertEqual(2, len(document["evidence"]))
        self.assertEqual(
            "semiconductor-atlas-release-v1",
            document["lineage"]["atlas_release"]["format"],
        )


if __name__ == "__main__":
    unittest.main()
