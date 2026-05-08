# Change - Add large-scale collaboration workflow

Date: 2026-05-08 01:54 +0900
Agent: codex
Status: completed

## Why

Need the history skill to support 20-person benchmark collaboration with a central canonical context, task/workstream summaries, inbox submissions, and maintainer promotion.

## How

Added collab bootstrap, submit-summary, promote, recall, and status commands; scoped BM25 retrieval with approval status; collaboration templates; sensitive-content warnings; and skill/reference documentation.

## Files

- scripts/history.py
- SKILL.md
- references/history-structure.md
- agents/openai.yaml

## Validation

- python3 -m py_compile scripts/history.py
- temp repo smoke: collab bootstrap, submit-summary, recall without inbox, recall with inbox, promote decision, status, strict warning
- temp repo smoke: promote workstream and accepted inbox metadata
- scale smoke: 15 tasks, 20 people, 200 submitted summaries, scoped recall excluded inbox by default and completed in 17 seconds

## Risks / Follow-Ups

Generated local history/ is untracked in this skill repo unless the maintainer chooses to keep it.

## Git Status Snapshot

```text
M SKILL.md
 M agents/openai.yaml
 M references/history-structure.md
 M scripts/history.py
?? history/
```
