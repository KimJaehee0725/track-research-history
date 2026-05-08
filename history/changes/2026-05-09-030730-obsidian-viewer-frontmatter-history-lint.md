---
type: change
title: "Obsidian viewer용 frontmatter와 history lint 추가"
date: "2026-05-09 03:07 +0900"
status: completed
tags: [history, change]
agent: codex
---
# Change - Obsidian viewer용 frontmatter와 history lint 추가

Date: 2026-05-09 03:07 +0900
Agent: codex
Status: completed

## Why

Obsidian은 Git history의 대체 저장소가 아니라 사람이 보는 viewer/editor로만 쓰기로 했으므로, 같은 markdown 파일을 graph/backlink에서 읽기 좋게 만들 필요가 있다.

## How

새 기록 생성 경로에 YAML frontmatter를 추가하고, collaboration promotion/archive metadata와 동기화되도록 했다. broken wiki link, ambiguous link, oversized note, missing frontmatter를 확인하는 lint 명령과 smoke test를 추가했다.

## Files

- scripts/history.py
- SKILL.md
- references/history-structure.md
- references/obsidian-llm-wiki-transition.md
- tests/collab_behavior_smoke.py

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 tests/collab_behavior_smoke.py
- python3 scripts/history.py --root . lint

## Risks / Follow-Ups

기존에 생성된 과거 history record는 자동 마이그레이션하지 않기 때문에 lint에서 missing frontmatter warning이 남을 수 있다.

## Git Status Snapshot

```text
M SKILL.md
 M history/INDEX.md
 M references/history-structure.md
 M references/obsidian-llm-wiki-transition.md
 M scripts/history.py
 M tests/collab_behavior_smoke.py
```
