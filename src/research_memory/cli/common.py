"""Shared CLI errors and subprocess boundaries."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CliError(RuntimeError):
    """A user-actionable CLI failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return payload


class CommandRunner(Protocol):
    """Injectable command boundary used by Git and GitHub integrations."""

    def which(self, executable: str) -> str | None: ...

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SystemCommandRunner:
    """Run explicit argument vectors without invoking a shell."""

    def which(self, executable: str) -> str | None:
        return shutil.which(executable)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        if args and args[0] == "gh":
            environment["GH_PROMPT_DISABLED"] = "1"
        if args and args[0] == "git":
            environment["GIT_TERMINAL_PROMPT"] = "0"
            environment["GCM_INTERACTIVE"] = "Never"
            environment["GIT_SSH_COMMAND"] = (
                "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "
                "-o NumberOfPasswordPrompts=0"
            )
            environment["SSH_ASKPASS_REQUIRE"] = "never"
        return subprocess.run(
            list(args),
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
            env=environment,
        )


def require_executable(runner: CommandRunner, executable: str, *, hint: str) -> None:
    if runner.which(executable) is None:
        raise CliError(
            f"{executable}_missing",
            f"Required executable is not installed: {executable}",
            hint=hint,
        )


def require_success(
    completed: subprocess.CompletedProcess[str],
    *,
    code: str,
    message: str,
    hint: str | None = None,
) -> subprocess.CompletedProcess[str]:
    if completed.returncode != 0:
        raise CliError(code, message, hint=hint)
    return completed


@dataclass(frozen=True)
class Check:
    """One stable doctor result."""

    name: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
        }
