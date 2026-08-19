from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
ATLAS_ADAPTER_DOC = ROOT / "docs" / "atlas-adapter.md"
DATACENTER_FIXTURE = (
    ROOT
    / "examples"
    / "fixtures"
    / "datacenter-atlas"
    / "2026-07-17-openai-abilene"
)


def _manifest_files(manifest_path: Path) -> set[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise AssertionError(f"manifest files must be an object: {manifest_path}")
    verified = {manifest_path}
    for relative, metadata in files.items():
        path = manifest_path.parent / relative
        if not path.is_file() or path.is_symlink():
            raise AssertionError(f"manifest payload is missing or not regular: {path}")
        raw = path.read_bytes()
        if metadata.get("bytes") != len(raw):
            raise AssertionError(f"manifest byte count mismatch: {path}")
        if metadata.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise AssertionError(f"manifest hash mismatch: {path}")
        verified.add(path)
    return verified


def _top_level_release_manifests() -> list[Path]:
    manifests = sorted(RELEASES.rglob("manifest.json"))
    return [
        manifest
        for manifest in manifests
        if not any(
            (parent / "manifest.json").is_file()
            for parent in manifest.parent.parents
            if parent != RELEASES and parent.is_relative_to(RELEASES)
        )
    ]


class RepositoryIntegrityTests(unittest.TestCase):
    def test_every_checked_release_file_is_hash_bound(self) -> None:
        verified = set()
        for manifest in _top_level_release_manifests():
            verified.update(_manifest_files(manifest))
        release_files = {path for path in RELEASES.rglob("*") if path.is_file()}
        self.assertEqual(release_files, verified)

    def test_datacenter_adapter_fixture_is_hash_complete(self) -> None:
        verified = _manifest_files(DATACENTER_FIXTURE / "manifest.json")
        fixture_files = {
            path for path in DATACENTER_FIXTURE.rglob("*") if path.is_file()
        }
        self.assertEqual(fixture_files, verified)

    def test_checked_releases_do_not_expose_personal_absolute_paths(self) -> None:
        for path in RELEASES.rglob("*"):
            if path.is_file():
                self.assertNotIn(
                    b"/Users/",
                    path.read_bytes(),
                    f"personal absolute path in checked release: {path}",
                )

    def test_atlas_adapter_docs_do_not_require_a_sibling_checkout(self) -> None:
        text = ATLAS_ADAPTER_DOC.read_text(encoding="utf-8")
        self.assertNotIn("../semiconductor_atlas", text)
        self.assertNotIn("PINNED_RELEASE", text)


if __name__ == "__main__":
    unittest.main()
