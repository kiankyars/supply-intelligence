"""Immutable, hash-verified upstream release ingestion for weekly pulses."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import re
import stat
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit


UPSTREAM_LOCK_FORMAT = "ai-supply-upstream-release-lock.v1"
UPSTREAM_LOCK_PRODUCT = "blackwell-constraint-pulse"
UPSTREAM_LOCK_TARGET_QUARTER = "2026-Q4"
UPSTREAM_MANIFEST_FORMAT = "ai-supply-upstream-claim-release-manifest.v1"
UPSTREAM_SCHEMA_VERSION = "ai-supply-upstream-claim-release.v1"

_UPSTREAM_REPOSITORIES = {
    "datacenter_atlas": "kiankyars/datacenter-atlas",
    "semiconductor_atlas": "kiankyars/semiconductor-atlas",
}
REQUIRED_UPSTREAMS = frozenset(_UPSTREAM_REPOSITORIES)
_FORBIDDEN_CACHE_COMPONENTS = REQUIRED_UPSTREAMS
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SIMPLE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BUNDLE_MEMBERS = frozenset({"manifest.json", "claims.json"})

Fetcher = Callable[[str], bytes]


class UpstreamReleaseError(ValueError):
    """A locked upstream release failed a strict validation boundary."""


class _CacheObjectMissing(UpstreamReleaseError):
    """The locked content address is not present under the cache root."""


@dataclass(frozen=True, slots=True)
class LockedAsset:
    name: str
    url: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class LockedManifest:
    path: str
    sha256: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class LockedUpstreamRelease:
    upstream_id: str
    repository: str
    release_tag: str
    asset: LockedAsset
    manifest: LockedManifest


@dataclass(frozen=True, slots=True)
class UpstreamReleaseLock:
    format: str
    product: str
    target_quarter: str
    upstreams: tuple[LockedUpstreamRelease, ...]
    raw: bytes
    sha256: str

    def get(self, upstream_id: str) -> LockedUpstreamRelease | None:
        return next(
            (item for item in self.upstreams if item.upstream_id == upstream_id),
            None,
        )


@dataclass(frozen=True, slots=True)
class VerifiedUpstreamRelease:
    entry: LockedUpstreamRelease
    object_path: Path
    manifest_sha256: str
    claims_sha256: str
    manifest: Mapping[str, Any]
    claims: Mapping[str, Any]

    @property
    def upstream_id(self) -> str:
        return self.entry.upstream_id

    @property
    def repository(self) -> str:
        return self.entry.repository

    @property
    def release_tag(self) -> str:
        return self.entry.release_tag


def _exact_object(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UpstreamReleaseError(f"{path} must be a JSON object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise UpstreamReleaseError(
            f"{path} fields must be exact; missing={missing}, unexpected={unexpected}"
        )
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise UpstreamReleaseError(f"{path} must be non-empty text")
    return value


def _sha256(value: Any, path: str) -> str:
    digest = _text(value, path)
    if not _SHA256_PATTERN.fullmatch(digest):
        raise UpstreamReleaseError(f"{path} must be a lowercase SHA-256 digest")
    return digest


def _byte_count(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise UpstreamReleaseError(f"{path} must be a positive integer")
    return value


def _json_object(raw: bytes, path: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UpstreamReleaseError(
                    f"{path} contains duplicate JSON field: {key}"
                )
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except UpstreamReleaseError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpstreamReleaseError(f"{path} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise UpstreamReleaseError(f"{path} must be a JSON object")
    return value


def _simple_component(value: Any, path: str) -> str:
    component = _text(value, path)
    if (
        not _SIMPLE_COMPONENT_PATTERN.fullmatch(component)
        or component in {".", ".."}
        or ".." in component
    ):
        raise UpstreamReleaseError(f"{path} must be a safe simple path component")
    return component


def _locked_asset(
    value: Any,
    *,
    repository: str,
    release_tag: str,
    path: str,
) -> LockedAsset:
    document = _exact_object(value, {"name", "url", "bytes", "sha256"}, path)
    name = _simple_component(document["name"], f"{path}.name")
    if not name.endswith(".zip"):
        raise UpstreamReleaseError(f"{path}.name must end with .zip")
    url = _text(document["url"], f"{path}.url")
    parsed = urlsplit(url)
    expected_url = (
        f"https://github.com/{repository}/releases/download/{release_tag}/{name}"
    )
    if (
        url != expected_url
        or parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or "/releases/latest/" in parsed.path
    ):
        raise UpstreamReleaseError(
            f"{path}.url must be the canonical locked GitHub release asset URL"
        )
    return LockedAsset(
        name=name,
        url=url,
        bytes=_byte_count(document["bytes"], f"{path}.bytes"),
        sha256=_sha256(document["sha256"], f"{path}.sha256"),
    )


def _locked_manifest(value: Any, path: str) -> LockedManifest:
    document = _exact_object(
        value,
        {"path", "sha256", "schema_version"},
        path,
    )
    manifest_path = _text(document["path"], f"{path}.path")
    if manifest_path != "manifest.json":
        raise UpstreamReleaseError(f"{path}.path must be manifest.json")
    schema_version = _text(document["schema_version"], f"{path}.schema_version")
    if schema_version != UPSTREAM_SCHEMA_VERSION:
        raise UpstreamReleaseError(
            f"{path}.schema_version must be {UPSTREAM_SCHEMA_VERSION}"
        )
    return LockedManifest(
        path=manifest_path,
        sha256=_sha256(document["sha256"], f"{path}.sha256"),
        schema_version=schema_version,
    )


def _locked_upstream(value: Any, index: int) -> LockedUpstreamRelease:
    path = f"lock.upstreams[{index}]"
    document = _exact_object(
        value,
        {"upstream_id", "repository", "release_tag", "asset", "manifest"},
        path,
    )
    upstream_id = _text(document["upstream_id"], f"{path}.upstream_id")
    if upstream_id not in _UPSTREAM_REPOSITORIES:
        raise UpstreamReleaseError(f"{path}.upstream_id is not an allowed upstream")
    repository = _text(document["repository"], f"{path}.repository")
    if repository != _UPSTREAM_REPOSITORIES[upstream_id]:
        raise UpstreamReleaseError(
            f"{path}.repository does not match {upstream_id}"
        )
    release_tag = _simple_component(
        document["release_tag"],
        f"{path}.release_tag",
    )
    return LockedUpstreamRelease(
        upstream_id=upstream_id,
        repository=repository,
        release_tag=release_tag,
        asset=_locked_asset(
            document["asset"],
            repository=repository,
            release_tag=release_tag,
            path=f"{path}.asset",
        ),
        manifest=_locked_manifest(document["manifest"], f"{path}.manifest"),
    )


def load_upstream_release_lock(path: str | Path) -> UpstreamReleaseLock:
    """Load the exact v1 Blackwell pulse upstream release lockfile."""

    lock_path = ensure_not_upstream_worktree_path(path, "lockfile")
    try:
        raw = lock_path.read_bytes()
    except OSError as exc:
        raise UpstreamReleaseError("unable to read upstream release lockfile") from exc
    document = _exact_object(
        _json_object(raw, "lock"),
        {"format", "product", "target_quarter", "upstreams"},
        "lock",
    )
    if document["format"] != UPSTREAM_LOCK_FORMAT:
        raise UpstreamReleaseError(f"lock.format must be {UPSTREAM_LOCK_FORMAT}")
    if document["product"] != UPSTREAM_LOCK_PRODUCT:
        raise UpstreamReleaseError(f"lock.product must be {UPSTREAM_LOCK_PRODUCT}")
    if document["target_quarter"] != UPSTREAM_LOCK_TARGET_QUARTER:
        raise UpstreamReleaseError(
            f"lock.target_quarter must be {UPSTREAM_LOCK_TARGET_QUARTER}"
        )
    upstream_values = document["upstreams"]
    if not isinstance(upstream_values, list):
        raise UpstreamReleaseError("lock.upstreams must be a JSON array")
    upstreams = tuple(
        _locked_upstream(value, index)
        for index, value in enumerate(upstream_values)
    )
    upstream_ids = [item.upstream_id for item in upstreams]
    if len(upstream_ids) != len(set(upstream_ids)):
        raise UpstreamReleaseError("lock.upstreams contains duplicate upstream_id")
    if upstream_ids != sorted(upstream_ids):
        raise UpstreamReleaseError("lock.upstreams must be sorted by upstream_id")
    return UpstreamReleaseLock(
        format=UPSTREAM_LOCK_FORMAT,
        product=UPSTREAM_LOCK_PRODUCT,
        target_quarter=UPSTREAM_LOCK_TARGET_QUARTER,
        upstreams=upstreams,
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def ensure_not_upstream_worktree_path(
    path: str | Path,
    purpose: str,
) -> Path:
    """Reject lexical or resolved paths through either concurrent Atlas worktree."""

    lexical = Path(path).expanduser()
    resolved = lexical.resolve(strict=False)
    for candidate in (lexical.absolute(), resolved):
        if any(
            part.casefold() in _FORBIDDEN_CACHE_COMPONENTS
            for part in candidate.parts
        ):
            raise UpstreamReleaseError(
                f"{purpose} cannot be inside an upstream sibling repository"
            )
    return resolved


def _validated_cache_root(cache_root: str | Path) -> Path:
    return ensure_not_upstream_worktree_path(cache_root, "cache root")


def _object_path(entry: LockedUpstreamRelease, cache_root: str | Path) -> Path:
    root = _validated_cache_root(cache_root)
    return root / "objects" / "sha256" / entry.asset.sha256[:2] / entry.asset.sha256


_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | os.O_DIRECTORY
    | os.O_CLOEXEC
    | os.O_NOFOLLOW
)
_FILE_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW_ANY", os.O_NOFOLLOW)


def _directory_open_error(
    exc: OSError,
    message: str,
    symlink_message: str,
) -> UpstreamReleaseError:
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        return UpstreamReleaseError(symlink_message)
    return UpstreamReleaseError(message)


def _open_child_directory(
    parent_descriptor: int,
    component: str,
    *,
    create: bool,
    missing_message: str,
    error_message: str,
    symlink_message: str,
) -> int:
    try:
        return os.open(
            component,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )
    except FileNotFoundError:
        if not create:
            raise _CacheObjectMissing(missing_message)
        try:
            os.mkdir(component, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        except OSError as exc:
            raise _directory_open_error(
                exc,
                error_message,
                symlink_message,
            ) from exc
        else:
            try:
                os.fsync(parent_descriptor)
            except OSError as exc:
                raise _directory_open_error(
                    exc,
                    error_message,
                    symlink_message,
                ) from exc
        try:
            return os.open(
                component,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise _directory_open_error(
                exc,
                error_message,
                symlink_message,
            ) from exc
    except OSError as exc:
        raise _directory_open_error(
            exc,
            error_message,
            symlink_message,
        ) from exc


def _open_directory_path(
    path: Path,
    *,
    create: bool,
    missing_message: str = "locked asset is not present in cache",
    error_message: str = "unable to open upstream asset cache directory",
    symlink_message: str = (
        "upstream asset cache path cannot contain symbolic links or non-directories"
    ),
) -> int:
    """Open an absolute directory through no-follow, descriptor-relative steps."""

    if not path.is_absolute():
        raise UpstreamReleaseError("cache directory path must be absolute")
    descriptor = os.open("/", _DIRECTORY_OPEN_FLAGS)
    try:
        for component in path.parts[1:]:
            child = _open_child_directory(
                descriptor,
                component,
                create=create,
                missing_message=missing_message,
                error_message=error_message,
                symlink_message=symlink_message,
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_cache_object_parent(
    entry: LockedUpstreamRelease,
    cache_root: Path,
    *,
    create: bool,
) -> int:
    descriptor = _open_directory_path(cache_root, create=create)
    try:
        for component in ("objects", "sha256", entry.asset.sha256[:2]):
            child = _open_child_directory(
                descriptor,
                component,
                create=create,
                missing_message=(
                    f"locked asset is not present in cache for {entry.upstream_id}"
                ),
                error_message=(
                    f"unable to inspect cached asset for {entry.upstream_id}"
                ),
                symlink_message=(
                    "upstream asset cache path cannot contain symbolic links "
                    "or non-directories"
                ),
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _verify_asset_bytes(raw: bytes, entry: LockedUpstreamRelease) -> None:
    if len(raw) != entry.asset.bytes:
        raise UpstreamReleaseError(
            f"locked asset byte count mismatch for {entry.upstream_id}"
        )
    if hashlib.sha256(raw).hexdigest() != entry.asset.sha256:
        raise UpstreamReleaseError(
            f"locked asset SHA-256 mismatch for {entry.upstream_id}"
        )


def _verified_cached_bytes(
    entry: LockedUpstreamRelease,
    cache_root: str | Path,
) -> tuple[Path, bytes]:
    root = _validated_cache_root(cache_root)
    object_path = _object_path(entry, root)
    parent_descriptor = _open_cache_object_parent(entry, root, create=False)
    try:
        try:
            descriptor = os.open(
                entry.asset.sha256,
                os.O_RDONLY
                | os.O_CLOEXEC
                | os.O_NONBLOCK
                | _FILE_NOFOLLOW_FLAG,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError as exc:
            raise _CacheObjectMissing(
                f"locked asset is not present in cache for {entry.upstream_id}"
            ) from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UpstreamReleaseError(
                    f"cached asset cannot be a symbolic link for {entry.upstream_id}"
                ) from exc
            raise UpstreamReleaseError(
                f"unable to inspect cached asset for {entry.upstream_id}"
            ) from exc
    finally:
        os.close(parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise UpstreamReleaseError(
                f"cached asset must be a regular file for {entry.upstream_id}"
            )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read()
    except UpstreamReleaseError:
        raise
    except OSError as exc:
        raise UpstreamReleaseError(
            f"unable to read cached asset for {entry.upstream_id}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _verify_asset_bytes(raw, entry)
    return object_path, raw


def _urllib_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def _durable_atomic_write(
    entry: LockedUpstreamRelease,
    raw: bytes,
    cache_root: Path,
) -> Path:
    parent_descriptor = _open_cache_object_parent(entry, cache_root, create=True)
    temporary_name = f".{entry.asset.sha256}.{os.urandom(16).hex()}.tmp"
    descriptor = -1
    try:
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_descriptor,
            )
        except FileExistsError as exc:
            raise UpstreamReleaseError(
                "unable to allocate an exclusive upstream cache temporary"
            ) from exc
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary_name,
                entry.asset.sha256,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except OSError as exc:
        raise UpstreamReleaseError(
            "unable to atomically write upstream asset cache"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_descriptor)
        except (FileNotFoundError, OSError):
            pass
        os.close(parent_descriptor)
    verified_path, _ = _verified_cached_bytes(entry, cache_root)
    return verified_path


def fetch_locked_release(
    entry: LockedUpstreamRelease,
    cache_root: str | Path,
    fetcher: Fetcher | None = None,
) -> Path:
    """Fetch one locked asset into the verified content-addressed cache."""

    cache = _validated_cache_root(cache_root)
    try:
        verified_path, _ = _verified_cached_bytes(entry, cache)
        return verified_path
    except _CacheObjectMissing:
        pass
    fetch = fetcher or _urllib_fetch
    try:
        raw = fetch(entry.asset.url)
    except Exception as exc:
        raise UpstreamReleaseError(
            f"unable to fetch locked asset for {entry.upstream_id}"
        ) from exc
    if not isinstance(raw, bytes):
        raise UpstreamReleaseError("upstream asset fetcher must return bytes")
    _verify_asset_bytes(raw, entry)
    return _durable_atomic_write(entry, raw, cache)


def _safe_bundle_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise UpstreamReleaseError("upstream release bundle contains duplicate entries")
    for info in infos:
        member = PurePosixPath(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        if (
            info.is_dir()
            or member.is_absolute()
            or any(part in {"", ".", ".."} for part in member.parts)
            or "\\" in info.filename
            or stat.S_IFMT(mode) == stat.S_IFLNK
        ):
            raise UpstreamReleaseError(
                "upstream release bundle contains unsafe entries"
            )
    if set(names) != _BUNDLE_MEMBERS or len(names) != len(_BUNDLE_MEMBERS):
        raise UpstreamReleaseError(
            "upstream release bundle must contain exactly claims.json and manifest.json"
        )
    return {info.filename: info for info in infos}


def _iso_date(value: Any, path: str) -> str:
    text = _text(value, path)
    if not _DATE_PATTERN.fullmatch(text):
        raise UpstreamReleaseError(f"{path} must be an ISO date")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise UpstreamReleaseError(f"{path} must be an ISO date") from exc
    return text


def _iso_timestamp(value: Any, path: str) -> str:
    text = _text(value, path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpstreamReleaseError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UpstreamReleaseError(f"{path} must include a timezone")
    return text


def _load_verified_bundle(
    entry: LockedUpstreamRelease,
    object_path: Path,
    bundle_raw: bytes,
) -> VerifiedUpstreamRelease:
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_raw), mode="r") as archive:
            members = _safe_bundle_members(archive)
            try:
                manifest_raw = archive.read(members["manifest.json"])
                claims_raw = archive.read(members["claims.json"])
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise UpstreamReleaseError(
                    "unable to read locked upstream release bundle"
                ) from exc
    except UpstreamReleaseError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpstreamReleaseError("locked upstream asset must be a valid zip") from exc

    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_sha256 != entry.manifest.sha256:
        raise UpstreamReleaseError(
            f"manifest SHA-256 mismatch for {entry.upstream_id}"
        )
    manifest = _exact_object(
        _json_object(manifest_raw, "manifest"),
        {
            "format",
            "schema_version",
            "upstream_id",
            "repository",
            "release_tag",
            "comparison",
            "as_of_date",
            "recorded_at",
            "files",
        },
        "manifest",
    )
    if manifest["format"] != UPSTREAM_MANIFEST_FORMAT:
        raise UpstreamReleaseError(
            f"manifest.format must be {UPSTREAM_MANIFEST_FORMAT}"
        )
    if manifest["schema_version"] != entry.manifest.schema_version:
        raise UpstreamReleaseError("manifest schema_version does not match lock")
    for field_name, expected in (
        ("upstream_id", entry.upstream_id),
        ("repository", entry.repository),
        ("release_tag", entry.release_tag),
    ):
        if manifest[field_name] != expected:
            raise UpstreamReleaseError(f"manifest {field_name} does not match lock")
    comparison_value = manifest["comparison"]
    if comparison_value is None:
        comparison = None
    else:
        comparison_document = _exact_object(
            comparison_value,
            {"release_tag", "manifest_sha256", "claims_sha256"},
            "manifest.comparison",
        )
        comparison_tag = _simple_component(
            comparison_document["release_tag"],
            "manifest.comparison.release_tag",
        )
        if comparison_tag == entry.release_tag:
            raise UpstreamReleaseError(
                "manifest.comparison.release_tag must identify a different prior release"
            )
        comparison = {
            "release_tag": comparison_tag,
            "manifest_sha256": _sha256(
                comparison_document["manifest_sha256"],
                "manifest.comparison.manifest_sha256",
            ),
            "claims_sha256": _sha256(
                comparison_document["claims_sha256"],
                "manifest.comparison.claims_sha256",
            ),
        }
    manifest["comparison"] = comparison
    as_of_date = date.fromisoformat(
        _iso_date(manifest["as_of_date"], "manifest.as_of_date")
    )
    recorded_at = datetime.fromisoformat(
        _iso_timestamp(manifest["recorded_at"], "manifest.recorded_at").replace(
            "Z",
            "+00:00",
        )
    ).astimezone(timezone.utc)
    if as_of_date > recorded_at.date():
        raise UpstreamReleaseError("manifest.as_of_date cannot follow recorded_at")
    files = _exact_object(manifest["files"], {"claims.json"}, "manifest.files")
    claims_descriptor = _exact_object(
        files["claims.json"],
        {"bytes", "sha256"},
        "manifest.files.claims.json",
    )
    expected_claims_bytes = _byte_count(
        claims_descriptor["bytes"],
        "manifest.files.claims.json.bytes",
    )
    expected_claims_sha256 = _sha256(
        claims_descriptor["sha256"],
        "manifest.files.claims.json.sha256",
    )
    if len(claims_raw) != expected_claims_bytes:
        raise UpstreamReleaseError(
            f"claims.json byte count mismatch for {entry.upstream_id}"
        )
    claims_sha256 = hashlib.sha256(claims_raw).hexdigest()
    if claims_sha256 != expected_claims_sha256:
        raise UpstreamReleaseError(
            f"claims.json SHA-256 mismatch for {entry.upstream_id}"
        )
    claims = _json_object(claims_raw, "claims.json")
    return VerifiedUpstreamRelease(
        entry=entry,
        object_path=object_path,
        manifest_sha256=manifest_sha256,
        claims_sha256=claims_sha256,
        manifest=manifest,
        claims=claims,
    )


def load_cached_release(
    entry: LockedUpstreamRelease,
    cache_root: str | Path,
) -> VerifiedUpstreamRelease:
    """Reverify and parse one already-cached locked upstream release."""

    object_path, raw = _verified_cached_bytes(entry, cache_root)
    return _load_verified_bundle(entry, object_path, raw)


def fetch_and_load_locked_release(
    entry: LockedUpstreamRelease,
    cache_root: str | Path,
    fetcher: Fetcher | None = None,
) -> VerifiedUpstreamRelease:
    """Fetch, cache, reverify, and parse one locked upstream release."""

    fetch_locked_release(entry, cache_root, fetcher)
    return load_cached_release(entry, cache_root)
