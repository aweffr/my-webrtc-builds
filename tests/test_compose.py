import json
import hashlib
import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from builder.compose import (
    CompositionError,
    compose_macos_xcframework,
    create_preview_release_manifest,
    create_release_manifest,
    prepare_macos_inputs,
)
from builder.config import get_target
from builder.metadata import BuildMetadata, save_metadata
from builder.package import create_tar_gz, create_zip, package_filename


def java8_jar_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as stream:
        stream.writestr(
            "org/webrtc/Contract.class",
            b"\xca\xfe\xba\xbe\x00\x00\x00\x34",
        )
    return output.getvalue()


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


def create_package(
    directory: Path,
    target: str,
    metadata: BuildMetadata | None = None,
    framework_header: str = "header",
) -> Path:
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
        (framework / "Headers" / "WebRTC.h").write_text(framework_header)
    elif target == "android":
        (root / "jar").mkdir()
        (root / "jar" / "webrtc.jar").write_bytes(java8_jar_bytes())
        jni = root / "jni" / "arm64-v8a"
        jni.mkdir(parents=True)
        (jni / "libjingle_peerconnection_so.so").write_bytes(b"android-jni")
    archive = directory / package_filename(target)
    if target == "windows-x64":
        create_zip(root, archive, arcname="webrtc")
    else:
        create_tar_gz(root, archive, arcname="webrtc")
    return archive


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_android_aar(directory: Path) -> Path:
    aar = directory / "webrtc-m150-android-arm64-v8a.aar"
    with zipfile.ZipFile(aar, "w") as stream:
        stream.writestr("AndroidManifest.xml", "<manifest />")
        stream.writestr("classes.jar", java8_jar_bytes())
        stream.writestr(
            "jni/arm64-v8a/libjingle_peerconnection_so.so", b"android-jni"
        )
    return aar


def create_xcframework_inputs(directory: Path) -> tuple[Path, Path]:
    xcframework = directory / "WebRTC-m150-macos-universal.xcframework.zip"
    xcframework.write_bytes(b"xcframework")
    metadata = directory / "xcframework-metadata.json"
    metadata.write_text(
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
    return xcframework, metadata


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

    def test_platform_generated_header_metadata_can_differ(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64")
            changed = replace(build_metadata("macos-arm64"), header_manifest="different")
            arm64 = create_package(root, "macos-arm64", changed)
            inputs = prepare_macos_inputs(x64, arm64, root / "extract")
        self.assertEqual(inputs.arm64_metadata.header_manifest, "different")

    def test_composition_rejects_different_framework_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            x64 = create_package(root, "macos-x64", framework_header="x64")
            arm64 = create_package(root, "macos-arm64", framework_header="arm64")
            with self.assertRaisesRegex(CompositionError, "different public headers"):
                compose_macos_xcframework(
                    x64_archive=x64,
                    arm64_archive=arm64,
                    work_dir=root / "work",
                    output_dir=root / "dist",
                    builder_commit="a" * 40,
                    runner=object(),
                )


class ReleaseManifestTests(unittest.TestCase):
    def test_release_requires_platform_packages_android_aar_and_xcframework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = {
                target: create_package(root, target)
                for target in (
                    "android",
                    "ios",
                    "macos-x64",
                    "macos-arm64",
                    "windows-x64",
                )
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
                packages=packages,
                android_aar=create_android_aar(root),
                xcframework=xcframework,
                xcframework_metadata=xc_metadata,
                output_dir=root / "release",
                builder_commit="a" * 40,
                release_date="20260712",
                platform="all",
            )
            payload = json.loads(manifest.read_text())
        self.assertEqual(payload["tag"], "webrtc-m150.7871.3-aaaaaaa-20260712-all")
        self.assertEqual(len(payload["assets"]), 7)
        self.assertIn(
            "webrtc-m150-android-arm64-v8a.aar",
            {asset["name"] for asset in payload["assets"]},
        )

    def test_release_rejects_workflow_commit_different_from_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = {
                target: create_package(root, target)
                for target in (
                    "android",
                    "ios",
                    "macos-x64",
                    "macos-arm64",
                    "windows-x64",
                )
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
                        "artifact_digest": "sha256:" + "b" * 64,
                        "source": build_metadata("macos-x64").source,
                        "header_manifest": "same-headers",
                    }
                )
            )
            with self.assertRaisesRegex(CompositionError, "workflow builder commit"):
                create_release_manifest(
                    packages=packages,
                    android_aar=create_android_aar(root),
                    xcframework=xcframework,
                    xcframework_metadata=xc_metadata,
                    output_dir=root / "release",
                    builder_commit="b" * 40,
                    release_date="20260712",
                    platform="all",
                )


class PreviewReleaseManifestTests(unittest.TestCase):
    def test_preview_requires_bound_android_and_macos_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            android = create_package(root, "android")
            android_aar = create_android_aar(root)
            macos_x64 = create_package(root, "macos-x64")
            macos_arm64 = create_package(root, "macos-arm64")
            xcframework, xcframework_metadata = create_xcframework_inputs(root)
            android_evidence = root / "android-evidence.json"
            android_evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workflow_run_id": 123,
                        "builder_commit": "a" * 40,
                        "artifact_digest": "sha256:" + "b" * 64,
                        "aar_sha256": sha256(android_aar),
                        "android_api_level": 31,
                        "abi": "arm64-v8a",
                        "marker": "AAR_SMOKE_OK",
                    }
                )
            )
            macos_evidence = root / "macos-evidence.json"
            macos_evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "xcframework_zip_sha256": sha256(xcframework),
                        "hardware_model": "Mac16,7",
                        "os_version": "26.5.2",
                        "macos_x64_hardware_runtime_verified": False,
                        "modes": [
                            {
                                "mode": "normal",
                                "session_status": "success",
                                "encoder_id": "com.apple.videotoolbox.videoencoder.ave.avc",
                                "sps_profile": "BASELINE",
                                "profile_mismatch": False,
                            },
                            {
                                "mode": "low_latency",
                                "session_status": "success",
                                "encoder_id": "com.apple.videotoolbox.videoencoder.h264.rtvc",
                                "sps_profile": "HIGH",
                                "profile_mismatch": False,
                            },
                        ],
                    }
                )
            )

            manifest = create_preview_release_manifest(
                android_package=android,
                android_aar=android_aar,
                macos_x64_package=macos_x64,
                macos_arm64_package=macos_arm64,
                xcframework=xcframework,
                xcframework_metadata=xcframework_metadata,
                android_smoke_evidence=android_evidence,
                macos_probe_evidence=macos_evidence,
                output_dir=root / "preview",
                builder_commit="a" * 40,
                android_workflow_run_id=123,
                android_artifact_digest="sha256:" + "b" * 64,
                release_date="20260714",
                preview_revision=1,
            )
            payload = json.loads(manifest.read_text())

        self.assertEqual(
            payload["tag"],
            "webrtc-m150.7871.3-aaaaaaa-20260714-macos-android-preview.1",
        )
        self.assertEqual(
            {asset["name"] for asset in payload["assets"]},
            {
                "webrtc-m150-android-arm64-v8a.tar.gz",
                "webrtc-m150-android-arm64-v8a.aar",
                "webrtc-m150-macos-x64.tar.gz",
                "webrtc-m150-macos-arm64.tar.gz",
                "WebRTC-m150-macos-universal.xcframework.zip",
            },
        )
        self.assertFalse(
            payload["verification"]["macos_x64_hardware_runtime_verified"]
        )

    def test_preview_rejects_evidence_for_different_aar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            android_aar = create_android_aar(root)
            xcframework, xcframework_metadata = create_xcframework_inputs(root)
            android_evidence = root / "android-evidence.json"
            android_evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workflow_run_id": 123,
                        "builder_commit": "a" * 40,
                        "artifact_digest": "sha256:" + "b" * 64,
                        "aar_sha256": "0" * 64,
                        "android_api_level": 31,
                        "abi": "arm64-v8a",
                        "marker": "AAR_SMOKE_OK",
                    }
                )
            )
            macos_evidence = root / "macos-evidence.json"
            macos_evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "xcframework_zip_sha256": sha256(xcframework),
                        "hardware_model": "Mac16,7",
                        "os_version": "26.5.2",
                        "macos_x64_hardware_runtime_verified": False,
                        "modes": [
                            {"mode": "normal", "session_status": "success"},
                            {
                                "mode": "low_latency",
                                "session_status": "success",
                                "encoder_id": "h264.rtvc",
                            },
                        ],
                    }
                )
            )
            with self.assertRaisesRegex(CompositionError, "AAR SHA"):
                create_preview_release_manifest(
                    android_package=create_package(root, "android"),
                    android_aar=android_aar,
                    macos_x64_package=create_package(root, "macos-x64"),
                    macos_arm64_package=create_package(root, "macos-arm64"),
                    xcframework=xcframework,
                    xcframework_metadata=xcframework_metadata,
                    android_smoke_evidence=android_evidence,
                    macos_probe_evidence=macos_evidence,
                    output_dir=root / "preview",
                    builder_commit="a" * 40,
                    android_workflow_run_id=123,
                    android_artifact_digest="sha256:" + "b" * 64,
                    release_date="20260714",
                    preview_revision=1,
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
                    packages=packages,
                    android_aar=create_android_aar(root),
                    xcframework=xcframework,
                    xcframework_metadata=xc_metadata,
                    output_dir=root / "release",
                    builder_commit="a" * 40,
                    release_date="20260712",
                    platform="all",
                )


if __name__ == "__main__":
    unittest.main()
