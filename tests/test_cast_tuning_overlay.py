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
