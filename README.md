# Track Research History

A small, repository-local research memory for coding agents and humans. Every project keeps its own durable Markdown under `history/`; Git remains the source of truth.

## Quick start

```bash
python3 /path/to/track-research-history/scripts/history.py bootstrap
python3 /path/to/track-research-history/scripts/history.py start --query "current task"
python3 /path/to/track-research-history/scripts/history.py search "decision or experiment" --limit 10
python3 /path/to/track-research-history/scripts/history.py change --title "Describe the change" --why "Why" --how "How"
python3 /path/to/track-research-history/scripts/history.py commit --record "describe-the-change" --message "Describe the change" --path path/to/changed-file
python3 /path/to/track-research-history/scripts/history.py finish
```

## Commit pairing

Each record carries a stable `Record Id:` and a `## Commits` section, and each paired commit carries a `History-Record: <id>` trailer. A summary always has a diff behind it, in both directions.

```bash
python3 /path/to/track-research-history/scripts/history.py link-commit --record <id>   # pair an existing commit
python3 /path/to/track-research-history/scripts/history.py sync-commits                # rebuild pairing from trailers
python3 /path/to/track-research-history/scripts/history.py commits --record <id> --stat
```

## Long-term archive

On projects that run for months, old records move out of the way instead of crowding recall. The full text goes to `history-archive/YYYY-MM/<kind>/`, and `history/` keeps a summary stub with the record id, paired commits, and a pointer back.

```bash
python3 /path/to/track-research-history/scripts/history.py archive adopt --dry-run  # first run on an existing history
python3 /path/to/track-research-history/scripts/history.py archive status
python3 /path/to/track-research-history/scripts/history.py archive plan
python3 /path/to/track-research-history/scripts/history.py archive run
python3 /path/to/track-research-history/scripts/history.py archive restore --record <id>
python3 /path/to/track-research-history/scripts/history.py search "<query>" --include-archive
```

Nothing is deleted: archiving is a move plus a stub, and `archive restore` reverses it.

Ranked recall uses the vendored BM25S implementation and NumPy. It reads the current Markdown into memory; no SQLite database, server, password mode, SSH RPC, or central vault is required.

## Obsidian

Open a project's `history/` directory as an Obsidian vault and start at `PROJECT_MAP.md`. Bootstrap, record, and index commands regenerate that map with portable relative wikilinks. Per-user `.obsidian/` settings are ignored while the Markdown notes stay tracked in Git.

```bash
python3 /path/to/track-research-history/scripts/history.py obsidian-map
python3 /path/to/track-research-history/scripts/history.py lint --strict
```

See [SKILL.md](SKILL.md) for the complete agent workflow and [references/history-structure.md](references/history-structure.md) for the file layout.

## Requirements

- Python 3.10+ on POSIX (Linux/macOS), with `fcntl` for writer locks
- NumPy

## Versioned local installation

Clone this repository and run its tests before installing. Install the same payload into explicit discovery paths to keep Codex and Claude on one version:

```bash
python3 -m unittest discover -s tests -p '*.py' -q
python3 scripts/install.py --target "$HOME/.codex/skills/track-research-history" --target "$HOME/.claude/skills/track-research-history" --dry-run
python3 scripts/install.py --target "$HOME/.codex/skills/track-research-history" --target "$HOME/.claude/skills/track-research-history"
python3 scripts/history.py --version
python3 scripts/history.py --capabilities
```

The installer copies a consistent skill payload, records hashes and the source revision in `INSTALLATION.json`, and preserves each prior directory or symlink as a sibling backup. It does not change a symlink's old target or overwrite a Git checkout. Copy-based installs require reinstalling after a source update. A failed multi-target installation rolls back completed replacements. If an existing real skill directory is a mount point and cannot be renamed (EXDEV/EBUSY), installation uses managed-file backups and per-file atomic replacement with the installation manifest published last. This mode preserves the mount root and unrelated files; it is not a whole-directory atomic switch. Other permission or read-only errors are not bypassed.

## File history and retrieval

```bash
python3 scripts/history.py commits --file src/module.py --ref HEAD --limit 5
python3 scripts/history.py search "src/module.py" --json --no-variants
python3 scripts/history.py finish --base <starting-commit>
```

See [retrieval-and-provenance.md](references/retrieval-and-provenance.md) for relation types, scope, diagnostics, and limits. Recall is now read-only; `recall --update` explicitly requests the legacy daily/index writes.
