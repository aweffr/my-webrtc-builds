import json
import tempfile
import unittest
from pathlib import Path

from builder.observability import BuildJournal, collect_toolchain


class BuildJournalTests(unittest.TestCase):
    def test_phase_records_start_success_and_duration(self) -> None:
        ticks = iter((10.0, 12.5))
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "build-events.jsonl")
            journal = BuildJournal(path, logger=messages.append, clock=lambda: next(ticks))
            with journal.phase("source-sync", target="android"):
                pass
            events = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([event["status"] for event in events], ["started", "succeeded"])
        self.assertEqual(events[1]["duration_seconds"], 2.5)
        self.assertIn("source-sync", "\n".join(messages))

    def test_failure_is_persisted_before_exception_escapes(self) -> None:
        ticks = iter((5.0, 6.0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "build-events.jsonl")
            journal = BuildJournal(path, logger=lambda _: None, clock=lambda: next(ticks))
            with self.assertRaisesRegex(RuntimeError, "ninja broke"):
                with journal.phase("compile", architecture="arm64"):
                    raise RuntimeError("ninja broke")
            events = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual(events[-1]["status"], "failed")
        self.assertEqual(events[-1]["error_type"], "RuntimeError")
        self.assertEqual(events[-1]["error"], "ninja broke")
        self.assertEqual(events[-1]["duration_seconds"], 1.0)


class ToolchainObservationTests(unittest.TestCase):
    def test_platform_specific_toolchain_is_recorded(self) -> None:
        class VersionRunner:
            def __init__(self) -> None:
                self.commands: list[tuple[str, ...]] = []

            def capture(self, argv, *, cwd=None, env=None) -> str:
                command = tuple(argv)
                self.commands.append(command)
                return "version output"

        mac_runner = VersionRunner()
        mac = collect_toolchain("macos-arm64", mac_runner)
        self.assertIn("xcode", mac)
        self.assertIn(("xcodebuild", "-version"), mac_runner.commands)

        android_runner = VersionRunner()
        android = collect_toolchain("android", android_runner)
        self.assertIn("java", android)
        self.assertIn(("javac", "-version"), android_runner.commands)
        self.assertNotIn("xcode", android)


if __name__ == "__main__":
    unittest.main()
