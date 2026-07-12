import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from builder.build import BuildUnit
from builder.config import get_target
from builder.package import (
    PackageError,
    create_tar_gz,
    header_manifest,
    package_filename,
    safe_extract_tar,
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


class PackageContractTests(unittest.TestCase):
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
                if command[0] == "llvm-ar":
                    return "peer_connection.o"
                if command[:2] == ("jar", "tf"):
                    return (
                        "org/webrtc/HardwareVideoEncoderFactory.class\n"
                        "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class\n"
                    )
                return ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root / "work")
            (workspace.src / "api").mkdir(parents=True)
            (workspace.src / "api" / "peer_connection_interface.h").write_text("header")
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
            )
            extracted = root / "extracted"
            safe_extract_tar(archive, extracted)
            package = extracted / "webrtc"
            self.assertTrue(archive.name.endswith("android-arm64-v8a.tar.gz"))
            self.assertEqual((package / "NOTICE").read_text(), "third-party notices")
            self.assertTrue((package / "metadata.json").is_file())
            self.assertTrue((package / "lib" / "arm64-v8a" / "libwebrtc.a").is_file())
            self.assertTrue((package / "jar" / "webrtc.jar").is_file())
            self.assertTrue(any(command[0] == "llvm-ar" for command in runner.capture_commands))


if __name__ == "__main__":
    unittest.main()
