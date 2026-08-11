from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.claim_ledger import ingest_claim_pack, query_claim_snapshot
from supply_intelligence.cli import main
from supply_intelligence.sec_filing_text_index import (
    load_sec_filing_text_recipe,
    write_sec_filing_text_release,
)
from supply_intelligence.sec_reviewed_claims import (
    SEC_REVIEWED_CLAIMS_RELEASE_FORMAT,
    load_sec_reviewed_claims_recipe,
    write_sec_reviewed_claims_release,
)
from tests.test_sec_filing_text_index import (
    HTML,
    _document_release,
    _recipe_document,
    _write_recipe,
)
from tests.test_sec_filings_adapter import _json_bytes


PHRASE = "HBM demand remains strong"
ACCESSION = "0001045810-26-000112"


def _text_release(root: Path) -> Path:
    documents = _document_release(root)
    recipe = load_sec_filing_text_recipe(
        _write_recipe(root, _recipe_document(documents))
    )
    destination = root / "text-release"
    write_sec_filing_text_release(documents, recipe, destination)
    return destination


def _claim() -> dict:
    return {
        "claim_key": "company.nvidia.hbm-demand-signal.2026q2",
        "subject": "NVIDIA CORP",
        "predicate": "reports HBM demand signal",
        "value": "strong",
        "unit": "qualitative_signal",
        "dimensions": {
            "entity_scope": "company",
            "geography": "global",
            "period": "2026-Q2",
            "stage": "company_disclosure",
            "capacity_basis": "not_capacity",
            "quantity_semantics": "qualitative_signal",
            "product": "HBM",
            "process_node": None,
            "customer": None,
            "technology": "HBM",
            "qualifier": "management_disclosure",
        },
        "posture": "reported",
        "status": "asserted",
        "valid_from": "2026-06-24",
        "valid_to": None,
        "methodology": (
            "Record the reviewed qualitative wording without converting it into capacity, "
            "allocation, production, or shipment quantities."
        ),
        "confidence": 0.9,
        "confirming_evidence": (
            "A later company filing repeats the same HBM demand characterization."
        ),
        "falsifying_evidence": (
            "A later company filing retracts or materially weakens the HBM demand characterization."
        ),
        "supersedes_revision_id": None,
    }


def _review_recipe_document(
    release: Path,
    *,
    expected_text: str = PHRASE,
    source_manifest_sha256: str | None = None,
    recorded_at: str = "2026-07-19T22:00:00Z",
) -> dict:
    result = json.loads((release / "result.json").read_text(encoding="utf-8"))
    text_path = release / result["documents"][0]["text_file"]
    text = text_path.read_text(encoding="utf-8").rstrip("\n")
    start = text.index(PHRASE)
    return {
        "format": "ai-supply-sec-reviewed-claims.v1",
        "id": "nvidia-hbm-disclosure-review",
        "source_manifest_sha256": source_manifest_sha256
        or hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest(),
        "recorded_at": recorded_at,
        "reviewer": "AI Supply Intelligence analyst",
        "claims": [
            {
                "accession_number": ACCESSION,
                "character_start": start,
                "character_end": start + len(PHRASE),
                "expected_text": expected_text,
                "claim": _claim(),
            }
        ],
    }


def _write_review_recipe(root: Path, value: dict, name: str = "review.json") -> Path:
    path = root / name
    path.write_bytes(_json_bytes(value))
    return path


class SecReviewedClaimsTests(unittest.TestCase):
    def test_release_anchors_claim_and_ingests_into_common_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _text_release(root)
            recipe = load_sec_reviewed_claims_recipe(
                _write_review_recipe(root, _review_recipe_document(source))
            )
            destination = root / "reviewed-release"
            first = write_sec_reviewed_claims_release(source, recipe, destination)

            self.assertEqual(SEC_REVIEWED_CLAIMS_RELEASE_FORMAT, first["format"])
            self.assertEqual(1, first["claim_count"])
            self.assertEqual(
                HTML,
                (
                    destination
                    / "sources"
                    / "documents"
                    / "000104581026000112"
                    / "nvda-20260624.htm"
                ).read_bytes(),
            )
            result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            reviewed = result["reviewed_claims"][0]
            text = (destination / reviewed["text_file"]).read_text(encoding="utf-8").rstrip("\n")
            self.assertEqual(
                PHRASE,
                text[reviewed["character_start"] : reviewed["character_end"]],
            )
            self.assertIn("Anchor is not interpretation", (destination / "dashboard.html").read_text())

            database = root / "claims.sqlite3"
            ingested = ingest_claim_pack(database, destination / "ingest_pack.json")
            self.assertEqual(1, ingested["inserted_sources"])
            self.assertEqual(1, ingested["inserted_claims"])
            snapshot = query_claim_snapshot(
                database,
                valid_at="2026-06-24",
                known_at="2026-07-19T22:00:00Z",
            )
            self.assertEqual(1, snapshot["claim_count"])
            claim = snapshot["claims"][0]
            self.assertEqual("strong", claim["value"])
            self.assertEqual("not_capacity", claim["dimensions"]["capacity_basis"])
            self.assertIn("Exact evidence anchor", claim["methodology"])
            self.assertEqual(
                hashlib.sha256(HTML).hexdigest(),
                claim["evidence"][0]["content_sha256"],
            )

            replay = write_sec_reviewed_claims_release(source, recipe, destination)
            self.assertEqual(first["files"], replay["files"])

    def test_anchor_manifest_time_and_claim_schema_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _text_release(root)

            mismatch = load_sec_reviewed_claims_recipe(
                _write_review_recipe(
                    root,
                    _review_recipe_document(source, expected_text="HBM demand remains weak"),
                    "mismatch.json",
                )
            )
            with self.assertRaisesRegex(ValueError, "text anchor mismatch"):
                write_sec_reviewed_claims_release(source, mismatch, root / "mismatch")

            wrong_manifest = load_sec_reviewed_claims_recipe(
                _write_review_recipe(
                    root,
                    _review_recipe_document(source, source_manifest_sha256="0" * 64),
                    "wrong-manifest.json",
                )
            )
            with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
                write_sec_reviewed_claims_release(
                    source,
                    wrong_manifest,
                    root / "wrong-manifest",
                )

            early = load_sec_reviewed_claims_recipe(
                _write_review_recipe(
                    root,
                    _review_recipe_document(source, recorded_at="2026-07-19T20:59:59Z"),
                    "early.json",
                )
            )
            with self.assertRaisesRegex(ValueError, "cannot precede source retrieval"):
                write_sec_reviewed_claims_release(source, early, root / "early")

            invalid = _review_recipe_document(source)
            invalid["claims"][0]["claim"]["evidence"] = []
            with self.assertRaisesRegex(ValueError, "evidence is assigned"):
                load_sec_reviewed_claims_recipe(
                    _write_review_recipe(root, invalid, "invalid-evidence.json")
                )

            incomplete = _review_recipe_document(source)
            del incomplete["claims"][0]["claim"]["predicate"]
            incomplete_recipe = load_sec_reviewed_claims_recipe(
                _write_review_recipe(root, incomplete, "incomplete.json")
            )
            with self.assertRaisesRegex(ValueError, "predicate is required"):
                write_sec_reviewed_claims_release(
                    source,
                    incomplete_recipe,
                    root / "incomplete",
                )

    def test_source_semantic_hashes_and_existing_release_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _text_release(root)
            recipe = load_sec_reviewed_claims_recipe(
                _write_review_recipe(root, _review_recipe_document(source))
            )
            destination = root / "reviewed-release"
            write_sec_reviewed_claims_release(source, recipe, destination)
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_sec_reviewed_claims_release(source, recipe, destination)

            result_path = source / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["documents"][0]["text_sha256"] = "0" * 64
            result_path.write_bytes(_json_bytes(result))
            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw = result_path.read_bytes()
            manifest["files"]["result.json"] = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            manifest_path.write_bytes(_json_bytes(manifest))
            tampered_recipe_value = _review_recipe_document(source)
            tampered_recipe_value["source_manifest_sha256"] = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            tampered_recipe = load_sec_reviewed_claims_recipe(
                _write_review_recipe(root, tampered_recipe_value, "tampered.json")
            )
            with self.assertRaisesRegex(ValueError, "text metadata hash mismatch"):
                write_sec_reviewed_claims_release(
                    source,
                    tampered_recipe,
                    root / "tampered-release",
                )

    def test_offline_cli_builds_reviewed_claim_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _text_release(root)
            recipe_path = _write_review_recipe(root, _review_recipe_document(source))
            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-sec-reviewed-claims",
                        "--text-release",
                        str(source),
                        "--recipe",
                        str(recipe_path),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual(1, json.loads(output.getvalue())["claim_count"])
            self.assertTrue((destination / "ingest_pack.json").exists())


if __name__ == "__main__":
    unittest.main()
