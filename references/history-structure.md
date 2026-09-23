# Research History Structure

Use this reference when deciding where to store or find project memory.

## Files

- `history/CONTEXT.md`: durable project overview. Keep it short and current. Use it for goals, architecture map, active decisions, open questions, and next steps.
- `history/INDEX.md`: generated text navigation index. Rebuild with `history.py index`.
- `history/PROJECT_MAP.md`: generated Obsidian entry page with portable wikilinks. Rebuild with `history.py obsidian-map` or `history.py index`.
- `history/.gitignore`: ignores per-user `.obsidian/` UI state while keeping all markdown tracked.
- `history/README.md`: human-readable map of the history folder.
- `history/daily/YYYY-MM-DD.md`: chronological log for the day. The script links records here automatically.
- `history/changes/YYYY-MM-DD-HHMMSS-slug.md`: code or artifact change record.
- `history/decisions/0001-slug.md`: durable design, modeling, data, or process decision.
- `history/ideas/0001-slug.md`: hypothesis, paper angle, future feature, ablation, or method idea.
- `history/experiments/0001-slug.md`: experiment, analysis, evaluation, or figure export.
- `history/handoffs/YYYY-MM-DD-HHMMSS-slug.md`: transfer notes for collaborators or agents.
- `history/capsules/YYYY-MM-DD-HHMMSS-slug.md`: handoff agent capsule for continuing work across Codex, Claude, other agents, terminals, or servers.
- `history/sessions/YYYY-MM-DD-HHMMSS-agent-slug.md`: working-session note.
- `history/canonical/overview.md`: maintainer-curated accepted project context for large collaborations.
- `history/tasks/<task-id>/context.md`: accepted context for one benchmark task, including owner, metric, dataset, blocker, risks, and next steps.
- `history/tasks/<task-id>/workstreams/<name>.md`: accepted context for a task workstream such as data, eval, model, or writeup.
- `history/inbox/YYYY-MM-DD-HHMMSS-task-workstream-person-agent-title.md`: submitted summary-only `.md` record. Not canonical until promoted.
- `history-archive/README.md`: archive policy. The archive is tracked in Git for provenance but excluded from default recall, from the Obsidian vault, and from the default BM25 index.
- `history-archive/INDEX.md`: generated table of archived records with record id, kind, date, title, and paired commits.
- `history-archive/YYYY-MM/<kind>/<record>.md`: the full text of an archived record. The month comes from the record date, not the file mtime.
- `history/<kind>/<record>.md` with `Archive State: stub`: the summary left in place when a record is archived. It keeps the record id, metadata, paired commits, a condensed summary, and an `Archived To:` pointer.

## Record Identity And Commit Pairing

Every record written by the script carries:

- `Record Id:` - a stable id derived from the record kind and filename, such as `chg-2026-05-09-101500-add-reward-export` or `dec-0003-restore-repository-local-markdown-memory`. Commands that take `--record` accept the full id, a repo-relative path, or a unique fragment.
- `Commits:` metadata plus a `## Commits` section - the Git commits that implemented the record. Empty records show `-`.

Commits point back with a `History-Record: <record-id>` trailer, so the link survives file moves and renames.

```bash
python3 <skill-dir>/scripts/history.py commit --record <id> --message "..." --path <file>
python3 <skill-dir>/scripts/history.py commit --record <id> --message "..." --all
python3 <skill-dir>/scripts/history.py link-commit --record <id> --commit <sha>
python3 <skill-dir>/scripts/history.py sync-commits
python3 <skill-dir>/scripts/history.py commits --record <id> --stat
python3 <skill-dir>/scripts/history.py commits --commit <sha>
```

`commit` stages the requested paths, writes the trailer, writes the commit id back into the record, and then adds a small bookkeeping commit for that record update; `--no-record-commit` leaves the record edit uncommitted instead. `link-commit` pairs a commit that already exists and defaults to `HEAD`; it only rewrites Git history when `--amend-trailer` is passed, and it refuses to amend when changes are staged. `sync-commits` rebuilds pairing from trailers after rebases, cherry-picks, or hand-written commits.

Squash and rebase merges replace the commit a record was paired with. The reference still resolves in a local clone that holds the old object, but no branch or tag contains it, so it is gone for everyone else. `sync-commits` checks reachability with `git for-each-ref --contains` and reports such pairs; `sync-commits --prune` drops them once the replacement commit, which carries the same trailer, has been paired. `commits --record <id>` marks an unreachable pair inline. Pruning edits the record and its archived counterpart together, so a stub and its full text stay in step.

Record creation commands (`change`, `decision`, `idea`, `experiment`, `handoff`) also accept `--commit <sha>` when the commit already exists.

## Long-Term Archive

Long projects outgrow what an agent should load. Archiving trades full text for a summary stub:

- The full record moves to `history-archive/YYYY-MM/<kind>/<record>.md` with `Archived: yes`, `Archived From:`, and `Archive Stub:` metadata.
- The original path keeps a stub with `Archive State: stub`, `Archived To:`, the record id, the paired commits, and a `## Summary` section condensed from the record's own sections.
- Nothing is deleted, and `archive restore --record <id>` reverses the move exactly.

```bash
python3 <skill-dir>/scripts/history.py archive status
python3 <skill-dir>/scripts/history.py archive plan --older-than-days 180
python3 <skill-dir>/scripts/history.py archive run
python3 <skill-dir>/scripts/history.py archive run --record <id>
python3 <skill-dir>/scripts/history.py archive restore --record <id>
python3 <skill-dir>/scripts/history.py archive migrate
```

Default policy: kinds `changes, experiments, daily, sessions, handoffs, capsules, inbox`; older than 60 days; keep the newest 20 per kind; skip records still marked open, in-progress, or proposed; skip records that `CONTEXT.md`, `canonical/`, or `tasks/` still link to, since curated context pointing at a record is the available signal that it is still in use; skip records whose stub would not be meaningfully smaller than the record. `decisions` and `ideas` are excluded by default because they stay canonical; add them with `--include`. Override any of it with `--include`, `--older-than-days`, `--keep-recent`, `--min-saving`, `--include-open`, and `--include-referenced`.

The saving guard is measured rather than estimated. For each candidate the script builds the stub it would write and requires it to be at least `--min-saving` (default 0.30) and 400 characters smaller than the record. This matters more than it sounds: a stub carries frontmatter, a metadata block, a summary, a commit list, and a pointer, which costs roughly 1.6-1.9k characters. Records around 1.3-1.5k characters therefore grow when archived. `archive plan`, `archive status`, and `archive adopt` report how many records were skipped for this reason, so "no candidates" is a finding, not silence.

Record age comes from the record date (filename stamp, then `Date:` metadata), not the file mtime, so cloning or copying a repository does not change what is considered old.

Archived text stays out of default retrieval. Add `--include-archive` to `search`, `exact`, `start`, `recall`, or `collab recall` when you need it, and read `history-archive/INDEX.md` for the catalogue. Search output labels each hit with `archive_status=active|stub|archived`.

`archive migrate` moves a legacy `history/archive/` tree from earlier versions of this skill into `history-archive/`. The legacy folder stays readable for search and provenance until it is migrated.

### Applying This To An Existing History

Run `archive adopt` once. The steady-state policy keeps the newest 20 records per kind, which is correct for an active project and leaves a first adoption with nothing to do; `adopt` drops that guard, migrates a legacy `history/archive/` folder, archives the whole backlog past the age window in one pass, and prints the resulting reduction. It keeps the guards that serve the same goal (open records, records linked from curated context, records whose stub would not be smaller than the record) and is safe to re-run. On a history whose records are all short it correctly archives nothing and says so.

```bash
python3 <skill-dir>/scripts/history.py archive adopt --dry-run
python3 <skill-dir>/scripts/history.py archive adopt
python3 <skill-dir>/scripts/history.py sync-commits
```

Records written by earlier versions of this skill need no rewrite. `Record Id:` is derived from the record kind and filename when the field is absent, and a `## Commits` section is created on first pairing, so `--record <id>`, `archive run`, and `sync-commits` all work against old records as they are.

Measured on synthetic histories (Apple silicon, warm cache), with the default 60-day policy:

| History size | one-time archive | Recall surface before -> after | `search` before -> after |
| --- | --- | --- | --- |
| 718 records, 121 commits | `archive run` 1.0s / 493 records | 4.55M -> 1.15M chars (-75%) | 0.95s -> 0.62s |
| 707 records, 6 months | `archive adopt` 0.9s / 393 records | 3.41M -> 1.51M chars (-56%) | - |
| 19 records, this skill's own history | `archive adopt` archives nothing | unchanged, by design | - |
| 2455 records, 121 commits | `archive run` 3.5s / 1716 records | 17.97M -> 6.10M chars (-66%) | 2.36s -> 1.42s |

`search --include-archive` reads both the stubs and the full texts, so it costs slightly more than the unarchived history did (3.37s in the larger case). That is the intended trade: the default path gets cheaper, and the complete corpus stays one flag away.

The one-time cost is a large commit, not a long wait: `archive run` rewrites each archived record in place as a stub and adds its full text under `history-archive/`, so a first run on a long project touches two files per archived record. Run `archive plan` first, commit the move on its own, and use `archive restore --record <id>` if a record turns out to be needed again.

`sync-commits` and `finish` read the commit log in a single `git log` pass and build their record index once, so their cost scales with the number of records read, not with commits multiplied by records.

## Record Quality

Good records answer these questions:

- When did this happen?
- What changed?
- Why was it necessary?
- How was it implemented?
- Which files, commands, datasets, configs, and outputs matter?
- What validation was run?
- What remains risky, unresolved, or worth revisiting?

Avoid vague entries such as "fixed bug" or "updated code". Prefer "Changed reward normalization to use gain_normalized because the paper-facing scatter uses raw gain, normalized gain, and final reward as separate axes."

Write free-form record prose in the user's working language by default. Keep fixed metadata keys, command names, paths, code identifiers, and quoted evidence unchanged. For example, if the user is working in Korean, record the summary, rationale, validation interpretation, risks, and next steps in Korean while preserving fields such as `Task:`, `Workstream:`, `Approval Status:`, and file paths.

## Obsidian Compatibility

Obsidian is a viewer/editor for the same Git-tracked `history/` markdown files. It is not the source of truth, and its cache, remote vault internals, or plugin data should not replace Git history or the CLI index/recall path.

New records generated by `history.py` include YAML frontmatter at the top of the file:

```yaml
---
type: change
title: "Add reward export"
date: "2026-05-09 10:30 +0900"
status: completed
tags: [history, change]
---
```

Records also carry `record_id`, and `commits` once paired. Archived records add `archived`, `archived_date`, `archived_from`, and `archive_stub`; stubs add `archive_state: stub` and `archived_to`. Collaboration records also include frontmatter fields such as `task`, `workstream`, `approval_status`, and `promoted_to` when available. The existing plain markdown metadata block remains in the body so agents and simple text tools can keep working without an Obsidian dependency.

Use wiki links only when they point to durable history notes. Prefer unambiguous note names or explicit paths such as `[[decisions/0001-example]]`.

Open `history/` itself as the Obsidian vault, then use `PROJECT_MAP.md` as its start page. Generated links are relative to that folder, so the same graph works in every clone. Keep `.obsidian/` untracked.

Run lint before relying on Obsidian graph/backlinks:

```bash
python3 <skill-dir>/scripts/history.py lint
python3 <skill-dir>/scripts/history.py lint --strict
python3 <skill-dir>/scripts/history.py lint --max-chars 16000
```

`lint` reports broken `[[wiki links]]`, ambiguous note links, oversized pages, and records missing frontmatter. Errors fail by default; warnings fail only with `--strict`.

## Search Strategy

Search uses the vendored `bm25s` engine with NumPy and builds its in-memory corpus directly from repository-local markdown. Start broad, inspect generated variants and reflection, then narrow:

```bash
python3 <skill-dir>/scripts/history.py start --query "normalization" --limit 8
python3 <skill-dir>/scripts/history.py recall --limit 8
python3 <skill-dir>/scripts/history.py recall --query "normalization" --limit 10
python3 <skill-dir>/scripts/history.py search "gain_normalized" --limit 20
python3 <skill-dir>/scripts/history.py exact "gain_normalized" --limit 20
python3 <skill-dir>/scripts/history.py search "gain_normalized" --include-archive
```

Use exact field names, file names, method names, experiment ids, figure names, or paper-section names as queries.

Use `start` as the new-session trigger because it is read-only: it prints project context, latest daily notes, recent records, recent handoffs/capsules, and optional BM25 results without creating a daily file or rebuilding `INDEX.md`. Use `recall` when the existing mutating behavior is acceptable or when compatibility with older workflows matters.

BM25 indexing uses virtual chunks rather than treating every file as one large search document. Files up to 2600 characters stay as one chunk. Longer records are split by markdown `##` sections first, then by paragraph groups, with a 2200-character target and about 250 characters of overlap. Each chunk carries the file metadata prefix so task, workstream, approval, and provenance context stay visible. Search output reports the source file, chunk number, heading, line start, approval, and archive status.

The search command performs three steps:

1. Generate deterministic query variants from the original query, identifier/path splits, and intent words such as why, idea, experiment, code, or handoff.
2. Rank history records with vendored BM25S.
3. Print reflection notes about weak recall, missing query tokens, or over-concentrated result types.

Use `exact` only as a fallback for literal string matching.

## Collaboration Workflow

Use the `collab` subcommands when the history folder is the source of truth for a large multi-person benchmark project:

```bash
python3 <skill-dir>/scripts/history.py collab bootstrap --task-count 15 --default-workstreams
python3 <skill-dir>/scripts/history.py collab submit-summary --task task-01 --workstream data --person "Name" --agent codex --summary "What changed."
python3 <skill-dir>/scripts/history.py collab promote --inbox history/inbox/...md --target task --maintainer "Name"
python3 <skill-dir>/scripts/history.py collab archive --dry-run
python3 <skill-dir>/scripts/history.py collab recall --task task-01 --workstream data --query "dataset blocker"
python3 <skill-dir>/scripts/history.py collab status
```

`collab recall` is intentionally scoped: canonical overview, selected task context, selected workstream context, accepted decisions, and BM25 hits from that accepted scope. Accepted decisions are records marked with either `Status: accepted` or `Approval Status: accepted`. Handoffs and capsules join scoped collaboration recall only when they include task/workstream metadata such as `Task:` and `Workstream:`. It excludes `history/inbox/` and the archive by default. Pass `--include-inbox` only when you intentionally want to inspect unaccepted summaries, and treat `approval=submitted` output as noncanonical. Pass `--include-archive` only when you need provenance search over archived records; output labels each hit with `kind`, `approval`, and `archive_status`.

`collab submit-summary` should contain summary, claims, evidence, changed files, validation, open questions, and proposed decisions. It should not contain raw transcripts, credentials, private notes, or personal data. Sensitive-looking content produces warnings; `--strict` turns those warnings into failures.

`collab promote` is the PR-review gate. The `--inbox` input must be a `.md` file inside `history/inbox/`; it does not accept directories, non-markdown files, or arbitrary files outside the inbox. Maintainers can append curated updates to `canonical/overview.md`, a task context, a workstream context, or create an accepted decision in `decisions/`. `--note` is curated-only promotion, and submitted sections are appended only when `--include-submitted-sections` is passed. Promotion also marks the inbox record as accepted and records the target path.

`collab archive` is the promotion cleanup gate, separate from the long-term `archive` commands: it moves promoted inbox summaries out whole, without leaving a stub, because the accepted content already lives in canonical, task, or workstream context. By default it moves inbox summaries marked `Approval Status: accepted` with a non-empty `Promoted To:` into `history-archive/YYYY-MM/inbox/`. `--older-than-days N` filters by file age, and `--include inbox,daily,sessions` can also archive older daily logs and session notes. `--dry-run` prints the move plan without editing files. The command does not delete records.

Collaboration records should keep this top metadata when applicable:

- `Task:`
- `Workstream:`
- `Approval Status:`
- `Promoted To:`
- `Archived: yes/no`
- `Archived Date:`

`collab status` reports pending inbox submissions, accepted-but-unarchived inbox records, archive candidates, stale canonical/task/workstream context, unscoped handoffs/capsules, accepted decisions, and open risks.

## Vendored Retrieval

The repository vendors the BM25S implementation under `scripts/vendor/bm25s/`; NumPy is the only runtime dependency used by the retrieval path. Search builds an in-memory index from the current markdown files, so there is no SQLite database, persistent search index, or server-side state to administer.

## Collaboration Notes

When multiple agents or collaborators may touch the repo:

- Record ownership boundaries in `handoffs/`.
- Use `handoff-agent-capsule create` before switching agents, tools, local/remote terminals, or servers.
- Include `Task:` and `Workstream:` metadata when a handoff or capsule should appear in task/workstream-scoped `collab recall`.
- Use `handoff-agent-capsule resume` as the first command in the receiving agent before making changes.
- Use `handoff-agent-capsule import` when a capsule was copied from another machine or tool.
- Log shared-file edits as `change` records.
- Put durable choices in `decisions/`, not only in daily logs.
- Do not overwrite another person's unresolved note; append a dated correction or response.

## Finish Checks

Run `finish` before the final response for non-trivial work:

```bash
python3 <skill-dir>/scripts/history.py finish
python3 <skill-dir>/scripts/history.py finish --strict
```

`finish` prints git status, runs history lint without creating records, and warns when non-history files changed but no visible history record changed. It also reports change/experiment records with no paired commit, commits whose `History-Record:` trailer no record lists, uncommitted work past the commit thresholds (12 files or 90 minutes), and how many records are due for archiving. It does not infer or create the record automatically; create the narrowest useful `change`, `decision`, `idea`, `experiment`, `handoff`, or `handoff-agent-capsule` yourself.

## Handoff Agent Capsule Shape

Capsules are optimized for transfer. They should include:

- User requirements that must not be lost.
- Current state of the repo, server, or experiment.
- Concise public decision-rationale summary.
- Files and ownership boundaries.
- Commands already run and validation still needed.
- Open risks and next actions.
- BM25-generated read-first record links.
- Retrieval reflection so the receiving agent can judge whether recall was strong or partial.

Do not store hidden chain-of-thought. Store the actionable rationale: decisions, assumptions, constraints, evidence, and planned checks.
