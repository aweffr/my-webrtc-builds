from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class CommandError(RuntimeError):
    """A subprocess failed without exposing its environment."""


Executor = Callable[..., subprocess.CompletedProcess[str]]


class CommandRunner:
    def __init__(
        self,
        *,
        executor: Executor = subprocess.run,
        logger: Callable[[str], None] = print,
    ) -> None:
        self._executor = executor
        self._logger = logger

    def run(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._execute(argv, cwd=cwd, env=env, capture=False)

    def capture(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        result = self._execute(argv, cwd=cwd, env=env, capture=True)
        return (result.stdout or result.stderr or "").strip()

    def _execute(
        self,
        argv: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None,
        env: Mapping[str, str] | None,
        capture: bool,
    ) -> subprocess.CompletedProcess[str]:
        command = [os.fspath(value) for value in argv]
        rendered = shlex.join(command)
        location = f" (cwd: {cwd})" if cwd is not None else ""
        self._logger(f"+ {rendered}{location}")
        try:
            return self._executor(
                command,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                check=True,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            raise CommandError(
                f"command failed with status {exc.returncode}: {rendered}{suffix}"
            ) from exc
