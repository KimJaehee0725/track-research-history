# Research History Structure

Use this reference when deciding where to store or find project memory.

## Files

- `history/CONTEXT.md`: durable project overview. Keep it short and current. Use it for goals, architecture map, active decisions, open questions, and next steps.
- `history/INDEX.md`: generated navigation index. Rebuild with `history.py index`.
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
- `history/archive/README.md`: archive policy. Archive is tracked for provenance but excluded from default collaboration recall.
- `history/archive/inbox/YYYY-MM/`: accepted inbox summaries after they have been promoted and archived.
- `history/archive/daily/YYYY-MM/`: older daily logs moved out of the active daily folder.
- `history/archive/sessions/YYYY-MM/`: older session notes moved out of the active sessions folder.

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

## Search Strategy

Search uses the vendored `bm25s` implementation by default. Start broad, inspect generated variants and reflection, then narrow:

```bash
python3 <skill-dir>/scripts/history.py recall --limit 8
python3 <skill-dir>/scripts/history.py recall --query "normalization" --limit 10
python3 <skill-dir>/scripts/history.py search "gain_normalized" --limit 20
python3 <skill-dir>/scripts/history.py exact "gain_normalized" --limit 20
```

Use exact field names, file names, method names, experiment ids, figure names, or paper-section names as queries.

BM25 indexing uses virtual chunks rather than treating every file as one large search document. Files up to 2600 characters stay as one chunk. Longer records are split by markdown `##` sections first, then by paragraph groups, with a 2200-character target and about 250 characters of overlap. Each chunk carries the file metadata prefix so task, workstream, approval, and provenance context stay visible. Search output reports the source file, chunk number, heading, line start, approval, and archive status.

The search command performs three steps:

1. Generate deterministic query variants from the original query, identifier/path splits, and intent words such as why, idea, experiment, code, or handoff.
2. Rank history records with BM25S.
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

`collab recall` is intentionally scoped: canonical overview, selected task context, selected workstream context, accepted decisions, and BM25 hits from that accepted scope. Accepted decisions are records marked with either `Status: accepted` or `Approval Status: accepted`. Handoffs and capsules join scoped collaboration recall only when they include task/workstream metadata such as `Task:` and `Workstream:`. It excludes `history/inbox/` and `history/archive/` by default. Pass `--include-inbox` only when you intentionally want to inspect unaccepted summaries, and treat `approval=submitted` output as noncanonical. Pass `--include-archive` only when you need provenance search over archived records; output labels each hit with `kind`, `approval`, and `archive_status`.

`collab submit-summary` should contain summary, claims, evidence, changed files, validation, open questions, and proposed decisions. It should not contain raw transcripts, credentials, private notes, or personal data. Sensitive-looking content produces warnings; `--strict` turns those warnings into failures.

`collab promote` is the PR-review gate. The `--inbox` input must be a `.md` file inside `history/inbox/`; it does not accept directories, non-markdown files, or arbitrary files outside the inbox. Maintainers can append curated updates to `canonical/overview.md`, a task context, a workstream context, or create an accepted decision in `decisions/`. `--note` is curated-only promotion, and submitted sections are appended only when `--include-submitted-sections` is passed. Promotion also marks the inbox record as accepted and records the target path.

`collab archive` is the cleanup gate. By default it moves inbox summaries marked `Approval Status: accepted` with a non-empty `Promoted To:` into `history/archive/inbox/YYYY-MM/`. `--older-than-days N` filters by file age, and `--include inbox,daily,sessions` can also archive older daily logs and session notes. `--dry-run` prints the move plan without editing files. The command does not delete records.

Collaboration records should keep this top metadata when applicable:

- `Task:`
- `Workstream:`
- `Approval Status:`
- `Promoted To:`
- `Archived: yes/no`
- `Archived Date:`

`collab status` reports pending inbox submissions, accepted-but-unarchived inbox records, archive candidates, stale canonical/task/workstream context, unscoped handoffs/capsules, accepted decisions, and open risks.

## Vendored Retrieval

The bundled BM25 engine is `bm25s` from `https://github.com/xhluca/bm25s`, vendored under `scripts/vendor/bm25s` with its MIT license. It was chosen over `rank-bm25` because it is still lightweight while providing faster sparse scoring and a more complete retrieval API.

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
