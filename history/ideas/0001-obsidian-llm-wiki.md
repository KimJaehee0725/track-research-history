# Idea 0001 - Obsidian 기반 LLM-Wiki 전환 검토

Date: 2026-05-09 02:46 +0900
Status: open
Tags: obsidian, llm-wiki, architecture

## Problem / Opportunity

현재 history skill은 markdown 기록 전체를 BM25 chunk 검색으로 recall한다. 기록이 늘어날수록 검색은 가능하지만 agent가 스스로 구조화한 지식 그래프나 canonical synthesis를 유지하지 못할 수 있다.

## Hypothesis

Obsidian vault를 raw source, compiled wiki, schema, log 계층으로 두고 agent가 wiki page와 backlinks를 관리하면 Karpathy식 LLM-Wiki의 compounding 장점을 가져오면서 기존 CLI/BM25는 검증과 fallback 검색으로 남길 수 있다.

## Expected Value

사람은 Obsidian에서 그래프와 문서를 읽고, agent는 schema와 lint 규칙에 따라 wiki를 갱신한다. 단점은 hallucinated synthesis, link rot, merge conflict, scale 비용이므로 source citation, frontmatter schema, deterministic lint, raw-source immutability, BM25/vector fallback으로 보완한다.

## Links / Evidence

-

## Next Check

obsidian-llm-wiki-experiment 브랜치에서 vault 구조와 migration plan을 먼저 문서화한 뒤, bootstrap/recall/record CLI를 vault-aware로 확장한다.
