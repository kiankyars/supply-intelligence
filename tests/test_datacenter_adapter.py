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

from supply_intelligence.cli import main
from supply_intelligence.datacenter_adapter import (
    DATACENTER_RELEASE_FORMAT,
    DatacenterAggregationPolicy,
    DatacenterCapacityStage,
    DatacenterPowerSelection,
    load_datacenter_power,
    load_datacenter_selection,
)


RECORDED_AT = "2026-07-18T02:00:00Z"
CAPACITY_FIELDS = (
    "entity_id",
    "entity_kind",
    "name",
    "metric",
    "stage",
    "unit",
    "low",
    "base",
    "high",
    "method",
    "confidence",
    "as_of_date",
    "target_date",
    "evidence_id",
    "notes",
    "source_url",
    "source_publisher",
    "source_license",
    "source_retrieved_at",
)
ENTITY_FIELDS = (
    "entity_id",
    "entity_kind",
    "stable_key",
    "name",
    "country",
    "owner",
    "operator",
    "users",
    "status",
    "status_as_of",
    "status_confidence",
    "status_method",
    "status_evidence_id",
)
EVIDENCE_FIELDS = (
    "evidence_id",
    "kind",
    "title",
    "source_url",
    "publisher",
    "source_family",
    "license",
    "attribution",
    "published_at",
    "retrieved_at",
    "content_hash",
)


def _csv_bytes(fields: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _build_release(
    root: Path,
    *,
    stage: str = "operational",
    target_date: str = "",
) -> Path:
    release = root / "datacenter-release"
    release.mkdir()
    evidence_id = "evidence-site-a"
    files = {
        "capacity_estimates.csv": _csv_bytes(
            CAPACITY_FIELDS,
            [
                {
                    "entity_id": "site-a",
                    "entity_kind": "campus",
                    "name": "Fixture AI Campus",
                    "metric": "critical_it_mw",
                    "stage": stage,
                    "unit": "MW",
                    "low": 80,
                    "base": 100,
                    "high": 125,
                    "method": "modeled",
                    "confidence": 0.78,
                    "as_of_date": "2026-05-01",
                    "target_date": target_date,
                    "evidence_id": evidence_id,
                    "notes": "Fixture critical IT capacity interval.",
                    "source_url": "https://example.com/campus",
                    "source_publisher": "Fixture Data",
                    "source_license": "CC-BY-4.0",
                    "source_retrieved_at": RECORDED_AT,
                }
            ],
        ),
        "entities.csv": _csv_bytes(
            ENTITY_FIELDS,
            [
                {
                    "entity_id": "site-a",
                    "entity_kind": "campus",
                    "stable_key": "fixture:site-a",
                    "name": "Fixture AI Campus",
                    "country": "United States",
                    "owner": "Fixture Owner",
                    "operator": "Fixture Operator",
                    "users": "Customer A #confident",
                    "status": "expansion",
                    "status_as_of": "2026-07-17",
                    "status_confidence": 0.8,
                    "status_method": "fixture_method",
                    "status_evidence_id": evidence_id,
                }
            ],
        ),
        "evidence.csv": _csv_bytes(
            EVIDENCE_FIELDS,
            [
                {
                    "evidence_id": evidence_id,
                    "kind": "third_party_dataset",
                    "title": "Fixture data-center record",
                    "source_url": "https://example.com/campus",
                    "publisher": "Fixture Data",
                    "source_family": "fixture-data",
                    "license": "CC-BY-4.0",
                    "attribution": "Fixture Data (2026)",
                    "published_at": "",
                    "retrieved_at": RECORDED_AT,
                    "content_hash": "c" * 64,
                }
            ],
        ),
    }
    manifest = {
        "format": DATACENTER_RELEASE_FORMAT,
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


def _selection(
    *,
    stage: DatacenterCapacityStage = DatacenterCapacityStage.OPERATIONAL,
) -> DatacenterPowerSelection:
    return DatacenterPowerSelection(
        target_quarter="2026-Q3",
        stage=stage,
        entity_ids=("site-a",),
        aggregation_policy=DatacenterAggregationPolicy.SINGLE_SITE,
        aggregation_rationale="One resolved campus is selected.",
        scope_name="Fixture customer site envelope",
        scope_description="One site tagged for the fixture customer.",
        expected_release_as_of="2026-07-17",
        expected_release_recorded_at=RECORDED_AT,
        minimum_capacity_as_of="2026-01-01",
        confirming_evidence="Metered load and reservations establish unused headroom.",
        falsifying_evidence="Existing load consumes the full campus envelope.",
        required_user_labels=("Customer A #confident",),
        required_countries=("United States",),
        correlation_group="fixture-site-power",
    )


class DatacenterAdapterTests(unittest.TestCase):
    def test_import_preserves_gross_envelope_and_blocks_incremental_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            result = load_datacenter_power(release, _selection())
        self.assertEqual((80, 100, 125), (
            result.estimate.low,
            result.estimate.base,
            result.estimate.high,
        ))
        self.assertEqual("modeled", result.estimate.posture.value)
        self.assertFalse(result.usable_as_incremental_power_pool)
        self.assertEqual("Fixture AI Campus", result.sites[0]["name"])
        self.assertIn("not vacant or platform-allocated", result.estimate.methodology)
        self.assertEqual(1, len(result.evidence))

    def test_import_rejects_user_scope_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            selection = _selection()
            document = selection.as_dict()
            document["required_user_labels"] = ["Customer B #confident"]
            with self.assertRaisesRegex(ValueError, "user-label mismatch"):
                load_datacenter_power(
                    release,
                    load_selection_from_document(document, Path(temporary)),
                )

    def test_forecast_must_be_available_before_quarter_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(
                Path(temporary),
                stage="forecast",
                target_date="2026-11-01",
            )
            with self.assertRaisesRegex(ValueError, "not available by target quarter end"):
                load_datacenter_power(
                    release,
                    _selection(stage=DatacenterCapacityStage.FORECAST),
                )

    def test_import_rejects_release_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = _build_release(Path(temporary))
            with (release / "entities.csv").open("ab") as stream:
                stream.write(b"\n")
            with self.assertRaisesRegex(ValueError, "byte count mismatch"):
                load_datacenter_power(release, _selection())

    def test_selection_and_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = _build_release(root)
            selection_path = root / "selection.json"
            selection_path.write_text(
                json.dumps(_selection().as_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_selection(), load_datacenter_selection(selection_path))
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "import-datacenter-power",
                        "--release-dir",
                        str(release),
                        "--selection",
                        str(selection_path),
                    ]
                )
        self.assertEqual(0, status)
        document = json.loads(output.getvalue())
        self.assertFalse(document["usable_as_incremental_power_pool"])
        self.assertEqual(100, document["estimate"]["base"])
        self.assertEqual(4, len(document["blocking_inputs"]))


def load_selection_from_document(
    document: dict[str, object],
    root: Path,
) -> DatacenterPowerSelection:
    path = root / "modified-selection.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_datacenter_selection(path)


if __name__ == "__main__":
    unittest.main()
