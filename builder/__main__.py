from __future__ import annotations

import argparse
from pathlib import Path

from .build import build_webrtc
from .commands import CommandRunner
from .compose import (
    compose_macos_xcframework,
    create_preview_release_manifest,
    create_release_manifest,
)
from .config import DEPOT_TOOLS_COMMIT, TARGETS, get_target
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
        "--snapshot-cache-dir",
        type=Path,
        help="cache for the pinned snapshot archive (defaults to WORK_DIR/snapshot-cache)",
    )
    build.add_argument(
        "--patch-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "patches" / "m150",
    )
    build.add_argument(
        "--overlay-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "overlays" / "m150",
    )
    merge = subparsers.add_parser("merge-macos", help="compose thin macOS packages")
    merge.add_argument("--x64-package", required=True, type=Path)
    merge.add_argument("--arm64-package", required=True, type=Path)
    merge.add_argument("--work-dir", required=True, type=Path)
    merge.add_argument("--dist-dir", required=True, type=Path)
    merge.add_argument("--builder-commit", required=True)

    release = subparsers.add_parser("release-manifest", help="validate and compose release data")
    for target in ("android", "ios", "macos-x64", "macos-arm64", "windows-x64"):
        release.add_argument(f"--{target}-package", required=True, type=Path)
    release.add_argument("--android-aar", required=True, type=Path)
    release.add_argument("--xcframework", required=True, type=Path)
    release.add_argument("--xcframework-metadata", required=True, type=Path)
    release.add_argument("--output-dir", required=True, type=Path)
    release.add_argument("--builder-commit", required=True)
    release.add_argument("--release-date", required=True)
    release.add_argument("--platform", required=True)

    preview = subparsers.add_parser(
        "preview-release-manifest",
        help="validate Android/macOS runtime evidence and compose preview release data",
    )
    preview.add_argument("--android-package", required=True, type=Path)
    preview.add_argument("--android-aar", required=True, type=Path)
    preview.add_argument("--macos-x64-package", required=True, type=Path)
    preview.add_argument("--macos-arm64-package", required=True, type=Path)
    preview.add_argument("--xcframework", required=True, type=Path)
    preview.add_argument("--xcframework-metadata", required=True, type=Path)
    preview.add_argument("--android-smoke-evidence", required=True, type=Path)
    preview.add_argument("--macos-probe-evidence", required=True, type=Path)
    preview.add_argument("--output-dir", required=True, type=Path)
    preview.add_argument("--builder-commit", required=True)
    preview.add_argument("--android-workflow-run-id", required=True, type=int)
    preview.add_argument("--android-artifact-digest", required=True)
    preview.add_argument("--release-date", required=True)
    preview.add_argument("--preview-revision", required=True, type=int)
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
            snapshot=target.snapshot.name,
            snapshot_release=target.snapshot.release_tag,
            snapshot_archive_sha256=target.snapshot.archive_sha256,
        )
        with journal.phase("source-prepare", target=target.name):
            snapshot_manifest = prepare_source(
                target,
                workspace,
                args.patch_dir.resolve(),
                runner,
                args.overlay_dir.resolve(),
                snapshot_cache_dir=(
                    args.snapshot_cache_dir.resolve()
                    if args.snapshot_cache_dir is not None
                    else workspace.root / "snapshot-cache"
                ),
                journal=journal,
            )
        journal.record(
            "source-prepare",
            "verified",
            target=target.name,
            snapshot=snapshot_manifest["snapshot"],
            archive_sha256=snapshot_manifest["archive_sha256"],
        )
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
                overlay_dir=args.overlay_dir.resolve(),
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
                "windows-x64": args.windows_x64_package.resolve(),
            },
            android_aar=args.android_aar.resolve(),
            xcframework=args.xcframework.resolve(),
            xcframework_metadata=args.xcframework_metadata.resolve(),
            output_dir=args.output_dir.resolve(),
            builder_commit=args.builder_commit,
            release_date=args.release_date,
            platform=args.platform,
        )
        print(manifest)
        return 0
    if args.command == "preview-release-manifest":
        manifest = create_preview_release_manifest(
            android_package=args.android_package.resolve(),
            android_aar=args.android_aar.resolve(),
            macos_x64_package=args.macos_x64_package.resolve(),
            macos_arm64_package=args.macos_arm64_package.resolve(),
            xcframework=args.xcframework.resolve(),
            xcframework_metadata=args.xcframework_metadata.resolve(),
            android_smoke_evidence=args.android_smoke_evidence.resolve(),
            macos_probe_evidence=args.macos_probe_evidence.resolve(),
            output_dir=args.output_dir.resolve(),
            builder_commit=args.builder_commit,
            android_workflow_run_id=args.android_workflow_run_id,
            android_artifact_digest=args.android_artifact_digest,
            release_date=args.release_date,
            preview_revision=args.preview_revision,
        )
        print(manifest)
        return 0
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
