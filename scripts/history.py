#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


HISTORY_DIR = "history"
SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_PATTERN = r"(?u)\b[\w./:-]{2,}\b"
CHUNK_TARGET_CHARS = 2200
CHUNK_OVERLAP_CHARS = 250
CHUNK_SMALL_FILE_THRESHOLD = 2600
OBSIDIAN_LINT_MAX_CHARS = 12000
RECORD_DIRS = [
    "daily",
    "changes",
    "decisions",
    "ideas",
    "experiments",
    "handoffs",
    "capsules",
    "sessions",
    "templates",
]
DEFAULT_COLLAB_WORKSTREAMS = ["data", "eval", "model", "writeup"]
COLLAB_DIRS = ["canonical", "tasks", "inbox", "archive"]
ARCHIVE_TYPES = ["inbox", "daily", "sessions"]
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]"), "password-like field"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|credential)\b\s*[:=]"), "secret-like field"),
    (re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,})\b"), "token-shaped value"),
    (re.compile(r"(?i)\braw transcript\b"), "raw transcript reference"),
]


def now() -> datetime:
    return datetime.now().astimezone()


def date_stamp() -> str:
    return now().strftime("%Y-%m-%d")


def time_stamp() -> str:
    return now().strftime("%Y-%m-%d-%H%M%S")


def display_time() -> str:
    return now().strftime("%Y-%m-%d %H:%M %z")


def short_time() -> str:
    return now().strftime("%H:%M")


def slugify(text: str, fallback: str = "record") -> str:
    value = text.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:64].strip("-") or fallback


def detect_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return Path.cwd().resolve()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def bullets(items: list[str] | None) -> str:
    if not items:
        return "-"
    return "\n".join(f"- {item}" for item in items if item)


def value(text: str | None) -> str:
    return text.strip() if text and text.strip() else "-"


def write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def ensure_history(root: Path) -> None:
    history = root / HISTORY_DIR
    for name in RECORD_DIRS:
        (history / name).mkdir(parents=True, exist_ok=True)

    write_if_missing(
        history / "CONTEXT.md",
        """# Project Context

Last updated:

## Research Goal

-

## Current Architecture Or Structure

-

## Current Decisions

-

## Active Ideas

-

## Open Questions And Risks

-

## Next Steps

-
""",
    )
    write_if_missing(
        history / "README.md",
        """# Project History

This folder stores durable project memory for research coding, experiments, ideas, decisions, and collaboration.

## Read First

1. `CONTEXT.md`
2. `INDEX.md`
3. Latest file in `daily/`
4. Relevant records from `changes/`, `decisions/`, `ideas/`, `experiments/`, `handoffs/`, `capsules/`, and `sessions/`

## Trusted Context

For collaboration projects, default agent context comes from `canonical/`, `tasks/`, `decisions/`, and scoped handoffs/capsules with explicit `Task:` and `Workstream:` metadata.

## Pending

`inbox/` contains submitted summaries awaiting maintainer review. It is excluded from collaboration recall unless `--include-inbox` is passed.

## Archive

`archive/` is tracked for provenance and long-term review, but excluded from collaboration recall unless `--include-archive` is passed. Archive cleanup moves files; it does not delete them.

## Language

Write summaries, rationale, validation notes, risks, and handoff context in the user's working language by default. Keep metadata keys, commands, paths, code identifiers, and quoted evidence unchanged.

## Maintenance

- Keep entries concrete: paths, commands, parameters, rationale, validation, and risks.
- Append corrections instead of rewriting past history.
- Do not store secrets or credentials.
""",
    )
    templates = {
        "daily.md": """# Daily Log - {{date}}

## Focus

-

## Work Notes

-

## Linked Records

## Open Questions / Risks

-

## Next

-
""",
        "change.md": """# Change - {{title}}

Date: {{date}}
Agent: {{agent}}
Status: {{status}}

## Why

{{why}}

## How

{{how}}

## Files

{{files}}

## Validation

{{validation}}

## Risks / Follow-Ups

{{risks}}
""",
        "decision.md": """# Decision {{id}} - {{title}}

Date: {{date}}
Status: {{status}}

## Context

{{context}}

## Decision

{{decision}}

## Rationale

{{rationale}}

## Consequences

{{consequences}}
""",
        "idea.md": """# Idea {{id}} - {{title}}

Date: {{date}}
Status: {{status}}
Tags: {{tags}}

## Problem / Opportunity

{{problem}}

## Hypothesis

{{hypothesis}}

## Expected Value

{{expected}}

## Links / Evidence

{{links}}

## Next Check

{{next}}
""",
        "experiment.md": """# Experiment {{id}} - {{title}}

Date: {{date}}
Status: {{status}}
Tags: {{tags}}

## Goal

{{goal}}

## Setup

{{setup}}

## Metrics

{{metrics}}

## Results

{{results}}

## Artifacts

{{artifacts}}

## Interpretation / Next

{{next}}
""",
        "handoff.md": """# Handoff - {{title}}

Date: {{date}}
To: {{to}}
Task: {{task}}
Workstream: {{workstream}}

## Summary

{{summary}}

## Ownership / Files

{{files}}

## Next Actions

{{next}}

## Risks

{{risks}}
""",
        "handoff-agent-capsule.md": """# Handoff Agent Capsule - {{task}}

Date: {{date}}
Task: {{collab_task}}
Workstream: {{workstream}}
From Agent: {{from_agent}}
To Agent: {{to_agent}}
Target Host: {{target_host}}
Status: {{status}}

## User Requirements

{{requirements}}

## Current State

{{current_state}}

## Agent Reasoning Summary

{{reasoning_summary}}

## Files / Ownership

{{files}}

## Commands / Validation

{{validation}}

## Open Risks

{{risks}}

## Next Actions

{{next_actions}}

## Read These Records First

{{read_first}}

## BM25 Query Generation

{{generated_queries}}

## Retrieval Reflection

{{reflection}}

## Project Context Snapshot

{{project_context}}

## Git Status Snapshot

```text
{{git_status}}
```
""",
        "session.md": """# Session - {{task}}

Date: {{date}}
Agent: {{agent}}

## Scope

{{scope}}

## Read First

-

## Plan

-

## Work Log

-

## End Summary

-
""",
    }
    for filename, text in templates.items():
        write_if_missing(history / "templates" / filename, text)


def collab_templates() -> dict[str, str]:
    return {
        "collab-summary.md": """# Inbox Summary - {{task}} / {{workstream}} - {{title}}

Date: {{date}}
Task: {{task}}
Workstream: {{workstream}}
Person: {{person}}
Agent: {{agent}}
Approval Status: submitted
Promoted To: -
Archived: no
Archived Date: -
Source Type: summary-only
Raw Transcript Included: no

## Summary

{{summary}}

## Claims

{{claims}}

## Evidence

{{evidence}}

## Changed Files

{{changed_files}}

## Validation

{{validation}}

## Open Questions

{{open_questions}}

## Proposed Decisions

{{proposed_decisions}}

## Private / Local References

{{private_references}}

## Validation Warnings

{{warnings}}
""",
        "collab-canonical-overview.md": """# Canonical Research Overview

Approval Status: accepted
Promoted To: -
Archived: no
Archived Date: -
Last Updated: {{date}}

## Benchmark Goal

-

## Shared Rules

- Canonical context is maintainer-curated.
- Inbox summaries are unaccepted until promoted through review.
- Share summaries, claims, evidence, changed files, risks, and proposed decisions.
- Write free-form notes in the user's working language; keep metadata keys and quoted evidence unchanged.
- Do not store credentials, raw transcripts, private notes, or personal data.

## Current Accepted State

-

## Active Tasks

-

## Recent Accepted Decisions

-

## Open Questions / Risks

-
""",
        "collab-task-context.md": """# Task {{task}} Context

Task: {{task}}
Owner: {{owner}}
Status: {{status}}
Metric: {{metric}}
Dataset: {{dataset}}
Blocker: {{blocker}}
Approval Status: accepted
Promoted To: -
Archived: no
Archived Date: -
Last Updated: {{date}}

## Short State

-

## Accepted Decisions

-

## Open Questions

-

## Open Risks

-

## Next Steps

-
""",
        "collab-workstream-context.md": """# Workstream {{workstream}} Context

Task: {{task}}
Workstream: {{workstream}}
Owner: {{owner}}
Status: {{status}}
Approval Status: accepted
Promoted To: -
Archived: no
Archived Date: -
Last Updated: {{date}}

## Scope

-

## Accepted State

-

## Evidence / Artifacts

-

## Open Questions

-

## Open Risks

-

## Next Steps

-
""",
    }


def ensure_collab(root: Path) -> None:
    ensure_history(root)
    history = root / HISTORY_DIR
    for name in COLLAB_DIRS:
        (history / name).mkdir(parents=True, exist_ok=True)
    ensure_archive(root)
    for filename, text in collab_templates().items():
        write_if_missing(history / "templates" / filename, text)
    overview_template = history / "templates" / "collab-canonical-overview.md"
    overview = history / "canonical" / "overview.md"
    if not overview.exists():
        text = overview_template.read_text(encoding="utf-8").replace("{{date}}", display_time())
        text = add_obsidian_frontmatter(
            text,
            "canonical",
            "Canonical Research Overview",
            {"approval_status": "accepted", "archived": False},
        )
        overview.write_text(text, encoding="utf-8")
    write_if_missing(
        history / "tasks" / "README.md",
        """# Collaboration Tasks

Each task folder stores maintainer-accepted context for one benchmark task.

Use `context.md` for the task-level accepted state and `workstreams/` for focused data, eval, model, writeup, or custom workstream context.

Inbox summaries are not canonical until a maintainer promotes them.
""",
    )
    write_if_missing(
        history / "inbox" / "README.md",
        """# Collaboration Inbox

This folder stores submitted summaries that have not necessarily been accepted.

Allowed content: summary, claims, evidence, changed files, validation, open questions, and proposed decisions.

Do not store raw transcripts, credentials, private notes, or personal data.
""",
    )


def ensure_archive(root: Path) -> None:
    history = root / HISTORY_DIR
    archive = history / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVE_TYPES:
        (archive / name).mkdir(parents=True, exist_ok=True)
    write_if_missing(
        archive / "README.md",
        """# Collaboration Archive

Archived records are tracked for provenance and long-term review, but they are not part of default collaboration recall.

Use archived records as supporting evidence only after checking their provenance against accepted canonical, task, workstream, or decision context.

`collab recall` excludes this folder unless `--include-archive` is passed.
""",
    )


def normalize_collab_id(text: str, fallback: str) -> str:
    return slugify(text, fallback=fallback)


def task_context_path(root: Path, task: str) -> Path:
    return root / HISTORY_DIR / "tasks" / normalize_collab_id(task, "task") / "context.md"


def workstream_context_path(root: Path, task: str, workstream: str) -> Path:
    return (
        root
        / HISTORY_DIR
        / "tasks"
        / normalize_collab_id(task, "task")
        / "workstreams"
        / f"{normalize_collab_id(workstream, 'workstream')}.md"
    )


def ensure_collab_task(root: Path, task: str, workstreams: list[str] | None = None) -> None:
    ensure_collab(root)
    task_id = normalize_collab_id(task, "task")
    task_dir = root / HISTORY_DIR / "tasks" / task_id
    workstream_dir = task_dir / "workstreams"
    workstream_dir.mkdir(parents=True, exist_ok=True)
    context = task_dir / "context.md"
    if not context.exists():
        text = (root / HISTORY_DIR / "templates" / "collab-task-context.md").read_text(encoding="utf-8")
        text = (
            text.replace("{{task}}", task_id)
            .replace("{{owner}}", "-")
            .replace("{{status}}", "draft")
            .replace("{{metric}}", "-")
            .replace("{{dataset}}", "-")
            .replace("{{blocker}}", "-")
            .replace("{{date}}", display_time())
        )
        text = add_obsidian_frontmatter(text, "task-context", f"Task {task_id} Context")
        context.write_text(text, encoding="utf-8")
    for workstream in workstreams or []:
        path = workstream_context_path(root, task_id, workstream)
        if not path.exists():
            text = (root / HISTORY_DIR / "templates" / "collab-workstream-context.md").read_text(encoding="utf-8")
            text = (
                text.replace("{{task}}", task_id)
                .replace("{{workstream}}", normalize_collab_id(workstream, "workstream"))
                .replace("{{owner}}", "-")
                .replace("{{status}}", "draft")
                .replace("{{date}}", display_time())
            )
            text = add_obsidian_frontmatter(
                text,
                "workstream",
                f"Workstream {normalize_collab_id(workstream, 'workstream')} Context",
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def detect_sensitive_warnings(named_texts: list[tuple[str, str | None]]) -> list[str]:
    warnings: list[str] = []
    for label, text in named_texts:
        if not text:
            continue
        checked_text = re.sub(r"(?im)^Raw Transcript Included:\s*no\s*$", "", text)
        for pattern, description in SECRET_PATTERNS:
            if pattern.search(checked_text):
                warnings.append(f"{label}: possible {description}; review before sharing.")
    return sorted(set(warnings))


def metadata_key(key: str) -> str:
    return key.strip().lower().replace("_", " ")


def frontmatter_key(key: str) -> str:
    value_text = key.strip().lower()
    value_text = re.sub(r"[^a-z0-9]+", "_", value_text)
    return value_text.strip("_")


def frontmatter_bounds(text: str) -> tuple[int, int] | None:
    if not text.startswith("---\n"):
        return None
    match = re.search(r"^---\s*$", text[4:], flags=re.MULTILINE)
    if not match:
        return None
    return (4, 4 + match.start())


def has_frontmatter(text: str) -> bool:
    return frontmatter_bounds(text) is not None


def strip_frontmatter(text: str) -> str:
    bounds = frontmatter_bounds(text)
    if not bounds:
        return text
    _, body_end = bounds
    closing = re.search(r"^---\s*$", text[body_end:], flags=re.MULTILINE)
    if not closing:
        return text
    return text[body_end + closing.end() :].lstrip("\n")


def parse_yaml_scalar(value_text: str) -> str:
    value_text = value_text.strip()
    if value_text in {"[]", "{}"}:
        return ""
    if value_text.lower() == "true":
        return "yes"
    if value_text.lower() == "false":
        return "no"
    if len(value_text) >= 2 and value_text[0] == value_text[-1] == '"':
        return value_text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value_text) >= 2 and value_text[0] == value_text[-1] == "'":
        return value_text[1:-1].replace("''", "'")
    if value_text.startswith("[") and value_text.endswith("]"):
        return value_text[1:-1].strip()
    return value_text


def parse_frontmatter(text: str) -> dict[str, str]:
    bounds = frontmatter_bounds(text)
    if not bounds:
        return {}
    start, end = bounds
    meta: dict[str, str] = {}
    for line in text[start:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            meta[metadata_key(match.group(1))] = parse_yaml_scalar(match.group(2))
    return meta


def yaml_quote(value_text: str) -> str:
    return '"' + value_text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_value(value_obj: object) -> str:
    if isinstance(value_obj, bool):
        return "true" if value_obj else "false"
    if isinstance(value_obj, (list, tuple)):
        if not value_obj:
            return "[]"
        return "[" + ", ".join(yaml_value(item) for item in value_obj) + "]"
    value_text = str(value_obj).strip()
    if not value_text or value_text == "-":
        return yaml_quote(value_text or "-")
    if value_text.lower() in {"true", "false", "yes", "no", "null"}:
        return yaml_quote(value_text)
    if re.fullmatch(r"[A-Za-z0-9_./:+-]+", value_text):
        return value_text
    return yaml_quote(value_text)


def frontmatter_block(fields: dict[str, object]) -> str:
    lines = ["---"]
    for key, value_obj in fields.items():
        lines.append(f"{frontmatter_key(key)}: {yaml_value(value_obj)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def split_tags(value_text: str | None) -> list[str]:
    if not value_text or value_text.strip() == "-":
        return []
    tags: list[str] = []
    for item in re.split(r"[, ]+", value_text):
        cleaned = item.strip().lstrip("#")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags


def add_obsidian_frontmatter(
    text: str,
    record_type: str,
    title: str,
    extra_fields: dict[str, object] | None = None,
) -> str:
    if has_frontmatter(text):
        return text
    meta = parse_metadata(text)
    fields: dict[str, object] = {
        "type": record_type,
        "title": title,
        "date": meta.get("date") or meta.get("date imported") or display_time(),
    }
    status = meta.get("status") or meta.get("approval status")
    if status:
        fields["status"] = status
    tags = ["history", record_type]
    for tag in split_tags(meta.get("tags")):
        if tag not in tags:
            tags.append(tag)
    fields["tags"] = tags
    for key in ["task", "workstream", "agent", "person"]:
        if meta.get(key) and meta[key] != "-":
            fields[key] = meta[key]
    for key in ["approval status", "promoted to", "archived date", "archived from"]:
        if meta.get(key):
            fields[key] = meta[key]
    if meta.get("archived"):
        fields["archived"] = normalized_status(meta.get("archived")) in {"yes", "true", "archived"}
    if extra_fields:
        fields.update(extra_fields)
    return frontmatter_block(fields) + text.lstrip("\n")


def set_frontmatter_field(text: str, key: str, value_text: str) -> str:
    bounds = frontmatter_bounds(text)
    if not bounds:
        return text
    start, end = bounds
    yaml_key = frontmatter_key(key)
    value_obj: object = value_text
    if yaml_key == "archived":
        value_obj = normalized_status(value_text) in {"yes", "true", "archived"}
    replacement = f"{yaml_key}: {yaml_value(value_obj)}"
    body = text[start:end]
    pattern = re.compile(rf"^({re.escape(yaml_key)}:\s*).*$", re.MULTILINE)
    if pattern.search(body):
        body = pattern.sub(replacement, body, count=1)
    else:
        body = body.rstrip() + "\n" + replacement + "\n"
    return text[:start] + body + text[end:]


def parse_metadata(text: str) -> dict[str, str]:
    meta: dict[str, str] = parse_frontmatter(text)
    for line in strip_frontmatter(text).splitlines():
        if line.startswith("## "):
            break
        match = re.match(r"^([A-Za-z][A-Za-z /_-]*):\s*(.*)$", line)
        if match:
            meta[metadata_key(match.group(1))] = match.group(2).strip()
    return meta


def metadata_value(path: Path, key: str, default: str = "-") -> str:
    try:
        meta = parse_metadata(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return meta.get(metadata_key(key), default) or default


def normalized_status(text: str | None) -> str:
    return text.strip().lower() if text and text.strip() else ""


def approval_status(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "unknown"
    meta = parse_metadata(text)
    approval = normalized_status(meta.get("approval status"))
    if approval:
        return approval
    status = normalized_status(meta.get("status"))
    if status:
        return status
    kind = record_kind(path)
    if kind in {"canonical", "task-context", "workstream"}:
        return "accepted"
    if kind == "inbox":
        return "submitted"
    return "unknown"


def archived_value(path: Path) -> str:
    try:
        meta = parse_metadata(path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    value_text = normalized_status(meta.get("archived"))
    if value_text in {"yes", "true", "archived"}:
        return "yes"
    return "no"


def archive_status(path: Path) -> str:
    if "archive" in path.parts or archived_value(path) == "yes":
        return "archived"
    return "active"


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], flags=re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def set_metadata_line(text: str, key: str, value_text: str) -> str:
    text = set_frontmatter_field(text, key, value_text)
    pattern = re.compile(rf"^({re.escape(key)}:\s*).*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda match: match.group(1) + value_text, text, count=1)
    first_section = re.search(r"^##\s+", text, flags=re.MULTILINE)
    insert = f"{key}: {value_text}\n"
    if first_section:
        return text[: first_section.start()] + insert + text[first_section.start():]
    return text.rstrip() + "\n" + insert


def update_last_updated(text: str) -> str:
    return set_metadata_line(text, "Last Updated", display_time())


def today_file(root: Path) -> Path:
    ensure_history(root)
    path = root / HISTORY_DIR / "daily" / f"{date_stamp()}.md"
    if not path.exists():
        tmpl = (root / HISTORY_DIR / "templates" / "daily.md").read_text(encoding="utf-8")
        text = tmpl.replace("{{date}}", date_stamp())
        text = add_obsidian_frontmatter(
            text,
            "daily",
            f"Daily Log - {date_stamp()}",
            {"date": date_stamp(), "tags": ["history", "daily"]},
        )
        path.write_text(text, encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
        if not has_frontmatter(text):
            text = add_obsidian_frontmatter(
                text,
                "daily",
                f"Daily Log - {date_stamp()}",
                {"date": date_stamp(), "tags": ["history", "daily"]},
            )
            path.write_text(text, encoding="utf-8")
    return path


def append_daily(root: Path, kind: str, title: str, record_path: Path) -> None:
    path = today_file(root)
    line = f"- {short_time()} [{kind}] {title} -> `{rel(root, record_path)}`\n"
    text = path.read_text(encoding="utf-8")
    marker = "## Linked Records\n"
    if marker in text:
        text = text.replace(marker, marker + "\n" + line, 1)
    else:
        text = text.rstrip() + "\n\n## Linked Records\n\n" + line
    path.write_text(text, encoding="utf-8")


def next_id(folder: Path) -> str:
    highest = 0
    for path in folder.glob("*.md"):
        match = re.match(r"^(\d{4})-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{highest + 1:04d}"


def git_status(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "status", "--short"],
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
        return out or "clean"
    except Exception as exc:
        return f"unavailable: {exc}"


def write_record(root: Path, folder: str, filename: str, text: str, kind: str, title: str) -> Path:
    ensure_history(root)
    out = root / HISTORY_DIR / folder / filename
    text = add_obsidian_frontmatter(text, kind, title)
    out.write_text(text, encoding="utf-8")
    append_daily(root, kind, title, out)
    build_index(root)
    print(rel(root, out))
    return out


def build_index(root: Path) -> Path:
    ensure_history(root)
    history = root / HISTORY_DIR
    lines = [
        "# History Index",
        "",
        f"Generated: {display_time()}",
        "",
        "## Current Context",
        "",
        "- `history/CONTEXT.md`",
        "- `history/README.md`",
        "",
        "## Latest Records",
        "",
    ]
    for folder in ["daily", "changes", "decisions", "ideas", "experiments", "handoffs", "capsules", "sessions"]:
        files = sorted((history / folder).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        lines.append(f"### {folder}")
        lines.append("")
        if not files:
            lines.append("- none")
        for path in files[:12]:
            title = first_heading(path)
            lines.append(f"- `{rel(root, path)}` - {title}")
        lines.append("")
    collab_files = []
    for folder in ["canonical", "tasks", "inbox"]:
        base = history / folder
        if base.exists():
            collab_files.extend(p for p in base.rglob("*.md") if "/templates/" not in p.as_posix())
    lines.append("## Collaboration")
    lines.append("")
    if not collab_files:
        lines.append("- none")
    for path in sorted(collab_files, key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        title = first_heading(path)
        lines.append(f"- `{rel(root, path)}` - {title} (approval={approval_status(path)})")
    lines.append("")
    archive = history / "archive"
    archive_files = []
    if archive.exists():
        archive_files = [
            p
            for p in archive.rglob("*.md")
            if p.name != "README.md" and "/templates/" not in p.as_posix()
        ]
    lines.append("## Archive")
    lines.append("")
    lines.append("Archive records are tracked for provenance but excluded from default collaboration recall.")
    lines.append("")
    if not archive_files:
        lines.append("- none")
    for path in sorted(archive_files, key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        title = first_heading(path)
        lines.append(
            f"- `{rel(root, path)}` - {title} "
            f"(kind={record_kind(path)}, approval={approval_status(path)}, archive_status={archive_status(path)})"
        )
    lines.append("")
    out = history / "INDEX.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return path.stem


def record_kind(path: Path) -> str:
    if path.name == "CONTEXT.md":
        return "context"
    if path.name == "README.md":
        return "readme"
    parts = path.parts
    if "archive" in parts:
        archive_idx = parts.index("archive")
        if len(parts) > archive_idx + 1:
            return parts[archive_idx + 1]
        return "archive"
    if "canonical" in parts:
        return "canonical"
    if "inbox" in parts:
        return "inbox"
    if "tasks" in parts:
        if path.name == "context.md":
            return "task-context"
        if "workstreams" in parts:
            return "workstream"
        return "tasks"
    return path.parent.name


def split_identifier_text(text: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    value = re.sub(r"[/_.:-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def bm25_file_paths(root: Path) -> list[Path]:
    paths = []
    for path in iter_search_files(root):
        if path.name == "INDEX.md":
            continue
        if path.name.startswith("."):
            continue
        paths.append(path)
    return paths


def bm25_documents(root: Path) -> list[dict[str, str]]:
    docs = []
    for path in bm25_file_paths(root):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        docs.extend(
            search_documents_for_file(
                root=root,
                path=path,
                raw=raw,
                approval=approval_status(path),
                archive_state=archive_status(path),
            )
        )
    return docs


def metadata_context(text: str) -> str:
    first_section = re.search(r"^##\s+", text, flags=re.MULTILINE)
    if not first_section:
        return ""
    return text[: first_section.start()].strip()


def markdown_sections(text: str) -> list[tuple[str, str, int]]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE))
    if not matches:
        return [(first_nonempty_line(text) or "Full Record", text, 0)]

    sections: list[tuple[str, str, int]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        heading = match.group(1).strip() or "Section"
        sections.append((heading, text[start:end], start))
    return sections


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"\n\s*\n", text):
        end = match.end()
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def char_spans(start: int, end: int, target_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(end, cursor + target_chars)
        spans.append((cursor, chunk_end))
        if chunk_end >= end:
            break
        cursor = max(cursor + 1, chunk_end - overlap_chars)
    return spans


def split_text_spans(text: str, target_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    if len(text) <= target_chars:
        return [(0, len(text))]

    paragraphs = paragraph_spans(text)
    if not paragraphs:
        return char_spans(0, len(text), target_chars, overlap_chars)

    spans: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None
    for para_start, para_end in paragraphs:
        if para_end - para_start > target_chars:
            if current_start is not None and current_end is not None:
                spans.append((current_start, current_end))
                current_start = None
                current_end = None
            spans.extend(char_spans(para_start, para_end, target_chars, overlap_chars))
            continue

        if current_start is None:
            current_start = para_start
            current_end = para_end
        elif para_end - current_start <= target_chars:
            current_end = para_end
        else:
            spans.append((current_start, current_end or para_start))
            current_start = max(0, para_start - overlap_chars)
            current_end = para_end

    if current_start is not None and current_end is not None:
        spans.append((current_start, current_end))
    return spans


def line_number_at(text: str, char_offset: int) -> int:
    bounded = max(0, min(char_offset, len(text)))
    return text.count("\n", 0, bounded) + 1


def record_text_chunks(text: str) -> list[dict[str, str]]:
    if len(text) <= CHUNK_SMALL_FILE_THRESHOLD:
        return [
            {
                "text": text,
                "heading": first_nonempty_line(text) or "Full Record",
                "line_start": "1",
                "chunk_id": "1",
                "chunk_count": "1",
            }
        ]

    context = metadata_context(text)
    chunks: list[dict[str, str]] = []
    for heading, section_text, section_start in markdown_sections(text):
        for span_start, span_end in split_text_spans(section_text, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS):
            body = section_text[span_start:span_end].strip()
            if not body:
                continue
            chunk_text = "\n\n".join(part for part in [context, body] if part).strip()
            chunks.append(
                {
                    "text": chunk_text,
                    "heading": heading,
                    "line_start": str(line_number_at(text, section_start + span_start)),
                }
            )

    if not chunks:
        return [
            {
                "text": text,
                "heading": first_nonempty_line(text) or "Full Record",
                "line_start": "1",
                "chunk_id": "1",
                "chunk_count": "1",
            }
        ]

    total = str(len(chunks))
    for idx, chunk in enumerate(chunks, 1):
        chunk["chunk_id"] = str(idx)
        chunk["chunk_count"] = total
    return chunks


def search_documents_for_file(
    root: Path,
    path: Path,
    raw: str,
    approval: str,
    archive_state: str,
) -> list[dict[str, str]]:
    relative_path = rel(root, path)
    title = first_heading(path)
    kind = record_kind(path)
    path_terms = split_identifier_text(relative_path)
    title_terms = split_identifier_text(title)
    docs: list[dict[str, str]] = []
    for chunk in record_text_chunks(raw):
        heading = chunk["heading"]
        heading_terms = split_identifier_text(heading)
        weighted_text = "\n".join(
            [
                title,
                title_terms,
                title_terms,
                heading,
                heading_terms,
                relative_path,
                path_terms,
                path_terms,
                kind,
                kind,
                approval,
                archive_state,
                chunk["text"],
            ]
        )
        docs.append(
            {
                "path": relative_path,
                "title": title,
                "heading": heading,
                "line_start": chunk["line_start"],
                "chunk_id": chunk["chunk_id"],
                "chunk_count": chunk["chunk_count"],
                "kind": kind,
                "approval": approval,
                "archive_status": archive_state,
                "text": chunk["text"],
                "index_text": weighted_text,
            }
        )
    return docs


def history_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(TOKEN_PATTERN, text.lower()):
        candidates = [token]
        expanded = split_identifier_text(token).lower()
        if expanded and expanded != token:
            candidates.extend(re.findall(TOKEN_PATTERN, expanded))
        for candidate in candidates:
            if len(candidate) < 2 or candidate in seen:
                continue
            tokens.append(candidate)
            seen.add(candidate)
    return tokens


def fts_quote_token(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def fts_query(tokens: list[str]) -> str:
    return " OR ".join(fts_quote_token(token) for token in tokens)


def sqlite_fts_connection(docs: list[dict[str, str]]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    try:
        con.execute(
            """
            CREATE VIRTUAL TABLE search_docs USING fts5(
                title,
                heading,
                path,
                kind,
                approval,
                archive_status,
                body
            )
            """
        )
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            "SQLite FTS5 is unavailable in this Python build. "
            "Use a Python build with sqlite3 FTS5 support, or run literal `exact` search as a fallback."
        ) from exc
    con.executemany(
        """
        INSERT INTO search_docs(title, heading, path, kind, approval, archive_status, body)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                doc["title"],
                doc.get("heading", ""),
                doc["path"],
                doc["kind"],
                doc.get("approval", "unknown"),
                doc.get("archive_status", "active"),
                doc["index_text"],
            )
            for doc in docs
        ],
    )
    return con


def query_variants(query: str) -> list[tuple[str, str, float]]:
    cleaned = query.strip()
    expanded = split_identifier_text(cleaned)
    lower = cleaned.lower()
    variants: list[tuple[str, str, float]] = [("original", cleaned, 1.0)]
    if expanded and expanded.lower() != cleaned.lower():
        variants.append(("identifier/path expansion", expanded, 0.9))

    intent_expansions = []
    if re.search(r"\b(why|reason|rationale|decision|decide|choice|tradeoff)\b|왜|이유|결정", lower):
        intent_expansions.append("why rationale context decision consequence tradeoff")
    if re.search(r"\b(idea|hypothesis|proposal|future|ablation)\b|아이디어|가설|제안", lower):
        intent_expansions.append("idea problem opportunity hypothesis expected value next check ablation")
    if re.search(r"\b(experiment|eval|evaluation|metric|result|analysis|figure)\b|실험|평가|분석|결과", lower):
        intent_expansions.append("experiment goal setup metrics results artifacts interpretation")
    if re.search(r"\b(code|file|change|implement|implementation|config|script)\b|코드|구현|파일|수정", lower):
        intent_expansions.append("change code file why how validation git status")
    if re.search(r"\b(handoff|collaboration|agent|owner|ownership)\b|협업|인수인계|에이전트", lower):
        intent_expansions.append("handoff summary ownership files next actions risks")

    for idx, expansion in enumerate(intent_expansions, 1):
        variants.append((f"intent expansion {idx}", f"{expanded or cleaned} {expansion}", 0.7))

    seen = set()
    deduped = []
    for label, text, weight in variants:
        key = re.sub(r"\s+", " ", text.lower()).strip()
        if key and key not in seen:
            deduped.append((label, text, weight))
            seen.add(key)
    return deduped


def best_excerpt(text: str, query_tokens: list[str], max_chars: int = 260) -> str:
    lowered_tokens = [token.lower() for token in query_tokens if token]
    fallback = ""
    best_line = ""
    best_score = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not fallback and not stripped.startswith("#"):
            fallback = stripped
        lowered = stripped.lower()
        matched = [token for token in lowered_tokens if token in lowered]
        if matched:
            score = sum(len(token) for token in set(matched))
            if score > best_score:
                best_score = score
                best_line = stripped
    if best_line:
        return best_line[:max_chars]
    return (fallback or first_nonempty_line(text) or "-")[:max_chars]


def first_nonempty_line(text: str) -> str:
    for line in strip_frontmatter(text).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def bm25_search_documents(docs: list[dict[str, str]], query: str, limit: int = 8) -> dict:
    variants = query_variants(query)
    payload = {
        "query": query,
        "variants": variants,
        "results": [],
        "reflection": [],
    }
    if not docs:
        payload["reflection"].append("No history documents are available yet.")
        return payload
    if not variants:
        payload["reflection"].append("The query was empty after normalization.")
        return payload

    con = sqlite_fts_connection(docs)
    vocab: set[str] = set()
    for doc in docs:
        vocab.update(history_tokens(doc["index_text"]))

    combined = [0.0 for _ in docs]
    contributing: list[list[str]] = [[] for _ in docs]
    all_query_tokens: list[str] = []
    original_query_tokens: list[str] = []
    for label, text, weight in variants:
        tokens = history_tokens(text)
        if label == "original":
            original_query_tokens = list(tokens)
        all_query_tokens.extend(tokens)
        if not tokens:
            continue
        try:
            rows = con.execute(
                """
                SELECT rowid, bm25(search_docs, 4.0, 3.0, 2.5, 1.5, 0.7, 0.7, 1.0) AS score
                FROM search_docs
                WHERE search_docs MATCH ?
                ORDER BY score ASC
                """,
                (fts_query(tokens),),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for rowid, score in rows:
            idx = int(rowid) - 1
            if idx < 0 or idx >= len(docs):
                continue
            weighted = max(0.0, -float(score)) * weight
            if weighted > 0:
                combined[idx] += weighted
                contributing[idx].append(label)

    ranked = sorted(enumerate(combined), key=lambda item: item[1], reverse=True)
    query_counter = Counter(all_query_tokens)
    original_unknown = sorted([token for token in set(original_query_tokens) if token not in vocab])
    generated_unknown = sorted(
        [token for token in query_counter if token not in vocab and token not in original_unknown]
    )
    found_tokens = sorted([token for token in query_counter if token in vocab])
    excerpt_tokens = [token for token in original_query_tokens if token in vocab] or found_tokens or all_query_tokens

    results = []
    for idx, score in ranked[:limit]:
        if score <= 0:
            continue
        doc = docs[idx]
        results.append(
            {
                "score": score,
                "path": doc["path"],
                "title": doc["title"],
                "heading": doc.get("heading", ""),
                "line_start": doc.get("line_start", "1"),
                "chunk_id": doc.get("chunk_id", "1"),
                "chunk_count": doc.get("chunk_count", "1"),
                "kind": doc["kind"],
                "approval": doc.get("approval", "unknown"),
                "archive_status": doc.get("archive_status", "active"),
                "variants": sorted(set(contributing[idx])),
                "excerpt": best_excerpt(doc["text"], excerpt_tokens),
            }
        )

    payload["results"] = results
    payload["reflection"] = reflect_bm25_results(
        query, variants, results, original_unknown, generated_unknown
    )
    return payload


def bm25_search(root: Path, query: str, limit: int = 8) -> dict:
    return bm25_search_documents(bm25_documents(root), query, limit)


def reflect_bm25_results(
    query: str,
    variants: list[tuple[str, str, float]],
    results: list[dict],
    original_unknown: list[str],
    generated_unknown: list[str],
) -> list[str]:
    notes = []
    if not results:
        notes.append("No positive BM25 hit. Try exact file names, method names, dataset IDs, or record-type words such as decision, idea, change, experiment.")
    elif len(results) < 3:
        notes.append("Only a few records matched. Treat the recall as partial and verify current files before acting.")

    if original_unknown:
        preview = ", ".join(original_unknown[:8])
        notes.append(f"Some original query tokens were absent from the history index: {preview}.")
    elif generated_unknown:
        preview = ", ".join(generated_unknown[:8])
        notes.append(f"Some generated expansion tokens were absent from the history index: {preview}.")

    if results:
        kinds = Counter(result["kind"] for result in results)
        if len(kinds) == 1:
            only_kind = next(iter(kinds))
            notes.append(f"All top hits are `{only_kind}` records; consider a narrower query if you need decisions, ideas, experiments, or code changes specifically.")
        top_score = results[0]["score"]
        tail_score = results[-1]["score"]
        if top_score > 0 and tail_score / top_score < 0.15 and len(results) > 1:
            notes.append("The top hit is much stronger than the tail; read it first before broadening the search.")

    generated = [text for _, text, _ in variants[1:]]
    if generated:
        notes.append("Generated query variants were used; inspect them if the ranking feels off.")
    return notes


def print_bm25_payload(payload: dict, show_variants: bool = True) -> None:
    if show_variants:
        print("## Generated Queries")
        print("")
        for label, text, weight in payload["variants"]:
            print(f"- {label} (weight {weight:g}): {text}")
        print("")

    print("## BM25 Results")
    print("")
    if not payload["results"]:
        print("- none")
    for rank, result in enumerate(payload["results"], 1):
        variants = ", ".join(result["variants"]) if result["variants"] else "-"
        print(f"{rank}. `{result['path']}` - {result['title']}")
        approval = result.get("approval", "unknown")
        archive_state = result.get("archive_status", "active")
        print(
            f"   score={result['score']:.4f}; kind={result['kind']}; "
            f"approval={approval}; archive_status={archive_state}; matched={variants}"
        )
        print(
            f"   location=chunk {result.get('chunk_id', '1')}/{result.get('chunk_count', '1')}; "
            f"line={result.get('line_start', '1')}; heading={result.get('heading') or '-'}"
        )
        print(f"   excerpt: {result['excerpt']}")
    print("")

    print("## Reflection")
    print("")
    if not payload["reflection"]:
        print("- BM25 recall found usable matches.")
    else:
        for note in payload["reflection"]:
            print(f"- {note}")


def cmd_bootstrap(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    if args.today:
        today_file(root)
    out = build_index(root)
    print(f"OK: {rel(root, out)}")


def cmd_today(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    path = today_file(root)
    build_index(root)
    print(rel(root, path))


def cmd_index(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    print(rel(root, build_index(root)))


def cmd_change(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    title = args.title
    filename = f"{time_stamp()}-{slugify(title, 'change')}.md"
    ensure_history(root)
    template = root / HISTORY_DIR / "templates" / "change.md"
    text = template.read_text(encoding="utf-8")
    text = (
        text.replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{agent}}", value(args.agent))
        .replace("{{status}}", value(args.status))
        .replace("{{why}}", value(args.why))
        .replace("{{how}}", value(args.how))
        .replace("{{files}}", bullets(args.file))
        .replace("{{validation}}", bullets(args.validation))
        .replace("{{risks}}", value(args.risk))
    )
    if not args.no_git_status:
        text += "\n## Git Status Snapshot\n\n```text\n" + git_status(root) + "\n```\n"
    write_record(root, "changes", filename, text, "change", title)


def cmd_decision(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "decisions"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'decision')}.md"
    text = (root / HISTORY_DIR / "templates" / "decision.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{context}}", value(args.context))
        .replace("{{decision}}", value(args.decision))
        .replace("{{rationale}}", value(args.rationale))
        .replace("{{consequences}}", value(args.consequence))
    )
    write_record(root, "decisions", filename, text, "decision", title)


def cmd_idea(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "ideas"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'idea')}.md"
    text = (root / HISTORY_DIR / "templates" / "idea.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{tags}}", ", ".join(args.tag or []) or "-")
        .replace("{{problem}}", value(args.problem))
        .replace("{{hypothesis}}", value(args.hypothesis))
        .replace("{{expected}}", value(args.expected))
        .replace("{{links}}", bullets(args.link))
        .replace("{{next}}", value(args.next))
    )
    write_record(root, "ideas", filename, text, "idea", title)


def cmd_experiment(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "experiments"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'experiment')}.md"
    text = (root / HISTORY_DIR / "templates" / "experiment.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{tags}}", ", ".join(args.tag or []) or "-")
        .replace("{{goal}}", value(args.goal))
        .replace("{{setup}}", value(args.setup))
        .replace("{{metrics}}", bullets(args.metric))
        .replace("{{results}}", value(args.result))
        .replace("{{artifacts}}", bullets(args.artifact))
        .replace("{{next}}", value(args.next))
    )
    write_record(root, "experiments", filename, text, "experiment", title)


def cmd_handoff(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    title = args.title
    task = normalize_collab_id(args.task, "task") if args.task else ""
    workstream = normalize_collab_id(args.workstream, "workstream") if args.workstream else ""
    filename = f"{time_stamp()}-{slugify(title, 'handoff')}.md"
    text = (root / HISTORY_DIR / "templates" / "handoff.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{to}}", value(args.to))
        .replace("{{task}}", task)
        .replace("{{workstream}}", workstream)
        .replace("{{summary}}", value(args.summary))
        .replace("{{files}}", bullets(args.file))
        .replace("{{next}}", value(args.next))
        .replace("{{risks}}", value(args.risk))
    )
    text = set_metadata_line(text, "Task", task)
    text = set_metadata_line(text, "Workstream", workstream)
    if task or workstream:
        text = set_metadata_line(text, "Approval Status", "accepted")
        text = set_metadata_line(text, "Promoted To", "-")
        text = set_metadata_line(text, "Archived", "no")
        text = set_metadata_line(text, "Archived Date", "-")
    write_record(root, "handoffs", filename, text, "handoff", title)


def format_bm25_read_first(payload: dict) -> str:
    if not payload["results"]:
        return "-"
    lines = []
    for rank, result in enumerate(payload["results"], 1):
        lines.append(
            f"{rank}. `{result['path']}` - {result['title']} "
            f"(kind={result['kind']}, score={result['score']:.4f})"
        )
        lines.append(f"   - {result['excerpt']}")
    return "\n".join(lines)


def format_generated_queries(payload: dict) -> str:
    if not payload["variants"]:
        return "-"
    return "\n".join(
        f"- {label} (weight {weight:g}): {text}"
        for label, text, weight in payload["variants"]
    )


def format_reflection(payload: dict) -> str:
    if not payload["reflection"]:
        return "- BM25 recall found usable matches."
    return "\n".join(f"- {note}" for note in payload["reflection"])


def latest_capsule(root: Path) -> Path | None:
    folder = root / HISTORY_DIR / "capsules"
    if not folder.exists():
        return None
    files = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def cmd_handoff_agent_capsule_create(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    task = args.task
    collab_task = normalize_collab_id(args.collab_task, "task") if args.collab_task else ""
    workstream = normalize_collab_id(args.workstream, "workstream") if args.workstream else ""
    query = args.query or task
    payload = bm25_search(root, query, args.limit)
    context = root / HISTORY_DIR / "CONTEXT.md"
    project_context = clip(context.read_text(encoding="utf-8"), args.context_chars)
    filename = f"{time_stamp()}-{slugify(task, 'handoff-agent-capsule')}.md"
    template = root / HISTORY_DIR / "templates" / "handoff-agent-capsule.md"
    text = template.read_text(encoding="utf-8")
    text = (
        text.replace("{{task}}", task)
        .replace("{{collab_task}}", collab_task)
        .replace("{{workstream}}", workstream)
        .replace("{{date}}", display_time())
        .replace("{{from_agent}}", value(args.from_agent))
        .replace("{{to_agent}}", value(args.to_agent))
        .replace("{{target_host}}", value(args.target_host))
        .replace("{{status}}", value(args.status))
        .replace("{{requirements}}", bullets(args.user_requirement))
        .replace("{{current_state}}", value(args.current_state))
        .replace("{{reasoning_summary}}", value(args.reasoning_summary))
        .replace("{{files}}", bullets(args.file))
        .replace("{{validation}}", bullets(args.validation))
        .replace("{{risks}}", bullets(args.risk))
        .replace("{{next_actions}}", bullets(args.next_action))
        .replace("{{read_first}}", format_bm25_read_first(payload))
        .replace("{{generated_queries}}", format_generated_queries(payload))
        .replace("{{reflection}}", format_reflection(payload))
        .replace("{{project_context}}", project_context.rstrip())
        .replace("{{git_status}}", git_status(root))
    )
    text = set_metadata_line(text, "Task", collab_task)
    text = set_metadata_line(text, "Workstream", workstream)
    if collab_task or workstream:
        text = set_metadata_line(text, "Approval Status", "accepted")
        text = set_metadata_line(text, "Promoted To", "-")
        text = set_metadata_line(text, "Archived", "no")
        text = set_metadata_line(text, "Archived Date", "-")
    write_record(root, "capsules", filename, text, "handoff-agent-capsule", task)


def cmd_handoff_agent_capsule_resume(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    capsule: Path | None = None
    if args.path:
        capsule = (root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path).resolve()
    elif args.query:
        payload = bm25_search(root, args.query, max(args.limit, 5))
        for result in payload["results"]:
            candidate = root / result["path"]
            if record_kind(candidate) == "capsules":
                capsule = candidate
                break
        if capsule is None:
            capsule = latest_capsule(root)
    else:
        capsule = latest_capsule(root)

    if capsule is None or not capsule.exists():
        print("No handoff agent capsule found.")
        return

    print(f"# Resume From Handoff Agent Capsule")
    print("")
    print(f"Capsule: `{rel(root, capsule)}`")
    print("")
    text = capsule.read_text(encoding="utf-8")
    print(text.rstrip() if args.full else clip(text, args.chars).rstrip())

    if args.query:
        print("")
        print("## Additional BM25 Recall")
        print("")
        payload = bm25_search(root, args.query, args.limit)
        print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_handoff_agent_capsule_import(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    source = Path(args.file).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Capsule file does not exist: {source}")
    title = args.title or first_heading(source).replace("Handoff Agent Capsule - ", "")
    filename = f"{time_stamp()}-{slugify(title, 'imported-handoff-agent-capsule')}.md"
    raw = source.read_text(encoding="utf-8")
    text = "\n".join(
        [
            f"# Imported Handoff Agent Capsule - {title}",
            "",
            f"Date Imported: {display_time()}",
            f"Source: {source}",
            f"Imported By: {value(args.agent)}",
            "",
            "## Imported Content",
            "",
            raw.rstrip(),
            "",
        ]
    )
    write_record(root, "capsules", filename, text, "handoff-agent-capsule-import", title)


def cmd_session(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    task = args.task
    agent = args.agent or "agent"
    filename = f"{time_stamp()}-{slugify(agent, 'agent')}-{slugify(task, 'session')}.md"
    text = (root / HISTORY_DIR / "templates" / "session.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{task}}", task)
        .replace("{{date}}", display_time())
        .replace("{{agent}}", agent)
        .replace("{{scope}}", value(args.scope))
    )
    write_record(root, "sessions", filename, text, "session", task)


def iter_history_files(root: Path) -> list[Path]:
    history = root / HISTORY_DIR
    if not history.exists():
        return []
    files = [p for p in history.rglob("*.md") if "/templates/" not in p.as_posix()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def iter_search_files(root: Path) -> list[Path]:
    def rank(path: Path) -> tuple[int, float]:
        parent = path.parent.name
        parts = path.parts
        if path.name == "CONTEXT.md" or "canonical" in parts:
            bucket = 0
        elif "tasks" in parts and "workstreams" not in parts:
            bucket = 1
        elif "tasks" in parts and "workstreams" in parts:
            bucket = 2
        elif parent in {"changes", "decisions", "ideas", "experiments", "handoffs", "capsules", "sessions"}:
            bucket = 3
        elif parent == "daily":
            bucket = 4
        elif path.name in {"INDEX.md", "README.md"}:
            bucket = 5
        elif "inbox" in parts:
            bucket = 6
        else:
            bucket = 7
        return (bucket, -path.stat().st_mtime)

    return sorted(iter_history_files(root), key=rank)


def lint_requires_frontmatter(root: Path, path: Path) -> bool:
    if path.name in {"CONTEXT.md", "INDEX.md", "README.md"}:
        return False
    parts = path.relative_to(root).parts
    if "templates" in parts:
        return False
    return HISTORY_DIR in parts


def wikilink_target(raw: str) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    if target.endswith(".md"):
        target = target[:-3]
    return target.strip("/")


def note_indexes(root: Path) -> tuple[set[str], dict[str, list[Path]]]:
    history = root / HISTORY_DIR
    path_index: set[str] = set()
    stem_index: dict[str, list[Path]] = {}
    for path in iter_history_files(root):
        if path.name == "INDEX.md":
            continue
        history_rel = path.relative_to(history).with_suffix("").as_posix()
        root_rel = path.relative_to(root).with_suffix("").as_posix()
        path_index.add(history_rel)
        path_index.add(root_rel)
        stem_index.setdefault(path.stem.lower(), []).append(path)
    return path_index, stem_index


def resolve_wikilink(
    target: str,
    path_index: set[str],
    stem_index: dict[str, list[Path]],
) -> tuple[str, list[Path]]:
    if not target:
        return ("local-anchor", [])
    normalized = target[:-3] if target.endswith(".md") else target
    normalized = normalized.strip("/")
    if "/" in normalized:
        if normalized in path_index:
            return ("ok", [])
        if f"{HISTORY_DIR}/{normalized}" in path_index:
            return ("ok", [])
        return ("missing", [])
    matches = stem_index.get(normalized.lower(), [])
    if not matches:
        return ("missing", [])
    if len(matches) > 1:
        return ("ambiguous", matches)
    return ("ok", matches)


def format_lint_section(title: str, items: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("- none")
    lines.append("")
    return lines


def lint_history(root: Path, max_chars: int) -> tuple[list[str], list[str]]:
    ensure_history(root)
    errors: list[str] = []
    warnings: list[str] = []
    path_index, stem_index = note_indexes(root)
    wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")

    for path in sorted(iter_history_files(root), key=lambda p: rel(root, p)):
        relative = rel(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"{relative}: cannot read file ({exc})")
            continue

        if lint_requires_frontmatter(root, path) and not has_frontmatter(text):
            warnings.append(f"{relative}: missing YAML frontmatter for Obsidian navigation.")

        if len(text) > max_chars:
            warnings.append(f"{relative}: oversized note ({len(text)} chars > {max_chars}); split or archive if it becomes hard to scan.")

        for match in wikilink_pattern.finditer(text):
            raw_target = match.group(1).strip()
            target = wikilink_target(raw_target)
            state, matches = resolve_wikilink(target, path_index, stem_index)
            if state == "missing":
                errors.append(f"{relative}: broken wikilink [[{raw_target}]]")
            elif state == "ambiguous":
                choices = ", ".join(rel(root, item) for item in sorted(matches)[:5])
                warnings.append(f"{relative}: ambiguous wikilink [[{raw_target}]] matches {choices}")

    return errors, warnings


def cmd_lint(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    errors, warnings = lint_history(root, args.max_chars)
    lines = ["# History Lint", ""]
    lines.extend(format_lint_section("Errors", errors))
    lines.extend(format_lint_section("Warnings", warnings))
    lines.append(f"Summary: errors={len(errors)} warnings={len(warnings)}")
    print("\n".join(lines))
    if errors or (args.strict and warnings):
        raise SystemExit(1)


def clip(text: str, limit: int = 2800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]\n"


def search_lines(root: Path, query: str, limit: int) -> list[str]:
    results: list[str] = []
    needle = query.lower()
    for path in iter_search_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, 1):
            if needle in line.lower():
                snippet = line.strip()
                results.append(f"{rel(root, path)}:{idx}: {snippet}")
                if len(results) >= limit:
                    return results
    return results


def cmd_search(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    if args.exact:
        results = search_lines(root, args.query, args.limit)
        if not results:
            print("No matches.")
            return
        print("\n".join(results))
        return

    payload = bm25_search(root, args.query, args.limit)
    print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_exact(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    results = search_lines(root, args.query, args.limit)
    if not results:
        print("No matches.")
        return
    print("\n".join(results))


def cmd_recent(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    for path in iter_history_files(root)[: args.limit]:
        print(f"{rel(root, path)} - {first_heading(path)}")


def cmd_recall(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    today_file(root)
    build_index(root)

    print(f"# Recall ({root})")
    print("")
    context = root / HISTORY_DIR / "CONTEXT.md"
    print(f"## {rel(root, context)}")
    print("")
    print(clip(context.read_text(encoding="utf-8"), args.context_chars).rstrip())
    print("")

    latest_daily = sorted((root / HISTORY_DIR / "daily").glob("*.md"), reverse=True)
    if latest_daily:
        print(f"## Latest Daily: {rel(root, latest_daily[0])}")
        print("")
        print(clip(latest_daily[0].read_text(encoding="utf-8"), args.daily_chars).rstrip())
        print("")

    print("## Recent Records")
    print("")
    count = 0
    for path in iter_history_files(root):
        if path.name in {"CONTEXT.md", "INDEX.md", "README.md"} or "/daily/" in path.as_posix():
            continue
        print(f"- `{rel(root, path)}` - {first_heading(path)}")
        count += 1
        if count >= args.limit:
            break
    if count == 0:
        print("- none")
    print("")

    if args.query:
        print(f"## BM25 Recall: {args.query}")
        print("")
        payload = bm25_search(root, args.query, args.limit)
        print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_collab_bootstrap(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_collab(root)
    tasks = list(args.task or [])
    if args.task_count:
        width = max(2, len(str(args.task_count)))
        tasks.extend(f"task-{idx:0{width}d}" for idx in range(1, args.task_count + 1))
    workstreams = list(args.workstream or [])
    if args.default_workstreams or (tasks and not workstreams):
        workstreams = DEFAULT_COLLAB_WORKSTREAMS
    for task in tasks:
        ensure_collab_task(root, task, workstreams)
    out = build_index(root)
    print(f"OK: {rel(root, out)}")
    print(f"Collaboration root: {HISTORY_DIR}/")


def cmd_collab_submit_summary(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_collab(root)
    task = normalize_collab_id(args.task, "task")
    workstream = normalize_collab_id(args.workstream, "workstream")
    title = args.title or f"{task}-{workstream}-summary"
    warnings = detect_sensitive_warnings(
        [
            ("summary", args.summary),
            ("claims", "\n".join(args.claim or [])),
            ("evidence", "\n".join(args.evidence or [])),
            ("changed files", "\n".join(args.changed_file or [])),
            ("validation", "\n".join(args.validation or [])),
            ("open questions", "\n".join(args.open_question or [])),
            ("proposed decisions", "\n".join(args.proposed_decision or [])),
            ("private references", "\n".join(args.private_reference or [])),
        ]
    )
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if args.strict:
            raise SystemExit("Sensitive-looking content detected; rerun after removing it or omit --strict.")

    filename = (
        f"{time_stamp()}-{task}-{workstream}-"
        f"{normalize_collab_id(args.person, 'person')}-{normalize_collab_id(args.agent, 'agent')}-"
        f"{slugify(title, 'summary')}.md"
    )
    template = root / HISTORY_DIR / "templates" / "collab-summary.md"
    text = template.read_text(encoding="utf-8")
    text = (
        text.replace("{{task}}", task)
        .replace("{{workstream}}", workstream)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{person}}", value(args.person))
        .replace("{{agent}}", value(args.agent))
        .replace("{{summary}}", value(args.summary))
        .replace("{{claims}}", bullets(args.claim))
        .replace("{{evidence}}", bullets(args.evidence))
        .replace("{{changed_files}}", bullets(args.changed_file))
        .replace("{{validation}}", bullets(args.validation))
        .replace("{{open_questions}}", bullets(args.open_question))
        .replace("{{proposed_decisions}}", bullets(args.proposed_decision))
        .replace("{{private_references}}", bullets(args.private_reference))
        .replace("{{warnings}}", bullets(warnings) if warnings else "-")
    )
    text = set_metadata_line(text, "Task", task)
    text = set_metadata_line(text, "Workstream", workstream)
    text = set_metadata_line(text, "Approval Status", "submitted")
    text = set_metadata_line(text, "Promoted To", "-")
    text = set_metadata_line(text, "Archived", "no")
    text = set_metadata_line(text, "Archived Date", "-")
    text = add_obsidian_frontmatter(
        text,
        "inbox",
        title,
        {
            "task": task,
            "workstream": workstream,
            "person": value(args.person),
            "agent": value(args.agent),
            "approval_status": "submitted",
            "promoted_to": "-",
            "archived": False,
            "archived_date": "-",
        },
    )
    inbox = root / HISTORY_DIR / "inbox" / filename
    inbox.write_text(text, encoding="utf-8")
    append_daily(root, "collab-summary", title, inbox)
    build_index(root)
    print(rel(root, inbox))


def resolve_history_path(root: Path, path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def validate_promote_inbox_source(root: Path, source: Path) -> None:
    inbox_dir = (root / HISTORY_DIR / "inbox").resolve()
    if not source.exists():
        raise SystemExit(f"Inbox file does not exist: {source}")
    if not source.is_file():
        raise SystemExit(f"Promote source must be a markdown file inside {rel(root, inbox_dir)}: {source}")
    if source.suffix.lower() != ".md":
        raise SystemExit(f"Promote source must be a .md file inside {rel(root, inbox_dir)}: {source}")
    if source.name == "README.md":
        raise SystemExit("history/inbox/README.md cannot be promoted.")
    if not is_relative_to(source.resolve(), inbox_dir):
        raise SystemExit(f"Promote source must be inside {rel(root, inbox_dir)}: {source}")


def promotion_sections(raw: str, note: str | None, include_submitted_sections: bool = False) -> str:
    lines = ["### Maintainer Note", "", value(note) if note else value(extract_section(raw, "Summary"))]
    if note and not include_submitted_sections:
        return "\n".join(lines).rstrip() + "\n"
    for heading in ["Claims", "Evidence", "Changed Files", "Validation", "Open Questions", "Proposed Decisions"]:
        section = extract_section(raw, heading)
        if section and section.strip() != "-":
            lines.extend(["", f"### {heading}", "", section])
    return "\n".join(lines).rstrip() + "\n"


def append_promoted_update(
    root: Path,
    target_path: Path,
    title: str,
    source_path: Path,
    task: str,
    workstream: str,
    maintainer: str,
    body: str,
) -> None:
    if not target_path.exists():
        if target_path.name == "context.md":
            ensure_collab_task(root, task, [])
        elif "workstreams" in target_path.parts:
            ensure_collab_task(root, task, [workstream])
    raw = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    raw = update_last_updated(raw) if raw else raw
    update = "\n".join(
        [
            "",
            f"## Accepted Update - {title}",
            "",
            f"Date: {display_time()}",
            f"Source: `{rel(root, source_path)}`",
            f"Task: {task}",
            f"Workstream: {workstream}",
            f"Promoted By: {maintainer}",
            "Approval Status: accepted",
            "",
            body.rstrip(),
            "",
        ]
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(raw.rstrip() + "\n" + update, encoding="utf-8")


def mark_inbox_promoted(root: Path, source_path: Path, target_path: Path, maintainer: str) -> None:
    raw = source_path.read_text(encoding="utf-8")
    raw = set_metadata_line(raw, "Approval Status", "accepted")
    raw = set_metadata_line(raw, "Promoted To", rel(root, target_path))
    raw = set_metadata_line(raw, "Promoted Date", display_time())
    raw = set_metadata_line(raw, "Promoted By", maintainer)
    raw = set_metadata_line(raw, "Archived", "no")
    raw = set_metadata_line(raw, "Archived Date", "-")
    source_path.write_text(raw, encoding="utf-8")


def cmd_collab_promote(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_collab(root)
    source = resolve_history_path(root, args.inbox)
    validate_promote_inbox_source(root, source)
    raw = source.read_text(encoding="utf-8")
    warnings = detect_sensitive_warnings([("inbox file", raw), ("maintainer note", args.note)])
    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        if args.strict:
            raise SystemExit("Sensitive-looking content detected; rerun after removing it or omit --strict.")

    meta = parse_metadata(raw)
    task = normalize_collab_id(args.task or meta.get("task", "cross-task"), "task")
    workstream = normalize_collab_id(args.workstream or meta.get("workstream", "cross-workstream"), "workstream")
    title = args.title or first_heading(source).replace("Inbox Summary - ", "").strip() or source.stem
    body = promotion_sections(raw, args.note, args.include_submitted_sections)

    if args.target == "canonical":
        target = root / HISTORY_DIR / "canonical" / "overview.md"
        append_promoted_update(root, target, title, source, task, workstream, args.maintainer, body)
        append_daily(root, "collab-promote", title, target)
    elif args.target == "task":
        target = task_context_path(root, task)
        append_promoted_update(root, target, title, source, task, workstream, args.maintainer, body)
        append_daily(root, "collab-promote", title, target)
    elif args.target == "workstream":
        target = workstream_context_path(root, task, workstream)
        append_promoted_update(root, target, title, source, task, workstream, args.maintainer, body)
        append_daily(root, "collab-promote", title, target)
    elif args.target == "decision":
        folder = root / HISTORY_DIR / "decisions"
        rid = next_id(folder)
        target = folder / f"{rid}-{slugify(title, 'collab-decision')}.md"
        decision_text = "\n".join(
            [
                f"# Decision {rid} - {title}",
                "",
                f"Date: {display_time()}",
                "Status: accepted",
                f"Task: {task}",
                f"Workstream: {workstream}",
                f"Source: `{rel(root, source)}`",
                f"Promoted By: {args.maintainer}",
                "Approval Status: accepted",
                "Promoted To: -",
                "Archived: no",
                "Archived Date: -",
                "",
                "## Context",
                "",
                value(args.context) if args.context else value(extract_section(raw, "Summary")),
                "",
                "## Decision",
                "",
                value(args.decision) if args.decision else value(extract_section(raw, "Proposed Decisions")),
                "",
                "## Rationale / Evidence",
                "",
                value(args.rationale) if args.rationale else value(extract_section(raw, "Evidence")),
                "",
                "## Consequences / Open Questions",
                "",
                value(args.consequence) if args.consequence else value(extract_section(raw, "Open Questions")),
                "",
            ]
        )
        decision_text = add_obsidian_frontmatter(
            decision_text,
            "decision",
            title,
            {
                "task": task,
                "workstream": workstream,
                "status": "accepted",
                "approval_status": "accepted",
                "archived": False,
            },
        )
        target.write_text(decision_text, encoding="utf-8")
        append_daily(root, "decision", title, target)
    else:
        raise SystemExit(f"Unsupported promote target: {args.target}")

    mark_inbox_promoted(root, source, target, args.maintainer)
    build_index(root)
    print(rel(root, target))


def parse_archive_include(value_text: str | None) -> list[str]:
    if not value_text:
        return ["inbox"]
    requested = [item.strip().lower() for item in value_text.split(",") if item.strip()]
    unknown = sorted(set(requested) - set(ARCHIVE_TYPES))
    if unknown:
        raise SystemExit(
            "Unsupported archive include value(s): "
            + ", ".join(unknown)
            + f". Supported values: {', '.join(ARCHIVE_TYPES)}"
        )
    return requested or ["inbox"]


def is_older_than(path: Path, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone() < cutoff


def promoted_to_value(path: Path) -> str:
    value_text = metadata_value(path, "Promoted To", "")
    return "" if value_text in {"", "-"} else value_text


def record_month(path: Path) -> str:
    match = re.search(r"(\d{4})-(\d{2})", path.name)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    try:
        meta = parse_metadata(path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    for key in ["date", "promoted date", "last updated"]:
        match = re.search(r"(\d{4})-(\d{2})", meta.get(key, ""))
        if match:
            return f"{match.group(1)}-{match.group(2)}"
    return now().strftime("%Y-%m")


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}-{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def archive_destination(root: Path, archive_type: str, source: Path) -> Path:
    month = record_month(source)
    return root / HISTORY_DIR / "archive" / archive_type / month / source.name


def archive_candidate_paths(
    root: Path,
    include_types: list[str],
    older_than_days: int | None = None,
) -> list[tuple[str, Path]]:
    history = root / HISTORY_DIR
    cutoff = now() - timedelta(days=older_than_days) if older_than_days is not None else None
    candidates: list[tuple[str, Path]] = []
    if "inbox" in include_types:
        inbox = history / "inbox"
        if inbox.exists():
            for path in sorted(inbox.glob("*.md"), key=lambda p: p.stat().st_mtime):
                if path.name == "README.md" or not path.is_file():
                    continue
                if approval_status(path) != "accepted":
                    continue
                if not promoted_to_value(path):
                    continue
                if archive_status(path) == "archived":
                    continue
                if not is_older_than(path, cutoff):
                    continue
                candidates.append(("inbox", path))
    for archive_type in ["daily", "sessions"]:
        if archive_type not in include_types or cutoff is None:
            continue
        base = history / archive_type
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime):
            if not path.is_file():
                continue
            if archive_status(path) == "archived":
                continue
            if not is_older_than(path, cutoff):
                continue
            candidates.append((archive_type, path))
    return candidates


def archived_copy_text(root: Path, source: Path) -> str:
    raw = source.read_text(encoding="utf-8")
    raw = set_metadata_line(raw, "Archived", "yes")
    raw = set_metadata_line(raw, "Archived Date", display_time())
    raw = set_metadata_line(raw, "Archived From", rel(root, source))
    return raw


def cmd_collab_archive(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    if args.older_than_days is not None and args.older_than_days < 0:
        raise SystemExit("--older-than-days must be non-negative.")
    include_types = parse_archive_include(args.include)
    if not args.dry_run:
        ensure_collab(root)
    candidates = archive_candidate_paths(root, include_types, args.older_than_days)

    print("# Collaboration Archive")
    print("")
    print(f"Include: {', '.join(include_types)}")
    print(f"Older Than Days: {args.older_than_days if args.older_than_days is not None else '-'}")
    print(f"Dry Run: {'yes' if args.dry_run else 'no'}")
    print("")

    if not candidates:
        print("- no archive candidates")
        return

    if args.dry_run:
        print("## Candidates")
        print("")
        for archive_type, source in candidates:
            destination = archive_destination(root, archive_type, source)
            print(f"- `{rel(root, source)}` -> `{rel(root, destination)}`")
        return

    print("## Archived")
    print("")
    moved: list[Path] = []
    for archive_type, source in candidates:
        destination = unique_destination(archive_destination(root, archive_type, source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(archived_copy_text(root, source), encoding="utf-8")
        source.replace(destination)
        moved.append(destination)
        print(f"- `{rel(root, source)}` -> `{rel(root, destination)}`")
    build_index(root)
    print("")
    print(f"Archived Count: {len(moved)}")


def collab_relevant(path: Path, task: str | None, workstream: str | None) -> bool:
    try:
        meta = parse_metadata(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    meta_task = normalize_collab_id(meta.get("task", ""), "none") if meta.get("task") else ""
    meta_workstream = normalize_collab_id(meta.get("workstream", ""), "none") if meta.get("workstream") else ""
    if task and meta_task and meta_task not in {task, "all", "cross-task", "none"}:
        return False
    if workstream and meta_workstream and meta_workstream not in {workstream, "all", "cross-workstream", "none"}:
        return False
    return True


def collab_paths(
    root: Path,
    task: str | None,
    workstream: str | None,
    include_inbox: bool = False,
    include_archive: bool = False,
) -> list[Path]:
    history = root / HISTORY_DIR
    paths: list[Path] = []
    overview = history / "canonical" / "overview.md"
    if overview.exists():
        paths.append(overview)
    if task:
        task_path = task_context_path(root, task)
        if task_path.exists():
            paths.append(task_path)
        if workstream:
            workstream_path = workstream_context_path(root, task, workstream)
            if workstream_path.exists():
                paths.append(workstream_path)
    decisions = history / "decisions"
    if decisions.exists():
        for path in sorted(decisions.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if approval_status(path) == "accepted" and collab_relevant(path, task, workstream):
                paths.append(path)
    for folder in ["handoffs", "capsules"]:
        base = history / folder
        if not base.exists():
            continue
        for path in sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            meta = parse_metadata(path.read_text(encoding="utf-8"))
            if not meta.get("task") and not meta.get("workstream"):
                continue
            if collab_relevant(path, task, workstream):
                paths.append(path)
    if include_inbox:
        inbox = history / "inbox"
        if inbox.exists():
            for path in sorted(inbox.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name == "README.md":
                    continue
                if collab_relevant(path, task, workstream):
                    paths.append(path)
    if include_archive:
        archive = history / "archive"
        if archive.exists():
            for path in sorted(archive.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name == "README.md" or not path.is_file():
                    continue
                meta = parse_metadata(path.read_text(encoding="utf-8"))
                if (task or workstream) and record_kind(path) in {"daily", "sessions"}:
                    if not meta.get("task") and not meta.get("workstream"):
                        continue
                if collab_relevant(path, task, workstream):
                    paths.append(path)
    deduped: list[Path] = []
    seen = set()
    for path in paths:
        key = path.resolve()
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def collab_documents(
    root: Path,
    task: str | None,
    workstream: str | None,
    include_inbox: bool = False,
    include_archive: bool = False,
) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for path in collab_paths(root, task, workstream, include_inbox, include_archive):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        docs.extend(
            search_documents_for_file(
                root=root,
                path=path,
                raw=raw,
                approval=approval_status(path),
                archive_state=archive_status(path),
            )
        )
    return docs


def print_context_file(root: Path, label: str, path: Path, chars: int) -> None:
    print(f"## {label}")
    print("")
    if not path.exists():
        print(f"- missing: `{rel(root, path)}`")
        print("")
        return
    print(f"`{rel(root, path)}`")
    print("")
    print(clip(path.read_text(encoding="utf-8"), chars).rstrip())
    print("")


def print_decision_snapshot(root: Path, paths: list[Path], limit: int) -> None:
    print("## Recent Accepted Decisions / Risks / Open Questions")
    print("")
    shown = 0
    for path in paths:
        if record_kind(path) != "decisions":
            continue
        print(f"- `{rel(root, path)}` - {first_heading(path)}")
        shown += 1
        if shown >= limit:
            break
    if shown == 0:
        print("- no accepted decisions in scope")
    print("")
    risk_lines: list[str] = []
    for path in paths:
        if record_kind(path) not in {"canonical", "task-context", "workstream"}:
            continue
        for heading in ["Open Questions / Risks", "Open Questions", "Open Risks"]:
            section = extract_section(path.read_text(encoding="utf-8"), heading)
            if section and section.strip() != "-":
                risk_lines.append(f"- `{rel(root, path)}` {heading}: {section.splitlines()[0][:180]}")
    if risk_lines:
        print("### Open Items")
        print("")
        print("\n".join(risk_lines[:limit]))
        print("")


def cmd_collab_recall(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_collab(root)
    build_index(root)
    task = normalize_collab_id(args.task, "task") if args.task else None
    workstream = normalize_collab_id(args.workstream, "workstream") if args.workstream else None
    query = args.query or " ".join(item for item in [task, workstream, "benchmark collaboration"] if item)

    print(f"# Collaboration Recall ({root})")
    print("")
    print(f"Task: {task or '-'}")
    print(f"Workstream: {workstream or '-'}")
    print(f"Inbox Included: {'yes' if args.include_inbox else 'no'}")
    print(f"Archive Included: {'yes' if args.include_archive else 'no'}")
    print("")
    print_context_file(root, "Canonical Overview", root / HISTORY_DIR / "canonical" / "overview.md", args.context_chars)
    if task:
        print_context_file(root, "Task Context", task_context_path(root, task), args.context_chars)
    if task and workstream:
        print_context_file(root, "Workstream Context", workstream_context_path(root, task, workstream), args.context_chars)

    paths = collab_paths(root, task, workstream, include_inbox=args.include_inbox, include_archive=args.include_archive)
    print_decision_snapshot(root, paths, args.limit)
    print(f"## Scoped BM25 Recall: {query}")
    print("")
    payload = bm25_search_documents(
        collab_documents(root, task, workstream, args.include_inbox, args.include_archive),
        query,
        args.limit,
    )
    print_bm25_payload(payload, show_variants=not args.no_variants)
    if args.include_inbox:
        print("Note: inbox records are unaccepted unless `approval=accepted`; do not use submitted inbox summaries as canonical facts.")
    if args.include_archive:
        print("Note: archive records are retained for provenance; verify them against accepted context before using them as facts.")


def path_is_stale(path: Path, stale_after: datetime) -> bool:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone() < stale_after


def stale_text(path: Path, stale_after: datetime) -> str:
    return "yes" if path_is_stale(path, stale_after) else "no"


def pending_inbox_counts(root: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    inbox = root / HISTORY_DIR / "inbox"
    if not inbox.exists():
        return counts
    for path in inbox.glob("*.md"):
        if path.name == "README.md" or not path.is_file():
            continue
        if approval_status(path) == "accepted":
            continue
        meta = parse_metadata(path.read_text(encoding="utf-8"))
        task = normalize_collab_id(meta.get("task", ""), "cross-task") if meta.get("task") else "cross-task"
        workstream = (
            normalize_collab_id(meta.get("workstream", ""), "cross-workstream")
            if meta.get("workstream")
            else "cross-workstream"
        )
        counts[(task, workstream)] += 1
    return counts


def accepted_unarchived_inbox_counts(root: Path) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    inbox = root / HISTORY_DIR / "inbox"
    if not inbox.exists():
        return counts
    for path in inbox.glob("*.md"):
        if path.name == "README.md" or not path.is_file():
            continue
        if approval_status(path) != "accepted":
            continue
        if archive_status(path) == "archived":
            continue
        meta = parse_metadata(path.read_text(encoding="utf-8"))
        task = normalize_collab_id(meta.get("task", ""), "cross-task") if meta.get("task") else "cross-task"
        workstream = (
            normalize_collab_id(meta.get("workstream", ""), "cross-workstream")
            if meta.get("workstream")
            else "cross-workstream"
        )
        counts[(task, workstream)] += 1
    return counts


def file_count(root: Path, relative: str) -> int:
    base = root / HISTORY_DIR / relative
    if not base.exists():
        return 0
    return sum(1 for path in base.rglob("*.md") if "/templates/" not in path.as_posix())


def unscoped_collab_records(root: Path) -> list[Path]:
    history = root / HISTORY_DIR
    records: list[Path] = []
    for folder in ["handoffs", "capsules"]:
        base = history / folder
        if not base.exists():
            continue
        for path in base.glob("*.md"):
            if not path.is_file():
                continue
            meta = parse_metadata(path.read_text(encoding="utf-8"))
            if not meta.get("task") and not meta.get("workstream"):
                records.append(path)
    return sorted(records, key=lambda p: p.stat().st_mtime, reverse=True)


def cmd_collab_status(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_collab(root)
    history = root / HISTORY_DIR
    stale_after = now() - timedelta(days=args.stale_days)
    print("# Collaboration Status")
    print("")
    overview = history / "canonical" / "overview.md"
    print("## Canonical Overview")
    print("")
    if overview.exists():
        meta = parse_metadata(overview.read_text(encoding="utf-8"))
        print(
            f"- `{rel(root, overview)}` - stale={stale_text(overview, stale_after)}, "
            f"approval={approval_status(overview)}, last_updated={meta.get('last updated', '-') or '-'}"
        )
    else:
        print("- missing")
    print("")
    task_contexts = sorted((history / "tasks").glob("*/context.md"))
    workstream_contexts = sorted((history / "tasks").glob("*/workstreams/*.md"))
    inbox_counts = pending_inbox_counts(root)
    accepted_inbox_counts = accepted_unarchived_inbox_counts(root)
    archive_candidates = archive_candidate_paths(root, ["inbox"])
    unscoped_records = unscoped_collab_records(root)
    overview_stale = 1 if overview.exists() and path_is_stale(overview, stale_after) else 0
    stale_task_count = sum(1 for path in task_contexts if path_is_stale(path, stale_after))
    stale_workstream_count = sum(1 for path in workstream_contexts if path_is_stale(path, stale_after))
    print("## Summary")
    print("")
    print(f"- pending_inbox: {sum(inbox_counts.values())}")
    print(f"- accepted_unarchived_inbox: {sum(accepted_inbox_counts.values())}")
    print(f"- archive_candidates: {len(archive_candidates)}")
    print(f"- stale_canonical: {overview_stale}/1")
    print(f"- stale_tasks: {stale_task_count}/{len(task_contexts)}")
    print(f"- stale_workstreams: {stale_workstream_count}/{len(workstream_contexts)}")
    print(f"- unscoped_records: {len(unscoped_records)}")
    print("")
    print("## File Counts")
    print("")
    print("| Area | Files |")
    print("| --- | --- |")
    for area in ["canonical", "tasks", "decisions", "handoffs", "capsules", "inbox", "archive"]:
        print(f"| {area} | {file_count(root, area)} |")
    print("")
    print("## Tasks")
    print("")
    if not task_contexts:
        print("- no task contexts")
    else:
        print("| Task | Owner | Status | Metric | Dataset | Blocker | Stale |")
        print("| --- | --- | --- | --- | --- | --- | --- |")
        for path in task_contexts:
            meta = parse_metadata(path.read_text(encoding="utf-8"))
            print(
                "| "
                + " | ".join(
                    [
                        meta.get("task", path.parent.name) or "-",
                        meta.get("owner", "-") or "-",
                        meta.get("status", "-") or "-",
                        meta.get("metric", "-") or "-",
                        meta.get("dataset", "-") or "-",
                        meta.get("blocker", "-") or "-",
                        stale_text(path, stale_after),
                    ]
                )
                + " |"
            )
    print("")
    print("## Workstreams")
    print("")
    if not workstream_contexts:
        print("- no workstream contexts")
    else:
        stale_count = sum(1 for path in workstream_contexts if path_is_stale(path, stale_after))
        print(f"- stale: {stale_count}/{len(workstream_contexts)}")
        print("")
        print("| Task | Workstream | Owner | Status | Stale |")
        print("| --- | --- | --- | --- | --- |")
        for path in workstream_contexts:
            meta = parse_metadata(path.read_text(encoding="utf-8"))
            print(
                "| "
                + " | ".join(
                    [
                        meta.get("task", path.parent.parent.name) or "-",
                        meta.get("workstream", path.stem) or "-",
                        meta.get("owner", "-") or "-",
                        meta.get("status", "-") or "-",
                        stale_text(path, stale_after),
                    ]
                )
                + " |"
            )
    print("")
    print("## Pending Inbox")
    print("")
    if not inbox_counts:
        print("- none")
    else:
        print("| Task | Workstream | Pending |")
        print("| --- | --- | --- |")
        for (task, workstream), count in sorted(inbox_counts.items()):
            print(f"| {task} | {workstream} | {count} |")
    print("")
    print("## Accepted But Unarchived Inbox")
    print("")
    if not accepted_inbox_counts:
        print("- none")
    else:
        print("| Task | Workstream | Accepted Unarchived |")
        print("| --- | --- | --- |")
        for (task, workstream), count in sorted(accepted_inbox_counts.items()):
            print(f"| {task} | {workstream} | {count} |")
    print("")
    print("## Archive Candidates")
    print("")
    if not archive_candidates:
        print("- none")
    else:
        print("| Type | Source | Promoted To |")
        print("| --- | --- | --- |")
        for archive_type, path in archive_candidates[: args.limit]:
            print(f"| {archive_type} | `{rel(root, path)}` | `{promoted_to_value(path) or '-'}` |")
        if len(archive_candidates) > args.limit:
            print(f"| ... | {len(archive_candidates) - args.limit} more | - |")
    print("")
    print("## Unscoped Handoffs / Capsules")
    print("")
    if not unscoped_records:
        print("- none")
    else:
        for path in unscoped_records[: args.limit]:
            print(f"- `{rel(root, path)}` - {first_heading(path)}")
        if len(unscoped_records) > args.limit:
            print(f"- ... {len(unscoped_records) - args.limit} more")
    print("")
    decision_files = sorted((history / "decisions").glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    print("## Recent Accepted Decisions")
    print("")
    shown = 0
    for path in decision_files:
        if approval_status(path) != "accepted":
            continue
        meta = parse_metadata(path.read_text(encoding="utf-8"))
        print(f"- `{rel(root, path)}` - {first_heading(path)} (task={meta.get('task', '-')}, workstream={meta.get('workstream', '-')})")
        shown += 1
        if shown >= args.limit:
            break
    if shown == 0:
        print("- none")
    print("")
    print("## Open Risks")
    print("")
    risks: list[str] = []
    for path in task_contexts + sorted((history / "tasks").glob("*/workstreams/*.md")):
        section = extract_section(path.read_text(encoding="utf-8"), "Open Risks")
        if section and section.strip() != "-":
            risks.append(f"- `{rel(root, path)}`: {section.splitlines()[0][:180]}")
    print("\n".join(risks[: args.limit]) if risks else "- none")
    print("")


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Repository root. Defaults to git root, then current directory.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain searchable research project history.")
    add_root(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="Create history/ structure and templates.")
    p.add_argument("--today", action="store_true", help="Also create today's daily log.")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("today", help="Create or print today's daily log path.")
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("index", help="Rebuild history/INDEX.md.")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("change", help="Record a code or artifact change.")
    p.add_argument("--title", required=True)
    p.add_argument("--why")
    p.add_argument("--how")
    p.add_argument("--file", action="append")
    p.add_argument("--validation", action="append")
    p.add_argument("--risk")
    p.add_argument("--status", default="completed")
    p.add_argument("--agent", default="codex")
    p.add_argument("--no-git-status", action="store_true")
    p.set_defaults(func=cmd_change)

    p = sub.add_parser("decision", help="Record a durable decision.")
    p.add_argument("--title", required=True)
    p.add_argument("--context")
    p.add_argument("--decision")
    p.add_argument("--rationale")
    p.add_argument("--consequence")
    p.add_argument("--status", default="accepted")
    p.set_defaults(func=cmd_decision)

    p = sub.add_parser("idea", help="Record a research or implementation idea.")
    p.add_argument("--title", required=True)
    p.add_argument("--problem")
    p.add_argument("--hypothesis")
    p.add_argument("--expected")
    p.add_argument("--link", action="append")
    p.add_argument("--next")
    p.add_argument("--tag", action="append")
    p.add_argument("--status", default="open")
    p.set_defaults(func=cmd_idea)

    p = sub.add_parser("experiment", help="Record an experiment, analysis, or figure export.")
    p.add_argument("--title", required=True)
    p.add_argument("--goal")
    p.add_argument("--setup")
    p.add_argument("--metric", action="append")
    p.add_argument("--result")
    p.add_argument("--artifact", action="append")
    p.add_argument("--next")
    p.add_argument("--tag", action="append")
    p.add_argument("--status", default="recorded")
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("handoff", help="Record collaborator or agent handoff context.")
    p.add_argument("--title", required=True)
    p.add_argument("--to")
    p.add_argument("--summary")
    p.add_argument("--file", action="append")
    p.add_argument("--next")
    p.add_argument("--risk")
    p.add_argument("--task", help="Optional collaboration task id for scoped recall.")
    p.add_argument("--workstream", help="Optional collaboration workstream id for scoped recall.")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser(
        "handoff-agent-capsule",
        help="Create, import, or resume a cross-agent handoff context capsule.",
    )
    capsule_sub = p.add_subparsers(dest="capsule_command", required=True)

    cp = capsule_sub.add_parser("create", help="Create a handoff agent capsule for another agent, tool, or server.")
    cp.add_argument("--task", required=True)
    cp.add_argument("--collab-task", help="Optional collaboration task id for scoped recall.")
    cp.add_argument("--workstream", help="Optional collaboration workstream id for scoped recall.")
    cp.add_argument("--query", help="BM25 recall query. Defaults to --task.")
    cp.add_argument("--from-agent", default="codex")
    cp.add_argument("--to-agent", default="agent")
    cp.add_argument("--target-host")
    cp.add_argument("--user-requirement", action="append")
    cp.add_argument("--current-state")
    cp.add_argument(
        "--reasoning-summary",
        help="Concise public decision-rationale summary. Do not store hidden chain-of-thought.",
    )
    cp.add_argument("--file", action="append")
    cp.add_argument("--validation", action="append")
    cp.add_argument("--risk", action="append")
    cp.add_argument("--next-action", action="append")
    cp.add_argument("--status", default="ready")
    cp.add_argument("--limit", type=int, default=8)
    cp.add_argument("--context-chars", type=int, default=2200)
    cp.set_defaults(func=cmd_handoff_agent_capsule_create)

    cp = capsule_sub.add_parser("resume", help="Print the latest or matching handoff agent capsule.")
    cp.add_argument("--query", help="BM25 query for selecting a capsule and adding recall context.")
    cp.add_argument("--path", help="Specific capsule path to read.")
    cp.add_argument("--limit", type=int, default=8)
    cp.add_argument("--chars", type=int, default=5000)
    cp.add_argument("--full", action="store_true")
    cp.add_argument("--no-variants", action="store_true", help="Hide generated query variants in added recall.")
    cp.set_defaults(func=cmd_handoff_agent_capsule_resume)

    cp = capsule_sub.add_parser("import", help="Import a capsule markdown file from another machine or tool.")
    cp.add_argument("--file", required=True)
    cp.add_argument("--title")
    cp.add_argument("--agent", default="agent")
    cp.set_defaults(func=cmd_handoff_agent_capsule_import)

    p = sub.add_parser("session", help="Create a working-session note.")
    p.add_argument("--task", required=True)
    p.add_argument("--scope")
    p.add_argument("--agent", default="codex")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("search", help="Search history markdown files with SQLite FTS5 BM25 ranking.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true", help="Use exact substring matching instead of SQLite FTS5 BM25.")
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants.")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("exact", help="Exact substring search over history markdown files.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_exact)

    p = sub.add_parser("recent", help="List recent history records.")
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser("lint", help="Check history/ for Obsidian-friendly metadata and wikilinks.")
    p.add_argument(
        "--max-chars",
        type=int,
        default=OBSIDIAN_LINT_MAX_CHARS,
        help=f"Warn when a note exceeds this size. Defaults to {OBSIDIAN_LINT_MAX_CHARS}.",
    )
    p.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("recall", help="Print context, latest daily log, recent records, and optional query hits.")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--context-chars", type=int, default=2800)
    p.add_argument("--daily-chars", type=int, default=1800)
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants in BM25 recall.")
    p.set_defaults(func=cmd_recall)

    p = sub.add_parser("collab", help="Manage maintainer-curated collaboration history.")
    collab_sub = p.add_subparsers(dest="collab_command", required=True)

    cp = collab_sub.add_parser("bootstrap", help="Create central collaboration history structure.")
    cp.add_argument("--task", action="append", help="Create a task context. May be repeated.")
    cp.add_argument("--task-count", type=int, help="Create task-01 ... task-N contexts.")
    cp.add_argument("--workstream", action="append", help="Create this workstream for each task. May be repeated.")
    cp.add_argument(
        "--default-workstreams",
        action="store_true",
        help="Create data, eval, model, and writeup workstreams for each task.",
    )
    cp.set_defaults(func=cmd_collab_bootstrap)

    cp = collab_sub.add_parser("submit-summary", help="Submit a summary-only collaboration record to history/inbox.")
    cp.add_argument("--task", required=True)
    cp.add_argument("--workstream", required=True)
    cp.add_argument("--person", required=True)
    cp.add_argument("--agent", default="agent")
    cp.add_argument("--title")
    cp.add_argument("--summary", required=True)
    cp.add_argument("--claim", action="append")
    cp.add_argument("--evidence", action="append")
    cp.add_argument("--changed-file", action="append")
    cp.add_argument("--validation", action="append")
    cp.add_argument("--open-question", action="append")
    cp.add_argument("--proposed-decision", action="append")
    cp.add_argument("--private-reference", action="append")
    cp.add_argument("--strict", action="store_true", help="Fail on sensitive-looking fields instead of warning.")
    cp.set_defaults(func=cmd_collab_submit_summary)

    cp = collab_sub.add_parser("promote", help="Promote an inbox summary into accepted collaboration context.")
    cp.add_argument("--inbox", required=True, help="Path to a history/inbox summary.")
    cp.add_argument("--target", required=True, choices=["canonical", "task", "workstream", "decision"])
    cp.add_argument("--maintainer", default="maintainer")
    cp.add_argument("--task", help="Override or provide task id.")
    cp.add_argument("--workstream", help="Override or provide workstream id.")
    cp.add_argument("--title")
    cp.add_argument("--note", help="Curated maintainer note to promote. Defaults to the inbox summary.")
    cp.add_argument(
        "--include-submitted-sections",
        action="store_true",
        help="With --note, also append submitted claims/evidence/validation sections to canonical, task, or workstream targets.",
    )
    cp.add_argument("--context", help="Decision target only: curated context.")
    cp.add_argument("--decision", help="Decision target only: accepted decision text.")
    cp.add_argument("--rationale", help="Decision target only: rationale or evidence.")
    cp.add_argument("--consequence", help="Decision target only: consequences or open questions.")
    cp.add_argument("--strict", action="store_true", help="Fail on sensitive-looking fields instead of warning.")
    cp.set_defaults(func=cmd_collab_promote)

    cp = collab_sub.add_parser("archive", help="Move promoted or stale auxiliary records into history/archive.")
    cp.add_argument(
        "--older-than-days",
        type=int,
        help="Only archive records older than N days. Required for daily/sessions candidates.",
    )
    cp.add_argument(
        "--include",
        default="inbox",
        help="Comma-separated archive types: inbox,daily,sessions. Defaults to inbox.",
    )
    cp.add_argument("--dry-run", action="store_true", help="Print candidates without moving or editing files.")
    cp.set_defaults(func=cmd_collab_archive)

    cp = collab_sub.add_parser("recall", help="Print a scoped agent context pack for a task/workstream.")
    cp.add_argument("--task")
    cp.add_argument("--workstream")
    cp.add_argument("--query")
    cp.add_argument("--limit", type=int, default=8)
    cp.add_argument("--context-chars", type=int, default=2400)
    cp.add_argument("--include-inbox", action="store_true", help="Include unaccepted inbox summaries in retrieval output.")
    cp.add_argument("--include-archive", action="store_true", help="Include archived records for provenance search.")
    cp.add_argument("--no-variants", action="store_true", help="Hide generated query variants in BM25 recall.")
    cp.set_defaults(func=cmd_collab_recall)

    cp = collab_sub.add_parser("status", help="Show task owners, recent decisions, open risks, and stale contexts.")
    cp.add_argument("--stale-days", type=int, default=14)
    cp.add_argument("--limit", type=int, default=12)
    cp.set_defaults(func=cmd_collab_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
