# Change - Add collaboration archive workflow

Date: 2026-05-08 02:21 +0900
Agent: codex
Status: completed

## Why

Need Git-tracked history folders to stay manageable in large multi-agent projects without deleting promoted or stale records.

## How

Added collab archive movement, archive metadata, include-archive recall, richer status summaries, archive index separation, documentation, and behavior smoke tests.

## Files

- scripts/history.py
- tests/collab_behavior_smoke.py
- SKILL.md
- references/history-structure.md
- history/README.md
- history/archive/README.md

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 tests/collab_behavior_smoke.py
- manual smoke: bootstrap, submit-summary, promote, archive --dry-run, archive, recall --include-archive

## Risks / Follow-Ups

No git repository is present at /Users/jaeheemacbook/Desktop/custom-apps/history-skill, so git diff/status validation was unavailable.

## Git Status Snapshot

```text
M SKILL.md
 M agents/openai.yaml
 M references/history-structure.md
 M scripts/history.py
?? history/
?? tests/
```
