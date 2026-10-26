# Retrieval and file provenance

## Choosing the entry point

Use content search for decisions, hypotheses, experiments, and questions whose file is unknown. Use `commits --file` when an existing file is the anchor. The two tools complement each other: Git has exact changes and ancestry; records may contain rationale, experimental conditions, and results outside Git.

```bash
python3 scripts/history.py search "src/transition.py" --json --limit 5
python3 scripts/history.py search "repair budget" --kind decisions --limit 5
python3 scripts/history.py search "physical time" --scope history/changes --no-variants
python3 scripts/history.py commits --file src/transition.py --ref HEAD --limit 5 --json
```

`--kind` and search `--status` are repeatable. Search `--scope` is a history path prefix; record creation `--scope` is applicability metadata. Neither implicitly changes the Git ref. Search reads the current worktree's Markdown; the commit browser reads history at its explicitly selected ref.

## Search behavior

Ranked retrieval stays within vendored BM25S. Exact paths and symbols are protected from broad directory/word expansions. Structured diagnostics explain missing exact identifiers, insufficient target terms, and fallback matching. A missing history identifier does not mean the corresponding code or Git commit does not exist. A SHA that resolves locally carries a full-ID `commits --commit` next action, with its relation to HEAD identified.

Results are grouped by source file, one chunk by default (`--chunks-per-file 2` expands this). Excerpts come from the matching body with source locations. Generated query/reflection blocks and repeated frontmatter should not crowd out original evidence. Source status, correction links, and recorded branch/HEAD remain provenance, not automatic correctness guarantees.

Korean spacing fallback uses literal normalized Hangul evidence. It does not understand all inflections, synonyms, translated concepts, negation, or changes in applicability. Inspect the fallback label. Rephrase with a known field, file, method, version, or a transparent alternative query when the necessary vocabulary is absent. Do not equate BM25 scores across queries with probabilities.

`--no-variants` disables expansion, including identifier splitting that could broaden a precise query. `exact` remains literal substring lookup. Archived full records are available only with `--include-archive`; a stub is a lead requiring the linked original for details.

## File trace

The existing `commits` browser accepts `--file PATH --ref REF --limit N`, with optional `--follow`, `--diff`, and `--json`. It reports the resolved full commit ID, parents, selected ref, common Git directory, and available dirty-worktree observations. The default ref is `HEAD`.

Record associations are explicit about their basis:

- **Explicit:** commit trailer or record commit metadata names the commit. Inspect whether the record describes implementation, validation, or an experiment baseline.
- **Co-change:** a record and the file changed in one commit. This is structural evidence, not proof that every sentence explains that file.
- **Path candidate:** the selected ref's record literally mentions the tracked path. It may explain the subsystem generally and need not describe this exact commit.

A record written in a later documentation commit can explain earlier code; this is why path candidates are useful when pairing is incomplete. Avoid silently converting candidates or arbitrary SHA mentions into causal links.

Paths are passed after Git's `--` separator, and unknown refs/paths fail explicitly. Rename following is optional, single-file, and subject to Git's heuristic rename detection and merge-history simplification. Ref ancestry does not prove current behavior: a later revert can undo an ancestor; squash and cherry-pick can replace IDs. Open the actual ref's file/diff before claiming that a past implementation is active. Whole diffs and all refs are not default context.

## Quality checks

Behavioral tests cover missing identifiers, file grouping, body locations, no-op read commands, concurrent writes, ref isolation, rename/deletion, commit scope, and unresolved archive states. The retrieval fixture exercises more than the original FabGym examples and includes unanswerable and lexical-variation queries.

For a real project, compare with manual `git log`/`git show` and content lookup. Define the evidence needed for each task, including acceptable relationship types. Track evidence coverage in the first three unique documents, unrelated or wrong-ref evidence presented as confirmed, appropriate missing-evidence diagnostics, and the text/tool calls an agent must consume. Latency alone is insufficient. Synthetic retrieval cases do not establish the speed or correctness of end-to-end agent work.

## Explicit corrections

Known incoming correction and replacement links are attached as `related_records` even when that record does not repeat the query identifier. These are explicit relationship context, not additional BM25 matches. Linked context outside query filters is labelled `outside_filters`; its status and scope still require inspection. New capsule read-first lists retain this context. An older capsule remains a historical snapshot; resume it with `--query` to refresh known corrections.
