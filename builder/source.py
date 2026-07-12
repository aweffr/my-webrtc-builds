from __future__ import annotations

import os
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import SOURCE_VERSION, TargetConfig

# This is the depot_tools revision recorded by the pinned WebRTC M150 DEPS file.
DEPOT_TOOLS_COMMIT = "2f9bc10799af5aeb4a0ed903742ad69bb1d0ef75"


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
        if target is not None and target.name == "windows-x64":
            return self.depot_tools / f"{name}.bat"
        return name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlay_sources(
    target: TargetConfig, overlay_dir: Path
) -> tuple[tuple[Path, Path], ...]:
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


def _configure_target_os(target: TargetConfig, gclient_path: Path) -> None:
    if target.name == "android":
        target_os = "android"
    elif target.name == "ios":
        target_os = "ios"
    else:
        return
    content = gclient_path.read_text()
    declaration = f"target_os = [ '{target_os}' ]"
    if declaration not in content:
        gclient_path.write_text(content.rstrip() + f"\n{declaration}\n")


def prepare_source(
    target: TargetConfig,
    workspace: Workspace,
    patch_dir: Path,
    runner: Runner,
    overlay_dir: Path | None = None,
) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    environment = workspace.environment(target)
    if not workspace.depot_tools.exists():
        workspace.depot_tools.mkdir(parents=True)
        runner.run(["git", "init"], cwd=workspace.depot_tools)
        runner.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "https://chromium.googlesource.com/chromium/tools/depot_tools.git",
            ],
            cwd=workspace.depot_tools,
        )
        runner.run(
            ["git", "fetch", "--depth=1", "origin", DEPOT_TOOLS_COMMIT],
            cwd=workspace.depot_tools,
        )
        runner.run(
            ["git", "checkout", "--detach", DEPOT_TOOLS_COMMIT],
            cwd=workspace.depot_tools,
        )
    actual_depot_tools_commit = runner.capture(
        ["git", "rev-parse", "HEAD"], cwd=workspace.depot_tools
    )
    if actual_depot_tools_commit != DEPOT_TOOLS_COMMIT:
        raise BuildError(
            f"unexpected depot_tools commit {actual_depot_tools_commit!r}; "
            f"expected {DEPOT_TOOLS_COMMIT}"
        )
    if target.name != "windows-x64" and not (
        workspace.depot_tools / "python3_bin_reldir.txt"
    ).is_file():
        runner.run(
            [
                "bash",
                "-c",
                "source ./cipd_bin_setup.sh; cipd_bin_setup; "
                "source ./bootstrap_python3; bootstrap_python3",
            ],
            cwd=workspace.depot_tools,
            env=environment,
        )
    if not workspace.src.exists():
        workspace.checkout_root.mkdir(parents=True, exist_ok=True)
        runner.run(
            [workspace.tool("fetch", target), "--nohooks", "--no-history", "webrtc"],
            cwd=workspace.checkout_root,
            env=environment,
        )
        _configure_target_os(target, workspace.checkout_root / ".gclient")

    runner.run(["git", "reset", "--hard"], cwd=workspace.src, env=environment)
    runner.run(
        ["git", "fetch", "--depth=1", "origin", SOURCE_VERSION.commit],
        cwd=workspace.src,
        env=environment,
    )
    runner.run(
        ["git", "checkout", "--detach", SOURCE_VERSION.commit],
        cwd=workspace.src,
        env=environment,
    )
    runner.run(["git", "clean", "-df"], cwd=workspace.src, env=environment)
    runner.run(
        [
            workspace.tool("gclient", target),
            "sync",
            "-D",
            "--force",
            "--reset",
            "--no-history",
        ],
        cwd=workspace.src,
        env=environment,
    )
    actual_commit = runner.capture(["git", "rev-parse", "HEAD"], cwd=workspace.src, env=environment)
    if actual_commit != SOURCE_VERSION.commit:
        raise BuildError(
            f"unexpected WebRTC commit {actual_commit!r}; expected {SOURCE_VERSION.commit}"
        )

    for patch_name in target.patches:
        patch_path = patch_dir / patch_name
        if not patch_path.is_file():
            raise BuildError(f"required patch is missing: {patch_path}")
        runner.run(
            ["git", "apply", "--check", patch_path],
            cwd=workspace.src,
            env=environment,
        )
        runner.run(["git", "apply", patch_path], cwd=workspace.src, env=environment)
    if target.overlays:
        if overlay_dir is None:
            raise BuildError(f"target {target.name} requires an overlay directory")
        apply_overlays(target, workspace, overlay_dir)
