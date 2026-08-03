# Obsidian LLM-Wiki Transition Notes

Date: 2026-08-03
Status: accepted

## 요약

각 프로젝트 repo의 `history/` Markdown과 Git을 유일한 원본으로 유지한다. Agent recall은 vendored BM25S만 사용하며 SQLite, 중앙 메모리 서버, password/SSH RPC, 별도 search database를 사용하지 않는다.

Obsidian은 같은 `history/` 폴더를 직접 여는 viewer/editor다. `PROJECT_MAP.md`가 프로젝트 안의 활성 노트를 상대 wikilink로 묶어 주므로 clone 위치가 달라도 backlinks와 graph view가 유지된다.

## Adopted Decision

- Keep: repository-local `history/` Markdown and Git are the durable source of truth.
- Keep: vendored BM25S plus NumPy is the only ranked recall backend.
- Add: `history/PROJECT_MAP.md` as the generated Obsidian entry page.
- Add: YAML frontmatter and deterministic lint for broken/ambiguous wikilinks.
- Ignore: per-user `history/.obsidian/` settings.
- Do not use: SQLite/FTS, a central memory service, a remote vault cache, or a separate compiled wiki as canonical storage.

## 사용 방법

```bash
python3 <skill-dir>/scripts/history.py bootstrap
python3 <skill-dir>/scripts/history.py obsidian-map
python3 <skill-dir>/scripts/history.py search "task-specific query" --limit 10
python3 <skill-dir>/scripts/history.py lint --strict
```

Obsidian에서 해당 프로젝트의 `history/` 폴더를 vault로 열고 `PROJECT_MAP.md`부터 탐색한다. 모든 생성 링크는 `history/` 기준 상대 경로이므로 다른 서버나 clone에서도 그대로 동작한다.

## BM25S Backend

`scripts/vendor/bm25s/`에 고정된 구현을 포함하고 NumPy로 in-memory BM25 인덱스를 만든다. 검색할 때 현재 Markdown을 다시 읽으므로 별도 daemon, persistent index file, SQLite schema, migration, locking이 없다. `INDEX.md`와 `PROJECT_MAP.md`는 다른 기록의 내용을 재나열하므로 BM25S corpus에서 제외한다.

## 운영 원칙

- durable 수정은 Markdown과 Git commit으로 남긴다.
- Obsidian Sync나 file sync는 선택적 편의 계층일 뿐 canonical review trail이 아니다.
- agent는 `start --query`로 읽고, 의미 있는 변경은 record 명령으로 남기며, 마지막에 `finish`와 `lint`를 실행한다.
- raw transcript, credential, token, password, private key는 기록하지 않는다.
