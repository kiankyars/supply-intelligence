from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.sec_filing_documents import (
    SEC_FILING_DOCUMENTS_RELEASE_FORMAT,
    fetch_sec_filing_documents,
    load_local_sec_filing_documents,
    load_sec_filing_document_selection,
    resolve_sec_filing_document_selection,
    write_sec_filing_documents_release,
)
from supply_intelligence.sec_filings_adapter import (
    load_local_sec_sources,
    load_sec_watch,
    write_sec_filings_release,
)
from tests.test_sec_filings_adapter import (
    _json_bytes,
    _submissions,
    _write_source,
    _write_watch,
)


def _filings_release(root: Path) -> Path:
    watch = load_sec_watch(_write_watch(root))
    _write_source(root, _submissions())
    destination = root / "filings-release"
    write_sec_filings_release(
        watch,
        load_local_sec_sources(watch, root),
        destination,
        retrieved_at="2026-07-19T20:00:00Z",
    )
    return destination


def _selection_document(
    release: Path,
    *,
    accessions: list[str] | None = None,
    expected_sha256: str | None = None,
) -> dict:
    selected = accessions or ["0001045810-26-000112"]
    return {
        "format": "ai-supply-sec-filing-selection.v1",
        "id": "nvidia-filing-review",
        "source_manifest_sha256": hashlib.sha256(
            (release / "manifest.json").read_bytes()
        ).hexdigest(),
        "filings": [
            {
                "accession_number": accession,
                "review_reason": "Review official quarterly supply and demand disclosures.",
                "expected_sha256": expected_sha256,
            }
            for accession in selected
        ],
    }


def _write_selection(root: Path, value: dict) -> Path:
    path = root / "selection.json"
    path.write_bytes(_json_bytes(value))
    return path


class SecFilingDocumentTests(unittest.TestCase):
    def test_document_release_preserves_raw_bytes_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            filings_release = _filings_release(root)
            raw_document = b"<!doctype html><title>NVIDIA 8-K</title><p>Official filing.</p>\n"
            selection_path = _write_selection(
                root,
                _selection_document(
                    filings_release,
                    expected_sha256=hashlib.sha256(raw_document).hexdigest(),
                ),
            )
            selection = load_sec_filing_document_selection(selection_path)
            destination = root / "documents-release"
            first = write_sec_filing_documents_release(
                filings_release,
                selection,
                {"0001045810-26-000112": raw_document},
                destination,
                retrieved_at="2026-07-19T21:00:00Z",
            )
            self.assertEqual(SEC_FILING_DOCUMENTS_RELEASE_FORMAT, first["format"])
            self.assertEqual(1, first["document_count"])
            local = (
                destination
                / "documents"
                / "000104581026000112"
                / "nvda-20260624.htm"
            )
            self.assertEqual(raw_document, local.read_bytes())
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Raw evidence, not a claim", dashboard)
            self.assertIn("Review official quarterly", dashboard)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())
            replay = write_sec_filing_documents_release(
                filings_release,
                selection,
                {"0001045810-26-000112": raw_document},
                destination,
                retrieved_at="2026-07-19T21:00:00Z",
            )
            self.assertEqual(first["files"], replay["files"])
            local.write_bytes(b"drift")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_sec_filing_documents_release(
                    filings_release,
                    selection,
                    {"0001045810-26-000112": raw_document},
                    destination,
                    retrieved_at="2026-07-19T21:00:00Z",
                )

    def test_selection_pins_source_manifest_accession_and_document_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = _filings_release(root)
            selection_value = _selection_document(release)
            selection_value["source_manifest_sha256"] = "0" * 64
            selection = load_sec_filing_document_selection(
                _write_selection(root, selection_value)
            )
            with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
                resolve_sec_filing_document_selection(release, selection)

            missing_value = _selection_document(
                release,
                accessions=["0001045810-26-999999"],
            )
            missing = load_sec_filing_document_selection(
                _write_selection(root, missing_value)
            )
            with self.assertRaisesRegex(ValueError, "absent from source release"):
                resolve_sec_filing_document_selection(release, missing)

            mismatch_value = _selection_document(
                release,
                expected_sha256="f" * 64,
            )
            mismatch = load_sec_filing_document_selection(
                _write_selection(root, mismatch_value)
            )
            with self.assertRaisesRegex(ValueError, "document SHA-256 mismatch"):
                write_sec_filing_documents_release(
                    release,
                    mismatch,
                    {"0001045810-26-000112": b"actual"},
                    root / "mismatch",
                    retrieved_at="2026-07-19T21:00:00Z",
                )

    def test_fetch_requires_contact_and_uses_selected_sec_archive_url(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, limit):
                return b"<html>filing</html>"

        filing = {
            "accession_number": "0001045810-26-000112",
            "filing_url": "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000112/nvda.htm",
        }
        with self.assertRaisesRegex(ValueError, "contact email"):
            fetch_sec_filing_documents([filing], user_agent="AI Supply Intelligence")
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return Response()

        documents = fetch_sec_filing_documents(
            [filing],
            user_agent="AI Supply Intelligence research@example.com",
            opener=opener,
        )
        self.assertEqual(b"<html>filing</html>", documents[filing["accession_number"]])
        request, timeout = requests[0]
        self.assertEqual(60, timeout)
        self.assertEqual(filing["filing_url"], request.full_url)
        self.assertEqual(
            "AI Supply Intelligence research@example.com",
            request.get_header("User-agent"),
        )

    def test_offline_cli_builds_document_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = _filings_release(root)
            selection_path = _write_selection(root, _selection_document(release))
            selection = load_sec_filing_document_selection(selection_path)
            selected, _ = resolve_sec_filing_document_selection(release, selection)
            source_root = root / "captured"
            source_path = (
                source_root
                / "000104581026000112"
                / "nvda-20260624.htm"
            )
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"<html>captured</html>\n")
            self.assertEqual(
                {"0001045810-26-000112"},
                set(load_local_sec_filing_documents(selected, source_root)),
            )
            destination = root / "document-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-sec-filing-documents-release",
                        "--filings-release",
                        str(release),
                        "--selection",
                        str(selection_path),
                        "--source-dir",
                        str(source_root),
                        "--retrieved-at",
                        "2026-07-19T21:00:00Z",
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            metadata = json.loads(output.getvalue())
            self.assertEqual(1, metadata["document_count"])
            self.assertTrue((destination / "dashboard.html").exists())


if __name__ == "__main__":
    unittest.main()
