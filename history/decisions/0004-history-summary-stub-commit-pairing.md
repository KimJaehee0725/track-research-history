---
type: decision
title: "장기 프로젝트 history는 summary stub과 commit pairing으로 유지한다"
date: "2026-09-23 10:44 +0900"
status: accepted
tags: [history, decision]
record_id: dec-0004-history-summary-stub-commit-pairing
---
# Decision 0004 - 장기 프로젝트 history는 summary stub과 commit pairing으로 유지한다

Date: 2026-09-23 10:44 +0900
Status: accepted
Record Id: dec-0004-history-summary-stub-commit-pairing

## Context

몇 달 이상 지속되는 프로젝트에서 history/ 전체를 recall 대상으로 두면 기록량이 너무 커져서 agent가 읽어야 할 맥락이 과도해진다. 또한 기록이 단순 서술이라 실제 코드 변경과의 연결이 끊겨 있었다.

## Decision

오래되고 잘 쓰이지 않는 기록은 full text를 repo 루트의 history-archive/YYYY-MM/<kind>/로 옮기고 history/에는 summary stub만 남긴다. 모든 record는 고정 Record Id와 ## Commits 섹션을 갖고, 대응하는 commit은 History-Record: <id> trailer를 갖는다.

## Rationale

stub은 record id, 메타데이터, 요약, paired commit 포인터를 유지하므로 recall 비용은 줄이면서 추적성은 잃지 않는다. commit trailer는 파일 이동/이름 변경에도 살아남고, 요약만 남은 기록도 git show로 원본 diff를 확인할 수 있다. 삭제 대신 이동이므로 archive restore로 완전히 되돌릴 수 있다.

## Consequences

기본 recall/BM25/Obsidian vault에서 archive는 제외되고 --include-archive로만 접근한다. 기본 정책(120일, kind별 최근 20개 유지, open 상태·curated context 참조·1200자 미만 기록 제외)은 보수적이므로 프로젝트마다 --older-than-days/--keep-recent로 조정한다. collab archive는 promotion 정리용으로 stub 없이 이동하는 기존 동작을 유지한다.
