---
name: track-research-history
description: Record and recall repository-local research decisions, code changes, experiments, and handoffs. Use for continuity across coding sessions, finding a file's Git changes with their research context, and maintaining a project's history/ Markdown and portable archives.
---

# Track Research History

Keep durable research memory in the current repository's Git-tracked `history/` Markdown. Git is the source of truth. Ranked recall uses the bundled BM25S implementation and NumPy; no database or memory service is needed. Do not store secrets, raw private data, transcripts, or hidden chain-of-thought.

Write explanations, decisions, results, and limitations in the user's working language. Preserve metadata keys, code identifiers, paths, and quoted evidence.

Resolve `<skill-dir>` to the directory containing this file. Check `scripts/history.py --version` or `--capabilities` when a host's installed command differs from its instructions.

## Recall before work

```bash
python3 <skill-dir>/scripts/history.py start --brief --query "task terms"
python3 <skill-dir>/scripts/history.py search "specific identifier or question" --limit 5
```

`start`, `recall`, `search`, `exact`, `recent`, `lint`, status/plan commands, and capsule resume are read-only. If `history/` is missing, run `bootstrap` before creating records. `recall --update` explicitly restores the old behavior of creating today's daily log and refreshing indexes.

Read the matching body excerpt and source lines before opening a full record. Treat diagnostics as retrieval limits: no exact match, expansion-only evidence, or a missing target term is a reason to refine the query or inspect current files. A positive BM25 score is not an answer confidence. `--no-variants` actually disables query expansion.

For a file's implementation history, use the existing commit browser:

```bash
python3 <skill-dir>/scripts/history.py commits --file src/module.py --ref HEAD --limit 5
python3 <skill-dir>/scripts/history.py commits --record <record-id> --stat
python3 <skill-dir>/scripts/history.py commits --commit <sha>
```

File browsing uses the selected Git ref and distinguishes explicit record links, co-changed records, and literal-path candidates. A candidate is a lead, not an established reason for that commit. An ancestor commit may have been reverted. Check the selected ref's file/diff before asserting that an old change is still effective. Detailed scope, rename, JSON, filtering, and evaluation guidance is in [retrieval-and-provenance.md](references/retrieval-and-provenance.md).

## Record meaningful work

Use the narrowest useful type:

- `change`: code, configuration, data pipelines, documents, or structure changed.
- `decision`: a design or research choice, with rationale and consequences.
- `experiment`: a run, measurement, comparison, or analysis with conditions and artifacts.
- `idea`: an untested hypothesis or proposed next step.
- `handoff`: ownership and next actions for a collaborator.
- `handoff-agent-capsule`: context transferred to another agent, tool, or server.
- `session`: an overview only when a broad workstream needs one.

Skip trivial chat and routine read-only checks. A substantive review can warrant an experiment, idea, or decision record even when no code changed. Keep each record focused on what happened, why, exact evidence, validation scope, and unresolved limits.

```bash
python3 <skill-dir>/scripts/history.py change \
  --title "Add interval validation" \
  --why "Reject inconsistent accounting before committing a transition." \
  --how "Validate interval inputs and outputs atomically." \
  --file src/transition.py --validation "focused tests passed"

python3 <skill-dir>/scripts/history.py decision \
  --title "Correct the prior measurement premise" \
  --corrects <prior-record-id> --scope "v2.1" \
  --decision "The measured count describes actions, not causes." \
  --rationale "Rechecked the source schema and generated bundle."
```

Use `--corrects` for a partial correction and `--supersedes` for a full replacement. Refer to a full record ID or path; short display numbers may be ambiguous after branch merges. Creation preserves the original record and stores the relationship on the new one. A partial correction does not invalidate the whole earlier decision. `Scope:` describes applicability; the observed Git branch/HEAD metadata describes where the record was written, not the commit implementing it.

Keep `CONTEXT.md` a short current overview of goals, constraints, active versions, unresolved work, and evidence links. Move historical state into dated records. Do not keep adding contradictory "current" and "next" sections. Updating a summary does not replace the historical evidence.

## Pair recorded work with Git

When committing is authorized, stage only the work being recorded:

```bash
python3 <skill-dir>/scripts/history.py commit \
  --record <record-id> --message "Add interval validation" \
  --path src/transition.py --path tests/test_transition.py
```

The command rejects pre-staged paths outside its allowed scope; it does not silently absorb someone else's work. `--all` explicitly selects all work. A `History-Record:` trailer links the work commit back to its record. The record's reverse SHA reference may be stored in a small subsequent bookkeeping commit; only affected record/generated files belong there. `--no-record-commit` leaves that update uncommitted.

```bash
python3 <skill-dir>/scripts/history.py link-commit --record <id> --commit <sha>
python3 <skill-dir>/scripts/history.py sync-commits
```

`link-commit` does not rewrite commits unless `--amend-trailer` is explicitly selected. After squash/rebase, inspect replacement references before using `sync-commits --prune`; a different SHA is not proof of an equivalent patch.

## Finish

For non-trivial work, create the relevant record, then run:

```bash
python3 <skill-dir>/scripts/history.py finish
python3 <skill-dir>/scripts/history.py finish --base <starting-commit>
```

Resolve errors. Warnings identify metadata, ambiguous references, document size, or existing pairing/backlog issues; judge their relevance to this task. `--base` checks committed work in an explicit ancestor range so a clean working tree does not hide missing records. It recognizes explicit links and co-changed record files; it cannot prove that prose is sufficient or correct. `--strict` also fails on warnings and uncovered commits in that range. `finish` never creates a record for you.

Record/index commands maintain `INDEX.md` and `PROJECT_MAP.md`. Use `index` after manual edits. Generated navigation is deterministic; page-size warnings target prose rather than generated maps.

## Optional modes

- **Human browsing:** open `history/` as an Obsidian vault, start at `PROJECT_MAP.md`, and keep `.obsidian/` untracked. Plain Markdown and portable links remain authoritative.
- **Long projects:** inspect `archive plan` or `archive adopt --dry-run`. Full text moves to `history-archive/` and a summary stub remains. Unresolved and actively referenced records are protected by default. Summaries retain results/validation/risks, but may be incomplete; follow the original before relying on details. Use `archive restore --record <id>` to reverse a move.
- **Handoffs:** use `handoff-agent-capsule create` with requirements, current state, evidence, risks, and next actions. Resume with a query or an explicit path; a failed query does not select an unrelated capsule.
- **Large collaborations:** use `collab submit-summary` → maintainer `collab promote` → `collab recall`. Submitted inbox material is noncanonical until accepted. Only maintainers promote/archive submissions. Task/workstream metadata scopes retrieval.

Read [history-structure.md](references/history-structure.md) for storage, archive, capsule, and collaboration schemas. For installing one payload into Codex and Claude discovery paths, see [README.md](README.md).
