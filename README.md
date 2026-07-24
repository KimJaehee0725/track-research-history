# Research History and Memory Server

`track-research-history` keeps research context in plain Markdown while adding a
small, self-hosted memory service for multi-host and container workflows.

## What is canonical?

The personal Linux desktop server is the canonical home for project memory.
Each project has an isolated Markdown vault, a server-side search index, audit
log, revision history, and recoverable trash. The GitHub hub workflow remains
useful as a private backup and cross-project mirror, but it is not the live
write path for agents.

```text
containers and laptops --SSH RPC--> personal Linux server --backup--> private Git/NAS
                                      |
                                      +--> project Markdown vaults
                                      +--> FTS5 search / audit / trash
                                      +--> localhost-only admin UI
```

## Safety properties

- Project and note identifiers are validated before paths are constructed.
- Every write has a revision; callers may require an expected revision to avoid
  silently overwriting another agent's change.
- Deletion moves data to server-side trash first. Project deletion requires an
  explicit confirmation in the UI.
- Agent containers receive a project-scoped SSH key mounted read-only; no key
  belongs in an image, Git repository, or note.
- The admin UI listens on `127.0.0.1` only. Reach it remotely through an SSH
  tunnel rather than exposing a web port.

## Components

- `src/research_memory/`: storage, project authorization, search, audit, and
  JSON-RPC core.
- `server/`: localhost-only FastAPI administration UI and SSH forced-command
  RPC entry point.
- `client/`: 프로필을 지원하는 `memctl` SSH client와 `memory-run` 컨테이너 래퍼.
- `deploy/`: Docker and systemd deployment examples.
- `docs/`: server setup, container bootstrap, and Obsidian access guides.

The original `scripts/history.py` workflow remains available for local project
history and the private Git hub mirror.

## Before using it with research data

Read [서버 설치 안내](docs/server-setup.md) and create a separate private backup repository.
This source-code repository may be public, but server data, SSH keys, backup
credentials, and real research notes must never be committed here.

## 일상 사용을 단순하게 시작하기

처음 한 번만 장비별·프로젝트별 SSH 키를 만들고 `memctl profile add`로 로컬 프로필에 등록하면, 이후에는 `note list`, `note read PATH`, `note search QUERY`처럼 짧게 쓸 수 있습니다. 서버의 공개키 등록·조회·폐기도 별도 관리 명령으로 처리할 수 있습니다.

현재 Compose UI가 이미 정상 동작하는 서버는 그대로 유지하고, 나중에 점검 시간에만 systemd 단일 런타임 전환을 검토하세요. Compose와 systemd UI를 동시에 실행하면 안 됩니다. 전체 흐름은 [간단한 일상 운영 흐름](docs/simplified-operations.md)을 참고하세요.
