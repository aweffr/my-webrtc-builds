import json
import tempfile
import unittest
from pathlib import Path

from builder.observability import BuildJournal


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


if __name__ == "__main__":
    unittest.main()
