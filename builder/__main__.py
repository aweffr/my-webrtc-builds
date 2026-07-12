from __future__ import annotations

import argparse
from pathlib import Path

from .build import build_webrtc
from .commands import CommandRunner
from .config import TARGETS, get_target
from .observability import BuildJournal, collect_toolchain
from .package import stage_and_package
from .source import Workspace, prepare_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build pinned WebRTC M150 artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="build one fixed platform target")
    build.add_argument("--target", required=True, choices=tuple(TARGETS))
    build.add_argument("--work-dir", required=True, type=Path)
    build.add_argument("--dist-dir", required=True, type=Path)
    build.add_argument("--builder-commit", required=True)
    build.add_argument(
        "--patch-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "patches" / "m150",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        target = get_target(args.target)
        workspace = Workspace(args.work_dir.resolve())
        journal = BuildJournal(workspace.root / "diagnostics" / "build-events.jsonl")
        runner = CommandRunner(logger=journal.log)
        journal.record(
            "build",
            "configured",
            target=target.name,
            builder_commit=args.builder_commit,
        )
        with journal.phase("source-prepare", target=target.name):
            prepare_source(target, workspace, args.patch_dir.resolve(), runner)
        units = build_webrtc(target, workspace, runner, journal)
        with journal.phase("package", target=target.name):
            toolchain = collect_toolchain(target.name, runner)
            archive = stage_and_package(
                target,
                workspace,
                units,
                args.dist_dir.resolve(),
                args.patch_dir.resolve(),
                args.builder_commit,
                toolchain,
                runner,
            )
        journal.record("build", "completed", target=target.name, artifact=str(archive))
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
