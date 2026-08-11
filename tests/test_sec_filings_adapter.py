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
from supply_intelligence.sec_filings_adapter import (
    SEC_FILINGS_RELEASE_FORMAT,
    fetch_sec_sources,
    load_local_sec_sources,
    load_sec_watch,
    normalize_sec_submissions,
    write_sec_filings_release,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _watch_document(*, entity_count: int = 1) -> dict:
    entities = [{"id": "nvidia", "cik": "1045810"}]
    if entity_count == 2:
        entities.append({"id": "micron", "cik": "723125"})
    return {
        "format": "ai-supply-sec-filings-watch.v1",
        "id": "ai-supply-filings",
        "filing_date_from": "2026-01-01",
        "filing_date_to": "2026-07-19",
        "forms": ["10-K", "10-Q", "8-K", "6-K"],
        "entities": entities,
    }


def _filing(
    accession: str,
    *,
    form: str,
    filing_date: str,
    report_date: str = "",
    primary_document: str = "filing.htm",
    description: str = "",
) -> dict:
    return {
        "accessionNumber": accession,
        "filingDate": filing_date,
        "reportDate": report_date,
        "acceptanceDateTime": f"{filing_date}T16:07:31.000Z",
        "form": form,
        "items": "2.02,9.01" if form == "8-K" else "",
        "primaryDocument": primary_document,
        "primaryDocDescription": description or form,
        "isXBRL": 1 if form in {"10-K", "10-Q", "8-K"} else 0,
        "isInlineXBRL": 1 if form in {"10-K", "10-Q", "8-K"} else 0,
    }


def _submissions(
    *,
    cik: str = "1045810",
    name: str = "NVIDIA CORP",
    filings: list[dict] | None = None,
    supplemental: list[dict] | None = None,
) -> dict:
    rows = filings or [
        _filing(
            "0001045810-26-000111",
            form="10-Q",
            filing_date="2026-05-28",
            report_date="2026-04-26",
            primary_document="nvda-20260426.htm",
        ),
        _filing(
            "0001045810-26-000112",
            form="8-K",
            filing_date="2026-06-24",
            primary_document="nvda-20260624.htm",
        ),
        _filing(
            "0001045810-26-000113",
            form="4",
            filing_date="2026-06-25",
            primary_document="ownership.xml",
        ),
    ]
    fields = list(rows[0]) if rows else [
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "items",
        "primaryDocument",
        "primaryDocDescription",
        "isXBRL",
        "isInlineXBRL",
    ]
    return {
        "cik": cik,
        "name": name,
        "filings": {
            "recent": {field: [row[field] for row in rows] for field in fields},
            "files": supplemental or [],
        },
    }


def _write_watch(root: Path, *, entity_count: int = 1) -> Path:
    path = root / "watch.json"
    path.write_bytes(_json_bytes(_watch_document(entity_count=entity_count)))
    return path


def _write_source(root: Path, value: dict, *, cik: str = "0001045810") -> Path:
    path = root / f"CIK{cik}.json"
    path.write_bytes(_json_bytes(value))
    return path


class SecFilingsAdapterTests(unittest.TestCase):
    def test_offline_release_builds_auditable_claim_pack_and_replays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watch_path = _write_watch(root)
            source_path = _write_source(root, _submissions())
            watch = load_sec_watch(watch_path)
            destination = root / "release"
            first = write_sec_filings_release(
                watch,
                load_local_sec_sources(watch, root),
                destination,
                retrieved_at="2026-07-19T20:00:00Z",
            )
            self.assertEqual(SEC_FILINGS_RELEASE_FORMAT, first["format"])
            self.assertEqual(2, first["filing_count"])
            self.assertEqual(2, first["new_filing_count"])
            self.assertTrue(first["ingest_pack_present"])
            self.assertEqual(
                source_path.read_bytes(),
                (destination / "sources" / source_path.name).read_bytes(),
            )
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Disclosure signal only", dashboard)
            self.assertIn("not_capacity", dashboard)
            self.assertIn("0001045810-26-000112", dashboard)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            for name, descriptor in manifest["files"].items():
                raw = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(raw))
                self.assertEqual(descriptor["sha256"], hashlib.sha256(raw).hexdigest())

            database = root / "claims.sqlite3"
            ingest = ingest_claim_pack(database, destination / "ingest_pack.json")
            self.assertEqual(2, ingest["inserted_claims"])
            snapshot = query_claim_snapshot(
                database,
                valid_at="2026-07-19",
                known_at="2026-07-19T20:00:00Z",
            )
            self.assertEqual(2, snapshot["claim_count"])
            claim = snapshot["claims"][0]
            self.assertEqual("not_capacity", claim["dimensions"]["capacity_basis"])
            self.assertEqual("filing_event", claim["unit"])
            self.assertEqual("U.S. Securities and Exchange Commission", claim["evidence"][0]["publisher"])

            replay = write_sec_filings_release(
                watch,
                load_local_sec_sources(watch, root),
                destination,
                retrieved_at="2026-07-19T20:00:00Z",
            )
            self.assertEqual(first["files"], replay["files"])
            (destination / "filings.csv").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_sec_filings_release(
                    watch,
                    load_local_sec_sources(watch, root),
                    destination,
                    retrieved_at="2026-07-19T20:00:00Z",
                )

    def test_previous_release_emits_only_additions_and_no_change_omits_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watch = load_sec_watch(_write_watch(root))
            first_filing = _filing(
                "0001045810-26-000111",
                form="10-Q",
                filing_date="2026-05-28",
                report_date="2026-04-26",
            )
            first_sources = {"nvidia": _json_bytes(_submissions(filings=[first_filing]))}
            first_release = root / "first"
            write_sec_filings_release(
                watch,
                first_sources,
                first_release,
                retrieved_at="2026-07-19T20:00:00Z",
            )

            second_filing = _filing(
                "0001045810-26-000112",
                form="8-K",
                filing_date="2026-06-24",
            )
            second_sources = {
                "nvidia": _json_bytes(
                    _submissions(filings=[first_filing, second_filing])
                )
            }
            second_release = root / "second"
            second = write_sec_filings_release(
                watch,
                second_sources,
                second_release,
                retrieved_at="2026-07-19T21:00:00Z",
                previous_release=first_release,
            )
            self.assertEqual(1, second["new_filing_count"])
            pack = json.loads(
                (second_release / "ingest_pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, len(pack["claims"]))
            self.assertEqual("8-K", pack["claims"][0]["value"]["form"])

            unchanged_release = root / "unchanged"
            unchanged = write_sec_filings_release(
                watch,
                second_sources,
                unchanged_release,
                retrieved_at="2026-07-19T22:00:00Z",
                previous_release=second_release,
            )
            self.assertEqual(0, unchanged["new_filing_count"])
            self.assertFalse(unchanged["ingest_pack_present"])
            self.assertFalse((unchanged_release / "ingest_pack.json").exists())

    def test_source_contract_rejects_malformed_or_incomplete_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watch = load_sec_watch(_write_watch(root))
            mutations = {}

            wrong_cik = _submissions()
            wrong_cik["cik"] = "723125"
            mutations["source CIK"] = (wrong_cik, "source CIK does not match")

            unequal = _submissions()
            unequal["filings"]["recent"]["form"].pop()
            mutations["column lengths"] = (unequal, "different lengths")

            unsafe = _submissions()
            unsafe["filings"]["recent"]["primaryDocument"][0] = "../filing.htm"
            mutations["unsafe document"] = (unsafe, "must be a file name")

            duplicate = _submissions()
            duplicate["filings"]["recent"]["accessionNumber"][1] = duplicate[
                "filings"
            ]["recent"]["accessionNumber"][0]
            mutations["duplicate accession"] = (duplicate, "duplicate accession")

            incomplete = _submissions(
                supplemental=[
                    {
                        "name": "CIK0001045810-submissions-001.json",
                        "filingFrom": "1999-01-01",
                        "filingTo": "2025-05-27",
                    }
                ]
            )
            mutations["incomplete history"] = (incomplete, "predates recent submissions")

            for label, (source, message) in mutations.items():
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, message):
                    normalize_sec_submissions(
                        watch,
                        {"nvidia": _json_bytes(source)},
                        retrieved_at="2026-07-19T20:00:00Z",
                    )

    def test_previous_release_rejects_metadata_revision_disappearance_and_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watch = load_sec_watch(_write_watch(root))
            filings = [
                _filing(
                    "0001045810-26-000111",
                    form="10-Q",
                    filing_date="2026-05-28",
                ),
                _filing(
                    "0001045810-26-000112",
                    form="8-K",
                    filing_date="2026-06-24",
                ),
            ]
            previous = root / "previous"
            write_sec_filings_release(
                watch,
                {"nvidia": _json_bytes(_submissions(filings=filings))},
                previous,
                retrieved_at="2026-07-19T20:00:00Z",
            )

            changed = [dict(item) for item in filings]
            changed[0] = {**changed[0], "primaryDocDescription": "corrected"}
            with self.assertRaisesRegex(ValueError, "requires reviewed revision"):
                write_sec_filings_release(
                    watch,
                    {"nvidia": _json_bytes(_submissions(filings=changed))},
                    root / "changed",
                    retrieved_at="2026-07-19T21:00:00Z",
                    previous_release=previous,
                )

            with self.assertRaisesRegex(ValueError, "disappeared"):
                write_sec_filings_release(
                    watch,
                    {"nvidia": _json_bytes(_submissions(filings=filings[:1]))},
                    root / "missing",
                    retrieved_at="2026-07-19T21:00:00Z",
                    previous_release=previous,
                )

            (previous / "filings.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                write_sec_filings_release(
                    watch,
                    {"nvidia": _json_bytes(_submissions(filings=filings))},
                    root / "tampered",
                    retrieved_at="2026-07-19T21:00:00Z",
                    previous_release=previous,
                )

    def test_fetch_requires_declared_contact_and_sets_official_request_headers(self) -> None:
        class Response:
            status = 200

            def __init__(self, raw: bytes):
                self.raw = raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, limit: int) -> bytes:
                self.asserted_limit = limit
                return self.raw

        with tempfile.TemporaryDirectory() as temporary:
            watch = load_sec_watch(_write_watch(Path(temporary)))
            with self.assertRaisesRegex(ValueError, "contact email"):
                fetch_sec_sources(watch, user_agent="AI Supply Intelligence")
            with self.assertRaisesRegex(ValueError, "at least 0.1"):
                fetch_sec_sources(
                    watch,
                    user_agent="AI Supply Intelligence research@example.com",
                    minimum_interval_seconds=0.01,
                )

            requests = []

            def opener(request, timeout):
                requests.append((request, timeout))
                return Response(_json_bytes(_submissions()))

            documents = fetch_sec_sources(
                watch,
                user_agent="AI Supply Intelligence research@example.com",
                opener=opener,
            )
            self.assertEqual({"nvidia"}, set(documents))
            request, timeout = requests[0]
            self.assertEqual(30, timeout)
            self.assertEqual(
                "https://data.sec.gov/submissions/CIK0001045810.json",
                request.full_url,
            )
            self.assertEqual(
                "AI Supply Intelligence research@example.com",
                request.get_header("User-agent"),
            )

    def test_offline_cli_writes_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watch_path = _write_watch(root)
            _write_source(root, _submissions())
            destination = root / "release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-sec-filings-release",
                        "--watch",
                        str(watch_path),
                        "--source-dir",
                        str(root),
                        "--retrieved-at",
                        "2026-07-19T20:00:00Z",
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            metadata = json.loads(output.getvalue())
            self.assertEqual(2, metadata["new_filing_count"])
            self.assertEqual(str(destination.resolve()), metadata["output_dir"])


if __name__ == "__main__":
    unittest.main()
