---
type: change
title: "Restore local BM25S research history"
date: "2026-08-03 05:10 +0000"
status: completed
tags: [history, change]
agent: codex
---
# Change - Restore local BM25S research history

Date: 2026-08-03 05:10 +0000
Agent: codex
Status: completed

## Why

각 프로젝트의 Markdown history로 회귀하고 중앙 server/password/SSH/SQLite 운영 부담을 제거하면서 Obsidian graph 탐색을 유지해야 한다.

## How

중앙 서비스 코드를 제거하고 repo-local history CLI와 vendored BM25S를 복원했다. PROJECT_MAP.md 생성, 상대 wikilink, .obsidian ignore, strict lint 및 회귀 테스트를 추가했다.

## Files

- SKILL.md
- scripts/history.py
- scripts/vendor/bm25s/
- references/history-structure.md
- references/obsidian-llm-wiki-transition.md
- tests/collab_behavior_smoke.py

## Validation

- python3 tests/collab_behavior_smoke.py (21 tests passed)
- python3 scripts/history.py lint --strict (0 errors, 0 warnings)
- quick_validate.py . (Skill is valid)

## Risks / Follow-Ups

BM25S retrieval requires NumPy; no SQLite fallback is intentionally provided.
