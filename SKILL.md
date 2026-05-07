---
name: track-research-history
description: Maintain durable research-project history while coding, with BM25S-based recall, generated query variants, retrieval reflection, and handoff agent capsules for moving work across Codex, Claude, agents, or servers. Use when Codex or Claude needs to automatically record and recall why code changed, how it was implemented, which files changed, which ideas or hypotheses led to it, experiment decisions, collaboration handoffs, agent transition context, or project context in a repository-level history/ folder.
---

# Track Research History

## Core Rule

Treat history as part of the work product. For any non-trivial research, code, experiment, architecture, or collaboration task:

1. Recall relevant history before editing.
2. Record meaningful decisions, ideas, experiments, and code changes while working.
3. Leave the next agent or collaborator with searchable context before the final response.

Do not record secrets, credentials, private tokens, or raw personal data. Redact sensitive values and note that they were redacted.

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

Use the bundled script for deterministic structure, filenames, indexing, and BM25S recall:

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
- Use `search "<query>"` for BM25S-ranked retrieval; use `search --exact "<string>"` or `exact "<string>"` only when you need literal substring matches.
- Treat generated query variants as proposed search angles. If a variant is off-target, rerun with a more specific query.
- Treat reflection notes as retrieval QA: absent tokens, weak results, or one-type-only hits mean you should verify current files or refine the query before relying on the result.
- Follow links from `INDEX.md` only when they are relevant.
- Trust newer entries over older ones, but preserve old entries by appending corrections rather than rewriting history.
- If history conflicts with current files, verify the current files and record the correction.

For deeper schema details, read `references/history-structure.md`.
