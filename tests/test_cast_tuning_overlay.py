import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "overlays" / "m150" / "common" / "api" / "cast_tuning"


class CastTuningNativeContractTests(unittest.TestCase):
    def test_h264_hook_patch_applies_to_exact_m150_source(self) -> None:
        relative = Path("sdk/objc/components/video_codec/RTCVideoEncoderH264.mm")
        cached_source = ROOT / "references" / "M150" / "upstream" / relative
        self.assertTrue(cached_source.is_file())
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            destination = checkout / relative
            destination.parent.mkdir(parents=True)
            shutil.copy2(cached_source, destination)
            subprocess.run(
                [
                    "git",
                    "apply",
                    f"--include={relative.as_posix()}",
                    str(ROOT / "patches" / "m150" / "cast_tuning_hooks.patch"),
                ],
                cwd=checkout,
                check=True,
                text=True,
                capture_output=True,
            )
            transformed = destination.read_text()
        self.assertIn("encoder_runtime_qp_provider", transformed)
        self.assertIn("VTSessionCopySupportedPropertyDictionary", transformed)
        self.assertIn("kVTCompressionPropertyKey_MaxAllowedFrameQP", transformed)
        self.assertIn("VTSessionCopyProperty", transformed)
        self.assertIn("encoder_runtime_qp_result_handler", transformed)
        self.assertIn("encoder_runtime_qp_applied", transformed)
        self.assertIn("encoder_qp_sample", transformed)
        self.assertIn("resetCompressionSessionForRuntimeMaxQpIfNeeded", transformed)
        self.assertIn("encoderSessionId:encodeParams->encoder_session_id", transformed)

    def test_h265_hook_patch_applies_to_exact_m150_source(self) -> None:
        relative_paths = [
            Path("sdk/objc/components/video_codec/RTCVideoEncoderH265.h"),
            Path("sdk/objc/components/video_codec/RTCVideoEncoderH265.mm"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            subprocess.run(
                [
                    "git",
                    "apply",
                    *[f"--include={path.as_posix()}" for path in relative_paths],
                    str(ROOT / "patches" / "m150" / "h265_ios.patch"),
                ],
                cwd=checkout,
                check=True,
                text=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "apply",
                    *[f"--include={path.as_posix()}" for path in relative_paths],
                    str(
                        ROOT
                        / "patches"
                        / "m150"
                        / "macos_hevc_cast_tuning.patch"
                    ),
                ],
                cwd=checkout,
                check=True,
                text=True,
                capture_output=True,
            )
            header = (checkout / relative_paths[0]).read_text()
            implementation = (checkout / relative_paths[1]).read_text()

        self.assertIn("castTuningOptions", header)
        self.assertIn("kVTVideoEncoderSpecification_EnableLowLatencyRateControl", implementation)
        self.assertIn("kVTCompressionPropertyKey_SpatialAdaptiveQPLevel", implementation)
        self.assertIn("encoder_spatial_adaptive_qp_applied", implementation)
        self.assertIn('event_type" : @"encoder_session_properties', implementation)
        self.assertIn('effective_realtime', implementation)
        self.assertIn('effective_allow_frame_reordering', implementation)
        self.assertIn("kVTCompressionPropertyKey_MaxAllowedFrameQP", implementation)
        self.assertIn("VTSessionCopyProperty", implementation)
        self.assertIn("resetCompressionSessionForRuntimeMaxQpIfNeeded", implementation)
        self.assertIn("qp.value_or(-1)", implementation)
        self.assertIn('event[@"codec_name"] = @"H265"', implementation)

    def test_native_contract_tests_use_platform_neutral_paths(self) -> None:
        platform_absolute_path = re.compile(r'"(?:/|[A-Za-z]:[\\/]|\\\\)')
        violations: list[str] = []
        for path in sorted(CORE.glob("*test.cc")):
            for line_number, line in enumerate(path.read_text().splitlines(), start=1):
                if platform_absolute_path.search(line):
                    violations.append(f"{path.name}:{line_number}: {line.strip()}")
        self.assertEqual(violations, [])

    def test_example_profiles_are_valid_json(self) -> None:
        for path in (ROOT / "examples").glob("*.json"):
            with self.subTest(path=path.name):
                json.loads(path.read_text())

    def test_macos_factory_hook_does_not_pull_software_codec_factory(self) -> None:
        patch = (ROOT / "patches" / "m150" / "cast_tuning_hooks.patch").read_text()
        self.assertNotIn('":default_codec_factory_objc"', patch)
        self.assertIn('":videotoolbox_objc"', patch)
        objc = (
            ROOT
            / "overlays"
            / "m150"
            / "macos"
            / "sdk"
            / "objc"
            / "api"
            / "peerconnection"
            / "RTCCastTuning.mm"
        ).read_text()
        self.assertNotIn("RTCDefaultVideoEncoderFactory", objc)

    def test_native_validation_target_is_reachable_without_rtc_tests(self) -> None:
        root_patch = (ROOT / "patches" / "m150" / "cast_tuning_hooks.patch").read_text()
        build = (CORE / "BUILD.gn").read_text()
        self.assertIn('"api/cast_tuning:cast_tuning_native_tests"', root_patch)
        self.assertNotIn("testonly = true", build)

    def test_macos_exposes_per_factory_live_max_qp_control(self) -> None:
        objc_root = (
            ROOT
            / "overlays"
            / "m150"
            / "macos"
            / "sdk"
            / "objc"
            / "api"
            / "peerconnection"
        )
        header = (objc_root / "RTCCastTuning.h").read_text()
        implementation = (objc_root / "RTCCastTuning.mm").read_text()

        self.assertIn("NSNumber *maxQp", header)
        self.assertIn("NSNumber *requestedMaxQp", header)
        self.assertIn("NSNumber *effectiveMaxQp", header)
        self.assertIn("NSString *maxQpApplyState", header)
        self.assertIn("NSNumber *lastEncodedQp", header)
        self.assertIn("NSNumber *lastKeyFrameQp", header)
        self.assertIn("NSNumber *lastKeyFrameBytes", header)
        self.assertIn("NSString *maxQpAppliedEncoderSessionId", header)
        self.assertIn("uint64_t lastQpSampleGeneration", header)
        self.assertIn("NSString *lastQpSampleEncoderSessionId", header)
        self.assertIn("RTCCastTuningEncoderRuntimeState", implementation)
        self.assertIn('options[@"encoder_runtime_qp_provider"]', implementation)
        self.assertIn(
            'options[@"encoder_runtime_qp_result_handler"]', implementation
        )
        self.assertIn("class ObjCEncoderRuntimeAdapter", implementation)
        self.assertIn("ApplyMaxQp", implementation)
        self.assertIn("_lastKeyFrameQp = nil", implementation)
        self.assertIn(
            "[eventEncoderSessionId isEqualToString:_appliedEncoderSessionId]",
            implementation,
        )

    def test_macos_exposes_hevc_cast_tuning(self) -> None:
        implementation = (
            ROOT
            / "overlays"
            / "m150"
            / "macos"
            / "sdk"
            / "objc"
            / "api"
            / "peerconnection"
            / "RTCCastTuning.mm"
        ).read_text()

        self.assertIn('components/video_codec/RTCVideoEncoderH265.h', implementation)
        self.assertIn('caseInsensitiveCompare:@"H265"', implementation)
        self.assertIn("RTCVideoEncoderH265) alloc", implementation)
        self.assertIn("castTuningOptions:_options", implementation)
        self.assertIn('@"video_toolbox_spatial_adaptive_qp"', implementation)

    def test_android_jni_handles_are_raw_jlong_parameters(self) -> None:
        source = (
            ROOT
            / "overlays"
            / "m150"
            / "android"
            / "sdk"
            / "android"
            / "api"
            / "org"
            / "webrtc"
            / "CastTuningController.java"
        ).read_text()
        self.assertNotRegex(source, re.compile(r"native\w+\(long nativeController"))
        self.assertGreaterEqual(source.count("long pointer"), 13)

    def test_config_profiles_validation_and_field_trials(self) -> None:
        if os.name == "nt":
            self.skipTest("standalone -pthread contract compile is validated by GN on Windows")
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("a C++ compiler is required for native contract tests")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "cast_tuning_config_test"
            command = [
                compiler,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                f"-I{ROOT / 'overlays' / 'm150' / 'common'}",
                str(CORE / "cast_tuning_config.cc"),
                str(CORE / "cast_tuning_controller.cc"),
                str(CORE / "cast_tuning_recovery.cc"),
                str(CORE / "cast_tuning_telemetry.cc"),
                str(CORE / "cast_tuning_config_unittest.cc"),
                "-o",
                str(executable),
            ]
            subprocess.run(command, check=True, text=True, capture_output=True)
            result = subprocess.run(
                [executable], check=True, text=True, capture_output=True
            )
        self.assertEqual(result.stdout, "CastTuning config tests passed\n")

    def test_android_configuration_sources_are_explicit_and_testable(self) -> None:
        javac = shutil.which("javac")
        java = shutil.which("java")
        if javac is None or java is None:
            self.skipTest("Java is unavailable on this runner")
        android = ROOT / "overlays" / "m150" / "android" / "sdk" / "android"
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [
                    javac,
                    "-d",
                    directory,
                    str(android / "api" / "org" / "webrtc" / "CastTuningConfig.java"),
                    str(
                        android
                        / "tests"
                        / "src"
                        / "org"
                        / "webrtc"
                        / "CastTuningConfigContractTest.java"
                    ),
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            result = subprocess.run(
                [java, "-cp", directory, "org.webrtc.CastTuningConfigContractTest"],
                check=True,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.stdout, "CastTuning Java tests passed\n")


if __name__ == "__main__":
    unittest.main()
