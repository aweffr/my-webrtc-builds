import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from builder.compose import (
    CompositionError,
    compose_macos_xcframework,
    create_release_manifest,
    prepare_macos_inputs,
)
from builder.config import get_target
from builder.metadata import BuildMetadata, save_metadata
from builder.package import create_tar_gz, package_filename


def build_metadata(target: str, *, builder_commit: str = "a" * 40) -> BuildMetadata:
    config = get_target(target)
    return BuildMetadata.create(
        target=target,
        builder_commit=builder_commit,
        header_manifest="same-headers",
        patch_hashes={name: f"sha-{name}" for name in config.patches},
        gn_args={arch: config.gn_args_for(arch) for arch in config.architectures},
        toolchain={"test": "true"},
    )


def create_package(directory: Path, target: str, metadata: BuildMetadata | None = None) -> Path:
    root = directory / f"stage-{target}" / "webrtc"
    root.mkdir(parents=True)
    save_metadata(root / "metadata.json", metadata or build_metadata(target))
    (root / "include").mkdir()
    (root / "include" / "header.h").write_text("header")
    for name in ("LICENSE", "PATENTS", "AUTHORS", "NOTICE"):
        (root / name).write_text(name)
    if target.startswith("macos"):
        framework = root / "Frameworks" / "WebRTC.framework" / "Versions" / "A"
        framework.mkdir(parents=True)
        (framework / "WebRTC").write_bytes(target.encode())
        (framework / "Headers").mkdir()
        (framework / "Headers" / "WebRTC.h").write_text("header")
    archive = directory / package_filename(target)
    create_tar_gz(root, archive, arcname="webrtc")
    return archive


class MacOSInputTests(unittest.TestCase):
    def test_compatible_thin_packages_are_prepared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64")
            arm64 = create_package(root, "macos-arm64")
            inputs = prepare_macos_inputs(x64, arm64, root / "extract")
            self.assertEqual(inputs.x64_metadata.target, "macos-x64")
            self.assertEqual(inputs.arm64_metadata.target, "macos-arm64")

    def test_mixed_builder_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64")
            arm64 = create_package(
                root,
                "macos-arm64",
                build_metadata("macos-arm64", builder_commit="b" * 40),
            )
            with self.assertRaisesRegex(CompositionError, "builder commit"):
                prepare_macos_inputs(x64, arm64, root / "extract")

    def test_composition_lipos_thin_binaries_before_creating_xcframework(self) -> None:
        class ComposeRunner:
            def __init__(self) -> None:
                self.commands: list[tuple[str, ...]] = []

            def run(self, argv, *, cwd=None, env=None) -> None:
                command = tuple(map(str, argv))
                self.commands.append(command)
                if command[0] == "lipo":
                    output = Path(command[command.index("-output") + 1])
                    output.write_bytes(b"universal")
                elif command[0] == "xcodebuild":
                    output = Path(command[command.index("-output") + 1])
                    output.mkdir(parents=True)
                    (output / "Info.plist").write_text("plist")
                elif command[0] == "zip":
                    Path(command[3]).write_bytes(b"zip")

            def capture(self, argv, *, cwd=None, env=None) -> str:
                self.commands.append(tuple(map(str, argv)))
                return "x86_64 arm64"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64")
            arm64 = create_package(root, "macos-arm64")
            runner = ComposeRunner()
            archive, metadata = compose_macos_xcframework(
                x64_archive=x64,
                arm64_archive=arm64,
                work_dir=root / "work",
                output_dir=root / "dist",
                builder_commit="a" * 40,
                runner=runner,
            )
            commands = runner.commands
            lipo_index = next(
                i
                for i, command in enumerate(commands)
                if command[0] == "lipo" and "-create" in command
            )
            xcode_index = next(
                i for i, command in enumerate(commands) if command[0] == "xcodebuild"
            )
            self.assertLess(lipo_index, xcode_index)
            self.assertTrue(archive.is_file())
            self.assertEqual(json.loads(metadata.read_text())["target"], "macos-universal")

    def test_composition_rejects_workflow_commit_different_from_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(CompositionError, "workflow builder commit"):
                compose_macos_xcframework(
                    x64_archive=create_package(root, "macos-x64"),
                    arm64_archive=create_package(root, "macos-arm64"),
                    work_dir=root / "work",
                    output_dir=root / "dist",
                    builder_commit="b" * 40,
                    runner=object(),
                )

    def test_mixed_headers_or_apple_patch_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64")
            changed = replace(build_metadata("macos-arm64"), header_manifest="different")
            arm64 = create_package(root, "macos-arm64", changed)
            with self.assertRaisesRegex(CompositionError, "header manifest"):
                prepare_macos_inputs(x64, arm64, root / "extract")


class ReleaseManifestTests(unittest.TestCase):
    def test_release_requires_exact_four_platform_packages_and_xcframework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = {
                target: create_package(root, target)
                for target in ("android", "ios", "macos-x64", "macos-arm64")
            }
            xcframework = root / "WebRTC-m150-macos-universal.xcframework.zip"
            xcframework.write_bytes(b"xcframework")
            xc_metadata = root / "xcframework-metadata.json"
            xc_metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target": "macos-universal",
                        "builder_commit": "a" * 40,
                        "source": build_metadata("macos-x64").source,
                        "header_manifest": "same-headers",
                    }
                )
            )
            manifest = create_release_manifest(
                revision=1,
                packages=packages,
                xcframework=xcframework,
                xcframework_metadata=xc_metadata,
                output_dir=root / "release",
                builder_commit="a" * 40,
            )
            payload = json.loads(manifest.read_text())
        self.assertEqual(payload["tag"], "m150.7871.3-r1")
        self.assertEqual(len(payload["assets"]), 5)

    def test_release_rejects_workflow_commit_different_from_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = {
                target: create_package(root, target)
                for target in ("android", "ios", "macos-x64", "macos-arm64")
            }
            xcframework = root / "WebRTC-m150-macos-universal.xcframework.zip"
            xcframework.write_bytes(b"xcframework")
            xc_metadata = root / "xcframework-metadata.json"
            xc_metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target": "macos-universal",
                        "builder_commit": "a" * 40,
                        "source": build_metadata("macos-x64").source,
                        "header_manifest": "same-headers",
                    }
                )
            )
            with self.assertRaisesRegex(CompositionError, "workflow builder commit"):
                create_release_manifest(
                    revision=1,
                    packages=packages,
                    xcframework=xcframework,
                    xcframework_metadata=xc_metadata,
                    output_dir=root / "release",
                    builder_commit="b" * 40,
                )

    def test_release_rejects_missing_platform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = {"android": create_package(root, "android")}
            xcframework = root / "WebRTC-m150-macos-universal.xcframework.zip"
            xcframework.write_bytes(b"xcframework")
            xc_metadata = root / "xcframework-metadata.json"
            xc_metadata.write_text("{}")
            with self.assertRaisesRegex(CompositionError, "exact platform set"):
                create_release_manifest(
                    revision=1,
                    packages=packages,
                    xcframework=xcframework,
                    xcframework_metadata=xc_metadata,
                    output_dir=root / "release",
                    builder_commit="a" * 40,
                )


if __name__ == "__main__":
    unittest.main()
