# Obsidian LLM-Wiki Transition Notes

Date: 2026-05-09
Status: draft
Branch: obsidian-llm-wiki-experiment

## 요약

현재 `track-research-history`는 repository-local `history/` 폴더와 BM25 recall을 중심으로 동작한다. Obsidian은 이 구조를 대체하는 저장소가 아니라, Git-tracked markdown history를 사람이 읽고 탐색하기 좋은 viewer/editor로만 둔다.

권장 방향은 기존 Git-tracked history와 SQLite FTS5 BM25 검색을 유지하고, Obsidian-compatible conventions를 추가해 사람이 graph view, backlinks, frontmatter를 편하게 볼 수 있게 하는 것이다.

## Karpathy LLM-Wiki와의 관계

Karpathy의 핵심은 raw document chunk를 매번 query-time에 재조립하지 않고, LLM이 persistent markdown wiki를 누적 관리하게 하는 것이다.

비교:

- Karpathy 원형: raw sources는 immutable이고, LLM이 compiled wiki를 쓰며, schema 문서가 agent의 유지보수 규칙이 된다.
- 현재 skill: record markdown을 append하고 SQLite FTS5 BM25로 필요한 기록을 검색한다.
- 채택 방향: 이 Git-tracked markdown history를 source of truth로 유지하고, Obsidian은 같은 파일을 여는 viewer/editor로 사용한다.
- 보류 방향: `history/vault/` 아래에 별도 LLM-owned compiled wiki를 만들고 agent가 별도 wiki page를 canonical하게 관리하는 방식은 아직 채택하지 않는다.

## 장점

- source of truth가 하나다. agent는 Git-tracked `history/`를 읽고 쓰며, 사람은 Obsidian으로 같은 파일을 본다.
- Obsidian의 wiki links, backlinks, graph view, frontmatter를 사람이 탐색용으로 사용할 수 있다.
- 별도 Obsidian DB나 remote vault에 의존하지 않아 headless server, SSH, CI, Codex/Claude CLI 환경에서 일관성이 높다.
- markdown 기반이라 Git, file sync, Obsidian Sync, 일반 editor와 모두 호환된다.
- SQLite FTS5 BM25 recall은 agent 기본 검색 경로로 계속 남는다.

## 단점과 보완

- Obsidian-only affordances에 기대면 agent가 없는 서버에서 의미가 약해질 수 있다.
  - 보완: Obsidian-specific 기능은 optional convention으로만 두고, plain markdown과 CLI로 모든 기능이 동작해야 한다.
- 사람이 Obsidian에서 직접 수정한 내용이 Git에 commit되지 않으면 agent가 다른 서버에서 못 볼 수 있다.
  - 보완: durable change는 Git commit 또는 sync된 working tree에 남긴다. Obsidian Sync는 편의 sync이지 canonical review trail이 아니다.
- link rot, orphan page, duplicate concept가 생길 수 있다.
  - 보완: 향후 deterministic `history lint`로 broken link, orphan, oversized page, missing source, duplicate title/tag를 검사한다.
- 검색을 완전히 제거하면 edge-case evidence와 오래된 raw note를 놓칠 수 있다.
  - 보완: SQLite FTS5 BM25 search를 primary agent recall path로 유지한다.

## Obsidian 저장 모델

Obsidian의 vault는 기본적으로 local filesystem folder다. note는 markdown file이고, `.obsidian/`은 vault 설정과 plugin 설정을 담는다. Obsidian Sync를 쓰면 local vault들이 Obsidian의 remote vault와 file-level로 동기화된다.

따라서 "Obsidian DB에 저장해서 Git 없이 서버 간 이동"이라는 모델은 조심해서 봐야 한다.

- 가능: Obsidian Sync, Dropbox/iCloud/OneDrive, Syncthing, rsync/rclone 같은 file sync로 vault markdown files를 옮기는 것.
- 제한적 가능: Obsidian 앱 또는 plugin이 동작하는 환경에서 remote vault를 local vault로 sync하는 것.
- 비추천: Obsidian 내부 cache/index/database를 source of truth로 보고 headless server 간 이식하는 것. Obsidian의 durable artifact는 여전히 vault folder 안의 markdown files다.

서버 간 이동을 안정적으로 하려면 Git을 제거하지 않는다:

1. 연구 repo/다중 agent: Git을 source of truth로 유지하고, Obsidian은 viewer/editor로 사용한다.
2. 개인 보조 sync: Obsidian Sync 또는 Syncthing은 local convenience layer로만 사용한다.
3. headless server workflow: Git clone/pull/push가 기본이고, 필요할 때만 `rsync`/`rclone`으로 working tree를 복제한다.

## Adopted Decision

- Keep: Git-tracked repository-local `history/` remains the durable source of truth.
- Keep: SQLite FTS5 BM25 remains the agent recall backend.
- Add now: Obsidian-friendly frontmatter and deterministic `history.py lint` for broken wiki links, ambiguous links, oversized pages, and missing frontmatter.
- Add later: richer graph-friendly page conventions or curated synthesis pages if the existing record layer becomes too flat.
- Do not adopt now: Obsidian remote vault or internal cache as the canonical storage layer.
- Do not adopt now: separate LLM-owned compiled wiki that diverges from the existing `history/` records.

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
