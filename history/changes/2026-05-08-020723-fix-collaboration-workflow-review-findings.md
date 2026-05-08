# Change - Fix collaboration workflow review findings

Date: 2026-05-08 02:07 +0900
Agent: codex
Status: completed

## Why

The collaboration workflow review found that rejected decisions could appear accepted, promotion could bypass inbox, maintainer notes promoted unreviewed sections, scoped handoff metadata was missing, and status lacked pending/stale collaboration visibility.

## How

Updated approval status handling, inbox-only promotion validation, note-only promotion semantics with an explicit include flag, task/workstream metadata on handoffs and capsules, expanded collab status, added behavior smoke tests, and refreshed skill documentation.

## Files

- scripts/history.py
- tests/collab_behavior_smoke.py
- SKILL.md
- references/history-structure.md

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 tests/collab_behavior_smoke.py
- git diff --check
- scale smoke: 15 tasks, 20 people, 200 submitted summaries, default recall excluded inbox and include-inbox showed submitted approval in 16 seconds

## Risks / Follow-Ups

history/ remains untracked in this skill repo unless the maintainer decides to keep local history records under version control.

## Git Status Snapshot

```text
M SKILL.md
 M agents/openai.yaml
 M references/history-structure.md
 M scripts/history.py
?? history/
?? tests/
```
