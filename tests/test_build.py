import tempfile
import unittest
from pathlib import Path

from builder.build import BuildError, build_units, build_webrtc
from builder.config import SOURCE_VERSION, get_target
from builder.source import Workspace, prepare_source


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
            return self.commit
        if tuple(argv[:3]) == ("gn", "args", "--list"):
            return "is_debug = false"
        return ""


class SourcePreparationTests(unittest.TestCase):
    def test_source_is_pinned_and_patches_are_checked_before_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root)
            workspace.src.mkdir(parents=True)
            workspace.depot_tools.mkdir(parents=True)
            patch_dir = root / "patches"
            patch_dir.mkdir()
            for name in get_target("android").patches:
                (patch_dir / name).write_text("diff --git a/a b/a\n")
            runner = FakeRunner()

            prepare_source(get_target("android"), workspace, patch_dir, runner)

            commands = [call[1] for call in runner.calls]
            checkout = ("git", "checkout", "--detach", SOURCE_VERSION.commit)
            self.assertIn(checkout, commands)
            sync_index = next(
                i for i, command in enumerate(commands) if command[:2] == ("gclient", "sync")
            )
            for patch_name in get_target("android").patches:
                patch_path = str(patch_dir / patch_name)
                check_index = commands.index(("git", "apply", "--check", patch_path))
                apply_index = commands.index(("git", "apply", patch_path))
                self.assertGreater(check_index, sync_index)
                self.assertLess(check_index, apply_index)

    def test_unexpected_checkout_commit_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = Workspace(root)
            workspace.src.mkdir(parents=True)
            workspace.depot_tools.mkdir(parents=True)
            patch_dir = root / "patches"
            patch_dir.mkdir()
            for name in get_target("android").patches:
                (patch_dir / name).write_text("patch")
            with self.assertRaisesRegex(BuildError, "unexpected WebRTC commit"):
                prepare_source(
                    get_target("android"),
                    workspace,
                    patch_dir,
                    FakeRunner(commit="b" * 40),
                )


class BuildPlanTests(unittest.TestCase):
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
