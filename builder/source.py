from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from typing import Any

from .config import TargetConfig
from .snapshot import restore_source_snapshot

_UNIFIED_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(?: .*)?$")


class BuildError(RuntimeError):
    """The checked-out source or produced build violates the contract."""


class Runner(Protocol):
    def run(self, argv, *, cwd=None, env=None) -> None: ...

    def capture(self, argv, *, cwd=None, env=None) -> str: ...


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def depot_tools(self) -> Path:
        return self.root / "depot_tools"

    @property
    def checkout_root(self) -> Path:
        return self.root / "checkout"

    @property
    def src(self) -> Path:
        return self.checkout_root / "src"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def stage(self) -> Path:
        return self.root / "stage"

    def environment(self, target: TargetConfig | None = None) -> dict[str, str]:
        environment = dict(os.environ)
        is_windows = target is not None and target.name == "windows-x64"
        separator = ";" if is_windows else os.pathsep
        environment["PATH"] = f"{self.depot_tools}{separator}{environment.get('PATH', '')}"
        environment["DEPOT_TOOLS_UPDATE"] = "0"
        if is_windows:
            environment["DEPOT_TOOLS_WIN_TOOLCHAIN"] = "0"
            environment["GIT_CONFIG_COUNT"] = "1"
            environment["GIT_CONFIG_KEY_0"] = "core.longpaths"
            environment["GIT_CONFIG_VALUE_0"] = "true"
        return environment

    def tool(self, name: str, target: TargetConfig | None = None) -> Path | str:
        if name not in {"gn", "ninja"}:
            raise BuildError(f"snapshot build tool {name!r} is not permitted")
        if target is not None and target.name == "windows-x64":
            return self.depot_tools / f"{name}.bat"
        return name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlay_sources(target: TargetConfig, overlay_dir: Path) -> tuple[tuple[Path, Path], ...]:
    sources: list[tuple[Path, Path]] = []
    destinations: set[Path] = set()
    for group in target.overlays:
        root = overlay_dir / group
        if not root.is_dir():
            raise BuildError(f"required overlay group is missing: {root}")
        files = sorted(path for path in root.rglob("*") if path.is_file())
        if not files:
            raise BuildError(f"overlay group contains no files: {root}")
        for source in files:
            relative = source.relative_to(root)
            if relative in destinations:
                raise BuildError(f"duplicate overlay destination: {relative.as_posix()}")
            destinations.add(relative)
            sources.append((source, relative))
    return tuple(sources)


def overlay_manifest(target: TargetConfig, overlay_dir: Path) -> dict[str, str]:
    return {
        relative.as_posix(): _sha256(source)
        for source, relative in _overlay_sources(target, overlay_dir)
    }


def apply_overlays(target: TargetConfig, workspace: Workspace, overlay_dir: Path) -> None:
    for source, relative in _overlay_sources(target, overlay_dir):
        destination = workspace.src / relative
        if destination.exists() or destination.is_symlink():
            raise BuildError(f"overlay destination already exists: {relative.as_posix()}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _validated_patch_paths(target: TargetConfig, patch_dir: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for patch_name in target.patches:
        patch_path = patch_dir / patch_name
        if not patch_path.is_file():
            raise BuildError(f"required patch is missing: {patch_path}")
        for line_number, line in enumerate(patch_path.read_text().splitlines(), start=1):
            if line.startswith("@@") and not _UNIFIED_HUNK_HEADER.fullmatch(line):
                raise BuildError(f"invalid unified diff hunk header in {patch_path}:{line_number}")
        paths.append(patch_path)
    return tuple(paths)


def prepare_source(
    target: TargetConfig,
    workspace: Workspace,
    patch_dir: Path,
    runner: Runner,
    overlay_dir: Path | None = None,
    *,
    snapshot_cache_dir: Path | None = None,
    journal: Any | None = None,
) -> dict[str, object]:
    patch_paths = _validated_patch_paths(target, patch_dir)
    cache_dir = snapshot_cache_dir or workspace.root / "snapshot-cache"
    manifest = restore_source_snapshot(target.snapshot, workspace.root, cache_dir, journal=journal)
    patch_environment = dict(os.environ)
    # Snapshot worktrees intentionally contain no .git directory. CI workspaces can
    # live below the builder repository, where an unconstrained `git apply` finds
    # that parent repository and silently skips every snapshot-relative path.
    patch_environment["GIT_CEILING_DIRECTORIES"] = str(workspace.checkout_root.resolve())
    for patch_path in patch_paths:
        runner.run(
            ["git", "apply", "--check", patch_path],
            cwd=workspace.src,
            env=patch_environment,
        )
        runner.run(
            ["git", "apply", patch_path],
            cwd=workspace.src,
            env=patch_environment,
        )
        runner.run(
            ["git", "apply", "--reverse", "--check", patch_path],
            cwd=workspace.src,
            env=patch_environment,
        )
    if target.overlays:
        if overlay_dir is None:
            raise BuildError(f"target {target.name} requires an overlay directory")
        apply_overlays(target, workspace, overlay_dir)
    return manifest
