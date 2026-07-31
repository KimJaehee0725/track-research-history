# Getting started

## Prerequisites

Install:

- Python 3.9 or newer
- Git
- [uv](https://docs.astral.sh/uv/)
- [GitHub CLI](https://cli.github.com/)

The current CLI and optional server are supported on macOS and Linux.

Authenticate GitHub CLI once:

```bash
gh auth login
gh auth status --hostname github.com
```

Do not copy a personal access token into a Research Memory file. `gh` owns its
credential storage.

Configure a global Git identity before creation:

```bash
git config --global user.name "YOUR NAME"
git config --global user.email "YOUR EMAIL"
```

For SSH GitHub remotes, verify GitHub's published host fingerprint and add it
to `known_hosts` before using the CLI. Automated Git calls use
`StrictHostKeyChecking=yes` and `BatchMode=yes`; they fail instead of prompting.

## Install the CLI

Until a package-index release is published, install from the public source
repository:

```bash
uv tool install git+https://github.com/KimJaehee0725/track-research-history.git
research-memory --help
```

## Create your private data repository

From the directory that should contain the local checkout:

```bash
research-memory repo create --private
```

Defaults:

- repository name: `research-history`
- owner: the active `gh` account
- local path: `./research-history`
- visibility: private only

Customize those values explicitly:

```bash
research-memory repo create \
  --name lab-research-history \
  --owner YOUR_GITHUB_OWNER \
  --path /absolute/path/to/lab-research-history \
  --private \
  --non-interactive
```

The command checks the target, config destination, Git author identity, and
`gh` authentication before creating files. It then creates the data-only
layout, initializes Git, commits it, runs `gh repo create ... --private`,
verifies the GitHub visibility, verifies every effective `origin` fetch and
push URL, pushes to that verified URL, and creates a non-secret owner-only
config.

The config must live outside the data repository. Git
`url.*.insteadOf`/`pushInsteadOf` rewrites are unsupported for this workflow;
the CLI conservatively rejects any such rewrite, even one intended for another
host. Inspect the contributing config scope before changing it:

```bash
git config --show-origin --name-only --get-regexp '^url\.'
```

Remove the reported rewrite through the same local, global, or system scope
where it was defined, then configure the intended credential-free GitHub URL
directly.

If a later step fails, the local directory is preserved. Inspect
`.research-memory/operation.json` and run `research-memory doctor --path PATH`;
do not delete or retry over the directory blindly. The journal's `stage` and
the doctor output identify whether failure happened before the initial commit
or during GitHub creation. The CLI deliberately refuses to resume or overwrite
that path automatically; inspect `git status`, `git remote -v`, and
`gh repo view OWNER/NAME --json visibility` before choosing a manual recovery.

## Record and search

```bash
research-memory record --stdin
research-memory record --file result.md --title "Experiment 01"
research-memory search "Experiment"
```

`--stdin` reads UTF-8 text until EOF (Ctrl-D in an interactive terminal).
`--file` reads a UTF-8 file. Positional `record "TEXT"` is convenient for
non-sensitive notes, but its body can be retained in shell history or visible
in a process listing. Exactly one input form is required, with a 5 MiB limit.

`record` fails before writing when:

- the configured path is not the exact Git root;
- any effective `origin` fetch/push URL is unsupported or differs from the
  saved owner/repository;
- Git URL rewrite configuration could change the inspected destination;
- GitHub visibility cannot be checked;
- visibility is not exactly `PRIVATE`; or
- the working tree already has uncommitted changes.

By default a successful record is committed and pushed. Use `--no-push` only
when intentionally keeping the new commit local:

```bash
research-memory record --stdin --title "Offline note" --no-push
```

## Diagnose safely

```bash
research-memory doctor
research-memory --json doctor
```

`doctor` checks the saved config and permissions, data path, schema, unfinished
operation journal, exact Git root, every effective origin fetch/push URL,
GitHub authentication, live visibility, blocked tracked secret/index/runtime
paths, and working-tree state. Credential-shaped text is scanned from the Git
index, even when the working-tree copy has been edited.

For automation, `--json` emits one JSON document and returns a nonzero status
when an argument, command, or diagnostic check fails.
