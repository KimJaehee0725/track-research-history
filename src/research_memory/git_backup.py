"""Best-effort local Git snapshots for a project vault.

This module never configures a remote and never handles credentials.  The
memory store treats every failure here as non-fatal: Markdown storage remains
usable on hosts where Git is unavailable or local commits are disabled.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import GitBackupError


def git_available() -> bool:
    """Return whether a ``git`` executable is available on ``PATH``."""

    return shutil.which("git") is not None


def _run_git(project_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_dir), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def initialize_project_git(project_dir: Path) -> bool:
    """Initialize a local repository and return ``False`` if Git is absent.

    It intentionally does not add a remote.  A failed Git command is reported
    to explicit callers as :class:`GitBackupError` rather than hidden.
    """

    if not git_available():
        return False
    result = _run_git(project_dir, "init", "--quiet")
    if result.returncode:
        raise GitBackupError(result.stderr.strip() or "git init failed")
    return True


def commit_project_snapshot(project_dir: Path, message: str) -> str | None:
    """Commit a project's vault and manifest locally and return its hash.

    ``None`` means Git is unavailable or no staged change exists.  Supplying
    an explicit local identity makes server snapshots work even when a service
    account lacks a global Git configuration.
    """

    if not git_available():
        return None
    if not (project_dir / ".git").is_dir():
        initialize_project_git(project_dir)
    add = _run_git(project_dir, "add", "--", "vault", "project.yaml")
    if add.returncode:
        raise GitBackupError(add.stderr.strip() or "git add failed")
    changed = _run_git(project_dir, "diff", "--cached", "--quiet")
    if changed.returncode == 0:
        return None
    if changed.returncode != 1:
        raise GitBackupError(changed.stderr.strip() or "git diff failed")
    commit = _run_git(
        project_dir,
        "-c",
        "user.name=research-memory",
        "-c",
        "user.email=memory@localhost",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    if commit.returncode:
        raise GitBackupError(commit.stderr.strip() or "git commit failed")
    head = _run_git(project_dir, "rev-parse", "HEAD")
    if head.returncode:
        raise GitBackupError(head.stderr.strip() or "could not read Git revision")
    return head.stdout.strip()
