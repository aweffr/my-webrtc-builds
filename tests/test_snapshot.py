from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from builder.config import DEPOT_TOOLS_COMMIT, SOURCE_VERSION, SnapshotPart, get_target
from builder.snapshot import (
    SnapshotError,
    _download_verified,
    download_asset,
    ensure_snapshot_archive,
    restore_source_snapshot,
    validate_snapshot_manifest,
    validate_tar_member,
)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tiny_snapshot():
    base = get_target("macos-arm64").snapshot
    parts = (b"first", b"second")
    archive = b"".join(parts)
    spec = replace(
        base,
        name="tiny",
        manifest_name="tiny.manifest.json",
        manifest_size_bytes=1,
        manifest_sha256="0" * 64,
        archive_size_bytes=len(archive),
        archive_sha256=sha256(archive),
        parts=(
            SnapshotPart("tiny.part-000", len(parts[0]), sha256(parts[0])),
            SnapshotPart("tiny.part-001", len(parts[1]), sha256(parts[1])),
        ),
    )
    return spec, dict(zip((part.name for part in spec.parts), parts, strict=True))


def manifest_bytes(spec) -> bytes:
    return (
        json.dumps(
            {
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
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


class SnapshotContractTests(unittest.TestCase):
    def test_manifest_must_match_every_pinned_identity_field(self) -> None:
        spec = get_target("android").snapshot
        payload = {
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

        validate_snapshot_manifest(spec, json.dumps(payload).encode())
        for field in (
            "snapshot",
            "webrtc_commit",
            "depot_tools_commit",
            "target_os",
            "runner_os",
            "runner_arch",
            "xcode_version",
            "archive_sha256",
            "archive_size_bytes",
        ):
            changed = dict(payload)
            changed[field] = "wrong"
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                validate_snapshot_manifest(spec, json.dumps(changed).encode())

    def test_archive_is_reassembled_from_verified_parts_and_then_cached(self) -> None:
        spec, contents = tiny_snapshot()
        calls: list[str] = []

        def download(url: str, destination: Path) -> None:
            name = url.rsplit("/", 1)[-1]
            calls.append(name)
            destination.write_bytes(contents[name])

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            archive = ensure_snapshot_archive(spec, cache, download=download)
            self.assertEqual(archive.read_bytes(), b"firstsecond")
            self.assertEqual(calls, [part.name for part in spec.parts])

            calls.clear()
            self.assertEqual(ensure_snapshot_archive(spec, cache, download=download), archive)
            self.assertEqual(calls, [])

    def test_bad_part_is_rejected_without_publishing_cache_entry(self) -> None:
        spec, _ = tiny_snapshot()

        def corrupt_download(url: str, destination: Path) -> None:
            destination.write_bytes(b"wrong")

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with self.assertRaisesRegex(SnapshotError, "digest"):
                ensure_snapshot_archive(spec, cache, download=corrupt_download)
            self.assertFalse((cache / "tiny.tar.zst").exists())

    def test_short_part_download_is_retried_before_failing_restore(self) -> None:
        spec, contents = tiny_snapshot()
        calls: dict[str, int] = {}

        def download(url: str, destination: Path) -> None:
            name = url.rsplit("/", 1)[-1]
            calls[name] = calls.get(name, 0) + 1
            payload = contents[name]
            destination.write_bytes(payload[:-1] if calls[name] == 1 else payload)

        with tempfile.TemporaryDirectory() as directory:
            archive = ensure_snapshot_archive(spec, Path(directory), download=download)
            self.assertEqual(archive.read_bytes(), b"firstsecond")

        self.assertEqual(calls, {part.name: 2 for part in spec.parts})

    def test_part_downloads_are_parallel_but_capped_at_three(self) -> None:
        spec, contents = tiny_snapshot()
        spec = replace(
            spec,
            parts=spec.parts
            + (
                SnapshotPart("tiny.part-002", 1, sha256(b"!")),
                SnapshotPart("tiny.part-003", 1, sha256(b"?")),
            ),
            archive_size_bytes=13,
            archive_sha256=sha256(b"firstsecond!?"),
        )
        contents.update({"tiny.part-002": b"!", "tiny.part-003": b"?"})
        active = 0
        maximum = 0
        lock = threading.Lock()

        def download(url: str, destination: Path) -> None:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            destination.write_bytes(contents[url.rsplit("/", 1)[-1]])
            with lock:
                active -= 1

        with tempfile.TemporaryDirectory() as directory:
            ensure_snapshot_archive(spec, Path(directory), download=download)
        self.assertGreater(maximum, 1)
        self.assertLessEqual(maximum, 3)

    def test_download_retries_and_resumes_a_partial_asset(self) -> None:
        requests = []

        class Response(io.BytesIO):
            status = 206

        def opener(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.URLError("temporary")
            return Response(b"def")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.partial"
            destination.write_bytes(b"abc")
            _download_verified(
                "https://example.invalid/asset",
                destination,
                size_bytes=6,
                sha256=sha256(b"abcdef"),
                download=lambda url, path: download_asset(url, path, opener=opener),
            )
            self.assertEqual(destination.read_bytes(), b"abcdef")
        self.assertEqual(requests[0].get_header("Range"), "bytes=3-")
        self.assertEqual(requests[1].get_header("Range"), "bytes=3-")

    def test_default_transfer_is_called_at_most_four_times(self) -> None:
        calls = 0

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            raise urllib.error.URLError("persistent")

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "asset.partial"
            with self.assertRaises(urllib.error.URLError):
                _download_verified(
                    "https://example.invalid/asset",
                    destination,
                    size_bytes=1,
                    sha256=sha256(b"x"),
                    download=lambda url, path: download_asset(url, path, opener=opener),
                )

        self.assertEqual(calls, 4)

    def test_tar_member_and_link_cannot_escape_restore_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            traversal = tarfile.TarInfo("../outside")
            with self.assertRaises(SnapshotError):
                validate_tar_member(root, traversal)

            link = tarfile.TarInfo("checkout/src/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../outside"
            with self.assertRaises(SnapshotError):
                validate_tar_member(root, link)

    def test_tar_members_are_limited_to_snapshot_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            validate_tar_member(root, tarfile.TarInfo("checkout/src/BUILD.gn"))
            validate_tar_member(root, tarfile.TarInfo("depot_tools/gn"))
            for name in ("diagnostics/result.json", "snapshot-cache/part", "unrelated.txt"):
                with (
                    self.subTest(name=name),
                    self.assertRaisesRegex(SnapshotError, "unexpected top-level"),
                ):
                    validate_tar_member(root, tarfile.TarInfo(name))

    def test_restore_recreates_mutable_workspace_from_verified_snapshot(self) -> None:
        spec, contents = tiny_snapshot()
        manifest = manifest_bytes(spec)
        spec = replace(
            spec,
            manifest_size_bytes=len(manifest),
            manifest_sha256=sha256(manifest),
        )
        contents[spec.manifest_name] = manifest

        def download(url: str, destination: Path) -> None:
            destination.write_bytes(contents[url.rsplit("/", 1)[-1]])

        def extract(archive: Path, destination: Path) -> None:
            self.assertEqual(archive.read_bytes(), b"firstsecond")
            (destination / "checkout/src").mkdir(parents=True)
            (destination / "depot_tools").mkdir()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "work"
            cache = root / "snapshot-cache"
            for stale in ("checkout", "depot_tools", "out", "stage"):
                path = root / stale / "stale"
                path.mkdir(parents=True)
                (path / "old").write_text("old")
            (root / "diagnostics").mkdir(parents=True)

            phases = []

            class Journal:
                @contextmanager
                def phase(self, name, **details):
                    phases.append((name, details))
                    yield

            restored_manifest = restore_source_snapshot(
                spec,
                root,
                cache,
                download=download,
                extract=extract,
                journal=Journal(),
            )

            self.assertEqual(restored_manifest["snapshot"], "tiny")
            self.assertTrue((root / "checkout/src").is_dir())
            self.assertTrue((root / "depot_tools").is_dir())
            self.assertFalse((root / "out").exists())
            self.assertFalse((root / "stage").exists())
            self.assertTrue((root / "diagnostics").is_dir())
            self.assertTrue((cache / "tiny.tar.zst").is_file())
            self.assertEqual(
                [name for name, _ in phases],
                ["snapshot-manifest", "snapshot-archive", "snapshot-extract"],
            )

    def test_restore_rejects_forbidden_git_metadata(self) -> None:
        spec, contents = tiny_snapshot()
        manifest = manifest_bytes(spec)
        spec = replace(
            spec,
            manifest_size_bytes=len(manifest),
            manifest_sha256=sha256(manifest),
        )
        contents[spec.manifest_name] = manifest

        def download(url: str, destination: Path) -> None:
            destination.write_bytes(contents[url.rsplit("/", 1)[-1]])

        def extract(archive: Path, destination: Path) -> None:
            (destination / "checkout/src/.git").mkdir(parents=True)
            (destination / "depot_tools").mkdir()

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SnapshotError, "forbidden"):
                restore_source_snapshot(
                    spec,
                    Path(directory) / "work",
                    Path(directory) / "cache",
                    download=download,
                    extract=extract,
                )


if __name__ == "__main__":
    unittest.main()
