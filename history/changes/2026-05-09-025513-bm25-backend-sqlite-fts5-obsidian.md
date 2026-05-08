# Change - BM25 backend을 SQLite FTS5로 교체하고 Obsidian 전환 메모 추가

Date: 2026-05-09 02:55 +0900
Agent: codex
Status: completed

## Why

bm25s는 성능이 좋지만 vendored package와 NumPy/SciPy 계열 의존성 부담이 있어 skill 배포 footprint를 줄일 필요가 있다. Obsidian 기반 전환에서는 Git과 Obsidian Sync의 역할도 구분해야 한다.

## How

검색 backend를 Python 표준 라이브러리 sqlite3의 FTS5 bm25() ranking으로 바꾸고, query tokenization과 chunk scoring을 기존 virtual chunk 구조에 맞게 연결했다. scripts/vendor/bm25s를 제거하고 문서의 BM25 설명을 SQLite FTS5 기준으로 갱신했다. Obsidian LLM-Wiki 전환 메모에는 raw/wiki/schema/log 계층, sync 가능성과 한계, Git 유지 권장 조건을 정리했다.

## Files

- scripts/history.py
- SKILL.md
- references/history-structure.md
- references/obsidian-llm-wiki-transition.md
- scripts/vendor/bm25s

## Validation

- python3 -m py_compile scripts/history.py tests/collab_behavior_smoke.py
- python3 tests/collab_behavior_smoke.py
- manual smoke: python3 scripts/history.py --root . search 'SQLite FTS5 Obsidian' --limit 5 --no-variants

## Risks / Follow-Ups

SQLite FTS5가 없는 Python 빌드에서는 BM25 search가 동작하지 않는다. 이 경우 exact search는 fallback으로 남아 있다.

## Git Status Snapshot

```text
M SKILL.md
 M history/INDEX.md
 M references/history-structure.md
 M scripts/history.py
D  scripts/vendor/bm25s/__init__.py
D  scripts/vendor/bm25s/cli.py
D  scripts/vendor/bm25s/hf.py
D  scripts/vendor/bm25s/high_level/README.md
D  scripts/vendor/bm25s/high_level/__init__.py
D  scripts/vendor/bm25s/high_level/setup.py
D  scripts/vendor/bm25s/mcp/__init__.py
D  scripts/vendor/bm25s/mcp/server.py
D  scripts/vendor/bm25s/numba/__init__.py
D  scripts/vendor/bm25s/numba/retrieve_utils.py
D  scripts/vendor/bm25s/numba/selection.py
D  scripts/vendor/bm25s/scoring.py
D  scripts/vendor/bm25s/selection.py
D  scripts/vendor/bm25s/stopwords.py
D  scripts/vendor/bm25s/terminal/__init__.py
D  scripts/vendor/bm25s/tokenization.py
D  scripts/vendor/bm25s/utils/__init__.py
D  scripts/vendor/bm25s/utils/beir.py
D  scripts/vendor/bm25s/utils/benchmark.py
D  scripts/vendor/bm25s/utils/corpus.py
D  scripts/vendor/bm25s/utils/json_functions.py
D  scripts/vendor/bm25s/version.py
D  scripts/vendor/bm25s_LICENSE
D  scripts/vendor/bm25s_SOURCE.txt
?? history/daily/2026-05-09.md
?? history/ideas/
?? references/obsidian-llm-wiki-transition.md
```
