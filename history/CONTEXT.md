# Project Context

Last updated: 2026-08-03

## Research Goal

- 각 연구 프로젝트가 자신의 `history/` Markdown에 변경 이유, 결정, 실험, handoff를 가볍고 이식 가능하게 보관한다.

## Current Architecture Or Structure

- 프로젝트별 `history/`와 Git이 유일한 durable source of truth다.
- `scripts/history.py`가 구조, record, index, lint, recall을 관리한다.
- ranked recall은 `scripts/vendor/bm25s/`와 NumPy만 사용하며 검색 시 현재 Markdown으로 in-memory index를 만든다.
- `history/PROJECT_MAP.md`는 Obsidian에서 열 수 있는 repo-relative wikilink 진입점이다.

## Current Decisions

- SQLite, 중앙 memory server, password mode, SSH RPC, 별도 data vault를 사용하지 않는다.
- 각 프로젝트의 `history/` 폴더를 Obsidian vault로 직접 열며 `.obsidian/`은 Git에서 제외한다.
- collaboration layer도 별도 중앙 저장소가 아니라 해당 프로젝트의 `history/` 안에서만 사용한다.

## Active Ideas

- 기록 수가 커질 때 BM25S chunk 설정과 recall 품질을 실제 프로젝트별로 측정한다.

## Open Questions And Risks

- vendored BM25S 동작에는 NumPy가 필요하다.
- 매우 큰 프로젝트에서는 검색 시 in-memory index 생성 비용을 재평가할 수 있으나 SQLite로 전환하지 않는다.

## Next Steps

- Dolphin image가 이 skill을 직접 설치하고 중앙 Research Memory mount/config 없이 동작하도록 맞춘다.
