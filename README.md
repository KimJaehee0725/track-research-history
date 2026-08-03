# Track Research History

A small, repository-local research memory for coding agents and humans. Every project keeps its own durable Markdown under `history/`; Git remains the source of truth.

## Quick start

```bash
python3 /path/to/track-research-history/scripts/history.py bootstrap
python3 /path/to/track-research-history/scripts/history.py start --query "current task"
python3 /path/to/track-research-history/scripts/history.py search "decision or experiment" --limit 10
python3 /path/to/track-research-history/scripts/history.py change --title "Describe the change" --why "Why" --how "How"
python3 /path/to/track-research-history/scripts/history.py finish
```

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
