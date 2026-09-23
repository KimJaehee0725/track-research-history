#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


HISTORY_DIR = "history"
ARCHIVE_DIR = "history-archive"
LEGACY_ARCHIVE_DIR = "archive"
SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

TOKEN_PATTERN = r"(?u)\b[\w./:-]{2,}\b"
CHUNK_TARGET_CHARS = 2200
CHUNK_OVERLAP_CHARS = 250
CHUNK_SMALL_FILE_THRESHOLD = 2600
OBSIDIAN_LINT_MAX_CHARS = 12000
OBSIDIAN_MAP_FILE = "PROJECT_MAP.md"
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
COLLAB_DIRS = ["canonical", "tasks", "inbox"]
ARCHIVE_TYPES = ["inbox", "daily", "sessions"]
ARCHIVABLE_KINDS = [
    "changes",
    "decisions",
    "ideas",
    "experiments",
    "handoffs",
    "capsules",
    "sessions",
    "daily",
    "inbox",
]
DEFAULT_ARCHIVE_KINDS = ["changes", "experiments", "daily", "sessions", "handoffs", "capsules", "inbox"]
DEFAULT_ARCHIVE_AGE_DAYS = 60
DEFAULT_ARCHIVE_KEEP_RECENT = 20
ARCHIVE_SUMMARY_CHARS = 700
ARCHIVE_MIN_SAVING = 0.30
ARCHIVE_MIN_SAVING_CHARS = 400
ARCHIVE_ADOPT_HINT_RECORDS = 60
OPEN_STATUSES = {"open", "in-progress", "in progress", "active", "pending", "todo", "proposed", "draft", "ready"}
RECORD_ID_PREFIXES = {
    "changes": "chg",
    "change": "chg",
    "decisions": "dec",
    "decision": "dec",
    "ideas": "idea",
    "idea": "idea",
    "experiments": "exp",
    "experiment": "exp",
    "handoffs": "hnd",
    "handoff": "hnd",
    "capsules": "cap",
    "handoff-agent-capsule": "cap",
    "handoff-agent-capsule-import": "cap",
    "sessions": "ses",
    "session": "ses",
    "daily": "day",
    "inbox": "inb",
    "canonical": "can",
    "task-context": "tsk",
    "workstream": "wst",
}
COMMIT_TRAILER_KEY = "History-Record"
COMMIT_SECTION_HEADING = "Commits"
COMMIT_ELEMENT_PREFIX = "cmt"
COMMIT_DUE_MAX_FILES = 12
COMMIT_DUE_MAX_MINUTES = 90
ARCHIVE_INDEX_FILE = "INDEX.md"
ARCHIVE_STUB_TAG = "archive-stub"
ARCHIVE_SECTION_CHARS = 240
SUMMARY_SECTIONS = {
    "changes": ["Why", "How", "Files", "Validation", "Risks / Follow-Ups"],
    "change": ["Why", "How", "Files", "Validation", "Risks / Follow-Ups"],
    "decisions": ["Decision", "Context", "Rationale", "Consequences"],
    "decision": ["Decision", "Context", "Rationale", "Consequences"],
    "ideas": ["Problem / Opportunity", "Hypothesis", "Next Check"],
    "idea": ["Problem / Opportunity", "Hypothesis", "Next Check"],
    "experiments": ["Goal", "Results", "Interpretation / Next"],
    "experiment": ["Goal", "Results", "Interpretation / Next"],
    "handoffs": ["Summary", "Next Actions", "Risks"],
    "handoff": ["Summary", "Next Actions", "Risks"],
    "capsules": ["Current State", "Next Actions", "Open Risks"],
    "sessions": ["Scope", "End Summary"],
    "session": ["Scope", "End Summary"],
    "daily": ["Focus", "Work Notes", "Linked Records"],
    "inbox": ["Summary", "Claims", "Open Questions"],
}
DEFAULT_SUMMARY_SECTIONS = ["Summary", "Why", "Decision", "Goal", "Current State", "Focus"]
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

    write_if_missing(history / ".gitignore", ".obsidian/\n")
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
2. `PROJECT_MAP.md` in Obsidian, or `INDEX.md` in a text editor
3. Latest file in `daily/`
4. Relevant records from `changes/`, `decisions/`, `ideas/`, `experiments/`, `handoffs/`, `capsules/`, and `sessions/`
5. For anything older, the summary stubs here and their full text in `../history-archive/`

## Trusted Context

For collaboration projects, default agent context comes from `canonical/`, `tasks/`, `decisions/`, and scoped handoffs/capsules with explicit `Task:` and `Workstream:` metadata.

## Pending

`inbox/` contains submitted summaries awaiting maintainer review. It is excluded from collaboration recall unless `--include-inbox` is passed.

## Archive

Old, rarely used records keep a summary stub here and move their full text to `../history-archive/YYYY-MM/<kind>/`. A stub carries `Archive State: stub`, the record id, the paired commits, a condensed summary, and an `Archived To:` pointer.

The archive is tracked in Git for provenance but excluded from default recall, from this Obsidian vault, and from the default search index. Pass `--include-archive` to search it, or read `../history-archive/INDEX.md`. Nothing is deleted: `history.py archive restore --record <id>` reverses the move.

## Commits

Each record carries a `Record Id:` and a `## Commits` section, and each paired commit carries a `History-Record: <id>` trailer. Use `history.py commits --record <id>` to see the diffs behind a record, and `history.py sync-commits` to rebuild pairing from commit trailers.

## Obsidian

Open this `history/` folder directly as an Obsidian vault and start from `PROJECT_MAP.md`. Generated wikilinks are portable across clones. Keep `.obsidian/` untracked.

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


def archive_root(root: Path) -> Path:
    return root / ARCHIVE_DIR


def legacy_archive_root(root: Path) -> Path:
    return root / HISTORY_DIR / LEGACY_ARCHIVE_DIR


def ensure_archive(root: Path) -> None:
    archive = archive_root(root)
    archive.mkdir(parents=True, exist_ok=True)
    write_if_missing(
        archive / "README.md",
        """# History Archive

Long-term storage for history records that are old and rarely used. Full record text lives here; `history/` keeps only a
lightweight stub with the record id, metadata, paired commits, a short summary, and a pointer back to this folder.

Layout: `YYYY-MM/<kind>/<original-filename>.md`, where the month comes from the record date.

This folder is Git-tracked for provenance, but it is excluded from default recall, from the Obsidian vault opened at
`history/`, and from the default BM25 index. Pass `--include-archive` to search it.

Restore a record with `history.py archive restore --record <record-id>`; that moves the full text back into `history/`
and removes the stub.

`history/archive/` is the legacy location from earlier versions of this skill. It is still read for search and provenance;
run `history.py archive migrate` to move it here.
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


_TEXT_CACHE: dict[tuple[str, int, int], str] = {}
_META_CACHE: dict[tuple[str, int, int], dict[str, str]] = {}


def _file_key(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def read_record_text(path: Path) -> str:
    """Read a record, reusing the parse of an unchanged file within one run."""
    key = _file_key(path)
    if key is None:
        return ""
    cached = _TEXT_CACHE.get(key)
    if cached is None:
        try:
            cached = path.read_text(encoding="utf-8")
        except Exception:
            cached = ""
        if len(_TEXT_CACHE) > 5000:
            _TEXT_CACHE.clear()
        _TEXT_CACHE[key] = cached
    return cached


def record_metadata(path: Path) -> dict[str, str]:
    key = _file_key(path)
    if key is None:
        return {}
    cached = _META_CACHE.get(key)
    if cached is None:
        cached = parse_metadata(read_record_text(path))
        if len(_META_CACHE) > 5000:
            _META_CACHE.clear()
        _META_CACHE[key] = cached
    return cached


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
    return record_metadata(path).get(metadata_key(key), default) or default


def normalized_status(text: str | None) -> str:
    return text.strip().lower() if text and text.strip() else ""


def approval_status(path: Path) -> str:
    meta = record_metadata(path)
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
    value_text = normalized_status(record_metadata(path).get("archived"))
    if value_text in {"yes", "true", "archived"}:
        return "yes"
    return "no"


def in_archive_tree(path: Path) -> bool:
    parts = path.parts
    return ARCHIVE_DIR in parts or LEGACY_ARCHIVE_DIR in parts


def archive_status(path: Path) -> str:
    if in_archive_tree(path) or archived_value(path) == "yes":
        return "archived"
    if is_archive_stub(path):
        return "stub"
    return "active"


def is_archive_stub(path: Path) -> bool:
    if in_archive_tree(path):
        return False
    return normalized_status(metadata_value(path, "Archive State", "")) == "stub"


def archived_to_value(path: Path) -> str:
    value_text = metadata_value(path, "Archived To", "")
    return "" if value_text in {"", "-"} else value_text


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}[ \t]*$", re.IGNORECASE | re.MULTILINE)
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
        head = text[: first_section.start()].rstrip("\n")
        return head + "\n" + insert + "\n" + text[first_section.start():]
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


def git_status(root: Path, untracked_all: bool = False) -> str:
    try:
        command = ["git", "-C", str(root), "status", "--short"]
        if untracked_all:
            command.append("--untracked-files=all")
        out = subprocess.check_output(
            command,
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
        return out or "clean"
    except Exception as exc:
        return f"unavailable: {exc}"


# --- Record identity -------------------------------------------------------


_RECORD_DATE_CACHE: dict[tuple[str, float], datetime] = {}


def kind_prefix(kind: str) -> str:
    return RECORD_ID_PREFIXES.get(kind.strip().lower(), "rec")


def compose_record_id(kind: str, stem: str) -> str:
    prefix = kind_prefix(kind)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-").lower()
    if not cleaned:
        return prefix
    if cleaned.startswith(f"{prefix}-"):
        return cleaned
    return f"{prefix}-{cleaned}"


def record_id_for(path: Path) -> str:
    stored = metadata_value(path, "Record Id", "")
    if stored and stored != "-":
        return stored.strip()
    return compose_record_id(record_kind(path), path.stem)


def record_datetime(path: Path) -> datetime:
    """Record date from the filename, then metadata, then file mtime."""
    try:
        cache_key = (str(path.resolve()), path.stat().st_mtime)
    except OSError:
        cache_key = (str(path), 0.0)
    cached = _RECORD_DATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    stamp: datetime | None = None
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:-(\d{2})(\d{2})(\d{2}))?", path.name)
    if match:
        try:
            stamp = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                int(match.group(4) or 0),
                int(match.group(5) or 0),
                int(match.group(6) or 0),
            ).astimezone()
        except ValueError:
            stamp = None
    if stamp is None:
        meta = record_metadata(path)
        for key in ["date", "archived date", "promoted date", "last updated"]:
            found = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", meta.get(key, "") or "")
            if not found:
                continue
            try:
                stamp = datetime(
                    int(found.group(1)),
                    int(found.group(2)),
                    int(found.group(3)),
                    int(found.group(4) or 0),
                    int(found.group(5) or 0),
                ).astimezone()
                break
            except ValueError:
                continue
    if stamp is None:
        try:
            stamp = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            stamp = now()
    _RECORD_DATE_CACHE[cache_key] = stamp
    return stamp


def record_sort_key(path: Path) -> float:
    return record_datetime(path).timestamp()


def record_status(path: Path) -> str:
    status = normalized_status(metadata_value(path, "Status", ""))
    if status and status != "-":
        return status
    approval = normalized_status(metadata_value(path, "Approval Status", ""))
    return approval if approval != "-" else ""


def record_is_open(path: Path) -> bool:
    return record_status(path) in OPEN_STATUSES


def record_search_paths(root: Path) -> list[Path]:
    return list(iter_history_files(root)) + list(iter_archive_files(root))


def find_record(root: Path, ref: str) -> Path:
    """Resolve a record id, repo-relative path, or unique id fragment to a file."""
    ref = (ref or "").strip()
    if not ref:
        raise SystemExit("Record reference is empty.")
    direct = Path(ref) if Path(ref).is_absolute() else root / ref
    if direct.is_file() and direct.suffix == ".md":
        return direct
    needle = ref.lower()
    candidates = record_search_paths(root)
    exact = [path for path in candidates if record_id_for(path).lower() == needle]
    if exact:
        live = [path for path in exact if not in_archive_tree(path)]
        return (live or exact)[0]
    partial = [
        path
        for path in candidates
        if needle in record_id_for(path).lower() or needle in path.stem.lower()
    ]
    live_partial = [path for path in partial if not in_archive_tree(path)]
    if len({record_id_for(path) for path in partial}) == 1 and live_partial:
        return live_partial[0]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No history record matches '{ref}'.")
    listed = "\n".join(f"- {record_id_for(path)} ({rel(root, path)})" for path in partial[:10])
    raise SystemExit(f"Ambiguous record reference '{ref}'. Candidates:\n{listed}")


def remove_metadata_line(text: str, key: str) -> str:
    bounds = frontmatter_bounds(text)
    head = ""
    rest = text
    if bounds:
        start, end = bounds
        front = re.sub(rf"(?im)^{re.escape(frontmatter_key(key))}:.*\n?", "", text[start:end])
        head = text[:start] + front
        rest = text[end:]
    first_section = re.search(r"^##\s+", rest, flags=re.MULTILINE)
    limit = first_section.start() if first_section else len(rest)
    meta_part = re.sub(rf"(?im)^{re.escape(key)}:.*\n?", "", rest[:limit])
    return head + meta_part + rest[limit:]


def append_to_section(text: str, heading: str, line: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}[ \t]*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return text.rstrip() + f"\n\n## {heading}\n\n{line}\n"
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], flags=re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    body = text[start:end].strip()
    body = line if body in {"", "-"} else body + "\n" + line
    return text[:start] + "\n\n" + body + "\n\n" + text[end:].lstrip("\n")


# --- Git and commit pairing ------------------------------------------------


def git_output(root: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), *args],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return None
    return out.strip()


def git_available(root: Path) -> bool:
    return git_output(root, ["rev-parse", "--is-inside-work-tree"]) == "true"


def resolve_commit(root: Path, ref: str) -> str | None:
    return git_output(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])


def normalize_sha(sha: str) -> str:
    return re.sub(r"[^0-9a-fA-F]", "", sha or "").lower()[:12]


_COMMIT_META: dict[tuple[str, str], tuple[str, str]] = {}


def prefetch_commit_meta(root: Path, shas: list[str]) -> None:
    """Resolve date and subject for many commits in one `git log` call."""
    missing = []
    for sha in shas:
        short = normalize_sha(sha)
        if short and (str(root), short) not in _COMMIT_META:
            missing.append(sha)
    if not missing:
        return
    for batch_start in range(0, len(missing), 200):
        batch = missing[batch_start : batch_start + 200]
        out = git_output(
            root,
            [
                "log",
                "--no-walk",
                "--format=%H%x01%ad%x01%s",
                "--date=format:%Y-%m-%d %H:%M",
                *batch,
            ],
        )
        if not out:
            continue
        for line in out.splitlines():
            parts = line.split("\x01")
            if len(parts) != 3:
                continue
            _COMMIT_META[(str(root), normalize_sha(parts[0]))] = (parts[1].strip(), parts[2].strip())


def commit_meta(root: Path, sha: str) -> tuple[str, str]:
    key = (str(root), normalize_sha(sha))
    if key not in _COMMIT_META:
        prefetch_commit_meta(root, [sha])
    return _COMMIT_META.get(key, ("-", "-"))


def commit_subject(root: Path, sha: str) -> str:
    return commit_meta(root, sha)[1]


def commit_when(root: Path, sha: str) -> str:
    return commit_meta(root, sha)[0]


def commit_files(root: Path, sha: str) -> list[str]:
    out = git_output(root, ["show", "--name-only", "--format=", sha])
    return [line.strip() for line in out.splitlines() if line.strip()] if out else []


def commit_line(root: Path, sha: str) -> str:
    return f"- `{normalize_sha(sha)}` {commit_when(root, sha)} - {commit_subject(root, sha)}"


def parse_commit_list(value_text: str) -> list[str]:
    if not value_text or value_text.strip() in {"", "-"}:
        return []
    items: list[str] = []
    for token in re.split(r"[,\s]+", value_text.strip()):
        cleaned = normalize_sha(token.strip("`"))
        if len(cleaned) >= 7 and cleaned not in items:
            items.append(cleaned)
    return items


def record_commits(path: Path) -> list[str]:
    text = read_record_text(path)
    if not text:
        return []
    commits = parse_commit_list(record_metadata(path).get("commits", ""))
    for token in re.findall(r"\b[0-9a-f]{7,40}\b", extract_section(text, COMMIT_SECTION_HEADING)):
        cleaned = normalize_sha(token)
        if cleaned and cleaned not in commits:
            commits.append(cleaned)
    return commits


def write_commit_reference(root: Path, path: Path, sha: str) -> bool:
    short = normalize_sha(sha)
    if short in record_commits(path):
        return False
    text = read_record_text(path)
    if not text:
        return False
    commits = parse_commit_list(parse_metadata(text).get("commits", ""))
    commits.append(short)
    text = set_metadata_line(text, "Commits", ", ".join(commits))
    text = append_to_section(text, COMMIT_SECTION_HEADING, commit_line(root, sha))
    path.write_text(text, encoding="utf-8")
    return True


def pair_record_commit(root: Path, path: Path, sha: str) -> bool:
    """Write a commit reference into a record. Returns False when already paired."""
    short = normalize_sha(sha)
    if not short:
        return False
    paired = write_commit_reference(root, path, sha)
    # Keep an archived counterpart in step, so the stub and the full text agree.
    if is_archive_stub(path):
        target = archived_to_value(path)
        if target:
            archived = root / target
            if archived.exists():
                write_commit_reference(root, archived, sha)
    return paired


def commit_is_reachable(root: Path, sha: str) -> bool:
    """True when the commit is still reachable from a branch or tag.

    A squash or rebase merge replaces the commits a record was paired with, so a
    reference can resolve locally while no longer being part of any history.
    """
    if not resolve_commit(root, sha):
        return False
    return bool(git_output(root, ["for-each-ref", "--contains", sha, "--count=1", "--format=%(refname)"]))


def drop_commit_from_text(text: str, sha: str) -> str:
    remaining = [item for item in parse_commit_list(parse_metadata(text).get("commits", "")) if item != sha]
    text = set_metadata_line(text, "Commits", ", ".join(remaining) if remaining else "-")
    text = re.sub(rf"^-\s+`{re.escape(sha)}[0-9a-f]*`.*$\n?", "", text, flags=re.MULTILINE)
    section = extract_section(text, COMMIT_SECTION_HEADING)
    if not section.strip():
        pattern = re.compile(rf"^##\s+{re.escape(COMMIT_SECTION_HEADING)}[ \t]*$", re.IGNORECASE | re.MULTILINE)
        match = pattern.search(text)
        if match:
            start = match.end()
            next_heading = re.search(r"^##\s+", text[start:], flags=re.MULTILINE)
            end = start + next_heading.start() if next_heading else len(text)
            text = text[:start] + "\n\n-\n\n" + text[end:].lstrip("\n")
    return text


def unpair_record_commit(root: Path, path: Path, sha: str) -> bool:
    short = normalize_sha(sha)
    if short not in record_commits(path):
        return False
    text = read_record_text(path)
    if not text:
        return False
    path.write_text(drop_commit_from_text(text, short), encoding="utf-8")
    if is_archive_stub(path):
        target = archived_to_value(path)
        if target:
            archived = root / target
            if archived.exists():
                archived_text = read_record_text(archived)
                if archived_text:
                    archived.write_text(drop_commit_from_text(archived_text, short), encoding="utf-8")
    return True


def commit_trailer_block(record_ids: list[str]) -> str:
    return "\n".join(f"{COMMIT_TRAILER_KEY}: {rid}" for rid in record_ids)


def trailer_commit_map(root: Path, limit: int = 300) -> dict[str, list[str]]:
    """{commit sha: [record ids]} from one `git log` pass, not one call per commit."""
    out = git_output(
        root,
        [
            "log",
            f"-{limit}",
            f"--grep={COMMIT_TRAILER_KEY}:",
            "--format=%H%x01%B%x02",
        ],
    )
    mapping: dict[str, list[str]] = {}
    if not out:
        return mapping
    for entry in out.split("\x02"):
        entry = entry.strip("\n")
        if "\x01" not in entry:
            continue
        sha, body = entry.split("\x01", 1)
        ids: list[str] = []
        for item in re.findall(rf"(?im)^{re.escape(COMMIT_TRAILER_KEY)}:\s*(\S+)\s*$", body):
            if item not in ids:
                ids.append(item)
        if ids:
            mapping[sha.strip()] = ids
    return mapping


def record_commit_index(root: Path) -> dict[str, tuple[Path, list[str]]]:
    """{record id: (path, paired commits)} built once per command."""
    index: dict[str, tuple[Path, list[str]]] = {}
    for path in record_search_paths(root):
        record_id = record_id_for(path)
        if record_id in index and in_archive_tree(path):
            continue
        index[record_id] = (path, record_commits(path))
    return index


def commit_record_ids(root: Path, sha: str) -> list[str]:
    body = git_output(root, ["log", "-1", "--format=%B", sha]) or ""
    found = re.findall(rf"(?im)^{re.escape(COMMIT_TRAILER_KEY)}:\s*(\S+)\s*$", body)
    ids: list[str] = []
    for item in found:
        if item not in ids:
            ids.append(item)
    return ids


def commits_with_trailer(root: Path, limit: int = 300) -> list[str]:
    return list(trailer_commit_map(root, limit))


def paired_record_paths(root: Path, kinds: list[str] | None = None) -> list[Path]:
    kinds = kinds or ["changes", "experiments", "decisions", "ideas", "handoffs", "sessions"]
    paths: list[Path] = []
    for kind in kinds:
        base = root / HISTORY_DIR / kind
        if not base.exists():
            continue
        paths.extend(path for path in base.glob("*.md") if path.is_file() and path.name != "README.md")
    return sorted(paths, key=record_sort_key, reverse=True)


def unpaired_records(root: Path, limit: int = 10) -> list[Path]:
    kinds = ["changes", "experiments"]
    return [path for path in paired_record_paths(root, kinds) if not record_commits(path)][:limit]


def uncommitted_work_paths(root: Path) -> list[str]:
    status = git_status(root, untracked_all=True)
    paths = [status_path(line) for line in status_lines(root, status)]
    return [
        path
        for path in paths
        if path and not path.startswith(f"{HISTORY_DIR}/") and not path.startswith(f"{ARCHIVE_DIR}/")
    ]


def oldest_change_minutes(root: Path, paths: list[str]) -> int | None:
    oldest: float | None = None
    for item in paths:
        candidate = root / item
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        oldest = mtime if oldest is None else min(oldest, mtime)
    if oldest is None:
        return None
    return int((now().timestamp() - oldest) // 60)


def commit_due_notes(root: Path) -> list[str]:
    if not git_available(root):
        return []
    paths = uncommitted_work_paths(root)
    if not paths:
        return []
    notes: list[str] = []
    if len(paths) >= COMMIT_DUE_MAX_FILES:
        notes.append(
            f"commit due: {len(paths)} uncommitted non-history files "
            f"(threshold {COMMIT_DUE_MAX_FILES}). Commit with `commit --record <id> -m \"...\"`."
        )
    minutes = oldest_change_minutes(root, paths)
    if minutes is not None and minutes >= COMMIT_DUE_MAX_MINUTES:
        notes.append(
            f"commit due: oldest uncommitted change is {minutes} minutes old "
            f"(threshold {COMMIT_DUE_MAX_MINUTES}). Pair the work with a history record and commit."
        )
    return notes


def write_record(
    root: Path,
    folder: str,
    filename: str,
    text: str,
    kind: str,
    title: str,
    commits: list[str] | None = None,
) -> Path:
    ensure_history(root)
    out = root / HISTORY_DIR / folder / filename
    record_id = compose_record_id(folder, Path(filename).stem)
    text = set_metadata_line(text, "Record Id", record_id)
    resolved: list[str] = []
    for ref in commits or []:
        sha = resolve_commit(root, ref) or ref
        short = normalize_sha(sha)
        if short and short not in resolved:
            resolved.append(short)
    if resolved:
        text = set_metadata_line(text, "Commits", ", ".join(resolved))
    if f"## {COMMIT_SECTION_HEADING}" not in text:
        commit_body = "\n".join(commit_line(root, sha) for sha in resolved) if resolved else "-"
        text = text.rstrip() + f"\n\n## {COMMIT_SECTION_HEADING}\n\n{commit_body}\n"
    extra: dict[str, object] = {"record_id": record_id}
    if resolved:
        extra["commits"] = resolved
    text = add_obsidian_frontmatter(text, kind, title, extra)
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
    archive_files = iter_archive_files(root)
    stubs = archive_stub_paths(root)
    lines.append("## Archive")
    lines.append("")
    lines.append(
        f"`{ARCHIVE_DIR}/` holds {len(archive_files)} full record texts; "
        f"`{HISTORY_DIR}/` keeps {len(stubs)} summary stubs that point at them."
    )
    lines.append("")
    lines.append(f"Archived records stay out of default recall. Use `--include-archive` or `{ARCHIVE_DIR}/{ARCHIVE_INDEX_FILE}`.")
    lines.append("")
    if not archive_files:
        lines.append("- none")
    for path in archive_files[:30]:
        title = first_heading(path)
        commits = record_commits(path)
        lines.append(
            f"- `{rel(root, path)}` - {title} "
            f"(kind={record_kind(path)}, approval={approval_status(path)}, "
            f"commits={', '.join(commits) if commits else '-'})"
        )
    lines.append("")
    out = history / "INDEX.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    build_obsidian_map(root)
    build_archive_index(root)
    return out


def obsidian_map_paths(root: Path) -> list[Path]:
    history = root / HISTORY_DIR
    if not history.exists():
        return []
    paths = []
    for path in history.rglob("*.md"):
        relative = path.relative_to(history)
        if path.name == OBSIDIAN_MAP_FILE:
            continue
        if "archive" in relative.parts or "templates" in relative.parts:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(history).as_posix())


def build_obsidian_map(root: Path) -> Path:
    ensure_history(root)
    history = root / HISTORY_DIR
    grouped: dict[str, list[Path]] = {}
    for path in obsidian_map_paths(root):
        relative = path.relative_to(history)
        group = "root" if len(relative.parts) == 1 else relative.parts[0]
        grouped.setdefault(group, []).append(path)

    lines = [
        "---",
        "type: project-map",
        'title: "Project History Map"',
        "tags: [history, project-map, obsidian]",
        "---",
        "",
        "# Project History Map",
        "",
        "Open this `history/` directory as an Obsidian vault. These links stay repo-relative and portable.",
        "",
    ]
    for group in sorted(grouped, key=lambda value: (value != "root", value)):
        lines.extend([f"## {group}", ""])
        for path in grouped[group]:
            target = path.relative_to(history).with_suffix("").as_posix()
            lines.append(f"- [[{target}|{first_heading(path)}]]")
        lines.append("")

    out = history / OBSIDIAN_MAP_FILE
    content = "\n".join(lines).rstrip() + "\n"
    if not out.exists() or out.read_text(encoding="utf-8") != content:
        out.write_text(content, encoding="utf-8")
    return out


def first_heading(path: Path) -> str:
    for line in read_record_text(path).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
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


def bm25_file_paths(root: Path, include_archive: bool = False) -> list[Path]:
    paths = []
    for path in iter_search_files(root):
        if path.name in {"INDEX.md", OBSIDIAN_MAP_FILE}:
            continue
        if path.name.startswith("."):
            continue
        paths.append(path)
    if include_archive:
        paths.extend(iter_archive_files(root))
    return paths


def bm25_documents(root: Path, include_archive: bool = False) -> list[dict[str, str]]:
    docs = []
    for path in bm25_file_paths(root, include_archive):
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


def load_bm25s():
    try:
        import bm25s  # type: ignore

        return bm25s
    except Exception as exc:
        raise SystemExit(
            "BM25S is unavailable. This skill vendors bm25s under scripts/vendor/bm25s; "
            f"import failed with: {exc}"
        ) from exc


def tokenize_texts(texts: list[str]):
    bm25s = load_bm25s()
    return bm25s.tokenize(
        texts,
        lower=True,
        token_pattern=TOKEN_PATTERN,
        stopwords=None,
        return_ids=False,
        show_progress=False,
    )


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
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not fallback and not stripped.startswith("#"):
            fallback = stripped
        lowered = stripped.lower()
        if any(token in lowered for token in lowered_tokens):
            return stripped[:max_chars]
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

    bm25s = load_bm25s()
    corpus_tokens = tokenize_texts([doc["index_text"] for doc in docs])
    retriever = bm25s.BM25(method="lucene", corpus=docs)
    retriever.index(corpus_tokens, show_progress=False)

    combined = [0.0 for _ in docs]
    contributing: list[list[str]] = [[] for _ in docs]
    all_query_tokens: list[str] = []
    original_query_tokens: list[str] = []
    for label, text, weight in variants:
        tokenized = tokenize_texts([text])
        tokens = tokenized[0] if tokenized else []
        if label == "original":
            original_query_tokens = list(tokens)
        all_query_tokens.extend(tokens)
        if not tokens:
            continue
        scores = retriever.get_scores(tokens)
        for idx, score in enumerate(scores):
            weighted = float(score) * weight
            if weighted > 0:
                combined[idx] += weighted
                contributing[idx].append(label)

    ranked = sorted(enumerate(combined), key=lambda item: item[1], reverse=True)
    vocab = set(getattr(retriever, "vocab_dict", {}).keys())
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


def bm25_search(root: Path, query: str, limit: int = 8, include_archive: bool = False) -> dict:
    return bm25_search_documents(bm25_documents(root, include_archive), query, limit)


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

    if any(result.get("archive_status") == "stub" for result in results):
        notes.append(
            "Some hits are archive stubs (summary only). Open the linked `Archived To:` path, "
            "run `search --include-archive`, or `git show` the paired commit for the full record."
        )

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


def cmd_obsidian_map(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    print(rel(root, build_obsidian_map(root)))


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
    write_record(root, "changes", filename, text, "change", title, args.commit)


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
    write_record(root, "decisions", filename, text, "decision", title, args.commit)


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
    write_record(root, "ideas", filename, text, "idea", title, args.commit)


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
    write_record(root, "experiments", filename, text, "experiment", title, args.commit)


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
    write_record(root, "handoffs", filename, text, "handoff", title, args.commit)


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
    files = [
        p
        for p in history.rglob("*.md")
        if "/templates/" not in p.as_posix()
        and not any(part.startswith(".") for part in p.relative_to(history).parts)
    ]
    return sorted(files, key=record_sort_key, reverse=True)


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
    if normalized in path_index:
        return ("ok", [])
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


def lint_history(root: Path, max_chars: int, ensure: bool = True) -> tuple[list[str], list[str]]:
    if ensure:
        ensure_history(root)
    elif not (root / HISTORY_DIR).exists():
        return [], [f"{HISTORY_DIR}/ is missing; run `history.py bootstrap` before tracking durable history."]

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


def search_lines(root: Path, query: str, limit: int, include_archive: bool = False) -> list[str]:
    results: list[str] = []
    needle = query.lower()
    paths = list(iter_search_files(root))
    if include_archive:
        paths.extend(iter_archive_files(root))
    for path in paths:
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
        results = search_lines(root, args.query, args.limit, args.include_archive)
        if not results:
            print("No matches.")
            return
        print("\n".join(results))
        return

    payload = bm25_search(root, args.query, args.limit, args.include_archive)
    print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_exact(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    results = search_lines(root, args.query, args.limit, args.include_archive)
    if not results:
        print("No matches.")
        return
    print("\n".join(results))


def cmd_recent(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    paths = [path for path in iter_history_files(root) if path.name != OBSIDIAN_MAP_FILE]
    for path in paths[: args.limit]:
        print(f"{rel(root, path)} - {first_heading(path)}")


def latest_history_file(root: Path, folder: str) -> Path | None:
    base = root / HISTORY_DIR / folder
    if not base.exists():
        return None
    files = sorted(base.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def latest_handoff_paths(root: Path, limit: int) -> list[Path]:
    paths: list[Path] = []
    for folder in ["capsules", "handoffs"]:
        base = root / HISTORY_DIR / folder
        if base.exists():
            paths.extend(base.glob("*.md"))
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def record_brief(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return "-"
    for heading in ["Current State", "Summary", "Next Actions", "Open Risks"]:
        section = extract_section(text, heading)
        line = first_nonempty_line(section)
        if line and line != "-":
            return line[:220]
    return first_nonempty_line(text)[:220] or "-"


def status_lines(root: Path, status_text: str | None = None) -> list[str]:
    status = status_text if status_text is not None else git_status(root)
    if status == "clean" or status.startswith("unavailable:"):
        return []
    return [line for line in status.splitlines() if line.strip()]


def status_path(line: str) -> str:
    line = line.rstrip()
    if len(line) >= 3 and line[2] == " ":
        path = line[3:].strip()
    elif len(line) >= 2 and line[1] == " ":
        path = line[2:].strip()
    else:
        parts = line.split(maxsplit=1)
        path = parts[1].strip() if len(parts) == 2 else ""
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    return path


def is_history_record_path(path_text: str) -> bool:
    record_folders = ("changes", "decisions", "ideas", "experiments", "handoffs", "capsules", "sessions", "inbox")
    return path_text.endswith(".md") and any(path_text.startswith(f"{HISTORY_DIR}/{folder}/") for folder in record_folders)


def cmd_start(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    history = root / HISTORY_DIR
    print(f"# Session Start ({root})")
    print("")
    if not history.exists():
        print(f"- `{HISTORY_DIR}/` not found.")
        print("- Run `python3 <skill-dir>/scripts/history.py bootstrap` before recording durable history.")
        return

    context = history / "CONTEXT.md"
    if context.exists():
        print(f"## {rel(root, context)}")
        print("")
        print(clip(context.read_text(encoding="utf-8"), args.context_chars).rstrip())
        print("")
    else:
        print(f"## {HISTORY_DIR}/CONTEXT.md")
        print("")
        print("- missing")
        print("")

    latest_daily = latest_history_file(root, "daily")
    if latest_daily:
        print(f"## Latest Daily: {rel(root, latest_daily)}")
        print("")
        print(clip(latest_daily.read_text(encoding="utf-8"), args.daily_chars).rstrip())
        print("")

    print("## Recent Records")
    print("")
    count = 0
    for path in iter_history_files(root):
        if path.name in {"CONTEXT.md", "INDEX.md", "README.md", OBSIDIAN_MAP_FILE} or "/daily/" in path.as_posix():
            continue
        marker = " (archive stub)" if is_archive_stub(path) else ""
        print(f"- `{rel(root, path)}` - {first_heading(path)}{marker}")
        count += 1
        if count >= args.limit:
            break
    if count == 0:
        print("- none")
    print("")

    archived = iter_archive_files(root)
    if not archive_stub_paths(root):
        record_count = sum(
            1
            for path in iter_history_files(root)
            if path.name not in {"CONTEXT.md", "INDEX.md", "README.md", OBSIDIAN_MAP_FILE}
        )
        if record_count >= ARCHIVE_ADOPT_HINT_RECORDS:
            print("## Archive")
            print("")
            print(
                f"- {record_count} records and no archive yet. Older records still cost full text on every recall."
            )
            print("- Run `archive adopt --dry-run` once to see the one-time bulk archive for this history.")
            print("")
    if archived:
        print("## Archive")
        print("")
        print(
            f"- {len(archived)} older records live in `{ARCHIVE_DIR}/`; "
            f"`{HISTORY_DIR}/` keeps summary stubs with their paired commits."
        )
        print(f"- Search them with `search \"<query>\" --include-archive` or read `{ARCHIVE_DIR}/{ARCHIVE_INDEX_FILE}`.")
        print("")

    print("## Latest Handoffs / Capsules")
    print("")
    handoff_paths = latest_handoff_paths(root, min(args.limit, 3))
    if not handoff_paths:
        print("- none")
    for path in handoff_paths:
        print(f"- `{rel(root, path)}` - {first_heading(path)}")
        brief = record_brief(path)
        if brief and brief != "-":
            print(f"  {brief}")
    print("")

    if args.query:
        print(f"## BM25 Recall: {args.query}")
        print("")
        payload = bm25_search(root, args.query, args.limit, args.include_archive)
        print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_finish(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    print(f"# Finish Check ({root})")
    print("")
    print("## Git Status")
    print("")
    status = git_status(root, untracked_all=True)
    print("```text")
    print(status)
    print("```")
    print("")

    errors, warnings = lint_history(root, args.max_chars, ensure=False)
    lines = ["## History Lint", ""]
    lines.extend(format_lint_section("Errors", errors))
    lines.extend(format_lint_section("Warnings", warnings))
    lines.append(f"Summary: errors={len(errors)} warnings={len(warnings)}")
    print("\n".join(lines))
    print("")

    changed_paths = [status_path(line) for line in status_lines(root, status)]
    non_history_changes = [
        path for path in changed_paths if path and not path.startswith(f"{HISTORY_DIR}/")
    ]
    has_history_record_change = any(is_history_record_path(path) for path in changed_paths)

    print("## Recording Guidance")
    print("")
    if non_history_changes and not has_history_record_change:
        print("- Non-history files changed, but no history record change is visible in git status.")
        print("- If this was non-trivial research, code, experiment, architecture, or collaboration work, create a `change`, `decision`, `idea`, `experiment`, `handoff`, or `handoff-agent-capsule` record before final response.")
        preview = ", ".join(non_history_changes[:8])
        print(f"- Changed non-history paths: {preview}")
    else:
        print("- no obvious missing history record from git status")

    print("")
    print("## Commit Pairing")
    print("")
    if not git_available(root):
        print("- not a git repository; commit pairing is unavailable")
    else:
        pending = unpaired_records(root, 5)
        if pending:
            for path in pending:
                print(f"- unpaired: `{rel(root, path)}` ({record_id_for(path)})")
            print("- Pair each one with `commit --record <id> -m \"...\"` or `link-commit --record <id>`.")
        else:
            print("- every recent change/experiment record lists a commit")
        for note in commit_due_notes(root):
            print(f"- {note}")
        trailers = trailer_commit_map(root, 50)
        if trailers:
            index = record_commit_index(root)
            orphans = {
                sha
                for sha, record_ids in trailers.items()
                for record_id in record_ids
                if normalize_sha(sha) not in index.get(record_id, (None, []))[1]
            }
            if orphans:
                print(
                    f"- {len(orphans)} commit(s) carry a {COMMIT_TRAILER_KEY} trailer that no record lists; "
                    "run `sync-commits`."
                )

    print("")
    print("## Archive Pressure")
    print("")
    candidates = long_term_archive_candidates(
        root,
        list(DEFAULT_ARCHIVE_KINDS),
        DEFAULT_ARCHIVE_AGE_DAYS,
        DEFAULT_ARCHIVE_KEEP_RECENT,
    )
    stub_count = len(archive_stub_paths(root))
    bulk = long_term_archive_candidates(
        root,
        list(DEFAULT_ARCHIVE_KINDS),
        DEFAULT_ARCHIVE_AGE_DAYS,
        0,
    )
    if candidates:
        print(
            f"- {len(candidates)} record(s) are older than {DEFAULT_ARCHIVE_AGE_DAYS} days and beyond the "
            f"{DEFAULT_ARCHIVE_KEEP_RECENT} most recent per kind."
        )
        print("- Run `archive plan` to review, then `archive run` to keep summaries and move full texts.")
    else:
        print("- no records are due for archiving under the default policy")
    if stub_count == 0 and len(bulk) >= ARCHIVE_ADOPT_HINT_RECORDS:
        print(
            f"- this history has never been archived and {len(bulk)} record(s) predate the "
            f"{DEFAULT_ARCHIVE_AGE_DAYS}-day window; run `archive adopt --dry-run` to see a one-time bulk archive."
        )
    if legacy_archive_root(root).exists():
        print(f"- legacy `{rel(root, legacy_archive_root(root))}` folder found; run `archive migrate`.")

    if errors or (args.strict and warnings):
        raise SystemExit(1)


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
        if path.name in {"CONTEXT.md", "INDEX.md", "README.md", OBSIDIAN_MAP_FILE} or "/daily/" in path.as_posix():
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
        payload = bm25_search(root, args.query, args.limit, args.include_archive)
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
    return record_datetime(path) < cutoff


def promoted_to_value(path: Path) -> str:
    value_text = metadata_value(path, "Promoted To", "")
    return "" if value_text in {"", "-"} else value_text


def record_month(path: Path) -> str:
    return record_datetime(path).strftime("%Y-%m")


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


def archive_destination(root: Path, kind: str, source: Path) -> Path:
    month = record_month(source)
    return archive_root(root) / month / kind / source.name


def iter_archive_files(root: Path) -> list[Path]:
    """Full archived record texts, from the current and legacy archive folders."""
    paths: list[Path] = []
    for base in [archive_root(root), legacy_archive_root(root)]:
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            if not path.is_file():
                continue
            if path.name in {"README.md", ARCHIVE_INDEX_FILE}:
                continue
            if any(part.startswith(".") for part in path.relative_to(base).parts):
                continue
            paths.append(path)
    return sorted(paths, key=record_sort_key, reverse=True)


def archive_index_path(root: Path) -> Path:
    return archive_root(root) / ARCHIVE_INDEX_FILE


def archive_stub_paths(root: Path) -> list[Path]:
    return [path for path in iter_history_files(root) if is_archive_stub(path)]


def summary_lines_for(path: Path, max_chars: int = ARCHIVE_SUMMARY_CHARS) -> list[str]:
    """Condense a record into a handful of bullets that stay useful for recall."""
    text = read_record_text(path)
    if not text:
        return ["- (record could not be read)"]
    headings = SUMMARY_SECTIONS.get(record_kind(path), DEFAULT_SUMMARY_SECTIONS)
    lines: list[str] = []
    used = 0
    for heading in headings:
        if used >= max_chars:
            break
        section = extract_section(text, heading)
        if not section or section.strip() == "-":
            continue
        parts = [
            item.strip().lstrip("-").strip()
            for item in section.splitlines()
            if item.strip() and item.strip() != "-" and not item.strip().startswith("```")
        ]
        condensed = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if not condensed:
            continue
        snippet = condensed[:ARCHIVE_SECTION_CHARS].rstrip()
        if len(condensed) > ARCHIVE_SECTION_CHARS:
            snippet += "..."
        line = f"- **{heading}**: {snippet}"
        lines.append(line)
        used += len(line)
    if not lines:
        body = re.sub(r"^#.*$", "", strip_frontmatter(text), flags=re.MULTILINE)
        condensed = re.sub(r"\s+", " ", body).strip()
        if condensed:
            lines.append(f"- {condensed[:max_chars]}")
    return lines or ["- (no summary content found)"]


def archive_stub_text(root: Path, source: Path, destination: Path, summary: list[str]) -> str:
    text = source.read_text(encoding="utf-8")
    meta = parse_metadata(text)
    kind = meta.get("type") or record_kind(source)
    title = first_heading(source)
    record_id = record_id_for(source)
    commits = record_commits(source)

    tags = ["history", kind, ARCHIVE_STUB_TAG]
    for tag in split_tags(meta.get("tags")):
        if tag not in tags:
            tags.append(tag)
    fields: dict[str, object] = {
        "type": kind,
        "title": title,
        "date": meta.get("date") or record_datetime(source).strftime("%Y-%m-%d"),
        "record_id": record_id,
        "archive_state": "stub",
        "archived_to": rel(root, destination),
        "tags": tags,
    }
    if meta.get("status"):
        fields["status"] = meta["status"]
    if commits:
        fields["commits"] = commits
    for key in ["task", "workstream", "agent", "person", "approval status", "promoted to"]:
        if meta.get(key) and meta[key] != "-":
            fields[key] = meta[key]

    lines = [frontmatter_block(fields).rstrip(), "", f"# {title}", ""]
    lines.append(f"Record Id: {record_id}")
    lines.append(f"Date: {meta.get('date', '-') or '-'}")
    lines.append(f"Kind: {kind}")
    if meta.get("status"):
        lines.append(f"Status: {meta['status']}")
    for key, label in [("task", "Task"), ("workstream", "Workstream"), ("agent", "Agent"), ("person", "Person")]:
        if meta.get(key) and meta[key] != "-":
            lines.append(f"{label}: {meta[key]}")
    lines.append("Archive State: stub")
    lines.append(f"Archived To: {rel(root, destination)}")
    lines.append(f"Archived Date: {display_time()}")
    lines.append(f"Commits: {', '.join(commits) if commits else '-'}")
    lines.extend(["", "## Summary", ""])
    lines.extend(summary)
    lines.extend(["", f"## {COMMIT_SECTION_HEADING}", ""])
    if commits:
        lines.extend(commit_line(root, sha) for sha in commits)
    else:
        lines.append("-")
    lines.extend(
        [
            "",
            "## Full Record",
            "",
            f"- `{rel(root, destination)}` (`--include-archive`, or `archive restore --record {record_id}`)",
        ]
    )
    if commits:
        lines.append(f"- Paired diff: `git show {commits[0]}`")
    return "\n".join(lines).rstrip() + "\n"


def archived_record_text(root: Path, source: Path, stub_path: Path) -> str:
    text = source.read_text(encoding="utf-8")
    text = set_metadata_line(text, "Record Id", record_id_for(source))
    text = set_metadata_line(text, "Archived", "yes")
    text = set_metadata_line(text, "Archived Date", display_time())
    text = set_metadata_line(text, "Archived From", rel(root, source))
    text = set_metadata_line(text, "Archive Stub", rel(root, stub_path))
    return text


def restored_record_text(text: str) -> str:
    for key in [
        "Archived",
        "Archived Date",
        "Archived From",
        "Archive Stub",
        "Archive State",
        "Archived To",
    ]:
        text = remove_metadata_line(text, key)
    return text


def actively_referenced_paths(root: Path) -> set[Path]:
    """Records that curated context still points at, so age alone should not archive them."""
    history = root / HISTORY_DIR
    sources: list[Path] = []
    context = history / "CONTEXT.md"
    if context.exists():
        sources.append(context)
    for folder in ["canonical", "tasks"]:
        base = history / folder
        if base.exists():
            sources.extend(path for path in base.rglob("*.md") if path.is_file())

    referenced: set[Path] = set()
    known = {path.stem: path for path in iter_history_files(root)}
    for source in sources:
        try:
            text = source.read_text(encoding="utf-8")
        except Exception:
            continue
        for raw in re.findall(r"\[\[([^\]]+)\]\]", text):
            target = wikilink_target(raw)
            stem = Path(target).stem
            if stem in known:
                referenced.add(known[stem].resolve())
        for raw in re.findall(rf"`({re.escape(HISTORY_DIR)}/[^`]+\.md)`", text):
            candidate = root / raw
            if candidate.exists():
                referenced.add(candidate.resolve())
    return referenced


def stub_saving(root: Path, kind: str, source: Path, summary_chars: int) -> tuple[int, int]:
    """(record size, stub size) in characters, by building the stub we would write."""
    text = read_record_text(source)
    destination = archive_destination(root, kind, source)
    stub = archive_stub_text(root, source, destination, summary_lines_for(source, summary_chars))
    return len(text), len(stub)


def long_term_archive_candidates(
    root: Path,
    kinds: list[str],
    older_than_days: int | None,
    keep_recent: int,
    include_open: bool = False,
    min_saving: float = ARCHIVE_MIN_SAVING,
    include_referenced: bool = False,
    summary_chars: int = ARCHIVE_SUMMARY_CHARS,
    stats: Counter | None = None,
) -> list[tuple[str, Path]]:
    history = root / HISTORY_DIR
    cutoff = now() - timedelta(days=older_than_days) if older_than_days is not None else None
    referenced = set() if include_referenced else actively_referenced_paths(root)
    candidates: list[tuple[str, Path]] = []
    for kind in kinds:
        base = history / kind
        if not base.exists():
            continue
        files = [
            path
            for path in base.glob("*.md")
            if path.is_file() and path.name != "README.md"
        ]
        files = [
            path
            for path in files
            if not is_archive_stub(path) and archive_status(path) != "archived"
        ]
        files.sort(key=lambda path: (record_sort_key(path), path.name), reverse=True)
        for path in files[max(0, keep_recent):]:
            if not is_older_than(path, cutoff):
                continue
            if not include_open and record_is_open(path):
                continue
            if path.resolve() in referenced:
                # Canonical, task, or workstream context still links to it.
                continue
            if min_saving > 0:
                record_size, stub_size = stub_saving(root, kind, path, summary_chars)
                saved = record_size - stub_size
                worth_it = saved >= ARCHIVE_MIN_SAVING_CHARS and (
                    not record_size or saved / record_size >= min_saving
                )
            else:
                worth_it = True
            if not worth_it:
                # The stub would cost about as much to read as the record itself.
                if stats is not None:
                    stats["no-saving"] += 1
                continue
            candidates.append((kind, path))
    return candidates


def build_archive_index(root: Path) -> Path | None:
    base = archive_root(root)
    if not base.exists():
        return None
    files = iter_archive_files(root)
    lines = [
        "# History Archive Index",
        "",
        f"Generated: {display_time()}",
        "",
        f"Archived records: {len(files)}",
        "",
        "Full record texts live here; `history/` keeps a summary stub for each one.",
        "",
        "| Date | Kind | Record Id | Title | Commits | Archived Text |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path in files:
        commits = record_commits(path)
        lines.append(
            "| "
            + " | ".join(
                [
                    record_datetime(path).strftime("%Y-%m-%d"),
                    record_kind(path),
                    record_id_for(path),
                    first_heading(path).replace("|", "/"),
                    ", ".join(commits) if commits else "-",
                    f"`{rel(root, path)}`",
                ]
            )
            + " |"
        )
    if not files:
        lines.append("| - | - | - | none | - | - |")
    out = archive_index_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


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
    meta = record_metadata(path)
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
        for path in iter_archive_files(root):
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
    for area in ["canonical", "tasks", "decisions", "handoffs", "capsules", "inbox"]:
        print(f"| {area} | {file_count(root, area)} |")
    print(f"| {ARCHIVE_DIR} | {len(iter_archive_files(root))} |")
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


# --- Commit pairing commands ----------------------------------------------


def run_git(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{proc.stdout}{proc.stderr}".rstrip())
    return proc


def require_git(root: Path) -> None:
    if not git_available(root):
        raise SystemExit(f"{root} is not a git repository; commit pairing needs Git.")


def cmd_commit(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    require_git(root)
    records = [find_record(root, ref) for ref in args.record]
    record_ids = [record_id_for(path) for path in records]

    if args.all:
        run_git(root, ["add", "-A"])
    for item in args.path or []:
        run_git(root, ["add", "--", item])
    if not args.no_stage_record:
        run_git(root, ["add", "--", *[rel(root, path) for path in records]], check=False)

    staged = git_output(root, ["diff", "--cached", "--name-only"])
    if not staged:
        raise SystemExit(
            "Nothing is staged. Stage the work first, or pass --all / --path <file>."
        )

    message = args.message.rstrip() + "\n\n" + commit_trailer_block(record_ids) + "\n"
    run_git(root, ["commit", "-m", message])
    sha = resolve_commit(root, "HEAD") or "HEAD"
    short = normalize_sha(sha)

    print("# Paired Commit")
    print("")
    print(f"Commit: `{short}` - {commit_subject(root, sha)}")
    print(f"Trailer: {COMMIT_TRAILER_KEY}: {', '.join(record_ids)}")
    print("")
    print("## Records")
    print("")
    for path, record_id in zip(records, record_ids):
        pair_record_commit(root, path, sha)
        print(f"- `{rel(root, path)}` ({record_id}) -> `{short}`")
    print("")
    print("## Files")
    print("")
    for item in commit_files(root, sha)[:20]:
        print(f"- {item}")
    print("")

    build_index(root)
    if args.no_record_commit:
        print("Record files now carry the commit id and are left uncommitted.")
        return
    run_git(root, ["add", "--", HISTORY_DIR], check=False)
    if (archive_root(root)).exists():
        run_git(root, ["add", "--", ARCHIVE_DIR], check=False)
    if git_output(root, ["diff", "--cached", "--name-only"]):
        # No History-Record trailer here: the bookkeeping commit records the pairing,
        # it is not itself the work the record describes.
        bookkeeping = f"history: pair {', '.join(record_ids)} with {short}\n"
        run_git(root, ["commit", "-m", bookkeeping])
        print(f"Bookkeeping commit: `{normalize_sha(resolve_commit(root, 'HEAD') or '')}`")


def cmd_link_commit(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    require_git(root)
    records = [find_record(root, ref) for ref in args.record]
    record_ids = [record_id_for(path) for path in records]
    refs = args.commit or ["HEAD"]
    shas: list[str] = []
    for ref in refs:
        sha = resolve_commit(root, ref)
        if not sha:
            raise SystemExit(f"Unknown commit: {ref}")
        shas.append(sha)

    print("# Link Commit")
    print("")
    linked = 0
    for path, record_id in zip(records, record_ids):
        for sha in shas:
            if pair_record_commit(root, path, sha):
                linked += 1
                print(f"- `{rel(root, path)}` ({record_id}) -> `{normalize_sha(sha)}` {commit_subject(root, sha)}")
            else:
                print(f"- `{rel(root, path)}` ({record_id}) already lists `{normalize_sha(sha)}`")
    print("")

    if args.amend_trailer:
        head = resolve_commit(root, "HEAD")
        if len(shas) != 1 or shas[0] != head:
            print("- skipped --amend-trailer: it only applies to a single commit that is HEAD.")
        elif git_output(root, ["diff", "--cached", "--name-only"]):
            print("- skipped --amend-trailer: staged changes would be folded into the amended commit.")
        else:
            missing = [rid for rid in record_ids if rid not in commit_record_ids(root, head)]
            if not missing:
                print("- HEAD already carries the record trailer.")
            else:
                body = git_output(root, ["log", "-1", "--format=%B", head]) or ""
                new_body = body.rstrip() + "\n\n" + commit_trailer_block(missing) + "\n"
                run_git(root, ["commit", "--amend", "-m", new_body])
                new_head = resolve_commit(root, "HEAD") or ""
                print(f"- amended HEAD trailer; commit id is now `{normalize_sha(new_head)}`")
                for path in records:
                    text = path.read_text(encoding="utf-8")
                    text = text.replace(normalize_sha(head), normalize_sha(new_head))
                    path.write_text(text, encoding="utf-8")
                print("- rewrote the record commit ids to match the amended commit.")

    build_index(root)
    print(f"Linked: {linked}")


def cmd_commits(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    print("# Commit Pairing")
    print("")
    if args.record:
        path = find_record(root, args.record)
        record_id = record_id_for(path)
        commits = record_commits(path)
        print(f"Record: {record_id}")
        print(f"Path: `{rel(root, path)}`")
        print(f"Archive Status: {archive_status(path)}")
        print("")
        print("## Paired Commits")
        print("")
        if not commits:
            print("- none")
        for sha in commits:
            if git_available(root) and resolve_commit(root, sha):
                suffix = "" if commit_is_reachable(root, sha) else "  <- unreachable; run `sync-commits --prune`"
                print(commit_line(root, sha) + suffix)
                if args.stat:
                    stat = git_output(root, ["show", "--stat", "--format=", sha]) or "-"
                    print("")
                    print("```text")
                    print(stat)
                    print("```")
                    print("")
            else:
                print(f"- `{sha}` (not found in this repository)")
        print("")
        if git_available(root):
            trailer_only = [
                sha
                for sha, record_ids in trailer_commit_map(root, args.limit).items()
                if record_id in record_ids and normalize_sha(sha) not in commits
            ]
            if trailer_only:
                print("## Commits Referencing This Record But Not Yet Paired")
                print("")
                for sha in trailer_only:
                    print(commit_line(root, sha))
                print("")
                print("Run `sync-commits` to write them into the record.")
                print("")
        return

    if args.commit:
        require_git(root)
        sha = resolve_commit(root, args.commit)
        if not sha:
            raise SystemExit(f"Unknown commit: {args.commit}")
        short = normalize_sha(sha)
        print(f"Commit: `{short}` - {commit_subject(root, sha)}")
        print(f"Date: {commit_when(root, sha)}")
        print("")
        print("## Records")
        print("")
        found = False
        for record_id in commit_record_ids(root, sha):
            print(f"- trailer: {record_id}")
            found = True
        for path in record_search_paths(root):
            if short in record_commits(path):
                print(f"- record: `{rel(root, path)}` ({record_id_for(path)})")
                found = True
        if not found:
            print("- none")
        print("")
        print("## Files")
        print("")
        for item in commit_files(root, sha)[:20]:
            print(f"- {item}")
        print("")
        return

    print("## Recent Records")
    print("")
    for path in paired_record_paths(root)[: args.limit]:
        commits = record_commits(path)
        print(
            f"- `{rel(root, path)}` ({record_id_for(path)}) - "
            f"commits={', '.join(commits) if commits else 'none'}"
        )
    print("")
    pending = unpaired_records(root, args.limit)
    print("## Unpaired Change/Experiment Records")
    print("")
    if not pending:
        print("- none")
    for path in pending:
        print(f"- `{rel(root, path)}` ({record_id_for(path)})")
    print("")


def cmd_sync_commits(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    require_git(root)
    print("# Sync Commit Pairing")
    print("")
    linked = 0
    unknown: list[str] = []
    index = record_commit_index(root)
    trailers = trailer_commit_map(root, args.limit)
    prefetch_commit_meta(root, list(trailers))
    for sha, record_ids in trailers.items():
        for record_id in record_ids:
            entry = index.get(record_id)
            if entry is None:
                unknown.append(f"- `{normalize_sha(sha)}` references unknown record `{record_id}`")
                continue
            path, paired = entry
            if normalize_sha(sha) in paired:
                continue
            if pair_record_commit(root, path, sha):
                linked += 1
                paired.append(normalize_sha(sha))
                print(f"- `{rel(root, path)}` <- `{normalize_sha(sha)}` {commit_subject(root, sha)}")
    if linked == 0:
        print("- nothing new to pair")
    print("")

    stale: list[tuple[Path, str]] = []
    for record_id, (path, paired) in record_commit_index(root).items():
        for sha in paired:
            if not commit_is_reachable(root, sha):
                stale.append((path, sha))
    if stale:
        print("## Unreachable Commits")
        print("")
        for path, sha in stale:
            reachable_note = "squashed, rebased, or removed"
            if args.prune:
                unpair_record_commit(root, path, sha)
                print(f"- dropped `{sha}` from `{rel(root, path)}` ({reachable_note})")
            else:
                print(f"- `{rel(root, path)}` lists `{sha}`, which no branch or tag contains ({reachable_note})")
        if not args.prune:
            print("")
            print("Re-run with --prune to drop these references.")
        print("")

    if unknown:
        print("## Unresolved Trailers")
        print("")
        print("\n".join(sorted(set(unknown))))
        print("")
    build_index(root)
    print(f"Linked: {linked}")


# --- Long-term archive commands -------------------------------------------


def resolve_archive_kinds(value_text: str | None) -> list[str]:
    if not value_text:
        return list(DEFAULT_ARCHIVE_KINDS)
    requested = [item.strip().lower() for item in value_text.split(",") if item.strip()]
    if "all" in requested:
        return list(ARCHIVABLE_KINDS)
    unknown = sorted(set(requested) - set(ARCHIVABLE_KINDS))
    if unknown:
        raise SystemExit(
            "Unsupported archive kind(s): "
            + ", ".join(unknown)
            + f". Supported kinds: {', '.join(ARCHIVABLE_KINDS)}, all"
        )
    return requested


def archive_plan_pairs(
    root: Path,
    args: argparse.Namespace,
    stats: Counter | None = None,
) -> list[tuple[str, Path]]:
    if getattr(args, "record", None):
        pairs: list[tuple[str, Path]] = []
        for ref in args.record:
            path = find_record(root, ref)
            if in_archive_tree(path) or is_archive_stub(path):
                print(f"- skip (already archived): `{rel(root, path)}`")
                continue
            pairs.append((record_kind(path), path))
        return pairs
    return long_term_archive_candidates(
        root,
        resolve_archive_kinds(args.include),
        args.older_than_days,
        args.keep_recent,
        args.include_open,
        args.min_saving,
        args.include_referenced,
        getattr(args, "summary_chars", ARCHIVE_SUMMARY_CHARS),
        stats,
    )


def print_skip_stats(stats: Counter) -> None:
    skipped = stats.get("no-saving", 0)
    if skipped:
        print(
            f"- skipped {skipped} record(s) whose summary stub would not be meaningfully "
            "smaller than the record; archiving them would cost more to read, not less."
        )


def print_archive_policy(args: argparse.Namespace) -> None:
    if getattr(args, "record", None):
        print(f"Selection: explicit records ({', '.join(args.record)})")
        return
    print(f"Kinds: {', '.join(resolve_archive_kinds(args.include))}")
    print(f"Older Than Days: {args.older_than_days if args.older_than_days is not None else '-'}")
    print(f"Keep Recent Per Kind: {args.keep_recent}")
    print(f"Min Saving Per Record: {args.min_saving:.0%}")
    print(f"Include Open Records: {'yes' if args.include_open else 'no'}")
    print(f"Include Records Linked From Curated Context: {'yes' if args.include_referenced else 'no'}")


def cmd_archive_plan(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    print("# Archive Plan")
    print("")
    print_archive_policy(args)
    print("")
    stats: Counter = Counter()
    pairs = archive_plan_pairs(root, args, stats)
    print("## Candidates")
    print("")
    if not pairs:
        print("- none")
        print_skip_stats(stats)
    for kind, source in pairs:
        destination = archive_destination(root, kind, source)
        print(
            f"- `{rel(root, source)}` ({record_id_for(source)}, {record_datetime(source).strftime('%Y-%m-%d')}) "
            f"-> `{rel(root, destination)}`"
        )
    print("")
    print(f"Candidate Count: {len(pairs)}")


def cmd_archive_run(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    print("# Archive Run")
    print("")
    print_archive_policy(args)
    print(f"Dry Run: {'yes' if args.dry_run else 'no'}")
    print("")
    stats: Counter = Counter()
    pairs = archive_plan_pairs(root, args, stats)
    if not pairs:
        print("- no archive candidates")
        print_skip_stats(stats)
        return
    if args.dry_run:
        print("## Candidates")
        print("")
        for kind, source in pairs:
            print(f"- `{rel(root, source)}` -> `{rel(root, archive_destination(root, kind, source))}`")
        print("")
        print(f"Candidate Count: {len(pairs)}")
        return

    ensure_archive(root)
    print("## Archived")
    print("")
    moved = 0
    for kind, source in pairs:
        destination = unique_destination(archive_destination(root, kind, source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        summary = summary_lines_for(source, args.summary_chars)
        stub = archive_stub_text(root, source, destination, summary)
        destination.write_text(archived_record_text(root, source, source), encoding="utf-8")
        source.write_text(stub, encoding="utf-8")
        moved += 1
        print(f"- `{rel(root, source)}` -> `{rel(root, destination)}` (summary stub kept in place)")
    build_index(root)
    print("")
    print(f"Archived Count: {moved}")


def cmd_archive_restore(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    path = find_record(root, args.record)
    if in_archive_tree(path):
        archived = path
        stub_ref = metadata_value(archived, "Archive Stub", "")
        stub = root / stub_ref if stub_ref not in {"", "-"} else None
    else:
        if not is_archive_stub(path):
            raise SystemExit(f"`{rel(root, path)}` is not an archive stub; nothing to restore.")
        stub = path
        target = archived_to_value(path)
        if not target:
            raise SystemExit(f"`{rel(root, path)}` has no `Archived To:` pointer.")
        archived = root / target
    if not archived.exists():
        raise SystemExit(f"Archived text is missing: `{rel(root, archived)}`")

    destination = stub if stub is not None else root / HISTORY_DIR / record_kind(archived) / archived.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(restored_record_text(archived.read_text(encoding="utf-8")), encoding="utf-8")
    archived.unlink()
    for parent in [archived.parent, archived.parent.parent]:
        try:
            parent.rmdir()
        except OSError:
            break
    build_index(root)
    print("# Archive Restore")
    print("")
    print(f"- restored `{rel(root, destination)}` from `{rel(root, archived)}`")


def cmd_archive_status(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    archived = iter_archive_files(root)
    stubs = archive_stub_paths(root)
    print("# Archive Status")
    print("")
    print(f"Archive Folder: `{ARCHIVE_DIR}/`")
    print(f"Archived Records: {len(archived)}")
    print(f"Summary Stubs In history/: {len(stubs)}")
    legacy = legacy_archive_root(root)
    if legacy.exists():
        print(f"Legacy Folder Present: `{rel(root, legacy)}` (run `archive migrate`)")
    print("")
    print("## Active Records By Kind")
    print("")
    print("| Kind | Active | Stub | Archived |")
    print("| --- | --- | --- | --- |")
    for kind in ARCHIVABLE_KINDS:
        base = root / HISTORY_DIR / kind
        files = [p for p in base.glob("*.md") if p.is_file() and p.name != "README.md"] if base.exists() else []
        stub_count = sum(1 for p in files if is_archive_stub(p))
        archived_count = sum(1 for p in archived if record_kind(p) == kind)
        print(f"| {kind} | {len(files) - stub_count} | {stub_count} | {archived_count} |")
    print("")
    print("## Archive By Month")
    print("")
    months = Counter(record_month(path) for path in archived)
    if not months:
        print("- none")
    for month, count in sorted(months.items(), reverse=True):
        print(f"- {month}: {count}")
    print("")
    print("## Candidates Under The Current Policy")
    print("")
    print_archive_policy(args)
    print("")
    stats = Counter()
    pairs = long_term_archive_candidates(
        root,
        resolve_archive_kinds(args.include),
        args.older_than_days,
        args.keep_recent,
        args.include_open,
        args.min_saving,
        args.include_referenced,
        ARCHIVE_SUMMARY_CHARS,
        stats,
    )
    if not pairs:
        print("- none")
        print_skip_stats(stats)
    for kind, source in pairs[: args.limit]:
        print(f"- `{rel(root, source)}` ({record_datetime(source).strftime('%Y-%m-%d')})")
    if len(pairs) > args.limit:
        print(f"- ... {len(pairs) - args.limit} more")
    print("")
    print(f"Candidate Count: {len(pairs)}")


def legacy_archive_sources(root: Path) -> list[Path]:
    legacy = legacy_archive_root(root)
    if not legacy.exists():
        return []
    return [
        path
        for path in sorted(legacy.rglob("*.md"))
        if path.is_file() and path.name not in {"README.md", ARCHIVE_INDEX_FILE}
    ]


def migrate_legacy_archive(root: Path, dry_run: bool, verbose: bool = True) -> int:
    """Move a legacy history/archive/ tree into history-archive/. Returns the count."""
    legacy = legacy_archive_root(root)
    sources = legacy_archive_sources(root)
    if not dry_run and sources:
        ensure_archive(root)
    for source in sources:
        destination = archive_destination(root, record_kind(source), source)
        if not dry_run:
            destination = unique_destination(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        if verbose:
            print(f"- `{rel(root, source)}` -> `{rel(root, destination)}`")
    if dry_run or not legacy.exists():
        return len(sources)
    for path in sorted(legacy.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    leftover = [
        path
        for path in legacy.rglob("*.md")
        if path.name not in {"README.md", ARCHIVE_INDEX_FILE}
    ]
    if not leftover:
        for name in ["README.md", ARCHIVE_INDEX_FILE]:
            stale = legacy / name
            if stale.exists():
                stale.unlink()
        try:
            legacy.rmdir()
        except OSError:
            pass
    return len(sources)


def recall_surface(root: Path) -> tuple[int, int]:
    """(files, bytes) that default recall would read. Uses stat, not reads."""
    total = 0
    paths = bm25_file_paths(root)
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return len(paths), total


def cmd_archive_migrate(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    legacy = legacy_archive_root(root)
    print("# Archive Migrate")
    print("")
    if not legacy.exists():
        print(f"- no legacy `{rel(root, legacy)}` folder")
        return
    if not legacy_archive_sources(root):
        print("- legacy folder has no archived records")
    moved = migrate_legacy_archive(root, args.dry_run)
    print("")
    if args.dry_run:
        print(f"Candidate Count: {moved}")
        return
    build_index(root)
    print(f"Migrated Count: {moved}")


def cmd_archive_adopt(args: argparse.Namespace) -> None:
    """First-run bulk archive for a history that predates summary stubs."""
    root = detect_root(args.root)
    ensure_history(root)
    kinds = resolve_archive_kinds(args.include)
    stubs_before = len(archive_stub_paths(root))

    print("# Archive Adopt")
    print("")
    print("One-time bulk archive for a history written before summary stubs existed.")
    print("")
    print(f"Kinds: {', '.join(kinds)}")
    print(f"Older Than Days: {args.older_than_days}")
    print(f"Keep Recent Per Kind: {args.keep_recent}")
    print(f"Min Saving Per Record: {args.min_saving:.0%}")
    print(f"Include Open Records: {'yes' if args.include_open else 'no'}")
    print(f"Include Records Linked From Curated Context: {'yes' if args.include_referenced else 'no'}")
    print(f"Dry Run: {'yes' if args.dry_run else 'no'}")
    print("")

    if stubs_before:
        print(f"- note: {stubs_before} summary stub(s) already exist, so this history was adopted before.")
        print("- Already-archived records are skipped; this run only covers what is still full text.")
        print("")

    legacy_count = len(legacy_archive_sources(root))
    if legacy_count:
        print("## Legacy Archive Folder")
        print("")
        migrate_legacy_archive(root, args.dry_run)
        print("")
        print(f"Legacy Records Moved: {legacy_count}")
        print("")

    before_files, before_bytes = recall_surface(root)
    stats: Counter = Counter()
    pairs = long_term_archive_candidates(
        root,
        kinds,
        args.older_than_days,
        args.keep_recent,
        args.include_open,
        args.min_saving,
        args.include_referenced,
        args.summary_chars,
        stats,
    )

    print("## Records To Archive")
    print("")
    if not pairs:
        print("- none")
        print_skip_stats(stats)
        print("")
        print(
            "This history is already as cheap to recall as summary stubs would make it. "
            "Re-run later, or lower the bar with `--min-saving 0`."
        )
    else:
        by_kind = Counter(kind for kind, _ in pairs)
        for kind, count in sorted(by_kind.items()):
            print(f"- {kind}: {count}")
        oldest = min(record_datetime(path) for _, path in pairs)
        newest = max(record_datetime(path) for _, path in pairs)
        print(f"- date range: {oldest:%Y-%m-%d} .. {newest:%Y-%m-%d}")
    print("")

    if args.dry_run:
        print(f"Candidate Count: {len(pairs)}")
        if pairs:
            print_skip_stats(stats)
        print("")
        print("Re-run without --dry-run to apply. Nothing was changed.")
        return

    if pairs:
        ensure_archive(root)
        for kind, source in pairs:
            destination = unique_destination(archive_destination(root, kind, source))
            destination.parent.mkdir(parents=True, exist_ok=True)
            summary = summary_lines_for(source, args.summary_chars)
            stub = archive_stub_text(root, source, destination, summary)
            destination.write_text(archived_record_text(root, source, source), encoding="utf-8")
            source.write_text(stub, encoding="utf-8")
        build_index(root)

    after_files, after_bytes = recall_surface(root)
    print("## Result")
    print("")
    print(f"- archived: {len(pairs)} record(s)")
    if pairs:
        print_skip_stats(stats)
    print(f"- recall surface: {before_bytes / 1000:.1f}k -> {after_bytes / 1000:.1f}k chars across {after_files} files")
    if before_bytes and after_bytes < before_bytes:
        print(f"- reduction: {(1 - after_bytes / before_bytes) * 100:.1f}%")
    if not pairs:
        return
    print("")
    print("Next:")
    print(f"- Review the move, then commit `{HISTORY_DIR}/` and `{ARCHIVE_DIR}/` together.")
    print(f"- Full texts stay in `{ARCHIVE_DIR}/`; reach them with `--include-archive` or `archive restore --record <id>`.")
    if git_available(root):
        print("- Run `sync-commits` to pair existing commits that carry a History-Record trailer.")


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Repository root. Defaults to git root, then current directory.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain searchable research project history.")
    add_root(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="Create history/ structure and templates.")
    p.add_argument("--today", action="store_true", help="Also create today's daily log.")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("start", help="Print read-only startup context for a new agent/session.")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--context-chars", type=int, default=2800)
    p.add_argument("--daily-chars", type=int, default=1800)
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants in BM25 recall.")
    p.add_argument("--include-archive", action="store_true", help="Also search archived record texts.")
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("today", help="Create or print today's daily log path.")
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("index", help="Rebuild history/INDEX.md and the Obsidian project map.")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("obsidian-map", help="Rebuild history/PROJECT_MAP.md with portable wikilinks.")
    p.set_defaults(func=cmd_obsidian_map)

    p = sub.add_parser("change", help="Record a code or artifact change.")
    p.add_argument("--title", required=True)
    p.add_argument("--why")
    p.add_argument("--how")
    p.add_argument("--file", action="append")
    p.add_argument("--validation", action="append")
    p.add_argument("--risk")
    p.add_argument("--status", default="completed")
    p.add_argument("--agent", default="codex")
    p.add_argument("--commit", action="append", help="Pair this commit-ish with the record. Repeatable.")
    p.add_argument("--no-git-status", action="store_true")
    p.set_defaults(func=cmd_change)

    p = sub.add_parser("decision", help="Record a durable decision.")
    p.add_argument("--title", required=True)
    p.add_argument("--context")
    p.add_argument("--decision")
    p.add_argument("--rationale")
    p.add_argument("--consequence")
    p.add_argument("--status", default="accepted")
    p.add_argument("--commit", action="append", help="Pair this commit-ish with the record. Repeatable.")
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
    p.add_argument("--commit", action="append", help="Pair this commit-ish with the record. Repeatable.")
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
    p.add_argument("--commit", action="append", help="Pair this commit-ish with the record. Repeatable.")
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
    p.add_argument("--commit", action="append", help="Pair this commit-ish with the record. Repeatable.")
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

    p = sub.add_parser("search", help="Search history markdown files with BM25S ranking.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true", help="Use exact substring matching instead of BM25S.")
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants.")
    p.add_argument("--include-archive", action="store_true", help="Also search archived record texts.")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("exact", help="Exact substring search over history markdown files.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--include-archive", action="store_true", help="Also search archived record texts.")
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

    p = sub.add_parser("finish", help="Run final history checks and recording guidance without creating records.")
    p.add_argument(
        "--max-chars",
        type=int,
        default=OBSIDIAN_LINT_MAX_CHARS,
        help=f"Warn when a note exceeds this size. Defaults to {OBSIDIAN_LINT_MAX_CHARS}.",
    )
    p.add_argument("--strict", action="store_true", help="Treat lint warnings as failures.")
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser("recall", help="Print context, latest daily log, recent records, and optional query hits.")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--context-chars", type=int, default=2800)
    p.add_argument("--daily-chars", type=int, default=1800)
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants in BM25 recall.")
    p.add_argument("--include-archive", action="store_true", help="Also search archived record texts.")
    p.set_defaults(func=cmd_recall)

    p = sub.add_parser("commit", help="Create a Git commit paired with one or more history records.")
    p.add_argument("--record", action="append", required=True, help="Record id, path, or unique id fragment. Repeatable.")
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--all", action="store_true", help="Stage every change before committing.")
    p.add_argument("--path", action="append", help="Stage this path before committing. Repeatable.")
    p.add_argument("--no-stage-record", action="store_true", help="Do not stage the record files themselves.")
    p.add_argument(
        "--no-record-commit",
        action="store_true",
        help="Leave the updated record files uncommitted instead of adding a bookkeeping commit.",
    )
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("link-commit", help="Pair an existing commit with one or more history records.")
    p.add_argument("--record", action="append", required=True)
    p.add_argument("--commit", action="append", help="Commit-ish. Defaults to HEAD. Repeatable.")
    p.add_argument(
        "--amend-trailer",
        action="store_true",
        help=f"Add the {COMMIT_TRAILER_KEY} trailer to HEAD. This rewrites the HEAD commit id.",
    )
    p.set_defaults(func=cmd_link_commit)

    p = sub.add_parser("commits", help="Show record-to-commit pairing in both directions.")
    p.add_argument("--record", help="Record id, path, or unique id fragment.")
    p.add_argument("--commit", help="Show which records reference this commit.")
    p.add_argument("--stat", action="store_true", help="Print `git show --stat` for each paired commit.")
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(func=cmd_commits)

    p = sub.add_parser("sync-commits", help=f"Backfill pairing from {COMMIT_TRAILER_KEY} commit trailers.")
    p.add_argument("--limit", type=int, default=300, help="How many commits to scan.")
    p.add_argument(
        "--prune",
        action="store_true",
        help="Also drop paired commits that no branch or tag contains, such as after a squash merge.",
    )
    p.set_defaults(func=cmd_sync_commits)

    p = sub.add_parser(
        "archive",
        help=f"Move old records into {ARCHIVE_DIR}/ and keep a summary stub in {HISTORY_DIR}/.",
    )
    archive_sub = p.add_subparsers(dest="archive_command", required=True)

    def add_archive_policy(target: argparse.ArgumentParser, keep_recent_default: int | None = None) -> None:
        target.add_argument(
            "--include",
            help=(
                "Comma-separated kinds to consider "
                f"({', '.join(ARCHIVABLE_KINDS)}) or `all`. "
                f"Defaults to {', '.join(DEFAULT_ARCHIVE_KINDS)}."
            ),
        )
        target.add_argument(
            "--older-than-days",
            type=int,
            default=DEFAULT_ARCHIVE_AGE_DAYS,
            help=f"Only consider records older than N days. Defaults to {DEFAULT_ARCHIVE_AGE_DAYS}.",
        )
        keep_default = DEFAULT_ARCHIVE_KEEP_RECENT if keep_recent_default is None else keep_recent_default
        target.add_argument(
            "--keep-recent",
            type=int,
            default=keep_default,
            help=f"Always keep the newest N records per kind. Defaults to {keep_default}.",
        )
        target.add_argument(
            "--min-saving",
            type=float,
            default=ARCHIVE_MIN_SAVING,
            help=(
                "Archive a record only when its summary stub is at least this much smaller "
                f"than the record (and at least {ARCHIVE_MIN_SAVING_CHARS} characters smaller). "
                f"Defaults to {ARCHIVE_MIN_SAVING:.2f}; pass 0 to archive regardless."
            ),
        )
        target.add_argument(
            "--include-open",
            action="store_true",
            help="Also archive records whose status is still open, in-progress, or proposed.",
        )
        target.add_argument(
            "--include-referenced",
            action="store_true",
            help="Also archive records that CONTEXT.md, canonical/, or tasks/ still link to.",
        )

    ap = archive_sub.add_parser("plan", help="List records that would be archived.")
    add_archive_policy(ap)
    ap.add_argument("--record", action="append", help="Plan these specific records instead of using the age policy.")
    ap.set_defaults(func=cmd_archive_plan)

    ap = archive_sub.add_parser("run", help="Archive full record texts and leave summary stubs behind.")
    add_archive_policy(ap)
    ap.add_argument("--record", action="append", help="Archive these specific records regardless of age.")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan without moving or rewriting files.")
    ap.add_argument(
        "--summary-chars",
        type=int,
        default=ARCHIVE_SUMMARY_CHARS,
        help=f"Summary budget kept in the stub. Defaults to {ARCHIVE_SUMMARY_CHARS}.",
    )
    ap.set_defaults(func=cmd_archive_run)

    ap = archive_sub.add_parser(
        "adopt",
        help="First run on an existing history: bulk-archive everything past the age window.",
    )
    add_archive_policy(ap, keep_recent_default=0)
    ap.add_argument("--dry-run", action="store_true", help="Print the plan without moving or rewriting files.")
    ap.add_argument(
        "--summary-chars",
        type=int,
        default=ARCHIVE_SUMMARY_CHARS,
        help=f"Summary budget kept in each stub. Defaults to {ARCHIVE_SUMMARY_CHARS}.",
    )
    ap.set_defaults(func=cmd_archive_adopt)

    ap = archive_sub.add_parser("restore", help="Move an archived record back into history/ and drop its stub.")
    ap.add_argument("--record", required=True, help="Record id, stub path, or archived path.")
    ap.set_defaults(func=cmd_archive_restore)

    ap = archive_sub.add_parser("status", help="Show archive counts, stub counts, and current candidates.")
    add_archive_policy(ap)
    ap.add_argument("--limit", type=int, default=12)
    ap.set_defaults(func=cmd_archive_status)

    ap = archive_sub.add_parser("migrate", help=f"Move a legacy {HISTORY_DIR}/{LEGACY_ARCHIVE_DIR}/ folder into {ARCHIVE_DIR}/.")
    ap.add_argument("--dry-run", action="store_true")
    ap.set_defaults(func=cmd_archive_migrate)

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

    cp = collab_sub.add_parser(
        "archive",
        help=f"Move promoted or stale auxiliary records into {ARCHIVE_DIR}/ without leaving a stub.",
    )
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
