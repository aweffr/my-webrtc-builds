from __future__ import annotations

import os
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

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        environment["PATH"] = f"{self.depot_tools}{os.pathsep}{environment.get('PATH', '')}"
        environment["DEPOT_TOOLS_UPDATE"] = "0"
        return environment


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
) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    environment = workspace.environment()
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
    if not (workspace.depot_tools / "python3_bin_reldir.txt").is_file():
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
            ["fetch", "--nohooks", "--no-history", "webrtc"],
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
        ["gclient", "sync", "-D", "--force", "--reset", "--no-history"],
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
