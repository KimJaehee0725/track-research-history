"""Privacy-gated local Markdown recording and dependency-free search."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import CliError, CommandRunner, require_success
from .data_repo import validate_data_repository
from .github_repo import verify_private_repository


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9가-힣]+", "-", value.strip().lower()).strip("-")
    return (cleaned[:48] or "note").strip("-") or "note"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _exact_git_root(runner: CommandRunner, root: Path) -> None:
    completed = runner.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if completed.returncode != 0 or not completed.stdout.strip():
        raise CliError("git_root_unavailable", f"Not a Git repository: {root}")
    if Path(completed.stdout.strip()).expanduser().resolve() != root:
        raise CliError(
            "git_root_mismatch",
            "Configured data path is nested inside a different Git repository.",
        )


def record_note(
    runner: CommandRunner,
    *,
    root: Path,
    text: str,
    title: str | None,
    expected_repository: str | None,
    push: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    validate_data_repository(root)
    _exact_git_root(runner, root)
    remote = verify_private_repository(
        runner,
        root,
        expected_repository=expected_repository,
    )
    status = runner.run(["git", "-C", str(root), "status", "--porcelain"])
    require_success(
        status,
        code="git_status_failed",
        message="Could not inspect the data repository working tree.",
    )
    if status.stdout.strip():
        raise CliError(
            "working_tree_dirty",
            "Refusing to record while the data repository has uncommitted changes.",
            hint="Commit, push, or discard those changes explicitly, then retry.",
        )
    body = text.strip()
    if not body:
        raise CliError("record_empty", "Research record text must not be empty.")
    display_title = (title or body.splitlines()[0]).strip()[:160]
    if not display_title:
        display_title = "Research note"

    created = now or datetime.now().astimezone()
    folder = root / "history" / "daily"
    stem = f"{created:%Y-%m-%d-%H%M%S}-{_slug(display_title)}"
    note_path = folder / f"{stem}.md"
    suffix = 2
    while note_path.exists() or note_path.is_symlink():
        note_path = folder / f"{stem}-{suffix:02d}.md"
        suffix += 1
    relative_note = note_path.relative_to(root)
    note_text = f"""---
type: daily
title: {json.dumps(display_title, ensure_ascii=False)}
date: {created:%Y-%m-%d}
created_at: {created.isoformat()}
status: recorded
tags: []
---

# {display_title}

{body}
"""
    _atomic_write(note_path, note_text)

    index_path = root / "history" / "INDEX.md"
    try:
        current_index = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(
            "index_unavailable", f"Could not read history index: {index_path}"
        ) from exc
    safe_title = display_title.replace("[", "(").replace("]", ")")
    link = relative_note.relative_to("history").as_posix()
    updated_index = (
        current_index.rstrip() + f"\n\n- {created.isoformat()} [{safe_title}]({link})\n"
    )
    _atomic_write(index_path, updated_index)

    add = runner.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            "--",
            str(relative_note),
            "history/INDEX.md",
        ]
    )
    require_success(
        add,
        code="git_add_failed",
        message="Record was written, but Git staging failed.",
    )
    commit = runner.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-m",
            f"Record research note: {display_title[:72]}",
        ]
    )
    require_success(
        commit,
        code="git_commit_failed",
        message="Record was written and staged, but Git commit failed.",
    )
    if push:
        pushed = runner.run(["git", "-C", str(root), "push", remote.push_url, "HEAD"])
        require_success(
            pushed,
            code="git_push_failed",
            message="Record was committed locally, but push to the private origin failed.",
        )
    return {
        "path": str(note_path),
        "repository": remote.repository,
        "pushed": push,
        "title": display_title,
    }


def search_records(root: Path, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    validate_data_repository(root)
    needle = query.strip().casefold()
    if not needle:
        raise CliError("query_empty", "Search query must not be empty.")
    if not 1 <= limit <= 1000:
        raise CliError("limit_invalid", "Search limit must be between 1 and 1000.")
    results: list[dict[str, Any]] = []
    history = root / "history"
    for path in sorted(history.rglob("*.md")):
        if path.name == "INDEX.md" or path.is_symlink():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            if needle in line.casefold():
                results.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": line_number,
                        "excerpt": line.strip()[:300],
                    }
                )
                break
        if len(results) >= limit:
            break
    return results
