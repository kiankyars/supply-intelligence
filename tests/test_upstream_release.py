from __future__ import annotations

import copy
import hashlib
import inspect
import io
import json
import os
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import supply_intelligence.upstream_release as upstream_release
from supply_intelligence.upstream_release import (
    UPSTREAM_LOCK_FORMAT,
    UPSTREAM_LOCK_PRODUCT,
    UPSTREAM_LOCK_TARGET_QUARTER,
    UPSTREAM_MANIFEST_FORMAT,
    UPSTREAM_SCHEMA_VERSION,
    UpstreamReleaseError,
    fetch_and_load_locked_release,
    fetch_locked_release,
    load_cached_release,
    load_upstream_release_lock,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 20, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return stream.getvalue()


def _bundle(
    *,
    upstream_id: str = "datacenter_atlas",
    repository: str = "kiankyars/datacenter-atlas",
    release_tag: str = "2026-q4-week-01",
    claims: object | None = None,
    manifest_overrides: dict[str, Any] | None = None,
    extra_entries: list[tuple[str, bytes]] | None = None,
) -> tuple[bytes, bytes]:
    claims_raw = _json_bytes(
        claims
        if claims is not None
        else {
            "format": UPSTREAM_SCHEMA_VERSION,
            "claims": [],
        }
    )
    manifest: dict[str, Any] = {
        "format": UPSTREAM_MANIFEST_FORMAT,
        "schema_version": UPSTREAM_SCHEMA_VERSION,
        "upstream_id": upstream_id,
        "repository": repository,
        "release_tag": release_tag,
        "comparison": None,
        "as_of_date": "2026-10-02",
        "recorded_at": "2026-10-03T02:00:00Z",
        "files": {
            "claims.json": {
                "bytes": len(claims_raw),
                "sha256": hashlib.sha256(claims_raw).hexdigest(),
            }
        },
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    manifest_raw = _json_bytes(manifest)
    entries = [("manifest.json", manifest_raw), ("claims.json", claims_raw)]
    entries.extend(extra_entries or [])
    return _zip_bytes(entries), manifest_raw


def _entry(
    bundle_raw: bytes,
    manifest_raw: bytes,
    *,
    upstream_id: str = "datacenter_atlas",
    repository: str = "kiankyars/datacenter-atlas",
    release_tag: str = "2026-q4-week-01",
    asset_name: str = "blackwell-claims.zip",
) -> dict[str, Any]:
    return {
        "upstream_id": upstream_id,
        "repository": repository,
        "release_tag": release_tag,
        "asset": {
            "name": asset_name,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{release_tag}/{asset_name}"
            ),
            "bytes": len(bundle_raw),
            "sha256": hashlib.sha256(bundle_raw).hexdigest(),
        },
        "manifest": {
            "path": "manifest.json",
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "schema_version": UPSTREAM_SCHEMA_VERSION,
        },
    }


def _lock(upstreams: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": UPSTREAM_LOCK_FORMAT,
        "product": UPSTREAM_LOCK_PRODUCT,
        "target_quarter": UPSTREAM_LOCK_TARGET_QUARTER,
        "upstreams": upstreams,
    }


def _write_lock(root: Path, document: dict[str, Any]) -> Path:
    path = root / "upstream-release-lock.json"
    path.write_bytes(_json_bytes(document))
    return path


class UpstreamReleaseTests(unittest.TestCase):
    def test_zero_entries_is_a_valid_unavailable_release_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = _write_lock(Path(temporary), _lock([]))
            loaded = load_upstream_release_lock(path)

        self.assertEqual(loaded.format, UPSTREAM_LOCK_FORMAT)
        self.assertEqual(loaded.product, UPSTREAM_LOCK_PRODUCT)
        self.assertEqual(loaded.target_quarter, "2026-Q4")
        self.assertEqual(loaded.upstreams, ())
        self.assertIsNone(loaded.get("datacenter_atlas"))

    def test_lock_fields_identities_order_and_nested_shapes_are_exact(self) -> None:
        datacenter_bundle, datacenter_manifest = _bundle()
        semiconductor_bundle, semiconductor_manifest = _bundle(
            upstream_id="semiconductor_atlas",
            repository="kiankyars/semiconductor-atlas",
        )
        datacenter = _entry(datacenter_bundle, datacenter_manifest)
        semiconductor = _entry(
            semiconductor_bundle,
            semiconductor_manifest,
            upstream_id="semiconductor_atlas",
            repository="kiankyars/semiconductor-atlas",
        )
        mutations = {
            "top-level extra": (
                _lock([]) | {"release_dir": "../datacenter_atlas"},
                "fields must be exact",
            ),
            "wrong product": (_lock([]) | {"product": "other"}, "lock.product"),
            "unsorted": (_lock([semiconductor, datacenter]), "sorted by upstream_id"),
            "duplicate": (
                _lock([datacenter, copy.deepcopy(datacenter)]),
                "duplicate upstream_id",
            ),
            "wrong repository": (
                _lock([datacenter | {"repository": "someone/datacenter-atlas"}]),
                "repository does not match",
            ),
            "nested extra": (
                _lock([datacenter | {"release_dir": "../datacenter_atlas"}]),
                "fields must be exact",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, (document, message) in mutations.items():
                with self.subTest(name=name):
                    path = _write_lock(root, document)
                    with self.assertRaisesRegex(UpstreamReleaseError, message):
                        load_upstream_release_lock(path)

    def test_fetches_to_content_addressed_cache_and_reverifies_cache_hit(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            calls: list[str] = []

            def fetcher(url: str) -> bytes:
                calls.append(url)
                return bundle_raw

            release = fetch_and_load_locked_release(entry, root / "cache", fetcher)
            expected_path = (
                root
                / "cache"
                / "objects"
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            ).resolve()
            self.assertEqual(release.object_path, expected_path)
            self.assertEqual(expected_path.read_bytes(), bundle_raw)
            self.assertEqual(calls, [entry.asset.url])
            self.assertEqual(release.upstream_id, "datacenter_atlas")
            self.assertEqual(release.manifest_sha256, entry.manifest.sha256)
            self.assertEqual(release.claims["claims"], [])

            def unexpected_fetch(_: str) -> bytes:
                raise AssertionError("a verified cache hit must not refetch")

            self.assertEqual(
                fetch_locked_release(entry, root / "cache", unexpected_fetch),
                expected_path,
            )
            self.assertEqual(
                load_cached_release(entry, root / "cache").claims,
                release.claims,
            )

    def test_fetched_hash_mismatch_never_populates_cache(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        corrupted = bytes([bundle_raw[0] ^ 1]) + bundle_raw[1:]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            with self.assertRaisesRegex(UpstreamReleaseError, "SHA-256 mismatch"):
                fetch_locked_release(entry, root / "cache", lambda _: corrupted)
            object_path = (
                root
                / "cache"
                / "objects"
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            )
            self.assertFalse(object_path.exists())

    def test_tampered_cache_fails_closed_without_refetch(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            object_path = fetch_locked_release(
                entry,
                root / "cache",
                lambda _: bundle_raw,
            )
            object_path.write_bytes(bytes([bundle_raw[0] ^ 1]) + bundle_raw[1:])

            with self.assertRaisesRegex(UpstreamReleaseError, "SHA-256 mismatch"):
                load_cached_release(entry, root / "cache")

            def unexpected_fetch(_: str) -> bytes:
                raise AssertionError("a tampered cache entry must not be healed")

            with self.assertRaisesRegex(UpstreamReleaseError, "SHA-256 mismatch"):
                fetch_locked_release(entry, root / "cache", unexpected_fetch)

    def test_non_regular_cached_fifo_fails_closed_without_blocking(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            object_path = (
                root
                / "cache"
                / "objects"
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            )
            object_path.parent.mkdir(parents=True)
            os.mkfifo(object_path)

            with self.assertRaisesRegex(UpstreamReleaseError, "regular file"):
                load_cached_release(entry, root / "cache")

    def test_manifest_hash_and_schema_identity_are_pinned(self) -> None:
        valid_bundle, valid_manifest = _bundle()
        wrong_schema_bundle, wrong_schema_manifest = _bundle(
            manifest_overrides={"schema_version": "future-schema.v2"}
        )
        future_as_of_bundle, future_as_of_manifest = _bundle(
            manifest_overrides={"as_of_date": "2026-10-04"}
        )
        self_comparison_bundle, self_comparison_manifest = _bundle(
            manifest_overrides={
                "comparison": {
                    "release_tag": "2026-q4-week-01",
                    "manifest_sha256": "1" * 64,
                    "claims_sha256": "2" * 64,
                }
            }
        )
        cases = {
            "manifest hash drift": (
                valid_bundle,
                _entry(valid_bundle, valid_manifest)
                | {
                    "manifest": {
                        "path": "manifest.json",
                        "sha256": "0" * 64,
                        "schema_version": UPSTREAM_SCHEMA_VERSION,
                    }
                },
                "manifest SHA-256 mismatch",
            ),
            "manifest schema drift": (
                wrong_schema_bundle,
                _entry(wrong_schema_bundle, wrong_schema_manifest),
                "schema_version does not match lock",
            ),
            "manifest time order": (
                future_as_of_bundle,
                _entry(future_as_of_bundle, future_as_of_manifest),
                "as_of_date cannot follow recorded_at",
            ),
            "manifest self comparison": (
                self_comparison_bundle,
                _entry(self_comparison_bundle, self_comparison_manifest),
                "must identify a different prior release",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, (bundle, locked_entry, message) in cases.items():
                with self.subTest(name=name):
                    entry = load_upstream_release_lock(
                        _write_lock(root, _lock([locked_entry]))
                    ).upstreams[0]
                    cache = root / f"cache-{name.replace(' ', '-')}"
                    with self.assertRaisesRegex(UpstreamReleaseError, message):
                        fetch_and_load_locked_release(entry, cache, lambda _: bundle)

    def test_only_canonical_github_zip_assets_are_accepted(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        base = _entry(bundle_raw, manifest_raw)
        mutations = {
            "local file": "file:///example/datacenter_atlas/release.zip",
            "relative sibling": "../datacenter_atlas/release.zip",
            "latest": (
                "https://github.com/kiankyars/datacenter-atlas/releases/latest/"
                "download/blackwell-claims.zip"
            ),
            "query": base["asset"]["url"] + "?download=1",
            "wrong tag": base["asset"]["url"].replace("week-01", "week-02"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, url in mutations.items():
                with self.subTest(name=name):
                    entry = copy.deepcopy(base)
                    entry["asset"]["url"] = url
                    with self.assertRaisesRegex(
                        UpstreamReleaseError,
                        "canonical locked",
                    ):
                        load_upstream_release_lock(_write_lock(root, _lock([entry])))

            unsafe_name = copy.deepcopy(base)
            unsafe_name["asset"]["name"] = "../blackwell-claims.zip"
            with self.assertRaisesRegex(UpstreamReleaseError, "safe simple"):
                load_upstream_release_lock(_write_lock(root, _lock([unsafe_name])))

    def test_cache_roots_cannot_resolve_inside_upstream_siblings(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            for sibling_name in ("datacenter_atlas", "semiconductor_atlas"):
                cache = root / sibling_name / "cache"
                with self.subTest(sibling=sibling_name):
                    with self.assertRaisesRegex(
                        UpstreamReleaseError,
                        "upstream sibling repository",
                    ):
                        fetch_locked_release(entry, cache, lambda _: bundle_raw)
                    self.assertFalse(cache.exists())

    def test_intermediate_cache_symlink_cannot_supply_a_locked_asset(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            sibling = root / "datacenter_atlas"
            sibling_object = (
                sibling
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            )
            sibling_object.parent.mkdir(parents=True)
            sibling_object.write_bytes(bundle_raw)
            cache = root / "cache"
            cache.mkdir()
            (cache / "objects").symlink_to(sibling, target_is_directory=True)

            with self.assertRaisesRegex(UpstreamReleaseError, "symbolic links"):
                load_cached_release(entry, cache)

    def test_intermediate_cache_symlink_is_rejected_before_any_write(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            sibling = root / "semiconductor_atlas"
            sibling.mkdir()
            cache = root / "cache"
            cache.mkdir()
            (cache / "objects").symlink_to(sibling, target_is_directory=True)
            fetch_calls = 0

            def fetcher(_: str) -> bytes:
                nonlocal fetch_calls
                fetch_calls += 1
                return bundle_raw

            with self.assertRaisesRegex(UpstreamReleaseError, "symbolic links"):
                fetch_locked_release(entry, cache, fetcher)

            self.assertEqual(fetch_calls, 0)
            self.assertEqual(list(sibling.iterdir()), [])

    def test_cache_read_stays_on_open_descriptor_during_path_swap(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            cache = root / "cache"
            object_path = fetch_locked_release(entry, cache, lambda _: bundle_raw)
            object_path.write_bytes(bytes([bundle_raw[0] ^ 1]) + bundle_raw[1:])
            sibling_object = (
                root
                / "datacenter_atlas"
                / "objects"
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            )
            sibling_object.parent.mkdir(parents=True)
            sibling_object.write_bytes(bundle_raw)
            original_open = upstream_release.os.open
            swapped = False

            def swap_before_leaf_open(path: Any, *args: Any, **kwargs: Any) -> int:
                nonlocal swapped
                if not swapped and path == entry.asset.sha256:
                    (cache / "objects").rename(cache / "objects-opened")
                    (cache / "objects").symlink_to(
                        root / "datacenter_atlas" / "objects",
                        target_is_directory=True,
                    )
                    swapped = True
                return original_open(path, *args, **kwargs)

            with patch.object(
                upstream_release.os,
                "open",
                side_effect=swap_before_leaf_open,
            ), self.assertRaisesRegex(UpstreamReleaseError, "SHA-256 mismatch"):
                load_cached_release(entry, cache)

            self.assertTrue(swapped)

    def test_cache_write_stays_on_open_descriptor_during_path_swap(self) -> None:
        bundle_raw, manifest_raw = _bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            cache = root / "cache"
            sibling_objects = root / "semiconductor_atlas" / "objects"
            sibling_objects.mkdir(parents=True)
            original_open = upstream_release.os.open
            swapped = False

            def swap_before_temporary_open(
                path: Any,
                *args: Any,
                **kwargs: Any,
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and isinstance(path, str)
                    and path.startswith(f".{entry.asset.sha256}.")
                    and path.endswith(".tmp")
                ):
                    (cache / "objects").rename(cache / "objects-opened")
                    (cache / "objects").symlink_to(
                        sibling_objects,
                        target_is_directory=True,
                    )
                    swapped = True
                return original_open(path, *args, **kwargs)

            with patch.object(
                upstream_release.os,
                "open",
                side_effect=swap_before_temporary_open,
            ), self.assertRaisesRegex(UpstreamReleaseError, "symbolic links"):
                fetch_locked_release(entry, cache, lambda _: bundle_raw)

            self.assertTrue(swapped)
            self.assertEqual(list(sibling_objects.iterdir()), [])

    def test_bundle_members_are_exact_unique_and_safe(self) -> None:
        valid_bundle, manifest_raw = _bundle()
        claims_raw = _json_bytes({"claims": []})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            duplicate_bundle = _zip_bytes(
                [
                    ("manifest.json", manifest_raw),
                    ("claims.json", claims_raw),
                    ("claims.json", claims_raw),
                ]
            )
        unsafe_bundle = _zip_bytes(
            [
                ("manifest.json", manifest_raw),
                ("claims.json", claims_raw),
                ("../local.json", b"{}"),
            ]
        )
        missing_bundle = _zip_bytes([("manifest.json", manifest_raw)])
        cases = {
            "duplicate": (duplicate_bundle, "duplicate entries"),
            "unsafe": (unsafe_bundle, "unsafe entries"),
            "missing": (missing_bundle, "exactly claims.json and manifest.json"),
        }
        self.assertTrue(valid_bundle)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, (bundle, message) in cases.items():
                with self.subTest(name=name):
                    locked = _entry(bundle, manifest_raw)
                    entry = load_upstream_release_lock(
                        _write_lock(root, _lock([locked]))
                    ).upstreams[0]
                    with self.assertRaisesRegex(UpstreamReleaseError, message):
                        fetch_and_load_locked_release(
                            entry,
                            root / f"cache-{name}",
                            lambda _url, payload=bundle: payload,
                        )

    def test_claims_bytes_are_verified_before_object_parsing(self) -> None:
        claims_raw = b"[]\n"
        manifest = {
            "format": UPSTREAM_MANIFEST_FORMAT,
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "upstream_id": "datacenter_atlas",
            "repository": "kiankyars/datacenter-atlas",
            "release_tag": "2026-q4-week-01",
            "comparison": None,
            "as_of_date": "2026-10-02",
            "recorded_at": "2026-10-03T02:00:00Z",
            "files": {
                "claims.json": {
                    "bytes": len(claims_raw),
                    "sha256": hashlib.sha256(claims_raw).hexdigest(),
                }
            },
        }
        manifest_raw = _json_bytes(manifest)
        bundle_raw = _zip_bytes(
            [("manifest.json", manifest_raw), ("claims.json", claims_raw)]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = load_upstream_release_lock(
                _write_lock(root, _lock([_entry(bundle_raw, manifest_raw)]))
            ).upstreams[0]
            with self.assertRaisesRegex(UpstreamReleaseError, "must be a JSON object"):
                fetch_and_load_locked_release(
                    entry,
                    root / "cache",
                    lambda _: bundle_raw,
                )

    def test_public_ingestion_has_no_release_directory_escape_hatch(self) -> None:
        public_functions = (
            load_upstream_release_lock,
            fetch_locked_release,
            load_cached_release,
            fetch_and_load_locked_release,
        )
        for function in public_functions:
            self.assertNotIn("release_dir", inspect.signature(function).parameters)
        self.assertFalse(hasattr(upstream_release, "load_upstream_release_dir"))


if __name__ == "__main__":
    unittest.main()
