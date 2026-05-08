# Decision 0001 - Obsidian은 viewer/editor로만 사용하고 Git history를 source of truth로 유지

Date: 2026-05-09 02:59 +0900
Status: accepted

## Context

Obsidian 기반 LLM-Wiki 전환을 검토했지만, 서버 간 이동과 다중 agent 협업에서는 Obsidian remote vault나 내부 cache를 durable source로 삼기 어렵다.

## Decision

기존 repository-local history/ markdown과 Git tracking을 source of truth로 유지한다. Obsidian은 같은 markdown을 사람이 탐색하는 viewer/editor로만 간주한다. SQLite FTS5 BM25 recall은 agent 기본 검색 backend로 유지한다.

## Rationale

이 구조는 headless server, SSH, CI, Codex/Claude CLI 환경에서 동일하게 동작하고, Git diff/review/rollback을 유지한다. Obsidian의 graph/backlink/frontmatter는 편의 계층으로만 쓰면 lock-in과 sync 불확실성을 피할 수 있다.

## Consequences

다음 설계는 별도 vault나 compiled wiki 전환보다 Obsidian-friendly frontmatter/link conventions와 deterministic lint에 집중한다.
