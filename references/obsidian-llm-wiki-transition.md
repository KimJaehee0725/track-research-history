# Obsidian LLM-Wiki Transition Notes

Date: 2026-05-09
Status: draft
Branch: obsidian-llm-wiki-experiment

## 요약

현재 `track-research-history`는 repository-local `history/` 폴더와 BM25 recall을 중심으로 동작한다. Obsidian 기반 전환은 단순히 UI를 바꾸는 것이 아니라, Karpathy식 LLM-Wiki 패턴에 가깝게 `raw source`, `compiled wiki`, `schema`, `log` 계층을 분리하는 변화다.

권장 방향은 기존 BM25 검색을 버리는 것이 아니라, Obsidian-friendly compiled wiki를 기본 recall 대상으로 삼고 SQLite FTS5 BM25를 fallback/provenance search로 유지하는 것이다.

## Karpathy LLM-Wiki와의 관계

Karpathy의 핵심은 raw document chunk를 매번 query-time에 재조립하지 않고, LLM이 persistent markdown wiki를 누적 관리하게 하는 것이다.

비교:

- Karpathy 원형: raw sources는 immutable이고, LLM이 compiled wiki를 쓰며, schema 문서가 agent의 유지보수 규칙이 된다.
- 현재 skill: record markdown을 append하고 SQLite FTS5 BM25로 필요한 기록을 검색한다.
- 제안 전환: `history/vault/`를 Obsidian-compatible vault로 만들고, agent가 wiki page, backlinks, source references, lint 상태를 관리한다.

## 장점

- agent가 매번 검색 결과를 재조합하지 않고 누적된 synthesis page를 읽을 수 있다.
- Obsidian의 wiki links, backlinks, graph view, frontmatter를 사람과 agent가 함께 사용할 수 있다.
- `concept`, `decision`, `task`, `experiment`, `runbook`, `source`, `claim` 같은 page type으로 장기 지식을 구조화할 수 있다.
- markdown 기반이라 Git, file sync, Obsidian Sync, 일반 editor와 모두 호환된다.
- 기존 BM25 recall은 raw/provenance/fallback 검색으로 계속 쓸 수 있다.

## 단점과 보완

- 잘못된 synthesis가 canonical처럼 굳을 수 있다.
  - 보완: 모든 claim에 `Sources`, `Evidence`, `Last Verified`, `Confidence` frontmatter를 요구한다.
- link rot, orphan page, duplicate concept가 생길 수 있다.
  - 보완: deterministic `wiki-lint`로 broken link, orphan, oversized page, missing source, duplicate title/tag를 검사한다.
- 다중 agent가 같은 page를 동시에 수정하면 conflict가 늘 수 있다.
  - 보완: shared wiki page 직접 수정 대신 `inbox/` 또는 `proposals/`에 쓰고 maintainer가 promote/merge한다.
- Obsidian Sync나 file sync만 믿으면 review trail이 약해질 수 있다.
  - 보완: 중요한 canonical 변화는 Git commit 또는 append-only `log.md`에 남긴다.
- 검색을 완전히 제거하면 edge-case evidence와 오래된 raw note를 놓칠 수 있다.
  - 보완: SQLite FTS5 BM25 search를 lightweight fallback으로 유지한다.

## Obsidian 저장 모델

Obsidian의 vault는 기본적으로 local filesystem folder다. note는 markdown file이고, `.obsidian/`은 vault 설정과 plugin 설정을 담는다. Obsidian Sync를 쓰면 local vault들이 Obsidian의 remote vault와 file-level로 동기화된다.

따라서 "Obsidian DB에 저장해서 Git 없이 서버 간 이동"이라는 모델은 조심해서 봐야 한다.

- 가능: Obsidian Sync, Dropbox/iCloud/OneDrive, Syncthing, rsync/rclone 같은 file sync로 vault markdown files를 옮기는 것.
- 제한적 가능: Obsidian 앱 또는 plugin이 동작하는 환경에서 remote vault를 local vault로 sync하는 것.
- 비추천: Obsidian 내부 cache/index/database를 source of truth로 보고 headless server 간 이식하는 것. Obsidian의 durable artifact는 여전히 vault folder 안의 markdown files다.

서버 간 이동을 안정적으로 하려면 Git을 완전히 제거하기보다 다음 중 하나가 낫다:

1. 개인/단일 사용자: Obsidian Sync 또는 Syncthing으로 vault files를 sync하고, 중요한 milestone만 Git commit.
2. 연구 repo/다중 agent: Git을 source of truth로 유지하고, Obsidian은 viewer/editor로 사용.
3. headless server workflow: `rsync`/`rclone`/object storage로 vault folder를 동기화하되, `log.md`와 lint report를 append-only로 남김.

## BM25 Backend Decision

`bm25s`는 빠르고 품질이 좋지만 vendored package와 NumPy/SciPy 계열 의존성 부담이 있다. 이 branch에서는 Python 표준 라이브러리 `sqlite3`가 제공하는 SQLite FTS5와 내장 `bm25()` ranking으로 바꿨다.

선택 이유:

- 추가 Python package가 필요 없다.
- SQLite FTS5는 local lexical search에 충분히 빠르고 유지보수 부담이 낮다.
- `rank-bm25`보다 운영 의존성이 낮고, `bm25s`보다 배포 footprint가 작다.
- BM25 search는 Obsidian 전환 이후에도 fallback/provenance search로 남기기 좋다.

주의:

- Python 빌드가 FTS5를 포함한 SQLite와 링크되어 있어야 한다.
- ranking 결과 숫자는 기존 `bm25s`와 scale이 다르다.
- 대규모 corpus에서는 persistent SQLite index/cache가 필요할 수 있다. 현재는 검색 시점 in-memory index를 만든다.
