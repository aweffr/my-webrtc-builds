import tempfile
import unittest
from pathlib import Path

from builder.verify import VerificationError, verify_binaries, verify_package_layout


def create_common_tree(root: Path) -> None:
    (root / "include" / "api").mkdir(parents=True)
    (root / "include" / "api" / "peer_connection_interface.h").write_text("header")
    tuning = root / "include" / "api" / "cast_tuning"
    tuning.mkdir()
    (tuning / "cast_tuning_config.h").write_text("header")
    for name in ("metadata.json", "LICENSE", "PATENTS", "AUTHORS", "NOTICE", "SHA256SUMS"):
        (root / name).write_text(name)


class PackageLayoutVerificationTests(unittest.TestCase):
    def test_android_requires_static_library_jar_and_jni_shared_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_common_tree(root)
            (root / "lib" / "arm64-v8a").mkdir(parents=True)
            (root / "lib" / "arm64-v8a" / "libwebrtc.a").write_bytes(b"archive")
            with self.assertRaisesRegex(VerificationError, "jar/webrtc.jar"):
                verify_package_layout("android", root)
            (root / "jar").mkdir()
            (root / "jar" / "webrtc.jar").write_bytes(b"jar")
            with self.assertRaisesRegex(VerificationError, "libjingle_peerconnection_so.so"):
                verify_package_layout("android", root)
            (root / "jni" / "arm64-v8a").mkdir(parents=True)
            (root / "jni" / "arm64-v8a" / "libjingle_peerconnection_so.so").write_bytes(
                b"shared"
            )
            verify_package_layout("android", root)

    def test_ios_requires_separate_device_and_simulator_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_common_tree(root)
            (root / "lib" / "device-arm64").mkdir(parents=True)
            (root / "lib" / "device-arm64" / "libwebrtc.a").write_bytes(b"archive")
            with self.assertRaisesRegex(VerificationError, "simulator-arm64"):
                verify_package_layout("ios", root)

    def test_macos_requires_both_static_library_and_framework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_common_tree(root)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            with self.assertRaisesRegex(VerificationError, "WebRTC.framework"):
                verify_package_layout("macos-arm64", root)
            headers = root / "Frameworks" / "WebRTC.framework" / "Headers"
            headers.mkdir(parents=True)
            with self.assertRaisesRegex(VerificationError, "RTCVideoEncoderH265.h"):
                verify_package_layout("macos-arm64", root)
            (headers / "RTCVideoEncoderH265.h").write_text("encoder")
            (headers / "RTCVideoDecoderH265.h").write_text("decoder")
            with self.assertRaisesRegex(VerificationError, "RTCCastTuning.h"):
                verify_package_layout("macos-arm64", root)
            (headers / "RTCCastTuning.h").write_text("cast tuning")
            verify_package_layout("macos-arm64", root)

    def test_macos_requires_public_cast_tuning_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_common_tree(root)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            framework = root / "Frameworks" / "WebRTC.framework"
            framework.mkdir(parents=True)
            headers = framework / "Headers"
            headers.mkdir()
            (headers / "RTCVideoEncoderH265.h").write_text("encoder")
            (headers / "RTCVideoDecoderH265.h").write_text("decoder")
            with self.assertRaisesRegex(VerificationError, "RTCCastTuning.h"):
                verify_package_layout("macos-arm64", root)

    def test_windows_requires_library_and_cast_tuning_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_common_tree(root)
            (root / "lib").mkdir()
            with self.assertRaisesRegex(VerificationError, "lib/webrtc.lib"):
                verify_package_layout("windows-x64", root)
            (root / "lib" / "webrtc.lib").write_bytes(b"archive")
            tuning = root / "include" / "api" / "cast_tuning" / "cast_tuning_config.h"
            tuning.unlink()
            with self.assertRaisesRegex(VerificationError, "cast_tuning_config.h"):
                verify_package_layout("windows-x64", root)


class FakeRunner:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def capture(self, argv, *, cwd=None, env=None) -> str:
        command = tuple(map(str, argv))
        self.commands.append(command)
        normalized = command[0].replace("\\", "/")
        basename = normalized.rsplit("/", maxsplit=1)[-1]
        normalized_responses = {
            key.replace("\\", "/"): value for key, value in self.responses.items()
        }
        return self.responses.get(
            command[0],
            normalized_responses.get(
                normalized, normalized_responses.get(basename, "")
            ),
        )


class BinaryVerificationTests(unittest.TestCase):
    def test_android_can_use_hermetic_archiver(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib" / "arm64-v8a").mkdir(parents=True)
            (root / "lib" / "arm64-v8a" / "libwebrtc.a").write_bytes(b"archive")
            (root / "jar").mkdir()
            (root / "jar" / "webrtc.jar").write_bytes(b"jar")
            (root / "jni" / "arm64-v8a").mkdir(parents=True)
            (root / "jni" / "arm64-v8a" / "libjingle_peerconnection_so.so").write_bytes(
                b"shared"
            )
            runner = FakeRunner(
                {
                    "/checkout/llvm-ar": "peer_connection.o",
                    "llvm-readelf": "Class: ELF64\nMachine: AArch64",
                    "llvm-nm": "0000000000000000 T JNI_OnLoad",
                    "jar": (
                        "org/webrtc/CastTuningAndroidConfig.class\n"
                        "org/webrtc/CastTuningConfig.class\n"
                        "org/webrtc/CastTuningController.class\n"
                        "org/webrtc/CastTuningSnapshot.class\n"
                        "org/webrtc/CastTuningVideoDecoderFactory.class\n"
                        "org/webrtc/HardwareVideoEncoderFactory.class\n"
                        "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class\n"
                    ),
                    "javap": (
                        "configureFactory configurePeerConnection attachReceiver "
                        "createVideoDecoderFactory snapshot"
                    ),
                }
            )
            verify_binaries(
                "android",
                root,
                runner,
                android_archiver=Path("/checkout/llvm-ar"),
            )
        self.assertEqual(
            runner.commands[0][0].replace("\\", "/"), "/checkout/llvm-ar"
        )
        self.assertTrue(
            any(command[0] == "llvm-readelf" for command in runner.commands)
        )
        self.assertTrue(
            any(command[0] == "llvm-nm" for command in runner.commands)
        )

    def test_android_missing_cast_tuning_class_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib" / "arm64-v8a").mkdir(parents=True)
            (root / "lib" / "arm64-v8a" / "libwebrtc.a").write_bytes(b"archive")
            (root / "jar").mkdir()
            (root / "jar" / "webrtc.jar").write_bytes(b"jar")
            runner = FakeRunner(
                {
                    "llvm-ar": "peer_connection.o",
                    "llvm-readelf": "Class: ELF64\nMachine: AArch64",
                    "llvm-nm": "0000000000000000 T JNI_OnLoad",
                    "jar": (
                        "org/webrtc/HardwareVideoEncoderFactory.class\n"
                        "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class\n"
                    ),
                    "javap": "",
                }
            )
            with self.assertRaisesRegex(VerificationError, "CastTuning"):
                verify_binaries("android", root, runner)

    def test_android_missing_cast_tuning_method_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib" / "arm64-v8a").mkdir(parents=True)
            (root / "lib" / "arm64-v8a" / "libwebrtc.a").write_bytes(b"archive")
            (root / "jar").mkdir()
            (root / "jar" / "webrtc.jar").write_bytes(b"jar")
            runner = FakeRunner(
                {
                    "llvm-ar": "peer_connection.o",
                    "llvm-readelf": "Class: ELF64\nMachine: AArch64",
                    "llvm-nm": "0000000000000000 T JNI_OnLoad",
                    "jar": (
                        "org/webrtc/CastTuningAndroidConfig.class\n"
                        "org/webrtc/CastTuningConfig.class\n"
                        "org/webrtc/CastTuningController.class\n"
                        "org/webrtc/CastTuningSnapshot.class\n"
                        "org/webrtc/CastTuningVideoDecoderFactory.class\n"
                        "org/webrtc/HardwareVideoEncoderFactory.class\n"
                        "org/webrtc/VideoEncoder$CodecSpecificInfoH265.class\n"
                    ),
                    "javap": "configureFactory configurePeerConnection attachReceiver snapshot",
                }
            )
            with self.assertRaisesRegex(VerificationError, "createVideoDecoderFactory"):
                verify_binaries("android", root, runner)

    def test_macos_checks_archives_framework_arch_and_codec_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            framework = root / "Frameworks" / "WebRTC.framework" / "Versions" / "A"
            framework.mkdir(parents=True)
            (framework / "WebRTC").write_bytes(b"framework")
            runner = FakeRunner(
                {
                    "/usr/bin/ar": "peer_connection.o",
                    "lipo": "arm64",
                    "nm": (
                        "H264EncoderImpl H264DecoderImpl RTCVideoEncoderH265 "
                        "RTCVideoDecoderH265 RTCCastTuningController "
                        "kVTVideoEncoderSpecification_EnableLowLatencyRateControl"
                    ),
                }
            )
            verify_binaries("macos-arm64", root, runner)
        self.assertTrue(any(command[0] == "lipo" for command in runner.commands))
        self.assertTrue(any(command[0] == "nm" for command in runner.commands))

    def test_macos_missing_software_h264_symbol_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            framework = root / "Frameworks" / "WebRTC.framework"
            framework.mkdir(parents=True)
            (framework / "WebRTC").write_bytes(b"framework")
            runner = FakeRunner(
                {
                    "/usr/bin/ar": "peer_connection.o",
                    "lipo": "arm64",
                    "nm": "RTCVideoEncoderH265 RTCVideoDecoderH265",
                }
            )
            with self.assertRaisesRegex(VerificationError, "H264EncoderImpl"):
                verify_binaries("macos-arm64", root, runner)

    def test_macos_missing_cast_tuning_symbol_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            framework = root / "Frameworks" / "WebRTC.framework"
            framework.mkdir(parents=True)
            (framework / "WebRTC").write_bytes(b"framework")
            runner = FakeRunner(
                {
                    "/usr/bin/ar": "peer_connection.o",
                    "lipo": "arm64",
                    "nm": (
                        "H264EncoderImpl H264DecoderImpl RTCVideoEncoderH265 "
                        "RTCVideoDecoderH265"
                    ),
                }
            )
            with self.assertRaisesRegex(VerificationError, "RTCCastTuningController"):
                verify_binaries("macos-arm64", root, runner)

    def test_macos_missing_low_latency_rate_control_symbol_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "libwebrtc.a").write_bytes(b"archive")
            framework = root / "Frameworks" / "WebRTC.framework"
            framework.mkdir(parents=True)
            (framework / "WebRTC").write_bytes(b"framework")
            runner = FakeRunner(
                {
                    "/usr/bin/ar": "peer_connection.o",
                    "lipo": "arm64",
                    "nm": (
                        "H264EncoderImpl H264DecoderImpl RTCVideoEncoderH265 "
                        "RTCVideoDecoderH265 RTCCastTuningController"
                    ),
                }
            )
            with self.assertRaisesRegex(
                VerificationError, "EnableLowLatencyRateControl"
            ):
                verify_binaries("macos-arm64", root, runner)

    def test_windows_checks_coff_architecture_and_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            library = root / "lib" / "webrtc.lib"
            library.write_bytes(b"archive")
            runner = FakeRunner(
                {
                    "dumpbin.exe": (
                        "FILE HEADER VALUES\n"
                        "             8664 machine (x64)\n"
                        "LINKER MEMBERS\n"
                        "H264EncoderImpl H264DecoderImpl "
                        "?run@CastTuningController@cast_tuning@webrtc@@SAXXZ"
                    ),
                }
            )
            verify_binaries("windows-x64", root, runner)
        self.assertTrue(any(command[0].endswith("dumpbin.exe") for command in runner.commands))
        self.assertTrue(any("/headers" in command for command in runner.commands))
        self.assertTrue(any("/linkermember:2" in command for command in runner.commands))
        self.assertFalse(any(command[0].endswith("llvm-lib.exe") for command in runner.commands))

    def test_windows_rejects_wrong_coff_architecture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "webrtc.lib").write_bytes(b"archive")
            runner = FakeRunner(
                {
                    "dumpbin.exe": (
                        "FILE HEADER VALUES\n"
                        "             14c machine (x86)\n"
                        "LINKER MEMBERS\n"
                    ),
                }
            )
            with self.assertRaisesRegex(VerificationError, "AMD64"):
                verify_binaries("windows-x64", root, runner)

    def test_windows_rejects_cast_tuning_symbol_from_wrong_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lib").mkdir()
            (root / "lib" / "webrtc.lib").write_bytes(b"archive")
            runner = FakeRunner(
                {
                    "dumpbin.exe": (
                        "FILE HEADER VALUES\n"
                        "             8664 machine (x64)\n"
                        "LINKER MEMBERS\n"
                        "H264EncoderImpl H264DecoderImpl "
                        "?run@CastTuningController@other_namespace@@SAXXZ"
                    ),
                }
            )
            with self.assertRaisesRegex(VerificationError, "CastTuningController"):
                verify_binaries("windows-x64", root, runner)


if __name__ == "__main__":
    unittest.main()
