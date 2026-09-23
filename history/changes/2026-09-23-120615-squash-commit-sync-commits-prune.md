---
type: change
title: "squash 머지로 끊긴 commit 참조를 sync-commits --prune으로 정리"
date: "2026-09-23 12:06 +0900"
status: completed
tags: [history, change]
agent: codex
record_id: chg-2026-09-23-120615-squash-commit-sync-commits-prune
commits: 7c3b48bfc8a0
---
# Change - squash 머지로 끊긴 commit 참조를 sync-commits --prune으로 정리

Date: 2026-09-23 12:06 +0900
Agent: codex
Status: completed
Record Id: chg-2026-09-23-120615-squash-commit-sync-commits-prune
Commits: 7c3b48bfc8a0

## Why

PR #3을 squash 머지한 뒤 레코드가 가리키던 30428ed가 어느 브랜치에도 없는 커밋이 됐다. sync-commits는 trailer에서 추가만 할 뿐 죽은 참조를 지우지 못해서, squash 머지를 쓰면 머지할 때마다 같은 문제가 반복된다.

## How

commit_is_reachable가 git for-each-ref --contains로 도달 가능성을 확인하고, unpair_record_commit/drop_commit_from_text가 Commits 메타데이터와 ## Commits 섹션에서 참조를 제거한다. sync-commits는 도달 불가 참조를 항상 보고하고 --prune일 때만 삭제한다. stub이면 archive 원문도 같이 갱신한다. commits --record는 도달 불가 pair를 인라인으로 표시한다.

## Files

- scripts/history.py
- SKILL.md
- references/history-structure.md
- tests/archive_commit_behavior.py

## Validation

- python3 -m unittest tests.archive_commit_behavior tests.collab_behavior_smoke (38 tests, OK)
- python3 scripts/history.py lint --strict
- 이 저장소에서 실제 재현 후 --prune으로 30428ed 제거, efbc403으로 재연결 확인

## Risks / Follow-Ups

삭제는 opt-in이다. 로컬에만 있고 아직 push하지 않은 커밋은 어느 ref에도 없으면 도달 불가로 판정되므로, push 전에 --prune을 돌리면 유효한 pair가 지워질 수 있다.

## Commits

- `7c3b48bfc8a0` 2026-09-23 12:06 - Prune commit pairings a squash merge left unreachable
