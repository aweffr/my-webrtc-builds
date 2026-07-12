from __future__ import annotations

import json
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
    return workspace.src / "third_party/llvm-build/Release+Asserts/bin/llvm-ar"


def _production_library(target: TargetConfig, unit: BuildUnit) -> Path:
    return unit.output_dir / ("webrtc.lib" if target.name == "windows-x64" else "libwebrtc.a")


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
    response_file = unit.output_dir / "libwebrtc-objects.rsp"
    response_file.write_text(
        "\n".join(json.dumps(str(object_file)) for object_file in object_files) + "\n"
    )
    runner.run([archiver, "rcs", output, f"@{response_file}"])
    archived_members = [
        member for member in runner.capture([archiver, "t", output]).splitlines() if member.strip()
    ]
    if len(archived_members) != len(object_files):
        raise BuildError(
            f"archive contains {len(archived_members)} members; expected {len(object_files)}"
        )
    return output


def build_webrtc(
    target: TargetConfig,
    workspace: Workspace,
    runner: Runner,
    journal: Any | None = None,
) -> tuple[BuildUnit, ...]:
    environment = workspace.environment(target)
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
                [workspace.tool("gn", target), "gen", unit.output_dir, f"--args={args_string}"],
                cwd=workspace.src,
                env=environment,
            )
        resolved_args = runner.capture(
            [workspace.tool("gn", target), "args", "--list", unit.output_dir],
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
                [workspace.tool("ninja", target), "-C", unit.output_dir, *target.ninja_targets],
                cwd=workspace.src,
                env=environment,
            )
        phase = (
            journal.phase("static-archive", target=target.name, architecture=unit.architecture)
            if journal
            else nullcontext()
        )
        with phase:
            if target.name == "windows-x64":
                source = unit.output_dir / "obj" / "webrtc.lib"
                if not source.is_file():
                    raise BuildError(f"complete static library is missing: {source}")
                source.replace(_production_library(target, unit))
            else:
                _archive_objects(target, workspace, unit, runner)
        if target.validation_targets:
            phase = (
                journal.phase(
                    "cast-tuning-validation-build",
                    target=target.name,
                    architecture=unit.architecture,
                )
                if journal
                else nullcontext()
            )
            with phase:
                runner.run(
                    [
                        workspace.tool("ninja", target),
                        "-C",
                        unit.output_dir,
                        *target.validation_targets,
                    ],
                    cwd=workspace.src,
                    env=environment,
                )
            if target.name.startswith("macos") or target.name == "windows-x64":
                executable = unit.output_dir / "cast_tuning_native_tests"
                if target.name == "windows-x64":
                    executable = executable.with_suffix(".exe")
                phase = (
                    journal.phase(
                        "cast-tuning-validation-run",
                        target=target.name,
                        architecture=unit.architecture,
                    )
                    if journal
                    else nullcontext()
                )
                with phase:
                    runner.run([executable], cwd=unit.output_dir, env=environment)
    return units
