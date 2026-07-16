from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from .config import DEPOT_TOOLS_COMMIT, SOURCE_VERSION, SnapshotSpec


class SnapshotError(RuntimeError):
    """A source snapshot violates its pinned identity or archive contract."""


Download = Callable[[str, Path], None]
_SNAPSHOT_ROOTS = frozenset({"checkout", "depot_tools"})


def download_asset(
    url: str,
    destination: Path,
    *,
    opener=urllib.request.urlopen,
    timeout: int = 60,
) -> None:
    """Perform one HTTP transfer, resuming an existing partial asset."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    offset = destination.stat().st_size if destination.exists() else 0
    request = urllib.request.Request(url)
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    with opener(request, timeout=timeout) as response:
        status = getattr(response, "status", None)
        if status is None:
            status = response.getcode()
        append = offset > 0 and status == 206
        mode = "ab" if append else "wb"
        with destination.open(mode) as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_file(path: Path, *, size_bytes: int, sha256: str) -> None:
    if not path.is_file():
        raise SnapshotError(f"snapshot asset is missing: {path}")
    if path.stat().st_size != size_bytes:
        raise SnapshotError(
            f"snapshot asset size mismatch for {path.name}: {path.stat().st_size} != {size_bytes}"
        )
    actual = sha256_file(path)
    if actual != sha256:
        raise SnapshotError(f"snapshot asset digest mismatch for {path.name}: {actual} != {sha256}")


def _download_verified(
    url: str,
    destination: Path,
    *,
    size_bytes: int,
    sha256: str,
    download: Download,
    attempts: int = 4,
) -> None:
    """Retry the complete download-and-integrity-check operation."""
    for attempt in range(1, attempts + 1):
        try:
            if destination.exists():
                try:
                    _validate_file(destination, size_bytes=size_bytes, sha256=sha256)
                    return
                except SnapshotError:
                    pass
            download(url, destination)
            _validate_file(destination, size_bytes=size_bytes, sha256=sha256)
            return
        except Exception:
            if attempt == attempts:
                raise


def validate_snapshot_manifest(spec: SnapshotSpec, content: bytes) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"invalid snapshot manifest JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotError("snapshot manifest root must be an object")
    expected = {
        "schema_version": 1,
        "snapshot": spec.name,
        "webrtc_commit": SOURCE_VERSION.commit,
        "depot_tools_commit": DEPOT_TOOLS_COMMIT,
        "target_os": spec.target_os,
        "runner_os": spec.runner_os,
        "runner_arch": spec.runner_arch,
        "xcode_version": spec.xcode_version,
        "source_is_clean": True,
        "contains_git_metadata": False,
        "contains_project_patches": False,
        "contains_build_outputs": False,
        "archive_sha256": spec.archive_sha256,
        "archive_size_bytes": spec.archive_size_bytes,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise SnapshotError(
                f"snapshot manifest field {field!r} is {payload.get(field)!r}; expected {value!r}"
            )
    return payload


def ensure_snapshot_archive(
    spec: SnapshotSpec,
    cache_dir: Path,
    *,
    download: Download,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = cache_dir / f"{spec.name}.tar.zst"
    if archive.exists():
        try:
            _validate_file(
                archive,
                size_bytes=spec.archive_size_bytes,
                sha256=spec.archive_sha256,
            )
            return archive
        except SnapshotError:
            archive.unlink(missing_ok=True)

    assembling = archive.with_suffix(archive.suffix + ".partial")
    assembling.unlink(missing_ok=True)
    temporary_parts = [cache_dir / f"{part.name}.partial" for part in spec.parts]
    try:
        for destination in temporary_parts:
            destination.unlink(missing_ok=True)

        def fetch(item: tuple[object, Path]) -> Path:
            part, destination = item
            _download_verified(
                spec.asset_url(part.name),
                destination,
                size_bytes=part.size_bytes,
                sha256=part.sha256,
                download=download,
            )
            return destination

        with ThreadPoolExecutor(max_workers=min(3, len(spec.parts))) as executor:
            temporary_parts = list(executor.map(fetch, zip(spec.parts, temporary_parts)))
        with assembling.open("wb") as output:
            for part in temporary_parts:
                with part.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        _validate_file(
            assembling,
            size_bytes=spec.archive_size_bytes,
            sha256=spec.archive_sha256,
        )
        assembling.replace(archive)
        return archive
    except BaseException:
        assembling.unlink(missing_ok=True)
        raise
    finally:
        for part in temporary_parts:
            part.unlink(missing_ok=True)


def ensure_snapshot_manifest(
    spec: SnapshotSpec,
    cache_dir: Path,
    *,
    download: Download,
) -> tuple[Path, dict[str, object]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = cache_dir / spec.manifest_name
    try:
        _validate_file(
            manifest,
            size_bytes=spec.manifest_size_bytes,
            sha256=spec.manifest_sha256,
        )
        return manifest, validate_snapshot_manifest(spec, manifest.read_bytes())
    except SnapshotError:
        manifest.unlink(missing_ok=True)

    temporary = manifest.with_suffix(manifest.suffix + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        _download_verified(
            spec.asset_url(spec.manifest_name),
            temporary,
            size_bytes=spec.manifest_size_bytes,
            sha256=spec.manifest_sha256,
            download=download,
        )
        payload = validate_snapshot_manifest(spec, temporary.read_bytes())
        temporary.replace(manifest)
        return manifest, payload
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _safe_destination(root: Path, name: str) -> Path:
    candidate = (root / name.replace("\\", "/")).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise SnapshotError(f"snapshot archive contains unsafe path: {name}")
    return candidate


def validate_tar_member(root: Path, member: tarfile.TarInfo) -> None:
    normalized_name = member.name.replace("\\", "/")
    top_level = normalized_name.split("/", 1)[0]
    if top_level not in _SNAPSHOT_ROOTS:
        raise SnapshotError(f"snapshot archive contains unexpected top-level path: {member.name}")
    _safe_destination(root, member.name)
    if not (member.issym() or member.islnk()):
        return
    linkname = member.linkname.replace("\\", "/")
    if os.path.isabs(linkname):
        raise SnapshotError(
            f"snapshot archive contains absolute link: {member.name} -> {member.linkname}"
        )
    target = Path(member.name.replace("\\", "/")).parent / linkname
    _safe_destination(root, str(target))


def extract_tar_zst(archive: Path, destination: Path) -> None:
    zstd = shutil.which("zstd")
    if zstd is None:
        raise SnapshotError("zstd is required to restore source snapshots")
    destination.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([zstd, "-d", "-c", str(archive)], stdout=subprocess.PIPE)
    assert process.stdout is not None
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|*") as stream:
            for member in stream:
                validate_tar_member(destination, member)
                if not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
                    raise SnapshotError(
                        f"snapshot archive contains unsupported entry: {member.name}"
                    )
                stream.extract(member, destination, set_attrs=True)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        process.stdout.close()
    if process.wait() != 0:
        raise SnapshotError("zstd failed while restoring source snapshot")


def _validate_restored_tree(workspace_root: Path) -> None:
    required = (workspace_root / "checkout/src", workspace_root / "depot_tools")
    for path in required:
        if not path.is_dir():
            raise SnapshotError(f"restored snapshot directory is missing: {path}")
    forbidden = {".git", "out", "stage", "dist", "diagnostics"}
    for root in (workspace_root / "checkout", workspace_root / "depot_tools"):
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if forbidden.intersection(relative.parts):
                raise SnapshotError(f"restored snapshot contains forbidden path: {path}")


def restore_source_snapshot(
    spec: SnapshotSpec,
    workspace_root: Path,
    cache_dir: Path,
    *,
    download: Download = download_asset,
    extract: Callable[[Path, Path], None] = extract_tar_zst,
    journal: Any | None = None,
) -> dict[str, object]:
    workspace_root.mkdir(parents=True, exist_ok=True)
    manifest_phase = (
        journal.phase("snapshot-manifest", snapshot=spec.name) if journal else nullcontext()
    )
    with manifest_phase:
        _, manifest = ensure_snapshot_manifest(spec, cache_dir, download=download)
    archive_phase = (
        journal.phase("snapshot-archive", snapshot=spec.name) if journal else nullcontext()
    )
    with archive_phase:
        archive = ensure_snapshot_archive(spec, cache_dir, download=download)
    extract_phase = (
        journal.phase("snapshot-extract", snapshot=spec.name) if journal else nullcontext()
    )
    with extract_phase:
        for name in ("checkout", "depot_tools", "out", "stage"):
            path = workspace_root / name
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path, ignore_errors=True)
        extract(archive, workspace_root)
        _validate_restored_tree(workspace_root)
    return manifest
