---
type: change
title: "Add trigger policy start and finish commands"
date: "2026-05-19 15:54 +0900"
status: completed
tags: [history, change]
agent: codex
---
# Change - Add trigger policy start and finish commands

Date: 2026-05-19 15:54 +0900
Agent: codex
Status: completed

## Why

Need explicit trigger points for new sessions, work start, handoffs, collaboration, and final-response checks without making startup recall mutate history.

## How

Added read-only start context output, advisory finish checks, trigger policy documentation, updated agent prompt text, and smoke tests for startup read-only behavior and finish guidance.

## Files

- scripts/history.py
- SKILL.md
- references/history-structure.md
- agents/openai.yaml
- tests/collab_behavior_smoke.py

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 -m unittest tests/collab_behavior_smoke.py
- python3 scripts/history.py start --query 'trigger start finish' --limit 3 --no-variants
- python3 scripts/history.py finish
- git diff --check

## Risks / Follow-Ups

Existing older history notes still produce missing-frontmatter lint warnings; this change leaves those warnings unchanged.

## Git Status Snapshot

```text
M SKILL.md
 M agents/openai.yaml
 M references/history-structure.md
 M scripts/history.py
 M tests/collab_behavior_smoke.py
```
