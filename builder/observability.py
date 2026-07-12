from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def collect_toolchain(target: str, runner: Any) -> dict[str, str]:
    commands: dict[str, list[str]] = {
        "python": ["python3", "--version"],
        "git": ["git", "--version"],
        "system": ["uname", "-a"],
    }
    if target.startswith("macos") or target == "ios":
        commands.update(
            {
                "xcode": ["xcodebuild", "-version"],
                "clang": ["clang", "--version"],
            }
        )
    if target == "android":
        commands["java"] = ["javac", "-version"]
    if target == "windows-x64":
        commands.update(
            {
                "windows": ["cmd", "/d", "/c", "ver"],
                "visual_studio": [
                    "vswhere",
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-property",
                    "installationVersion",
                ],
            }
        )
    return {
        name: " | ".join(runner.capture(command).splitlines()) for name, command in commands.items()
    }


class BuildJournal:
    """Append-only phase journal designed to survive failed Actions jobs."""

    def __init__(
        self,
        path: Path,
        *,
        logger: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger
        self._clock = clock

    def log(self, message: str) -> None:
        self._logger(message)

    def record(self, phase: str, status: str, **details: Any) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "phase": phase,
            "status": status,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        rendered_details = " ".join(
            f"{key}={value}" for key, value in details.items() if key not in {"error"}
        )
        suffix = f" {rendered_details}" if rendered_details else ""
        self._logger(f"[{phase}] {status}{suffix}")

    @contextmanager
    def phase(self, phase: str, **details: Any) -> Iterator[None]:
        started = self._clock()
        self.record(phase, "started", **details)
        try:
            yield
        except BaseException as exc:
            duration = round(self._clock() - started, 3)
            self.record(
                phase,
                "failed",
                **details,
                duration_seconds=duration,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        duration = round(self._clock() - started, 3)
        self.record(phase, "succeeded", **details, duration_seconds=duration)
