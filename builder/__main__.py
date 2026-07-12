from __future__ import annotations

import argparse
from pathlib import Path

from .build import build_webrtc
from .commands import CommandRunner
from .compose import compose_macos_xcframework, create_release_manifest
from .config import TARGETS, get_target
from .observability import BuildJournal, collect_toolchain
from .package import stage_and_package
from .source import DEPOT_TOOLS_COMMIT, Workspace, prepare_source


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
    merge = subparsers.add_parser("merge-macos", help="compose thin macOS packages")
    merge.add_argument("--x64-package", required=True, type=Path)
    merge.add_argument("--arm64-package", required=True, type=Path)
    merge.add_argument("--work-dir", required=True, type=Path)
    merge.add_argument("--dist-dir", required=True, type=Path)
    merge.add_argument("--builder-commit", required=True)

    release = subparsers.add_parser("release-manifest", help="validate and compose release data")
    for target in ("android", "ios", "macos-x64", "macos-arm64"):
        release.add_argument(f"--{target}-package", required=True, type=Path)
    release.add_argument("--xcframework", required=True, type=Path)
    release.add_argument("--xcframework-metadata", required=True, type=Path)
    release.add_argument("--output-dir", required=True, type=Path)
    release.add_argument("--builder-commit", required=True)
    release.add_argument("--release-date", required=True)
    release.add_argument("--platform", required=True)
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
            depot_tools_commit=DEPOT_TOOLS_COMMIT,
        )
        with journal.phase("source-prepare", target=target.name):
            prepare_source(target, workspace, args.patch_dir.resolve(), runner)
        units = build_webrtc(target, workspace, runner, journal)
        with journal.phase("package", target=target.name):
            toolchain = collect_toolchain(target.name, runner)
            toolchain["depot_tools_commit"] = DEPOT_TOOLS_COMMIT
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
    if args.command == "merge-macos":
        work_dir = args.work_dir.resolve()
        journal = BuildJournal(work_dir / "diagnostics" / "build-events.jsonl")
        runner = CommandRunner(logger=journal.log)
        with journal.phase("macos-xcframework"):
            archive, metadata = compose_macos_xcframework(
                x64_archive=args.x64_package.resolve(),
                arm64_archive=args.arm64_package.resolve(),
                work_dir=work_dir,
                output_dir=args.dist_dir.resolve(),
                builder_commit=args.builder_commit,
                runner=runner,
            )
        journal.record(
            "macos-xcframework",
            "completed",
            artifact=str(archive),
            metadata=str(metadata),
        )
        return 0
    if args.command == "release-manifest":
        manifest = create_release_manifest(
            packages={
                "android": args.android_package.resolve(),
                "ios": args.ios_package.resolve(),
                "macos-x64": args.macos_x64_package.resolve(),
                "macos-arm64": args.macos_arm64_package.resolve(),
            },
            xcframework=args.xcframework.resolve(),
            xcframework_metadata=args.xcframework_metadata.resolve(),
            output_dir=args.output_dir.resolve(),
            builder_commit=args.builder_commit,
            release_date=args.release_date,
            platform=args.platform,
        )
        print(manifest)
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
