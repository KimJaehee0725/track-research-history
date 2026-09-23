---
name: track-research-history
description: Maintain durable research-project history while coding, with repository-local vendored BM25S recall, generated query variants, retrieval reflection, record-to-commit pairing, long-term summary archiving, handoff agent capsules, and maintainer-curated collaboration history for large benchmark projects. Use when Codex or Claude needs to automatically record and recall why code changed, how it was implemented, which commit implemented it, which files changed, which ideas or hypotheses led to it, experiment decisions, collaboration handoffs, agent transition context, task/workstream context, or canonical project context in a repository-level history/ folder, including multi-month projects whose history must stay small enough to recall.
---

# Track Research History

## Core Rule

Treat history as part of the work product. For any non-trivial research, code, experiment, architecture, or collaboration task:

1. Recall relevant history before editing.
2. Record meaningful decisions, ideas, experiments, and code changes while working.
3. Leave the next agent or collaborator with searchable context before the final response.

Do not record secrets, credentials, private tokens, or raw personal data. Redact sensitive values and note that they were redacted.

## Trigger Points

Use these trigger points to decide when this skill should act:

| Trigger | Action |
| --- | --- |
| New agent/session opens | Run `start` with task-specific query terms. This is read-only and must not create daily logs, records, or index updates. |
| Substantial work begins | Recall relevant history before editing. If `history/` is missing, run `bootstrap`; otherwise prefer `start --query "<task terms>"`. |
| Broad task begins | Create a `session` record only when the work is broad enough that a later collaborator would need a session-level summary. |
| Meaningful change or finding appears | Record the narrowest useful type: `change`, `decision`, `idea`, or `experiment`. Skip trivial chat, one-line answers, and read-only checks. |
| Recorded work is ready to commit | Commit through `commit --record <id>` so the record and the commit point at each other. Use `link-commit` when the commit already exists. |
| An existing history adopts this skill for the first time | Run `archive adopt --dry-run`, then `archive adopt`, then `sync-commits`. It bulk-archives the whole backlog past the age window in one pass so old records stop costing full text on every recall. |
| History has grown over months | Run `archive plan`, then `archive run`. Old records keep a summary stub in `history/`; their full text moves to `history-archive/`. |
| Agent, tool, thread, host, or server handoff is needed | Create a `handoff-agent-capsule`; use a plain `handoff` for lighter collaborator transfer notes. |
| Large collaboration context is used | Start from `collab recall`; participants use `collab submit-summary`, and maintainers use `collab promote`, `collab archive`, and `collab status`. |
| Before final response for non-trivial work | Run `finish`, resolve lint errors, and create any missing history record manually. `finish` does not auto-create records. |

## Language

Write record prose in the user's working language by default. If the user is working in Korean, write summaries, rationale, validation notes, risks, and handoff context in Korean unless they ask for another language or the target artifact requires English.

Keep fixed metadata keys, CLI flags, file paths, code identifiers, command output, and quoted source text unchanged. Mixed-language records are acceptable when the project artifacts or evidence are mixed-language.

## Storage Model

Use a repository-local `history/` folder. If the project already has a history system, adapt to it rather than replacing it. Otherwise create this structure:

```text
history/
  CONTEXT.md
  INDEX.md
  PROJECT_MAP.md
  README.md
  daily/
  changes/
  decisions/
  ideas/
  experiments/
  handoffs/
  capsules/
  sessions/
  templates/
history-archive/
  INDEX.md
  YYYY-MM/<kind>/<record>.md
```

`history/` is the working memory an agent loads. `history-archive/` holds the full text of records that are old and rarely read; it stays in Git for provenance but out of default recall, out of the Obsidian vault, and out of the default BM25 index.

For large benchmark collaborations, use the `collab` layer in the same repository-local `history/` folder:

```text
history/
  canonical/overview.md
  tasks/<task-id>/context.md
  tasks/<task-id>/workstreams/<name>.md
  inbox/
  decisions/
  handoffs/
  capsules/
```

Use the bundled script for deterministic structure, filenames, indexing, and vendored BM25S recall:

```bash
python3 <skill-dir>/scripts/history.py bootstrap
python3 <skill-dir>/scripts/history.py start --query "reward shaping" --limit 8
python3 <skill-dir>/scripts/history.py recall --limit 8
python3 <skill-dir>/scripts/history.py recall --query "reward shaping" --limit 8
python3 <skill-dir>/scripts/history.py search "gain_normalized ablation idea" --limit 10
python3 <skill-dir>/scripts/history.py commit --record <record-id> --message "..." --path <changed-file>
python3 <skill-dir>/scripts/history.py archive plan
python3 <skill-dir>/scripts/history.py finish
```

Resolve `<skill-dir>` to the directory containing this `SKILL.md`.

## Obsidian Viewer Mode

Treat Obsidian as a human viewer/editor over the same Git-tracked markdown files, not as a replacement storage system. The durable source of truth remains repository-local `history/`, Git review, and the CLI recall/index commands.

New records created by the script include lightweight YAML frontmatter for Obsidian navigation (`type`, `title`, `date`, `status`, `tags`, and collaboration fields when available) while preserving the plain markdown metadata body used by agents. Do not rely on Obsidian's cache, remote vault internals, or plugin database as canonical project history.

Open the project's `history/` directory directly as an Obsidian vault and start from `PROJECT_MAP.md`. The map is regenerated by record/index commands and contains only portable repo-relative wikilinks. `.obsidian/` is ignored locally so vault UI settings do not become shared project memory.

```bash
python3 <skill-dir>/scripts/history.py obsidian-map
python3 <skill-dir>/scripts/history.py lint
python3 <skill-dir>/scripts/history.py lint --strict
```

`lint` reports broken `[[wiki links]]`, ambiguous note links, oversized pages, and records missing frontmatter. Warnings are advisory by default; `--strict` makes warnings fail.

## Start Of Work

Before making substantial changes:

1. Run `bootstrap` if `history/` is missing.
2. Run `start`; add `--query` terms from the user request, changed subsystem, paper section, method name, dataset, or experiment.
3. Inspect the generated query variants, BM25 ranked results, and reflection notes.
4. Read `history/CONTEXT.md`, the latest daily log, and any recall hits that affect the task.
5. If the task has broad scope, create a session note:

```bash
python3 <skill-dir>/scripts/history.py session \
  --task "Implement belief-shift reward export" \
  --scope "exp/gain analysis and paper-facing plots" \
  --agent "codex"
```

## Record Types

Use the narrowest useful record type:

- `change`: code, config, data pipeline, manuscript source, or directory structure changed.
- `decision`: a design, modeling, data, evaluation, or collaboration choice was made.
- `idea`: a hypothesis, possible method, paper angle, ablation, or future implementation direction appeared.
- `experiment`: a run, analysis, metric comparison, figure export, or evaluation was performed.
- `handoff`: another human or agent needs continuity, ownership boundaries, or next actions.
- `handoff-agent-capsule`: a portable context bundle for moving work across agents, tools, or servers.
- `daily`: lightweight chronological summary for the day.

Examples:

```bash
python3 <skill-dir>/scripts/history.py change \
  --title "Add step-level BSR scatter export" \
  --why "Need manuscript-facing diagnostic for BSR versus PRM fields." \
  --how "Added plotting entrypoint and reused existing score JSONL schema." \
  --file "exp/gain analysis/scripts/export_bsr_prm_scatter.py" \
  --validation "uv run python exp/gain analysis/scripts/export_bsr_prm_scatter.py"

python3 <skill-dir>/scripts/history.py decision \
  --title "Keep PRM and belief-shift signal separate" \
  --context "Related-work text was merging supervision source and reward-shaping signal." \
  --decision "Describe PRM as supervision lineage and BSR as the training signal." \
  --rationale "This avoids overclaiming PRM equivalence."

python3 <skill-dir>/scripts/history.py idea \
  --title "Prompt-wise qualitative comparison block" \
  --problem "Need short examples that make the reward mechanism intuitive." \
  --hypothesis "Compare 4 trajectories per prompt from quantile4 candidates." \
  --next "Mine 10 prompts and save markdown blocks under analysis outputs."
```

## Commit Pairing

Every record the script writes carries a stable `Record Id:` and a `## Commits` section. Pair each record with the commit that actually did the work, so a summary always has a diff behind it and an archived summary stays verifiable.

Record first, then commit through the script:

```bash
python3 <skill-dir>/scripts/history.py change \
  --title "Add step-level BSR scatter export" \
  --why "Need manuscript-facing diagnostic for BSR versus PRM fields." \
  --how "Added plotting entrypoint and reused existing score JSONL schema."

python3 <skill-dir>/scripts/history.py commit \
  --record bsr-scatter-export \
  --message "Add step-level BSR scatter export" \
  --path "exp/gain analysis/scripts/export_bsr_prm_scatter.py"
```

`--record` accepts the full record id, a repo-relative path, or a unique fragment. The commit message gets a `History-Record: <record-id>` trailer, the record gets the commit id in both `Commits:` metadata and its `## Commits` section, and a small bookkeeping commit stores that record update. Pass `--no-record-commit` to leave the record edit uncommitted, `--all` to stage everything, or repeat `--path` for specific files.

When the commit already exists, pair it afterwards instead:

```bash
python3 <skill-dir>/scripts/history.py link-commit --record bsr-scatter-export
python3 <skill-dir>/scripts/history.py link-commit --record bsr-scatter-export --commit 4f2a91c
python3 <skill-dir>/scripts/history.py sync-commits
```

`link-commit` defaults to `HEAD` and never rewrites Git history unless `--amend-trailer` is passed. `sync-commits` scans commit messages for `History-Record:` trailers and backfills any pairing the records are missing, which repairs drift after rebases, cherry-picks, or hand-written commits.

Read the pairing in either direction:

```bash
python3 <skill-dir>/scripts/history.py commits --record bsr-scatter-export --stat
python3 <skill-dir>/scripts/history.py commits --commit 4f2a91c
python3 <skill-dir>/scripts/history.py commits
```

Record commands also accept `--commit <sha>` at creation time when the commit already exists.

## Long-Term Archive

Multi-month projects accumulate more history than an agent should load. Archiving keeps the recall surface small without losing anything: the full record text moves to `history-archive/YYYY-MM/<kind>/`, and `history/` keeps a summary stub with the record id, metadata, paired commits, a condensed summary, and a pointer back to the full text.

```bash
python3 <skill-dir>/scripts/history.py archive status
python3 <skill-dir>/scripts/history.py archive plan
python3 <skill-dir>/scripts/history.py archive run
python3 <skill-dir>/scripts/history.py archive run --dry-run --older-than-days 180
python3 <skill-dir>/scripts/history.py archive run --record chg-2026-05-08-190555-change
python3 <skill-dir>/scripts/history.py archive restore --record chg-2026-05-08-190555-change
```

Defaults for the steady-state `archive run`: records older than 60 days, keeping the 20 most recent per kind, over `changes`, `experiments`, `daily`, `sessions`, `handoffs`, `capsules`, and `inbox`. `decisions` and `ideas` are never archived by default because they stay canonical. Three guards keep still-useful records in place unless you override them: records marked open, in-progress, or proposed (`--include-open`), records that `CONTEXT.md`, `canonical/`, or `tasks/` still link to (`--include-referenced`), and records whose stub would not actually be cheaper to read (`--min-saving 0`). Tune the rest with `--include`, `--older-than-days`, and `--keep-recent`.

The last guard is measured, not guessed: for every candidate the script builds the stub it would write and compares it against the record. A record is archived only when the stub is at least 30% and 400 characters smaller. Short records lose on that comparison, because a stub carries its own frontmatter, metadata block, commit list, and pointer; archiving them would make recall more expensive, not less. When `archive plan` reports no candidates, it says how many were skipped for this reason.

Archiving never deletes. `archive restore --record <id>` moves the full text back and removes the stub. `archive migrate` moves a legacy `history/archive/` folder from earlier versions of this skill into `history-archive/`.

### First Run On An Existing History

Those defaults are deliberately conservative, so a history that has never been archived often has zero candidates: `--keep-recent 20` protects the newest 20 records per kind even when every one of them is old. That is right for an active project and wrong for a first adoption, where the whole backlog should move at once.

Use `archive adopt` for that one-time pass. It migrates any legacy `history/archive/` folder, ignores `--keep-recent`, archives everything past the age window, and reports how much the recall surface shrank:

```bash
python3 <skill-dir>/scripts/history.py archive adopt --dry-run
python3 <skill-dir>/scripts/history.py archive adopt
python3 <skill-dir>/scripts/history.py sync-commits
```

It keeps the guards that serve the same goal: records still marked open, records that curated context links to, and records whose stub would not be smaller than the record stay in place. Override those with `--include-open`, `--include-referenced`, and `--min-saving 0`. The command is idempotent; a second run reports the existing stubs and archives nothing. Commit `history/` and `history-archive/` together as one move.

`start` and `finish` point at `archive adopt` when a history has 60 or more records and no stubs yet.

Archived text is excluded from default recall. Reach it deliberately:

```bash
python3 <skill-dir>/scripts/history.py search "reward normalization" --include-archive
python3 <skill-dir>/scripts/history.py exact "gain_normalized" --include-archive
python3 <skill-dir>/scripts/history.py start --query "reward normalization" --include-archive
```

Treat a stub as a lead, not a full answer: read its summary, then open the archived text or `git show` its paired commit before relying on details.

## Handoff Agent Capsules

Use a handoff agent capsule when work must continue in another agent, tool, terminal, or server. A capsule is a portable markdown bundle with user requirements, current state, public decision-rationale summary, touched files, validation, risks, next actions, BM25 read-first records, generated queries, and retrieval reflection.

Create one before switching from Codex to Claude, Claude to Codex, local to remote SSH, one server to another server, or one agent thread to another:

```bash
python3 <skill-dir>/scripts/history.py handoff-agent-capsule create \
  --task "Continue reward export on remote server" \
  --query "reward export gain_normalized validation" \
  --from-agent "codex" \
  --to-agent "claude" \
  --target-host "ssh lab-server" \
  --user-requirement "Preserve existing manuscript-facing field names." \
  --current-state "Export helper is implemented locally but remote validation is pending." \
  --reasoning-summary "Use existing score schema instead of introducing new reward names." \
  --file "scripts/export_reward.py" \
  --validation "python scripts/export_reward.py --dry-run" \
  --next-action "Run the export on the remote dataset and compare output columns."
```

Resume from the latest or matching capsule in the next agent:

```bash
python3 <skill-dir>/scripts/history.py handoff-agent-capsule resume
python3 <skill-dir>/scripts/history.py handoff-agent-capsule resume --query "reward export"
```

Import a capsule copied from another server or tool:

```bash
python3 <skill-dir>/scripts/history.py handoff-agent-capsule import --file /path/to/capsule.md
```

Store concise public reasoning summaries, not hidden chain-of-thought. Focus on decisions, constraints, assumptions, evidence, and next checks.

If a handoff or capsule should be included in task/workstream-scoped `collab recall`, include explicit `Task:` and `Workstream:` metadata in the record. Use `all`, `cross-task`, or `cross-workstream` for intentionally broad context; records without task/workstream metadata remain general history rather than scoped collaboration context.

## Large-Scale Collaboration

Use `collab` when a project has many people, many benchmark tasks, or a shared agent context that must stay curated. The central rule is summaries-only in `history/inbox/`, then maintainer promotion into accepted context.

Add the collaboration layer to the same project repository:

```bash
python3 <skill-dir>/scripts/history.py collab bootstrap --task-count 15 --default-workstreams
```

Participants submit concise summaries after work:

```bash
python3 <skill-dir>/scripts/history.py collab submit-summary \
  --task task-03 \
  --workstream eval \
  --person "Jaehee Kim" \
  --agent codex \
  --summary "Added the held-out metric check and found one dataset mismatch." \
  --evidence "logs/eval/heldout-2026-05-08.txt" \
  --changed-file "eval/run_heldout.py" \
  --open-question "Confirm whether task-03 uses v1 or v2 labels."
```

Do not submit raw transcripts, credentials, private notes, or personal data. The template accepts summary, claims, evidence, changed files, validation, open questions, proposed decisions, and optional private/local references. Sensitive-looking fields produce warnings; use `--strict` when the submitter should fail fast.

Maintainers promote reviewed material only:

```bash
python3 <skill-dir>/scripts/history.py collab promote \
  --inbox history/inbox/2026-05-08-120000-task-03-eval-jaehee-kim-codex-summary.md \
  --target workstream \
  --maintainer "maintainer-name" \
  --note "Accepted: task-03 held-out eval currently uses v2 labels; v1 labels remain an open risk."
```

`collab promote` only accepts `.md` files inside `history/inbox/` as `--inbox` input; do not promote directories, non-markdown files, or arbitrary files outside the inbox. `--note` is curated-only promotion: it promotes the maintainer's reviewed note without automatically carrying submitted sections. Add `--include-submitted-sections` only when reviewed submitted sections such as Claims, Evidence, Changed Files, Validation, Open Questions, or Proposed Decisions should be appended.

Start agents from the accepted context pack, not the raw inbox:

```bash
python3 <skill-dir>/scripts/history.py collab recall --task task-03 --workstream eval --query "held-out metric labels"
python3 <skill-dir>/scripts/history.py collab status
```

Default `collab recall` reads canonical overview, selected task context, selected workstream context, accepted decisions, and scoped BM25 hits. Accepted decisions are records marked with either `Status: accepted` or `Approval Status: accepted`. It excludes `history/inbox/` unless `--include-inbox` is explicitly passed, and retrieval output labels each hit with record type and approval status.

It also excludes the archive unless `--include-archive` is explicitly passed. Treat archived records as provenance/evidence leads, not canonical facts, until they are checked against accepted context.

Use archive cleanup after promotion review:

```bash
python3 <skill-dir>/scripts/history.py collab archive --dry-run
python3 <skill-dir>/scripts/history.py collab archive
python3 <skill-dir>/scripts/history.py collab archive --older-than-days 30 --include inbox,daily,sessions
```

`collab archive` moves promoted inbox records into `history-archive/` whole, without a summary stub, because the accepted content already lives in canonical, task, or workstream context. It does not delete them, and it is separate from the long-term `archive` commands above. By default it archives accepted inbox summaries that have `Promoted To:` metadata. Only maintainers should run `collab promote` and `collab archive`.

`collab status` shows pending inbox submissions, accepted-but-unarchived inbox records, archive candidates, stale canonical/task/workstream context, unscoped handoffs/capsules, accepted decisions, and open risks.

## Before Final Response

For non-trivial work, ensure the history reflects what actually happened:

1. Create or update a `change`, `decision`, `idea`, `experiment`, `handoff`, or `handoff-agent-capsule` record.
2. Include concrete paths, commands, parameters, validation results, and unresolved risks.
3. Update `history/CONTEXT.md` only when durable project state changed.
4. Run `finish`; fix lint errors and treat missing-record guidance as a prompt to create the right record manually. `finish` also reports change/experiment records with no paired commit, commits whose `History-Record:` trailer no record lists, uncommitted work that has grown past the commit thresholds, and records due for archiving.
5. Pair the work with its commit through `commit --record <id>` or `link-commit --record <id>`.
6. Rebuild the index after creating records or changing history files:

```bash
python3 <skill-dir>/scripts/history.py finish
python3 <skill-dir>/scripts/history.py lint
python3 <skill-dir>/scripts/history.py index
```

Mention the history record path in the final response when useful.

## Recall Discipline

Use history as a selective memory, not a prompt dump:

- Prefer `recall --query "<specific subsystem or idea>"` over loading every file.
- Use `start --query "<specific subsystem or idea>"` at new-session startup when you need read-only context. `recall` is still available for compatibility, but it may create today's daily log and rebuild `INDEX.md`.
- BM25 search runs over virtual markdown-aware chunks: small files stay whole, while longer records split by `##` section and paragraph-sized chunks with overlap. Read the reported chunk heading and line number before opening the full file.
- Use `search "<query>"` for vendored BM25S-ranked retrieval; use `search --exact "<string>"` or `exact "<string>"` only when you need literal substring matches.
- Treat generated query variants as proposed search angles. If a variant is off-target, rerun with a more specific query.
- Treat reflection notes as retrieval QA: absent tokens, weak results, or one-type-only hits mean you should verify current files or refine the query before relying on the result.
- Treat a hit labelled `archive_status=stub` as a summary. Follow its `Archived To:` path, rerun with `--include-archive`, or `git show` its paired commit before trusting details.
- Follow links from `INDEX.md` only when they are relevant.
- Trust newer entries over older ones, but preserve old entries by appending corrections rather than rewriting history.
- If history conflicts with current files, verify the current files and record the correction.

For deeper schema details, read `references/history-structure.md`.
