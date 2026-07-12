from __future__ import annotations

from dataclasses import dataclass
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .config import TargetConfig
from .source import BuildError, Runner, Workspace


@dataclass(frozen=True)
class BuildUnit:
    architecture: str
    output_dir: Path
    gn_args: tuple[str, ...]


def _directory_name(architecture: str) -> str:
    return architecture.replace(":", "-")


def build_units(target: TargetConfig, workspace: Workspace) -> tuple[BuildUnit, ...]:
    return tuple(
        BuildUnit(
            architecture=architecture,
            output_dir=workspace.out / target.name / _directory_name(architecture),
            gn_args=target.gn_args_for(architecture),
        )
        for architecture in target.architectures
    )


def _archiver(target: TargetConfig, workspace: Workspace) -> Path:
    if target.name in {"android"}:
        return workspace.src / "third_party/llvm-build/Release+Asserts/bin/llvm-ar"
    return Path("/usr/bin/ar")


def _archive_objects(
    target: TargetConfig,
    workspace: Workspace,
    unit: BuildUnit,
    runner: Runner,
) -> Path:
    object_files = sorted((unit.output_dir / "obj").rglob("*.o"))
    if not object_files:
        raise BuildError(f"no object files found for {target.name} {unit.architecture}")
    output = unit.output_dir / "libwebrtc.a"
    output.unlink(missing_ok=True)
    archiver = _archiver(target, workspace)
    chunk: list[Path] = []
    size = 0
    first = True
    for object_file in object_files:
        candidate_size = len(str(object_file)) + 1
        if chunk and size + candidate_size > 96_000:
            runner.run([archiver, "-rcs" if first else "-rs", output, *chunk])
            first = False
            chunk = []
            size = 0
        chunk.append(object_file)
        size += candidate_size
    if chunk:
        runner.run([archiver, "-rcs" if first else "-rs", output, *chunk])
    return output


def build_webrtc(
    target: TargetConfig,
    workspace: Workspace,
    runner: Runner,
    journal: Any | None = None,
) -> tuple[BuildUnit, ...]:
    environment = workspace.environment()
    units = build_units(target, workspace)
    for unit in units:
        unit.output_dir.mkdir(parents=True, exist_ok=True)
        args_string = " ".join(unit.gn_args)
        phase = (
            journal.phase("gn-generate", target=target.name, architecture=unit.architecture)
            if journal
            else nullcontext()
        )
        with phase:
            runner.run(
                ["gn", "gen", unit.output_dir, f"--args={args_string}"],
                cwd=workspace.src,
                env=environment,
            )
        resolved_args = runner.capture(
            ["gn", "args", "--list", unit.output_dir],
            cwd=workspace.src,
            env=environment,
        )
        (unit.output_dir / "gn-args.txt").write_text(resolved_args + "\n")
        phase = (
            journal.phase("ninja-build", target=target.name, architecture=unit.architecture)
            if journal
            else nullcontext()
        )
        with phase:
            runner.run(
                ["ninja", "-C", unit.output_dir, *target.ninja_targets],
                cwd=workspace.src,
                env=environment,
            )
        phase = (
            journal.phase("static-archive", target=target.name, architecture=unit.architecture)
            if journal
            else nullcontext()
        )
        with phase:
            _archive_objects(target, workspace, unit, runner)
    return units
