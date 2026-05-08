---
name: track-research-history
description: Maintain durable research-project history while coding, with dependency-light SQLite FTS5 BM25 recall, generated query variants, retrieval reflection, handoff agent capsules, and maintainer-curated collaboration history for large benchmark projects. Use when Codex or Claude needs to automatically record and recall why code changed, how it was implemented, which files changed, which ideas or hypotheses led to it, experiment decisions, collaboration handoffs, agent transition context, task/workstream context, or canonical project context in a repository-level history/ folder or central history repo.
---

# Track Research History

## Core Rule

Treat history as part of the work product. For any non-trivial research, code, experiment, architecture, or collaboration task:

1. Recall relevant history before editing.
2. Record meaningful decisions, ideas, experiments, and code changes while working.
3. Leave the next agent or collaborator with searchable context before the final response.

Do not record secrets, credentials, private tokens, or raw personal data. Redact sensitive values and note that they were redacted.

## Language

Write record prose in the user's working language by default. If the user is working in Korean, write summaries, rationale, validation notes, risks, and handoff context in Korean unless they ask for another language or the target artifact requires English.

Keep fixed metadata keys, CLI flags, file paths, code identifiers, command output, and quoted source text unchanged. Mixed-language records are acceptable when the project artifacts or evidence are mixed-language.

## Storage Model

Use a repository-local `history/` folder. If the project already has a history system, adapt to it rather than replacing it. Otherwise create this structure:

```text
history/
  CONTEXT.md
  INDEX.md
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
```

For large benchmark collaborations, use the `collab` layer in the same `history/` folder or in a dedicated central history repo:

```text
history/
  canonical/overview.md
  tasks/<task-id>/context.md
  tasks/<task-id>/workstreams/<name>.md
  inbox/
  archive/
    inbox/YYYY-MM/
    daily/YYYY-MM/
    sessions/YYYY-MM/
  decisions/
  handoffs/
  capsules/
```

Use the bundled script for deterministic structure, filenames, indexing, and SQLite FTS5 BM25 recall:

```bash
python3 <skill-dir>/scripts/history.py bootstrap
python3 <skill-dir>/scripts/history.py recall --limit 8
python3 <skill-dir>/scripts/history.py recall --query "reward shaping" --limit 8
python3 <skill-dir>/scripts/history.py search "gain_normalized ablation idea" --limit 10
```

Resolve `<skill-dir>` to the directory containing this `SKILL.md`.

## Start Of Work

Before making substantial changes:

1. Run `bootstrap` if `history/` is missing.
2. Run `recall`; add `--query` terms from the user request, changed subsystem, paper section, method name, dataset, or experiment.
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

Initialize a central history repo or add the collaboration layer to an existing repo:

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

It also excludes `history/archive/` unless `--include-archive` is explicitly passed. Treat archived records as provenance/evidence leads, not canonical facts, until they are checked against accepted context.

Use archive cleanup after promotion review:

```bash
python3 <skill-dir>/scripts/history.py collab archive --dry-run
python3 <skill-dir>/scripts/history.py collab archive
python3 <skill-dir>/scripts/history.py collab archive --older-than-days 30 --include inbox,daily,sessions
```

`collab archive` moves records into `history/archive/`; it does not delete them. By default it archives accepted inbox summaries that have `Promoted To:` metadata. Only maintainers should run `collab promote` and `collab archive`.

`collab status` shows pending inbox submissions, accepted-but-unarchived inbox records, archive candidates, stale canonical/task/workstream context, unscoped handoffs/capsules, accepted decisions, and open risks.

## Before Final Response

For non-trivial work, ensure the history reflects what actually happened:

1. Create or update a `change`, `decision`, `idea`, `experiment`, `handoff`, or `handoff-agent-capsule` record.
2. Include concrete paths, commands, parameters, validation results, and unresolved risks.
3. Update `history/CONTEXT.md` only when durable project state changed.
4. Run:

```bash
python3 <skill-dir>/scripts/history.py index
```

Mention the history record path in the final response when useful.

## Recall Discipline

Use history as a selective memory, not a prompt dump:

- Prefer `recall --query "<specific subsystem or idea>"` over loading every file.
- BM25 search runs over virtual markdown-aware chunks: small files stay whole, while longer records split by `##` section and paragraph-sized chunks with overlap. Read the reported chunk heading and line number before opening the full file.
- Use `search "<query>"` for SQLite FTS5 BM25-ranked retrieval; use `search --exact "<string>"` or `exact "<string>"` only when you need literal substring matches.
- Treat generated query variants as proposed search angles. If a variant is off-target, rerun with a more specific query.
- Treat reflection notes as retrieval QA: absent tokens, weak results, or one-type-only hits mean you should verify current files or refine the query before relying on the result.
- Follow links from `INDEX.md` only when they are relevant.
- Trust newer entries over older ones, but preserve old entries by appending corrections rather than rewriting history.
- If history conflicts with current files, verify the current files and record the correction.

For deeper schema details, read `references/history-structure.md`.
