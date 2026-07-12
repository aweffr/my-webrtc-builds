import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from builder.build import BuildUnit
from builder.config import get_target
from builder.metadata import load_metadata
from builder.package import (
    PackageError,
    create_tar_gz,
    create_zip,
    header_manifest,
    package_filename,
    safe_extract_tar,
    safe_extract_zip,
    stage_and_package,
    write_checksums,
)
from builder.source import Workspace


class HeaderManifestTests(unittest.TestCase):
    def test_manifest_depends_on_relative_path_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            include = Path(directory)
            (include / "api").mkdir()
            header = include / "api" / "peer_connection.h"
            header.write_text("first")
            first = header_manifest(include)
            header.write_text("second")
            second = header_manifest(include)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, second)


class ArchiveSafetyTests(unittest.TestCase):
    def test_tar_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory, "malicious.tar.gz")
            with tarfile.open(archive, "w:gz") as stream:
                info = tarfile.TarInfo("../escaped")
                info.size = 3
                stream.addfile(info, io.BytesIO(b"bad"))
            with self.assertRaisesRegex(PackageError, "unsafe archive path"):
                safe_extract_tar(archive, Path(directory, "output"))

    def test_archive_preserves_framework_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "root")
            root.mkdir()
            (root / "Versions").mkdir()
            (root / "Versions" / "A").mkdir()
            (root / "Versions" / "A" / "WebRTC").write_bytes(b"binary")
            (root / "WebRTC").symlink_to("Versions/A/WebRTC")
            archive = Path(directory, "framework.tar.gz")
            create_tar_gz(root, archive, arcname="webrtc")
            extracted = Path(directory, "extracted")
            safe_extract_tar(archive, extracted)
            self.assertTrue((extracted / "webrtc" / "WebRTC").is_symlink())

    def test_zip_path_traversal_and_drive_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                stream.writestr("../escaped", "bad")
                stream.writestr("C:/absolute", "bad")
            with self.assertRaisesRegex(PackageError, "unsafe archive path"):
                safe_extract_zip(archive, root / "output")

    def test_zip_round_trip_uses_webrtc_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "stage"
            source.mkdir()
            (source / "metadata.json").write_text("{}")
            archive = root / "package.zip"
            create_zip(source, archive, arcname="webrtc")
            extracted = root / "extracted"
            safe_extract_zip(archive, extracted)
            self.assertEqual((extracted / "webrtc" / "metadata.json").read_text(), "{}")


class PackageContractTests(unittest.TestCase):
    def test_cast_tuning_target_requires_overlay_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root / "work")
            with self.assertRaisesRegex(PackageError, "overlay directory"):
                stage_and_package(
                    get_target("android"),
                    workspace,
                    (),
                    root / "dist",
                    root / "patches",
                    "a" * 40,
                    {},
                    object(),
                )

    def test_fixed_package_filenames(self) -> None:
        self.assertEqual(
            package_filename("android"),
            "webrtc-m150-android-arm64-v8a.tar.gz",
        )
        self.assertEqual(package_filename("ios"), "webrtc-m150-ios.tar.gz")
        self.assertEqual(package_filename("macos-x64"), "webrtc-m150-macos-x64.tar.gz")
        self.assertEqual(
            package_filename("macos-arm64"),
            "webrtc-m150-macos-arm64.tar.gz",
        )
        self.assertEqual(
            package_filename("windows-x64"),
            "webrtc-m150-windows-x64.zip",
        )

    def test_checksums_cover_payload_but_not_checksum_file_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("a")
            (root / "nested").mkdir()
            (root / "nested" / "b.txt").write_text("b")
            checksum_path = write_checksums(root)
            lines = checksum_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("  a.txt"))
        self.assertTrue(lines[1].endswith("  nested/b.txt"))
        self.assertFalse(any("SHA256SUMS" in line for line in lines))

    def test_android_stage_contains_library_jar_metadata_and_notices(self) -> None:
        class LicenseRunner:
            def __init__(self) -> None:
                self.capture_commands: list[tuple[str, ...]] = []

            def run(self, argv, *, cwd=None, env=None) -> None:
                stage = Path(argv[-2])
                stage.joinpath("LICENSE.md").write_text("third-party notices")

            def capture(self, argv, *, cwd=None, env=None) -> str:
                command = tuple(map(str, argv))
                self.capture_commands.append(command)
                if command[0].replace("\\", "/").endswith("/llvm-ar"):
                    return "peer_connection.o"
                if command[:2] == ("jar", "tf"):
                    return (
                        "org/webrtc/CastTuningAndroidConfig.class\n"
                        "org/webrtc/CastTuningConfig.class\n"
                        "org/webrtc/CastTuningController.class\n"
                        "org/webrtc/CastTuningSnapshot.class\n"
                        "org/webrtc/CastTuningVideoDecoderFactory.class\n"
                        "org/webrtc/HardwareVideoEncoderFactory.class\n"
                        "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class\n"
                    )
                if command[0] == "javap":
                    return (
                        "configureFactory configurePeerConnection attachReceiver "
                        "createVideoDecoderFactory snapshot"
                    )
                return ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root / "work")
            (workspace.src / "api").mkdir(parents=True)
            (workspace.src / "api" / "peer_connection_interface.h").write_text("header")
            tuning = workspace.src / "api" / "cast_tuning"
            tuning.mkdir()
            (tuning / "cast_tuning_config.h").write_text("header")
            for name in ("LICENSE", "PATENTS", "AUTHORS"):
                (workspace.src / name).write_text(name)
            output = workspace.out / "android" / "arm64-v8a"
            (output / "lib.java" / "sdk" / "android").mkdir(parents=True)
            (output / "libwebrtc.a").write_bytes(b"archive")
            (output / "lib.java" / "sdk" / "android" / "libwebrtc.jar").write_bytes(b"jar")
            (output / "gn-args.txt").write_text("is_debug = false\n")
            patch_dir = root / "patches"
            patch_dir.mkdir()
            target = get_target("android")
            for name in target.patches:
                (patch_dir / name).write_text(name)
            overlay_dir = root / "overlays"
            for group in target.overlays:
                source = overlay_dir / group / group / "cast_tuning.h"
                source.parent.mkdir(parents=True)
                source.write_text(group)
            unit = BuildUnit("arm64-v8a", output, target.gn_args_for("arm64-v8a"))

            runner = LicenseRunner()
            archive = stage_and_package(
                target,
                workspace,
                (unit,),
                root / "dist",
                patch_dir,
                "a" * 40,
                {"python": "3.11"},
                runner,
                overlay_dir=overlay_dir,
            )
            extracted = root / "extracted"
            safe_extract_tar(archive, extracted)
            package = extracted / "webrtc"
            self.assertTrue(archive.name.endswith("android-arm64-v8a.tar.gz"))
            self.assertEqual((package / "NOTICE").read_text(), "third-party notices")
            self.assertTrue((package / "metadata.json").is_file())
            self.assertTrue((package / "lib" / "arm64-v8a" / "libwebrtc.a").is_file())
            self.assertTrue((package / "jar" / "webrtc.jar").is_file())
            metadata = load_metadata(package / "metadata.json")
            self.assertEqual(
                set(metadata.overlay_hashes),
                {"common/cast_tuning.h", "android/cast_tuning.h"},
            )
            self.assertTrue(
                any(
                    command[0].replace("\\", "/").endswith("/llvm-ar")
                    for command in runner.capture_commands
                )
            )

    def test_windows_stage_contains_coff_library_and_zip_payload(self) -> None:
        class WindowsLicenseRunner:
            def __init__(self) -> None:
                self.capture_commands: list[tuple[str, ...]] = []

            def run(self, argv, *, cwd=None, env=None) -> None:
                Path(argv[-2]).joinpath("LICENSE.md").write_text("third-party notices")

            def capture(self, argv, *, cwd=None, env=None) -> str:
                command = tuple(map(str, argv))
                self.capture_commands.append(command)
                if command[0].endswith("llvm-lib.exe"):
                    return "webrtc.obj"
                if command[0].endswith("llvm-readobj.exe"):
                    return "Machine: IMAGE_FILE_MACHINE_AMD64 (0x8664)"
                if command[0].endswith("llvm-nm.exe"):
                    return (
                        "H264EncoderImpl H264DecoderImpl "
                        "webrtc::cast_tuning::CastTuningController"
                    )
                return ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root / "work")
            (workspace.src / "api").mkdir(parents=True)
            (workspace.src / "api" / "peer_connection_interface.h").write_text("header")
            tuning = workspace.src / "api" / "cast_tuning"
            tuning.mkdir()
            (tuning / "cast_tuning_config.h").write_text("header")
            (tuning / "extra.h").write_text("common")
            for name in ("LICENSE", "PATENTS", "AUTHORS"):
                (workspace.src / name).write_text(name)
            output = workspace.out / "windows-x64" / "x64"
            output.mkdir(parents=True)
            (output / "webrtc.lib").write_bytes(b"archive")
            (output / "gn-args.txt").write_text("target_os = win\n")
            patch_dir = root / "patches"
            patch_dir.mkdir()
            target = get_target("windows-x64")
            for name in target.patches:
                (patch_dir / name).write_text(name)
            overlay_dir = root / "overlays"
            source = overlay_dir / "common" / "api" / "cast_tuning" / "extra.h"
            source.parent.mkdir(parents=True)
            source.write_text("common")
            unit = BuildUnit("x64", output, target.gn_args_for("x64"))

            archive = stage_and_package(
                target,
                workspace,
                (unit,),
                root / "dist",
                patch_dir,
                "a" * 40,
                {"python": "3.11"},
                WindowsLicenseRunner(),
                overlay_dir=overlay_dir,
            )
            extracted = root / "extracted"
            safe_extract_zip(archive, extracted)
            package = extracted / "webrtc"
            self.assertEqual(archive.name, "webrtc-m150-windows-x64.zip")
            self.assertEqual((package / "NOTICE").read_text(), "third-party notices")
            self.assertTrue((package / "lib" / "webrtc.lib").is_file())
            self.assertTrue((package / "include" / "api" / "cast_tuning" / "extra.h").is_file())


if __name__ == "__main__":
    unittest.main()
