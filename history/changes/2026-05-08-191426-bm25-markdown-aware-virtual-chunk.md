# Change - BM25 검색을 markdown-aware virtual chunk로 전환

Date: 2026-05-08 19:14 +0900
Agent: codex
Status: completed

## Why

파일 하나를 검색 document 하나로 유지하면 기록이 길어질수록 BM25 ranking과 excerpt 품질이 떨어진다.

## How

검색 시점에만 markdown 파일을 virtual chunk로 나누도록 공통 함수를 추가했다. 2600자 이하 파일은 그대로 두고, 긴 파일은 metadata prefix를 각 chunk에 붙인 뒤 ## section, paragraph group, char fallback 순서로 2200자 target과 250자 overlap을 적용한다. 검색 결과에는 chunk 번호, heading, line start를 출력하고 excerpt는 원래 query token을 우선해 선택한다.

## Files

- scripts/history.py
- tests/collab_behavior_smoke.py
- SKILL.md
- references/history-structure.md

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 tests/collab_behavior_smoke.py

## Risks / Follow-Ups

같은 긴 파일에서 여러 chunk가 동시에 상위 결과에 나올 수 있다. 현재는 중복 제거보다 정확한 위치 표시를 우선했다.

## Git Status Snapshot

```text
M SKILL.md
 M references/history-structure.md
 M scripts/history.py
 M tests/collab_behavior_smoke.py
```
