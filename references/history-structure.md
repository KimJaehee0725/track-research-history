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

## Search Strategy

Search uses the vendored `bm25s` implementation by default. Start broad, inspect generated variants and reflection, then narrow:

```bash
python3 <skill-dir>/scripts/history.py recall --limit 8
python3 <skill-dir>/scripts/history.py recall --query "normalization" --limit 10
python3 <skill-dir>/scripts/history.py search "gain_normalized" --limit 20
python3 <skill-dir>/scripts/history.py exact "gain_normalized" --limit 20
```

Use exact field names, file names, method names, experiment ids, figure names, or paper-section names as queries.

The search command performs three steps:

1. Generate deterministic query variants from the original query, identifier/path splits, and intent words such as why, idea, experiment, code, or handoff.
2. Rank history records with BM25S.
3. Print reflection notes about weak recall, missing query tokens, or over-concentrated result types.

Use `exact` only as a fallback for literal string matching.

## Vendored Retrieval

The bundled BM25 engine is `bm25s` from `https://github.com/xhluca/bm25s`, vendored under `scripts/vendor/bm25s` with its MIT license. It was chosen over `rank-bm25` because it is still lightweight while providing faster sparse scoring and a more complete retrieval API.

## Collaboration Notes

When multiple agents or collaborators may touch the repo:

- Record ownership boundaries in `handoffs/`.
- Use `handoff-agent-capsule create` before switching agents, tools, local/remote terminals, or servers.
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
