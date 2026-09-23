---
type: change
title: "history-archive summary stub과 record-commit pairing 추가"
date: "2026-09-23 10:44 +0900"
status: completed
tags: [history, change]
agent: codex
record_id: chg-2026-09-23-104430-history-archive-summary-stub-record-commit-pairing
commits: 30428ed2fc54
---
# Change - history-archive summary stub과 record-commit pairing 추가

Date: 2026-09-23 10:44 +0900
Agent: codex
Status: completed
Record Id: chg-2026-09-23-104430-history-archive-summary-stub-record-commit-pairing
Commits: 30428ed2fc54

## Why

장기 프로젝트에서 history/가 계속 커져 recall 부담이 커졌고, 기록이 실제 commit과 연결되지 않아 요약의 근거 diff를 찾기 어려웠다.

## How

scripts/history.py에 archive plan/run/restore/status/migrate와 commit/link-commit/commits/sync-commits 서브커맨드를 추가했다. write_record가 Record Id와 ## Commits 섹션을 기록에 새기고, archive run은 full text를 history-archive/YYYY-MM/<kind>/로 옮기면서 요약 stub을 제자리에 남긴다. record 나이는 mtime 대신 파일명/메타데이터 날짜에서 계산하고, search/exact/start/recall에 --include-archive를 추가했다. collab archive 목적지도 history-archive/로 통일했다.

## Files

- scripts/history.py
- SKILL.md
- README.md
- references/history-structure.md
- tests/archive_commit_behavior.py
- tests/collab_behavior_smoke.py

## Validation

- python3 -m unittest tests.archive_commit_behavior tests.collab_behavior_smoke (33 tests, OK)
- python3 scripts/history.py lint --strict
- 임시 git 저장소에서 bootstrap -> change -> commit --record -> archive run -> archive restore -> archive migrate 수동 확인

## Risks / Follow-Ups

기존 프로젝트의 history/archive/는 archive migrate를 실행해야 history-archive/로 이동한다. 이미 archive된 기록에는 stub이 생기지 않는다. archive 기본 정책은 보수적이므로 대형 프로젝트에서는 --keep-recent/--older-than-days 조정이 필요하다.

## Update 2026-09-23

- archive 기본 나이를 120일에서 **60일**로 낮췄다 (`DEFAULT_ARCHIVE_AGE_DAYS`). kind별 최근 20개 유지, open/참조/1200자 미만 보호 규칙은 그대로다.
- 기존 기록 적용 비용을 합성 저장소로 측정했다. `Record Id:`는 경로에서 유도되고 `## Commits`는 최초 pairing 때 생성되므로 **이전 버전 기록을 고쳐 쓸 필요가 없다**.
- 측정 중 O(commits x records) 스캔을 발견해 고쳤다: `trailer_commit_map`이 `git log` 한 번으로 trailer를 읽고, `record_commit_index`가 레코드 색인을 한 번만 만들며, `prefetch_commit_meta`가 커밋 메타데이터를 배치로 가져온다. 파일 읽기/메타데이터는 (path, mtime_ns, size) 키로 캐싱한다.
- 718 레코드 기준: `sync-commits` 6.96s -> 0.33s, `finish` 3.99s -> 0.51s. `archive run`은 493건 1.0s, recall corpus 4.55M -> 1.15M chars.
- `extract_section`/`append_to_section`의 `\s*$`가 뒤따르는 빈 줄까지 먹던 문제를 `[ \t]*$`로 고쳤다.

## Update 2026-09-23 (2)

- 레거시 저장소 첫 도입용 `archive adopt`를 추가했다. steady-state 정책은 kind별 최근 20개를 지키기 때문에 한 번도 아카이빙하지 않은 저장소에서는 후보가 0건으로 나온다. `adopt`는 그 guard를 끄고 age window 이후 전체를 한 번에 옮기며, 레거시 `history/archive/` 이관과 recall surface 감소율 리포트까지 한다.
- 같은 목적(비용 절감)에 기여하는 guard는 유지한다: open 상태, curated context가 링크한 기록, 1200자 미만 기록. 각각 `--include-open`/`--include-referenced`/`--min-chars 0`로 해제.
- 멱등이다. 두 번째 실행은 기존 stub 수를 보고하고 아무것도 옮기지 않는다.
- `start`/`finish`가 stub이 하나도 없고 레코드가 60개 이상이면 `archive adopt --dry-run`을 안내한다.
- 707 레코드(6개월) 기준: 393건 0.93초, recall surface 3.41M -> 1.54M chars (-55%).

## Update 2026-09-23 (3)

- 이 저장소 자체에 `archive adopt`를 적용해 보고 **아카이빙이 recall surface를 45.4k -> 48.2k로 오히려 늘리는** 것을 발견했다. 9건 중 8건에서 stub이 원본보다 컸다 (합계 +3,023자).
- 원인: `--min-chars 1200` 문자 수 하한이 stub 자체 비용(frontmatter + 메타데이터 블록 + 요약 + commit 목록 + 포인터 = 약 1.6~1.9k자)보다 낮았다. 1.3~1.5k자 기록은 아카이빙하면 커진다.
- 수정: 길이 추정 대신 **실제 stub을 만들어 절감량을 비교**한다 (`stub_saving`). stub이 원본보다 30% 이상 그리고 400자 이상 작을 때만 아카이빙한다. `--min-chars`는 `--min-saving`으로 교체했다.
- stub의 "Full Record" 보일러플레이트도 3~4줄에서 1~2줄로 줄였다.
- 후보가 0건일 때 "절감이 안 되어 N건 건너뜀"을 출력하도록 해서 침묵이 아니라 근거 있는 결론이 되게 했다.
- 결과: 이 저장소는 19건 전부 건너뛰고 "이미 충분히 싸다"고 보고한다. 합성 장기 저장소(707 레코드)는 393건 아카이빙, recall surface -55.7%로 그대로 동작한다.
- 교훈: 요약 기반 아카이빙은 기록 하나가 충분히 클 때만 이득이다. 기록이 짧은 프로젝트에는 적용하지 않는 것이 맞다.

## Commits

- `30428ed2fc54` 2026-09-23 11:57 - Add history-archive summary stubs and record-commit pairing
