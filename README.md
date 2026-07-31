# Research Memory

Keep personal research notes in a data-only Markdown repository that belongs to
you and is verified as private before the first record is written.

## Start in three commands

Install the current public source:

```bash
uv tool install git+https://github.com/KimJaehee0725/track-research-history.git
research-memory repo create --private
research-memory record --stdin
```

`repo create` uses the active [GitHub CLI](https://cli.github.com/) account,
creates `research-history/` locally, creates a private GitHub repository, then
queries GitHub again and requires the visibility to be exactly `PRIVATE`
before pushing the initial commit.
`record --stdin` reads until EOF (Ctrl-D), then repeats that privacy check
before changing any Markdown.

When a package-index release is available, the install command becomes:

```bash
uv tool install research-memory
```

See [Getting started](docs/getting-started.md) for prerequisites, custom
owners/paths, machine-readable output, and recovery behavior.

## Everyday commands

```bash
# Verify origin, GitHub visibility, schema, tracked files, and config mode.
research-memory doctor

# Record from stdin, commit, and push to the verified private origin.
research-memory record --stdin --title "Recovery ablation"

# Search local Markdown without changing it or requiring the network.
research-memory search "recovery"
```

Research data is deliberately separated from this public application
repository. The generated repository contains only Markdown, a schema marker,
and non-secret metadata. It excludes application source, credentials, local
SQLite indexes, caches, keys, and runtime state. See
[Data format](docs/data-format.md).

## Safety boundaries

- Existing files, directories, Git repositories, and origins are never
  overwritten by `repo create`.
- An existing client configuration is never replaced; choose a new
  `--config` path outside the data repository explicitly.
- `PUBLIC` and `INTERNAL` repositories both fail the privacy gate.
- Every effective fetch and push URL must identify the same private GitHub
  repository. Creation and recording push to the already verified URL, not an
  unchecked `pushurl`.
- Git `url.*.insteadOf` and `url.*.pushInsteadOf` rewrites are rejected because
  chained rewrites can change the destination after inspection.
- Git and GitHub commands use explicit argument arrays; no shell is invoked.
- Git credential, SSH, askpass, and signing prompts are disabled for automated
  operations. SSH remotes require a pre-verified GitHub host key.
- GitHub authentication output and tokens are never written to JSON output or
  configuration.
- The saved client configuration is non-secret and written atomically with
  owner-only permissions.
- A failed create operation preserves the local directory and an ignored
  operation journal for diagnosis; it never auto-deletes a remote.
- Positional `record TEXT` remains available for short non-sensitive notes.
  Prefer `--stdin` or `--file` because command arguments can appear in shell
  history and process listings.

The full creation contract is documented in
[Private GitHub repositories](docs/github-repository.md).

## Advanced: central SSH memory server

The optional self-hosted server is a different workflow from `repo create`.

- `research-memory repo create` creates a user-owned private GitHub **data
  repository**.
- `client/memctl.py project init PROJECT` creates a project in a central SSH
  memory **server**.

The server provides project-isolated Markdown vaults, FTS5 search, revisions,
audit logs, recoverable trash, and a loopback-only administration UI. It is an
advanced multi-host/container feature and is not required for the three-command
local + GitHub flow.

Read these guides before deploying it:

- [Server setup](docs/server-setup.md)
- [Password mode](docs/password-mode.md)
- [Container bootstrap](docs/container-bootstrap.md)
- [Administration UI](docs/admin-ui.md)
- [Security and backup](docs/security-and-backup.md)
- [Obsidian access](docs/obsidian.md)

The original `scripts/history.py` repository-development workflow and the
standalone `client/memctl.py` / `client/memory-run` server clients remain
available for compatibility. They are intentionally not silent aliases for the
new private-data-repository commands.
