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
- `client/`: `memctl` SSH client and `memory-run` container wrapper.
- `deploy/`: Docker and systemd deployment examples.
- `docs/`: server setup, container bootstrap, and Obsidian access guides.

The original `scripts/history.py` workflow remains available for local project
history and the private Git hub mirror.

## Before using it with research data

Read `docs/server-setup.md` and create a separate private backup repository.
This source-code repository may be public, but server data, SSH keys, backup
credentials, and real research notes must never be committed here.
