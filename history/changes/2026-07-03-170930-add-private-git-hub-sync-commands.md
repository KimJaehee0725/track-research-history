---
type: change
title: "Add private Git hub sync commands"
date: "2026-07-03 17:09 +0900"
status: completed
tags: [history, change]
agent: codex
---
# Change - Add private Git hub sync commands

Date: 2026-07-03 17:09 +0900
Agent: codex
Status: completed

## Why

Need cross-server and cross-project research history to sync through a GitHub private repository without making a local UI server the source of truth.

## How

Added hub init/client-init/sync/submit/recall/status commands, hub config and outbox handling, project history mirroring under history/projects/<project>/, Git-only history staging, docs, and smoke tests using a local bare Git remote.

## Files

- scripts/history.py
- tests/collab_behavior_smoke.py
- SKILL.md
- references/history-structure.md
- agents/openai.yaml

## Validation

- python3 -m py_compile scripts/history.py
- python3 -m unittest tests.collab_behavior_smoke
- manual no-op hub submit smoke: first submit committed, second submit did not

## Risks / Follow-Ups

Real GitHub setup still needs a private repo and SSH deploy key or credential helper on each server.

## Git Status Snapshot

```text
M SKILL.md
 M agents/openai.yaml
 M history/INDEX.md
 M references/history-structure.md
 M scripts/history.py
 M tests/collab_behavior_smoke.py
?? history/daily/2026-07-03.md
?? history/ideas/0002-paper-recall.md
```
