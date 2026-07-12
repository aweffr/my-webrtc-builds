import subprocess
import unittest
from pathlib import Path

from builder.commands import CommandError, CommandRunner


class CommandRunnerTests(unittest.TestCase):
    def test_failure_reports_command_and_status_without_environment(self) -> None:
        def failing_run(*args, **kwargs):
            raise subprocess.CalledProcessError(17, args[0], stderr="compile failed")

        messages: list[str] = []
        runner = CommandRunner(executor=failing_run, logger=messages.append)

        with self.assertRaises(CommandError) as raised:
            runner.run(
                ["ninja", "-C", "out"],
                cwd=Path("/tmp/source"),
                env={"GITHUB_TOKEN": "secret-token", "PATH": "/bin"},
            )

        message = str(raised.exception)
        self.assertIn("status 17", message)
        self.assertIn("ninja -C out", message)
        self.assertIn("compile failed", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("secret-token", "\n".join(messages))

    def test_capture_returns_trimmed_stdout(self) -> None:
        def successful_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=" value\n", stderr="")

        runner = CommandRunner(executor=successful_run, logger=lambda _: None)
        self.assertEqual(runner.capture(["git", "rev-parse", "HEAD"]), "value")

    def test_capture_uses_stderr_for_version_tools(self) -> None:
        def successful_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="javac 11.0.31\n")

        runner = CommandRunner(executor=successful_run, logger=lambda _: None)
        self.assertEqual(runner.capture(["javac", "-version"]), "javac 11.0.31")


if __name__ == "__main__":
    unittest.main()
