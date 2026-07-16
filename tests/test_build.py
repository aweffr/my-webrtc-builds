import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from builder.build import BuildError, _archive_objects, build_units, build_webrtc
from builder.config import DEPOT_TOOLS_COMMIT, SOURCE_VERSION, get_target
from builder.source import (
    Workspace,
    apply_overlays,
    overlay_manifest,
    prepare_source,
)


VALID_PATCH = """\
diff --git a/a b/a
--- a/a
+++ b/a
@@ -0,0 +1 @@
+placeholder
"""


def write_valid_patches(patch_dir: Path, names: tuple[str, ...]) -> None:
    for name in names:
        (patch_dir / name).write_text(VALID_PATCH)


class FakeRunner:
    def __init__(self, *, commit: str = SOURCE_VERSION.commit) -> None:
        self.calls: list[tuple[str, tuple[str, ...], Path | None]] = []
        self.commit = commit

    def run(self, argv, *, cwd=None, env=None) -> None:
        self.calls.append(("run", tuple(map(str, argv)), cwd))
        if argv and argv[0] == "ninja":
            output_dir = Path(argv[2])
            object_dir = output_dir / "obj"
            object_dir.mkdir(parents=True, exist_ok=True)
            (object_dir / "dummy.o").write_bytes(b"object")

    def capture(self, argv, *, cwd=None, env=None) -> str:
        self.calls.append(("capture", tuple(map(str, argv)), cwd))
        if tuple(argv[:3]) == ("git", "rev-parse", "HEAD"):
            if cwd is not None and Path(cwd).name == "depot_tools":
                return DEPOT_TOOLS_COMMIT
            return self.commit
        if tuple(argv[:3]) == ("gn", "args", "--list"):
            return "is_debug = false"
        if argv and str(argv[0]).endswith("llvm-ar") and argv[1] == "t":
            archive_call = next(
                call[1]
                for call in reversed(self.calls[:-1])
                if call[1][0].endswith("llvm-ar") and call[1][1] == "rcs"
            )
            return "\n".join(
                Path(line.strip('"')).name
                for line in Path(archive_call[3].removeprefix("@")).read_text().splitlines()
            )
        return ""


class SourcePreparationTests(unittest.TestCase):
    def test_depot_tools_cannot_self_update_after_snapshot_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = Workspace(Path(directory)).environment()
        self.assertEqual(environment.get("DEPOT_TOOLS_UPDATE"), "0")

    def test_windows_environment_uses_snapshot_gn_ninja_and_long_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            target = get_target("windows-x64")
            environment = workspace.environment(target)
            gn = workspace.tool("gn", target)
            ninja = workspace.tool("ninja", target)
        self.assertTrue(str(gn).endswith("gn.bat"))
        self.assertTrue(str(ninja).endswith("ninja.bat"))
        self.assertIn("DEPOT_TOOLS_WIN_TOOLCHAIN", environment)
        self.assertEqual(environment["DEPOT_TOOLS_WIN_TOOLCHAIN"], "0")
        self.assertEqual(environment["GIT_CONFIG_KEY_0"], "core.longpaths")
        self.assertEqual(environment["GIT_CONFIG_VALUE_0"], "true")
        self.assertIn(";", environment["PATH"])

    def test_source_acquisition_tools_are_not_available_to_builds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            for name in ("fetch", "gclient", "bootstrap_python3"):
                with self.subTest(name=name), self.assertRaisesRegex(BuildError, "not permitted"):
                    workspace.tool(name, get_target("android"))

    def test_malformed_patch_is_rejected_before_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = get_target("windows-x64")
            patch_dir = root / "patches"
            patch_dir.mkdir()
            write_valid_patches(patch_dir, target.patches)
            (patch_dir / target.patches[0]).write_text("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@\n")

            runner = FakeRunner()
            with self.assertRaisesRegex(BuildError, "invalid unified diff hunk header"):
                prepare_source(target, Workspace(root / "work"), patch_dir, runner)
            self.assertEqual(runner.calls, [])

    def test_overlay_manifest_is_deterministic_and_apply_rejects_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay = root / "overlays"
            common_header = overlay / "common" / "api" / "cast_tuning" / "config.h"
            android_source = overlay / "android" / "sdk" / "android" / "CastTuning.java"
            common_header.parent.mkdir(parents=True)
            android_source.parent.mkdir(parents=True)
            common_header.write_text("common")
            android_source.write_text("android")
            workspace = Workspace(root / "work")
            workspace.src.mkdir(parents=True)

            manifest = overlay_manifest(get_target("android"), overlay)
            self.assertEqual(
                set(manifest),
                {"api/cast_tuning/config.h", "sdk/android/CastTuning.java"},
            )
            self.assertTrue(all(len(digest) == 64 for digest in manifest.values()))

            apply_overlays(get_target("android"), workspace, overlay)
            self.assertEqual(
                (workspace.src / "api" / "cast_tuning" / "config.h").read_text(),
                "common",
            )
            with self.assertRaisesRegex(BuildError, "overlay destination already exists"):
                apply_overlays(get_target("android"), workspace, overlay)

    def test_snapshot_is_restored_before_patches_and_overlays_are_applied(self) -> None:
        class EnvironmentRunner(FakeRunner):
            def __init__(self) -> None:
                super().__init__()
                self.environments: list[tuple[tuple[str, ...], object]] = []

            def run(self, argv, *, cwd=None, env=None) -> None:
                self.environments.append((tuple(map(str, argv)), env))
                super().run(argv, cwd=cwd, env=env)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root)
            patch_dir = root / "patches"
            patch_dir.mkdir()
            write_valid_patches(patch_dir, get_target("android").patches)
            overlay_dir = root / "overlays"
            for group in get_target("android").overlays:
                source = overlay_dir / group / group / "placeholder.h"
                source.parent.mkdir(parents=True)
                source.write_text(group)
            runner = EnvironmentRunner()

            def restore(spec, workspace_root, cache_dir, journal=None):
                self.assertEqual(spec, get_target("android").snapshot)
                self.assertEqual(cache_dir, root / "cache")
                workspace.src.mkdir(parents=True)
                workspace.depot_tools.mkdir(parents=True)
                return {"snapshot": spec.name}

            with patch("builder.source.restore_source_snapshot", side_effect=restore) as restored:
                manifest = prepare_source(
                    get_target("android"),
                    workspace,
                    patch_dir,
                    runner,
                    overlay_dir,
                    snapshot_cache_dir=root / "cache",
                )

            commands = [call[1] for call in runner.calls]
            self.assertEqual(manifest["snapshot"], "webrtc-src-m150-android")
            restored.assert_called_once()
            for patch_name in get_target("android").patches:
                patch_path = str(patch_dir / patch_name)
                check_index = commands.index(("git", "apply", "--check", patch_path))
                apply_index = commands.index(("git", "apply", patch_path))
                reverse_check_index = commands.index(
                    ("git", "apply", "--reverse", "--check", patch_path)
                )
                self.assertLess(check_index, apply_index)
                self.assertLess(apply_index, reverse_check_index)
            self.assertTrue(
                all(
                    environment is None
                    for command, environment in runner.environments
                    if command[:2] == ("git", "apply")
                )
            )
            for group in get_target("android").overlays:
                self.assertTrue((workspace.src / group / "placeholder.h").is_file())


class BuildPlanTests(unittest.TestCase):
    def test_windows_copies_complete_static_library_and_runs_validation_exe(self) -> None:
        class WindowsRunner(FakeRunner):
            def run(self, argv, *, cwd=None, env=None) -> None:
                self.calls.append(("run", tuple(map(str, argv)), cwd))
                if argv and str(argv[0]).endswith("ninja.bat"):
                    output_dir = Path(argv[2])
                    (output_dir / "obj").mkdir(parents=True, exist_ok=True)
                    (output_dir / "obj" / "webrtc.lib").write_bytes(b"complete archive")

            def capture(self, argv, *, cwd=None, env=None) -> str:
                self.calls.append(("capture", tuple(map(str, argv)), cwd))
                if (
                    argv
                    and str(argv[0]).endswith("gn.bat")
                    and tuple(argv[1:3])
                    == (
                        "args",
                        "--list",
                    )
                ):
                    return 'target_os = "win"'
                return super().capture(argv, cwd=cwd, env=env)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.src.mkdir(parents=True)
            runner = WindowsRunner()
            units = build_webrtc(get_target("windows-x64"), workspace, runner)

            unit = units[0]
            self.assertEqual((unit.output_dir / "webrtc.lib").read_bytes(), b"complete archive")
            commands = [call[1] for call in runner.calls]
            self.assertTrue(any(command[0].endswith("ninja.bat") for command in commands))
            self.assertIn(
                (str(unit.output_dir / "cast_tuning_native_tests.exe"),),
                commands,
            )

    def test_archive_uses_one_response_file_for_duplicate_object_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            unit = build_units(get_target("macos-arm64"), workspace)[0]
            first = unit.output_dir / "obj" / "one" / "encoder.o"
            second = unit.output_dir / "obj" / "two" / "encoder.o"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            runner = FakeRunner()

            _archive_objects(get_target("macos-arm64"), workspace, unit, runner)

            archive_calls = [
                call[1]
                for call in runner.calls
                if call[1][0].endswith("llvm-ar") and call[1][1] == "rcs"
            ]
            self.assertEqual(len(archive_calls), 1)
            self.assertEqual(archive_calls[0][1], "rcs")
            response_file = Path(archive_calls[0][3].removeprefix("@"))
            members = response_file.read_text().splitlines()
            self.assertEqual(len(members), 2)
            self.assertNotEqual(members[0], members[1])

    def test_archive_rejects_missing_members_after_creation(self) -> None:
        class DroppingArchiver(FakeRunner):
            def capture(self, argv, *, cwd=None, env=None) -> str:
                if argv and str(argv[0]).endswith("llvm-ar") and argv[1] == "t":
                    return "encoder.o"
                return super().capture(argv, cwd=cwd, env=env)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            unit = build_units(get_target("macos-arm64"), workspace)[0]
            for parent in ("one", "two"):
                path = unit.output_dir / "obj" / parent / "encoder.o"
                path.parent.mkdir(parents=True)
                path.write_bytes(parent.encode())
            with self.assertRaisesRegex(BuildError, "archive contains 1 members; expected 2"):
                _archive_objects(get_target("macos-arm64"), workspace, unit, DroppingArchiver())

    def test_ios_has_separate_device_and_simulator_units(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            units = build_units(get_target("ios"), Workspace(Path(directory)))
        self.assertEqual([unit.architecture for unit in units], ["device:arm64", "simulator:arm64"])
        self.assertNotEqual(units[0].output_dir, units[1].output_dir)
        self.assertIn('target_environment="device"', units[0].gn_args)
        self.assertIn('target_environment="simulator"', units[1].gn_args)

    def test_build_invokes_gn_then_ninja_for_each_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.src.mkdir(parents=True)
            runner = FakeRunner()
            build_webrtc(get_target("macos-arm64"), workspace, runner)
            commands = [call[1] for call in runner.calls]
        gn_index = next(i for i, command in enumerate(commands) if command[:2] == ("gn", "gen"))
        ninja_index = next(i for i, command in enumerate(commands) if command[0] == "ninja")
        self.assertLess(gn_index, ninja_index)
        self.assertIn("sdk:mac_framework_objc", commands[ninja_index])
        self.assertIn('target_cpu="arm64"', commands[gn_index][-1])
        archive_index = next(
            i for i, command in enumerate(commands) if len(command) > 1 and command[1] == "rcs"
        )
        validation_index = next(
            i
            for i, command in enumerate(commands)
            if command[0] == "ninja" and "api/cast_tuning:cast_tuning_native_tests" in command
        )
        execute_index = commands.index(
            (str(workspace.out / "macos-arm64" / "arm64" / "cast_tuning_native_tests"),)
        )
        self.assertLess(archive_index, validation_index)
        self.assertLess(validation_index, execute_index)

    def test_missing_object_files_fails_instead_of_publishing_empty_library(self) -> None:
        class NoOutputRunner(FakeRunner):
            def run(self, argv, *, cwd=None, env=None) -> None:
                self.calls.append(("run", tuple(map(str, argv)), cwd))

        with tempfile.TemporaryDirectory() as directory:
            workspace = Workspace(Path(directory))
            workspace.src.mkdir(parents=True)
            with self.assertRaisesRegex(BuildError, "no object files"):
                build_webrtc(get_target("android"), workspace, NoOutputRunner())


if __name__ == "__main__":
    unittest.main()
