import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "overlays" / "m150" / "common" / "api" / "cast_tuning"


class CastTuningNativeContractTests(unittest.TestCase):
    def test_config_profiles_validation_and_field_trials(self) -> None:
        compiler = shutil.which("clang++") or shutil.which("g++")
        self.assertIsNotNone(compiler, "a C++ compiler is required for native contract tests")
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
        self.assertIsNotNone(javac, "javac is required for Java contract tests")
        self.assertIsNotNone(java, "java is required for Java contract tests")
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
