# Project History

This folder stores durable project memory for research coding, experiments, ideas, decisions, and collaboration.

## Read First

1. `CONTEXT.md`
2. `PROJECT_MAP.md` in Obsidian, or `INDEX.md` in a text editor
3. Latest file in `daily/`
4. Relevant records from `changes/`, `decisions/`, `ideas/`, `experiments/`, `handoffs/`, `capsules/`, and `sessions/`
5. For anything older, the summary stubs here and their full text in `../history-archive/`

## Trusted Context

For collaboration projects, default agent context comes from `canonical/`, `tasks/`, `decisions/`, and scoped handoffs/capsules with explicit `Task:` and `Workstream:` metadata.

## Pending

`inbox/` contains submitted summaries awaiting maintainer review. It is excluded from collaboration recall unless `--include-inbox` is passed.

## Archive

Old, rarely used records keep a summary stub here and move their full text to `../history-archive/YYYY-MM/<kind>/`. A stub carries `Archive State: stub`, the record id, the paired commits, a condensed summary, and an `Archived To:` pointer.

The archive is tracked in Git for provenance but excluded from default recall, from this Obsidian vault, and from the default search index. Pass `--include-archive` to search it, or read `../history-archive/INDEX.md`. Nothing is deleted: `history.py archive restore --record <id>` reverses the move.

## Commits

Each record carries a `Record Id:` and a `## Commits` section, and each paired commit carries a `History-Record: <id>` trailer. Use `history.py commits --record <id>` to see the diffs behind a record, and `history.py sync-commits` to rebuild pairing from commit trailers.

## Obsidian

Open this `history/` folder directly as an Obsidian vault and start from `PROJECT_MAP.md`. Generated wikilinks are portable across clones. Keep `.obsidian/` untracked.

## Language

Write summaries, rationale, validation notes, risks, and handoff context in the user's working language by default. Keep metadata keys, commands, paths, code identifiers, and quoted evidence unchanged.

## Maintenance

- Keep entries concrete: paths, commands, parameters, rationale, validation, and risks.
- Append corrections instead of rewriting past history.
- Do not store secrets or credentials.
