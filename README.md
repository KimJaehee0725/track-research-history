# Track Research History

A small, repository-local research memory for coding agents and humans. Every project keeps its own durable Markdown under `history/`; Git remains the source of truth.

## Quick start

```bash
python3 /path/to/track-research-history/scripts/history.py bootstrap
python3 /path/to/track-research-history/scripts/history.py start --query "current task"
python3 /path/to/track-research-history/scripts/history.py search "decision or experiment" --limit 10
python3 /path/to/track-research-history/scripts/history.py change --title "Describe the change" --why "Why" --how "How"
python3 /path/to/track-research-history/scripts/history.py commit --record "describe-the-change" --message "Describe the change" --all
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

- Python 3.10+
- NumPy
