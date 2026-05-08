# Idea 0001 - Obsidian 기반 LLM-Wiki 전환 검토

Date: 2026-05-09 02:46 +0900
Status: open
Tags: obsidian, llm-wiki, architecture

## Problem / Opportunity

현재 history skill은 markdown 기록 전체를 BM25 chunk 검색으로 recall한다. 기록이 늘어날수록 검색은 가능하지만 agent가 스스로 구조화한 지식 그래프나 canonical synthesis를 유지하지 못할 수 있다.

## Hypothesis

Git-tracked `history/`를 source of truth로 유지하고, Obsidian은 사람이 같은 markdown을 탐색하는 viewer/editor로만 두면 기존 CLI/BM25 흐름의 안정성을 유지하면서 Obsidian의 graph/backlink/frontmatter 장점을 선택적으로 쓸 수 있다.

## Expected Value

사람은 Obsidian에서 그래프와 문서를 읽고, agent는 기존처럼 Git-tracked history markdown과 SQLite FTS5 BM25 recall을 사용한다. 단점은 Obsidian-only metadata가 CLI에서 무의미해질 수 있다는 점이므로 plain markdown compatibility와 deterministic lint를 우선한다.

## Links / Evidence

-

## Next Check

obsidian-llm-wiki-experiment 브랜치에서 별도 vault 전환보다 Obsidian-friendly metadata/link conventions와 lint를 먼저 설계한다.
