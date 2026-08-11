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
    load_sec_filing_document_selection,
    write_sec_filing_documents_release,
)
from supply_intelligence.sec_filing_text_index import (
    SEC_FILING_TEXT_RELEASE_FORMAT,
    load_sec_filing_text_recipe,
    write_sec_filing_text_release,
)
from tests.test_sec_filing_documents import (
    _filings_release,
    _selection_document,
    _write_selection,
)
from tests.test_sec_filings_adapter import _json_bytes


HTML = b"""<!doctype html><html><head><style>.x{content:'HBM'}</style>
<script>const hidden = 'advanced packaging';</script><title>Quarterly filing</title></head>
<body><h1>Supply update</h1><p>HBM demand remains strong alongside advanced packaging.</p>
<p>HBM supply is under review.</p></body></html>\n"""


def _document_release(root: Path) -> Path:
    filings = _filings_release(root)
    selection = load_sec_filing_document_selection(
        _write_selection(root, _selection_document(filings))
    )
    destination = root / "document-release"
    write_sec_filing_documents_release(
        filings,
        selection,
        {"0001045810-26-000112": HTML},
        destination,
        retrieved_at="2026-07-19T21:00:00Z",
    )
    return destination


def _recipe_document(release: Path, *, maximum: int = 10) -> dict:
    return {
        "format": "ai-supply-sec-filing-text-index.v1",
        "id": "ai-supply-disclosure-terms",
        "source_manifest_sha256": hashlib.sha256(
            (release / "manifest.json").read_bytes()
        ).hexdigest(),
        "context_characters": 60,
        "max_hits_per_term_per_document": maximum,
        "terms": [
            {"id": "hbm", "label": "HBM", "category": "memory", "literal": "HBM"},
            {
                "id": "advanced-packaging",
                "label": "Advanced packaging",
                "category": "packaging",
                "literal": "advanced packaging",
            },
            {"id": "cowos", "label": "CoWoS", "category": "packaging", "literal": "CoWoS"},
        ],
    }


def _write_recipe(root: Path, value: dict) -> Path:
    path = root / "text-recipe.json"
    path.write_bytes(_json_bytes(value))
    return path


class SecFilingTextIndexTests(unittest.TestCase):
    def test_text_release_omits_script_style_and_preserves_offsets_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _document_release(root)
            recipe = load_sec_filing_text_recipe(
                _write_recipe(root, _recipe_document(source))
            )
            destination = root / "text-release"
            first = write_sec_filing_text_release(source, recipe, destination)
            self.assertEqual(SEC_FILING_TEXT_RELEASE_FORMAT, first["format"])
            self.assertEqual(3, first["hit_count"])
            result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
            text_path = destination / result["documents"][0]["text_file"]
            text = text_path.read_text(encoding="utf-8").rstrip("\n")
            self.assertNotIn("const hidden", text)
            self.assertNotIn("content:", text)
            self.assertEqual(2, text.count("HBM"))
            for hit in result["hits"]:
                matched = text[hit["character_start"] : hit["character_end"]]
                self.assertEqual(hit["literal"].casefold(), matched.casefold())
            raw_copy = (
                destination
                / "sources"
                / "documents"
                / "000104581026000112"
                / "nvda-20260624.htm"
            )
            self.assertEqual(HTML, raw_copy.read_bytes())
            dashboard = (destination / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Hits are not claims", dashboard)
            self.assertIn("advanced packaging", dashboard)
            replay = write_sec_filing_text_release(source, recipe, destination)
            self.assertEqual(first["files"], replay["files"])

    def test_recipe_and_source_hashes_fail_closed_and_hit_limit_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _document_release(root)
            limited = load_sec_filing_text_recipe(
                _write_recipe(root, _recipe_document(source, maximum=1))
            )
            destination = root / "limited"
            metadata = write_sec_filing_text_release(source, limited, destination)
            self.assertEqual(2, metadata["hit_count"])
            self.assertEqual(1, metadata["truncated_hit_count"])

            wrong = _recipe_document(source)
            wrong["source_manifest_sha256"] = "0" * 64
            wrong_recipe = load_sec_filing_text_recipe(_write_recipe(root, wrong))
            with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
                write_sec_filing_text_release(source, wrong_recipe, root / "wrong")

            (source / "documents.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                write_sec_filing_text_release(source, limited, root / "tampered")

    def test_recipe_rejects_duplicate_literals_and_offline_cli_builds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = _document_release(root)
            duplicate = _recipe_document(source)
            duplicate["terms"][1]["literal"] = "hbm"
            with self.assertRaisesRegex(ValueError, "case-insensitively unique"):
                load_sec_filing_text_recipe(_write_recipe(root, duplicate))

            recipe_path = _write_recipe(root, _recipe_document(source))
            destination = root / "cli-release"
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "build-sec-filing-text-index",
                        "--documents-release",
                        str(source),
                        "--recipe",
                        str(recipe_path),
                        "--output-dir",
                        str(destination),
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual(3, json.loads(output.getvalue())["hit_count"])
            self.assertTrue((destination / "hits.csv").exists())


if __name__ == "__main__":
    unittest.main()
