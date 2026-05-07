#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


HISTORY_DIR = "history"
SCRIPT_DIR = Path(__file__).resolve().parent
VENDOR_DIR = SCRIPT_DIR / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

TOKEN_PATTERN = r"(?u)\b[\w./:-]{2,}\b"
RECORD_DIRS = [
    "daily",
    "changes",
    "decisions",
    "ideas",
    "experiments",
    "handoffs",
    "capsules",
    "sessions",
    "templates",
]


def now() -> datetime:
    return datetime.now().astimezone()


def date_stamp() -> str:
    return now().strftime("%Y-%m-%d")


def time_stamp() -> str:
    return now().strftime("%Y-%m-%d-%H%M%S")


def display_time() -> str:
    return now().strftime("%Y-%m-%d %H:%M %z")


def short_time() -> str:
    return now().strftime("%H:%M")


def slugify(text: str, fallback: str = "record") -> str:
    value = text.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:64].strip("-") or fallback


def detect_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return Path.cwd().resolve()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def bullets(items: list[str] | None) -> str:
    if not items:
        return "-"
    return "\n".join(f"- {item}" for item in items if item)


def value(text: str | None) -> str:
    return text.strip() if text and text.strip() else "-"


def write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def ensure_history(root: Path) -> None:
    history = root / HISTORY_DIR
    for name in RECORD_DIRS:
        (history / name).mkdir(parents=True, exist_ok=True)

    write_if_missing(
        history / "CONTEXT.md",
        """# Project Context

Last updated:

## Research Goal

-

## Current Architecture Or Structure

-

## Current Decisions

-

## Active Ideas

-

## Open Questions And Risks

-

## Next Steps

-
""",
    )
    write_if_missing(
        history / "README.md",
        """# Project History

This folder stores durable project memory for research coding, experiments, ideas, decisions, and collaboration.

## Read First

1. `CONTEXT.md`
2. `INDEX.md`
3. Latest file in `daily/`
4. Relevant records from `changes/`, `decisions/`, `ideas/`, `experiments/`, `handoffs/`, `capsules/`, and `sessions/`

## Maintenance

- Keep entries concrete: paths, commands, parameters, rationale, validation, and risks.
- Append corrections instead of rewriting past history.
- Do not store secrets or credentials.
""",
    )
    templates = {
        "daily.md": """# Daily Log - {{date}}

## Focus

-

## Work Notes

-

## Linked Records

## Open Questions / Risks

-

## Next

-
""",
        "change.md": """# Change - {{title}}

Date: {{date}}
Agent: {{agent}}
Status: {{status}}

## Why

{{why}}

## How

{{how}}

## Files

{{files}}

## Validation

{{validation}}

## Risks / Follow-Ups

{{risks}}
""",
        "decision.md": """# Decision {{id}} - {{title}}

Date: {{date}}
Status: {{status}}

## Context

{{context}}

## Decision

{{decision}}

## Rationale

{{rationale}}

## Consequences

{{consequences}}
""",
        "idea.md": """# Idea {{id}} - {{title}}

Date: {{date}}
Status: {{status}}
Tags: {{tags}}

## Problem / Opportunity

{{problem}}

## Hypothesis

{{hypothesis}}

## Expected Value

{{expected}}

## Links / Evidence

{{links}}

## Next Check

{{next}}
""",
        "experiment.md": """# Experiment {{id}} - {{title}}

Date: {{date}}
Status: {{status}}
Tags: {{tags}}

## Goal

{{goal}}

## Setup

{{setup}}

## Metrics

{{metrics}}

## Results

{{results}}

## Artifacts

{{artifacts}}

## Interpretation / Next

{{next}}
""",
        "handoff.md": """# Handoff - {{title}}

Date: {{date}}
To: {{to}}

## Summary

{{summary}}

## Ownership / Files

{{files}}

## Next Actions

{{next}}

## Risks

{{risks}}
""",
        "handoff-agent-capsule.md": """# Handoff Agent Capsule - {{task}}

Date: {{date}}
From Agent: {{from_agent}}
To Agent: {{to_agent}}
Target Host: {{target_host}}
Status: {{status}}

## User Requirements

{{requirements}}

## Current State

{{current_state}}

## Agent Reasoning Summary

{{reasoning_summary}}

## Files / Ownership

{{files}}

## Commands / Validation

{{validation}}

## Open Risks

{{risks}}

## Next Actions

{{next_actions}}

## Read These Records First

{{read_first}}

## BM25 Query Generation

{{generated_queries}}

## Retrieval Reflection

{{reflection}}

## Project Context Snapshot

{{project_context}}

## Git Status Snapshot

```text
{{git_status}}
```
""",
        "session.md": """# Session - {{task}}

Date: {{date}}
Agent: {{agent}}

## Scope

{{scope}}

## Read First

-

## Plan

-

## Work Log

-

## End Summary

-
""",
    }
    for filename, text in templates.items():
        write_if_missing(history / "templates" / filename, text)


def today_file(root: Path) -> Path:
    ensure_history(root)
    path = root / HISTORY_DIR / "daily" / f"{date_stamp()}.md"
    if not path.exists():
        tmpl = (root / HISTORY_DIR / "templates" / "daily.md").read_text(encoding="utf-8")
        path.write_text(tmpl.replace("{{date}}", date_stamp()), encoding="utf-8")
    return path


def append_daily(root: Path, kind: str, title: str, record_path: Path) -> None:
    path = today_file(root)
    line = f"- {short_time()} [{kind}] {title} -> `{rel(root, record_path)}`\n"
    text = path.read_text(encoding="utf-8")
    marker = "## Linked Records\n"
    if marker in text:
        text = text.replace(marker, marker + "\n" + line, 1)
    else:
        text = text.rstrip() + "\n\n## Linked Records\n\n" + line
    path.write_text(text, encoding="utf-8")


def next_id(folder: Path) -> str:
    highest = 0
    for path in folder.glob("*.md"):
        match = re.match(r"^(\d{4})-", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{highest + 1:04d}"


def git_status(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(root), "status", "--short"],
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
        return out or "clean"
    except Exception as exc:
        return f"unavailable: {exc}"


def write_record(root: Path, folder: str, filename: str, text: str, kind: str, title: str) -> Path:
    ensure_history(root)
    out = root / HISTORY_DIR / folder / filename
    out.write_text(text, encoding="utf-8")
    append_daily(root, kind, title, out)
    build_index(root)
    print(rel(root, out))
    return out


def build_index(root: Path) -> Path:
    ensure_history(root)
    history = root / HISTORY_DIR
    lines = [
        "# History Index",
        "",
        f"Generated: {display_time()}",
        "",
        "## Current Context",
        "",
        "- `history/CONTEXT.md`",
        "- `history/README.md`",
        "",
        "## Latest Records",
        "",
    ]
    for folder in ["daily", "changes", "decisions", "ideas", "experiments", "handoffs", "capsules", "sessions"]:
        files = sorted((history / folder).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        lines.append(f"### {folder}")
        lines.append("")
        if not files:
            lines.append("- none")
        for path in files[:12]:
            title = first_heading(path)
            lines.append(f"- `{rel(root, path)}` - {title}")
        lines.append("")
    out = history / "INDEX.md"
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out


def first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except Exception:
        pass
    return path.stem


def record_kind(path: Path) -> str:
    if path.name == "CONTEXT.md":
        return "context"
    if path.name == "README.md":
        return "readme"
    return path.parent.name


def split_identifier_text(text: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    value = re.sub(r"[/_.:-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def bm25_file_paths(root: Path) -> list[Path]:
    paths = []
    for path in iter_search_files(root):
        if path.name == "INDEX.md":
            continue
        if path.name.startswith("."):
            continue
        paths.append(path)
    return paths


def bm25_documents(root: Path) -> list[dict[str, str]]:
    docs = []
    for path in bm25_file_paths(root):
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        relative_path = rel(root, path)
        title = first_heading(path)
        kind = record_kind(path)
        path_terms = split_identifier_text(relative_path)
        title_terms = split_identifier_text(title)
        weighted_text = "\n".join(
            [
                title,
                title_terms,
                title_terms,
                relative_path,
                path_terms,
                path_terms,
                kind,
                kind,
                raw,
            ]
        )
        docs.append(
            {
                "path": relative_path,
                "title": title,
                "kind": kind,
                "text": raw,
                "index_text": weighted_text,
            }
        )
    return docs


def load_bm25s():
    try:
        import bm25s  # type: ignore

        return bm25s
    except Exception as exc:
        raise SystemExit(
            "BM25S is unavailable. This skill vendors bm25s under scripts/vendor/bm25s; "
            f"import failed with: {exc}"
        ) from exc


def tokenize_texts(texts: list[str]):
    bm25s = load_bm25s()
    return bm25s.tokenize(
        texts,
        lower=True,
        token_pattern=TOKEN_PATTERN,
        stopwords=None,
        return_ids=False,
        show_progress=False,
    )


def query_variants(query: str) -> list[tuple[str, str, float]]:
    cleaned = query.strip()
    expanded = split_identifier_text(cleaned)
    lower = cleaned.lower()
    variants: list[tuple[str, str, float]] = [("original", cleaned, 1.0)]
    if expanded and expanded.lower() != cleaned.lower():
        variants.append(("identifier/path expansion", expanded, 0.9))

    intent_expansions = []
    if re.search(r"\b(why|reason|rationale|decision|decide|choice|tradeoff)\b|왜|이유|결정", lower):
        intent_expansions.append("why rationale context decision consequence tradeoff")
    if re.search(r"\b(idea|hypothesis|proposal|future|ablation)\b|아이디어|가설|제안", lower):
        intent_expansions.append("idea problem opportunity hypothesis expected value next check ablation")
    if re.search(r"\b(experiment|eval|evaluation|metric|result|analysis|figure)\b|실험|평가|분석|결과", lower):
        intent_expansions.append("experiment goal setup metrics results artifacts interpretation")
    if re.search(r"\b(code|file|change|implement|implementation|config|script)\b|코드|구현|파일|수정", lower):
        intent_expansions.append("change code file why how validation git status")
    if re.search(r"\b(handoff|collaboration|agent|owner|ownership)\b|협업|인수인계|에이전트", lower):
        intent_expansions.append("handoff summary ownership files next actions risks")

    for idx, expansion in enumerate(intent_expansions, 1):
        variants.append((f"intent expansion {idx}", f"{expanded or cleaned} {expansion}", 0.7))

    seen = set()
    deduped = []
    for label, text, weight in variants:
        key = re.sub(r"\s+", " ", text.lower()).strip()
        if key and key not in seen:
            deduped.append((label, text, weight))
            seen.add(key)
    return deduped


def best_excerpt(text: str, query_tokens: list[str], max_chars: int = 260) -> str:
    lowered_tokens = [token.lower() for token in query_tokens if token]
    fallback = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not fallback and not stripped.startswith("#"):
            fallback = stripped
        lowered = stripped.lower()
        if any(token in lowered for token in lowered_tokens):
            return stripped[:max_chars]
    return (fallback or first_nonempty_line(text) or "-")[:max_chars]


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def bm25_search(root: Path, query: str, limit: int = 8) -> dict:
    docs = bm25_documents(root)
    variants = query_variants(query)
    payload = {
        "query": query,
        "variants": variants,
        "results": [],
        "reflection": [],
    }
    if not docs:
        payload["reflection"].append("No history documents are available yet.")
        return payload
    if not variants:
        payload["reflection"].append("The query was empty after normalization.")
        return payload

    bm25s = load_bm25s()
    corpus_tokens = tokenize_texts([doc["index_text"] for doc in docs])
    retriever = bm25s.BM25(method="lucene", corpus=docs)
    retriever.index(corpus_tokens, show_progress=False)

    combined = [0.0 for _ in docs]
    contributing: list[list[str]] = [[] for _ in docs]
    all_query_tokens: list[str] = []
    original_query_tokens: list[str] = []
    for label, text, weight in variants:
        tokenized = tokenize_texts([text])
        tokens = tokenized[0] if tokenized else []
        if label == "original":
            original_query_tokens = list(tokens)
        all_query_tokens.extend(tokens)
        if not tokens:
            continue
        scores = retriever.get_scores(tokens)
        for idx, score in enumerate(scores):
            weighted = float(score) * weight
            if weighted > 0:
                combined[idx] += weighted
                contributing[idx].append(label)

    ranked = sorted(enumerate(combined), key=lambda item: item[1], reverse=True)
    vocab = set(getattr(retriever, "vocab_dict", {}).keys())
    query_counter = Counter(all_query_tokens)
    original_unknown = sorted([token for token in set(original_query_tokens) if token not in vocab])
    generated_unknown = sorted(
        [token for token in query_counter if token not in vocab and token not in original_unknown]
    )
    found_tokens = sorted([token for token in query_counter if token in vocab])

    results = []
    for idx, score in ranked[:limit]:
        if score <= 0:
            continue
        doc = docs[idx]
        results.append(
            {
                "score": score,
                "path": doc["path"],
                "title": doc["title"],
                "kind": doc["kind"],
                "variants": sorted(set(contributing[idx])),
                "excerpt": best_excerpt(doc["text"], found_tokens or all_query_tokens),
            }
        )

    payload["results"] = results
    payload["reflection"] = reflect_bm25_results(
        query, variants, results, original_unknown, generated_unknown
    )
    return payload


def reflect_bm25_results(
    query: str,
    variants: list[tuple[str, str, float]],
    results: list[dict],
    original_unknown: list[str],
    generated_unknown: list[str],
) -> list[str]:
    notes = []
    if not results:
        notes.append("No positive BM25 hit. Try exact file names, method names, dataset IDs, or record-type words such as decision, idea, change, experiment.")
    elif len(results) < 3:
        notes.append("Only a few records matched. Treat the recall as partial and verify current files before acting.")

    if original_unknown:
        preview = ", ".join(original_unknown[:8])
        notes.append(f"Some original query tokens were absent from the history index: {preview}.")
    elif generated_unknown:
        preview = ", ".join(generated_unknown[:8])
        notes.append(f"Some generated expansion tokens were absent from the history index: {preview}.")

    if results:
        kinds = Counter(result["kind"] for result in results)
        if len(kinds) == 1:
            only_kind = next(iter(kinds))
            notes.append(f"All top hits are `{only_kind}` records; consider a narrower query if you need decisions, ideas, experiments, or code changes specifically.")
        top_score = results[0]["score"]
        tail_score = results[-1]["score"]
        if top_score > 0 and tail_score / top_score < 0.15 and len(results) > 1:
            notes.append("The top hit is much stronger than the tail; read it first before broadening the search.")

    generated = [text for _, text, _ in variants[1:]]
    if generated:
        notes.append("Generated query variants were used; inspect them if the ranking feels off.")
    return notes


def print_bm25_payload(payload: dict, show_variants: bool = True) -> None:
    if show_variants:
        print("## Generated Queries")
        print("")
        for label, text, weight in payload["variants"]:
            print(f"- {label} (weight {weight:g}): {text}")
        print("")

    print("## BM25 Results")
    print("")
    if not payload["results"]:
        print("- none")
    for rank, result in enumerate(payload["results"], 1):
        variants = ", ".join(result["variants"]) if result["variants"] else "-"
        print(f"{rank}. `{result['path']}` - {result['title']}")
        print(f"   score={result['score']:.4f}; kind={result['kind']}; matched={variants}")
        print(f"   excerpt: {result['excerpt']}")
    print("")

    print("## Reflection")
    print("")
    if not payload["reflection"]:
        print("- BM25 recall found usable matches.")
    else:
        for note in payload["reflection"]:
            print(f"- {note}")


def cmd_bootstrap(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    if args.today:
        today_file(root)
    out = build_index(root)
    print(f"OK: {rel(root, out)}")


def cmd_today(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    path = today_file(root)
    build_index(root)
    print(rel(root, path))


def cmd_index(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    print(rel(root, build_index(root)))


def cmd_change(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    title = args.title
    filename = f"{time_stamp()}-{slugify(title, 'change')}.md"
    ensure_history(root)
    template = root / HISTORY_DIR / "templates" / "change.md"
    text = template.read_text(encoding="utf-8")
    text = (
        text.replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{agent}}", value(args.agent))
        .replace("{{status}}", value(args.status))
        .replace("{{why}}", value(args.why))
        .replace("{{how}}", value(args.how))
        .replace("{{files}}", bullets(args.file))
        .replace("{{validation}}", bullets(args.validation))
        .replace("{{risks}}", value(args.risk))
    )
    if not args.no_git_status:
        text += "\n## Git Status Snapshot\n\n```text\n" + git_status(root) + "\n```\n"
    write_record(root, "changes", filename, text, "change", title)


def cmd_decision(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "decisions"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'decision')}.md"
    text = (root / HISTORY_DIR / "templates" / "decision.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{context}}", value(args.context))
        .replace("{{decision}}", value(args.decision))
        .replace("{{rationale}}", value(args.rationale))
        .replace("{{consequences}}", value(args.consequence))
    )
    write_record(root, "decisions", filename, text, "decision", title)


def cmd_idea(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "ideas"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'idea')}.md"
    text = (root / HISTORY_DIR / "templates" / "idea.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{tags}}", ", ".join(args.tag or []) or "-")
        .replace("{{problem}}", value(args.problem))
        .replace("{{hypothesis}}", value(args.hypothesis))
        .replace("{{expected}}", value(args.expected))
        .replace("{{links}}", bullets(args.link))
        .replace("{{next}}", value(args.next))
    )
    write_record(root, "ideas", filename, text, "idea", title)


def cmd_experiment(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    folder = root / HISTORY_DIR / "experiments"
    rid = next_id(folder)
    title = args.title
    filename = f"{rid}-{slugify(title, 'experiment')}.md"
    text = (root / HISTORY_DIR / "templates" / "experiment.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{id}}", rid)
        .replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{status}}", value(args.status))
        .replace("{{tags}}", ", ".join(args.tag or []) or "-")
        .replace("{{goal}}", value(args.goal))
        .replace("{{setup}}", value(args.setup))
        .replace("{{metrics}}", bullets(args.metric))
        .replace("{{results}}", value(args.result))
        .replace("{{artifacts}}", bullets(args.artifact))
        .replace("{{next}}", value(args.next))
    )
    write_record(root, "experiments", filename, text, "experiment", title)


def cmd_handoff(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    title = args.title
    filename = f"{time_stamp()}-{slugify(title, 'handoff')}.md"
    text = (root / HISTORY_DIR / "templates" / "handoff.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{title}}", title)
        .replace("{{date}}", display_time())
        .replace("{{to}}", value(args.to))
        .replace("{{summary}}", value(args.summary))
        .replace("{{files}}", bullets(args.file))
        .replace("{{next}}", value(args.next))
        .replace("{{risks}}", value(args.risk))
    )
    write_record(root, "handoffs", filename, text, "handoff", title)


def format_bm25_read_first(payload: dict) -> str:
    if not payload["results"]:
        return "-"
    lines = []
    for rank, result in enumerate(payload["results"], 1):
        lines.append(
            f"{rank}. `{result['path']}` - {result['title']} "
            f"(kind={result['kind']}, score={result['score']:.4f})"
        )
        lines.append(f"   - {result['excerpt']}")
    return "\n".join(lines)


def format_generated_queries(payload: dict) -> str:
    if not payload["variants"]:
        return "-"
    return "\n".join(
        f"- {label} (weight {weight:g}): {text}"
        for label, text, weight in payload["variants"]
    )


def format_reflection(payload: dict) -> str:
    if not payload["reflection"]:
        return "- BM25 recall found usable matches."
    return "\n".join(f"- {note}" for note in payload["reflection"])


def latest_capsule(root: Path) -> Path | None:
    folder = root / HISTORY_DIR / "capsules"
    if not folder.exists():
        return None
    files = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def cmd_handoff_agent_capsule_create(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    task = args.task
    query = args.query or task
    payload = bm25_search(root, query, args.limit)
    context = root / HISTORY_DIR / "CONTEXT.md"
    project_context = clip(context.read_text(encoding="utf-8"), args.context_chars)
    filename = f"{time_stamp()}-{slugify(task, 'handoff-agent-capsule')}.md"
    template = root / HISTORY_DIR / "templates" / "handoff-agent-capsule.md"
    text = template.read_text(encoding="utf-8")
    text = (
        text.replace("{{task}}", task)
        .replace("{{date}}", display_time())
        .replace("{{from_agent}}", value(args.from_agent))
        .replace("{{to_agent}}", value(args.to_agent))
        .replace("{{target_host}}", value(args.target_host))
        .replace("{{status}}", value(args.status))
        .replace("{{requirements}}", bullets(args.user_requirement))
        .replace("{{current_state}}", value(args.current_state))
        .replace("{{reasoning_summary}}", value(args.reasoning_summary))
        .replace("{{files}}", bullets(args.file))
        .replace("{{validation}}", bullets(args.validation))
        .replace("{{risks}}", bullets(args.risk))
        .replace("{{next_actions}}", bullets(args.next_action))
        .replace("{{read_first}}", format_bm25_read_first(payload))
        .replace("{{generated_queries}}", format_generated_queries(payload))
        .replace("{{reflection}}", format_reflection(payload))
        .replace("{{project_context}}", project_context.rstrip())
        .replace("{{git_status}}", git_status(root))
    )
    write_record(root, "capsules", filename, text, "handoff-agent-capsule", task)


def cmd_handoff_agent_capsule_resume(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    capsule: Path | None = None
    if args.path:
        capsule = (root / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path).resolve()
    elif args.query:
        payload = bm25_search(root, args.query, max(args.limit, 5))
        for result in payload["results"]:
            candidate = root / result["path"]
            if record_kind(candidate) == "capsules":
                capsule = candidate
                break
        if capsule is None:
            capsule = latest_capsule(root)
    else:
        capsule = latest_capsule(root)

    if capsule is None or not capsule.exists():
        print("No handoff agent capsule found.")
        return

    print(f"# Resume From Handoff Agent Capsule")
    print("")
    print(f"Capsule: `{rel(root, capsule)}`")
    print("")
    text = capsule.read_text(encoding="utf-8")
    print(text.rstrip() if args.full else clip(text, args.chars).rstrip())

    if args.query:
        print("")
        print("## Additional BM25 Recall")
        print("")
        payload = bm25_search(root, args.query, args.limit)
        print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_handoff_agent_capsule_import(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    source = Path(args.file).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"Capsule file does not exist: {source}")
    title = args.title or first_heading(source).replace("Handoff Agent Capsule - ", "")
    filename = f"{time_stamp()}-{slugify(title, 'imported-handoff-agent-capsule')}.md"
    raw = source.read_text(encoding="utf-8")
    text = "\n".join(
        [
            f"# Imported Handoff Agent Capsule - {title}",
            "",
            f"Date Imported: {display_time()}",
            f"Source: {source}",
            f"Imported By: {value(args.agent)}",
            "",
            "## Imported Content",
            "",
            raw.rstrip(),
            "",
        ]
    )
    write_record(root, "capsules", filename, text, "handoff-agent-capsule-import", title)


def cmd_session(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    task = args.task
    agent = args.agent or "agent"
    filename = f"{time_stamp()}-{slugify(agent, 'agent')}-{slugify(task, 'session')}.md"
    text = (root / HISTORY_DIR / "templates" / "session.md").read_text(encoding="utf-8")
    text = (
        text.replace("{{task}}", task)
        .replace("{{date}}", display_time())
        .replace("{{agent}}", agent)
        .replace("{{scope}}", value(args.scope))
    )
    write_record(root, "sessions", filename, text, "session", task)


def iter_history_files(root: Path) -> list[Path]:
    history = root / HISTORY_DIR
    if not history.exists():
        return []
    files = [p for p in history.rglob("*.md") if "/templates/" not in p.as_posix()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def iter_search_files(root: Path) -> list[Path]:
    def rank(path: Path) -> tuple[int, float]:
        parent = path.parent.name
        if path.name == "CONTEXT.md":
            bucket = 0
        elif parent in {"changes", "decisions", "ideas", "experiments", "handoffs", "capsules", "sessions"}:
            bucket = 1
        elif parent == "daily":
            bucket = 2
        elif path.name in {"INDEX.md", "README.md"}:
            bucket = 3
        else:
            bucket = 4
        return (bucket, -path.stat().st_mtime)

    return sorted(iter_history_files(root), key=rank)


def clip(text: str, limit: int = 2800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]\n"


def search_lines(root: Path, query: str, limit: int) -> list[str]:
    results: list[str] = []
    needle = query.lower()
    for path in iter_search_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, 1):
            if needle in line.lower():
                snippet = line.strip()
                results.append(f"{rel(root, path)}:{idx}: {snippet}")
                if len(results) >= limit:
                    return results
    return results


def cmd_search(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    if args.exact:
        results = search_lines(root, args.query, args.limit)
        if not results:
            print("No matches.")
            return
        print("\n".join(results))
        return

    payload = bm25_search(root, args.query, args.limit)
    print_bm25_payload(payload, show_variants=not args.no_variants)


def cmd_exact(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    results = search_lines(root, args.query, args.limit)
    if not results:
        print("No matches.")
        return
    print("\n".join(results))


def cmd_recent(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    for path in iter_history_files(root)[: args.limit]:
        print(f"{rel(root, path)} - {first_heading(path)}")


def cmd_recall(args: argparse.Namespace) -> None:
    root = detect_root(args.root)
    ensure_history(root)
    today_file(root)
    build_index(root)

    print(f"# Recall ({root})")
    print("")
    context = root / HISTORY_DIR / "CONTEXT.md"
    print(f"## {rel(root, context)}")
    print("")
    print(clip(context.read_text(encoding="utf-8"), args.context_chars).rstrip())
    print("")

    latest_daily = sorted((root / HISTORY_DIR / "daily").glob("*.md"), reverse=True)
    if latest_daily:
        print(f"## Latest Daily: {rel(root, latest_daily[0])}")
        print("")
        print(clip(latest_daily[0].read_text(encoding="utf-8"), args.daily_chars).rstrip())
        print("")

    print("## Recent Records")
    print("")
    count = 0
    for path in iter_history_files(root):
        if path.name in {"CONTEXT.md", "INDEX.md", "README.md"} or "/daily/" in path.as_posix():
            continue
        print(f"- `{rel(root, path)}` - {first_heading(path)}")
        count += 1
        if count >= args.limit:
            break
    if count == 0:
        print("- none")
    print("")

    if args.query:
        print(f"## BM25 Recall: {args.query}")
        print("")
        payload = bm25_search(root, args.query, args.limit)
        print_bm25_payload(payload, show_variants=not args.no_variants)


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Repository root. Defaults to git root, then current directory.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain searchable research project history.")
    add_root(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="Create history/ structure and templates.")
    p.add_argument("--today", action="store_true", help="Also create today's daily log.")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("today", help="Create or print today's daily log path.")
    p.set_defaults(func=cmd_today)

    p = sub.add_parser("index", help="Rebuild history/INDEX.md.")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("change", help="Record a code or artifact change.")
    p.add_argument("--title", required=True)
    p.add_argument("--why")
    p.add_argument("--how")
    p.add_argument("--file", action="append")
    p.add_argument("--validation", action="append")
    p.add_argument("--risk")
    p.add_argument("--status", default="completed")
    p.add_argument("--agent", default="codex")
    p.add_argument("--no-git-status", action="store_true")
    p.set_defaults(func=cmd_change)

    p = sub.add_parser("decision", help="Record a durable decision.")
    p.add_argument("--title", required=True)
    p.add_argument("--context")
    p.add_argument("--decision")
    p.add_argument("--rationale")
    p.add_argument("--consequence")
    p.add_argument("--status", default="accepted")
    p.set_defaults(func=cmd_decision)

    p = sub.add_parser("idea", help="Record a research or implementation idea.")
    p.add_argument("--title", required=True)
    p.add_argument("--problem")
    p.add_argument("--hypothesis")
    p.add_argument("--expected")
    p.add_argument("--link", action="append")
    p.add_argument("--next")
    p.add_argument("--tag", action="append")
    p.add_argument("--status", default="open")
    p.set_defaults(func=cmd_idea)

    p = sub.add_parser("experiment", help="Record an experiment, analysis, or figure export.")
    p.add_argument("--title", required=True)
    p.add_argument("--goal")
    p.add_argument("--setup")
    p.add_argument("--metric", action="append")
    p.add_argument("--result")
    p.add_argument("--artifact", action="append")
    p.add_argument("--next")
    p.add_argument("--tag", action="append")
    p.add_argument("--status", default="recorded")
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("handoff", help="Record collaborator or agent handoff context.")
    p.add_argument("--title", required=True)
    p.add_argument("--to")
    p.add_argument("--summary")
    p.add_argument("--file", action="append")
    p.add_argument("--next")
    p.add_argument("--risk")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser(
        "handoff-agent-capsule",
        help="Create, import, or resume a cross-agent handoff context capsule.",
    )
    capsule_sub = p.add_subparsers(dest="capsule_command", required=True)

    cp = capsule_sub.add_parser("create", help="Create a handoff agent capsule for another agent, tool, or server.")
    cp.add_argument("--task", required=True)
    cp.add_argument("--query", help="BM25 recall query. Defaults to --task.")
    cp.add_argument("--from-agent", default="codex")
    cp.add_argument("--to-agent", default="agent")
    cp.add_argument("--target-host")
    cp.add_argument("--user-requirement", action="append")
    cp.add_argument("--current-state")
    cp.add_argument(
        "--reasoning-summary",
        help="Concise public decision-rationale summary. Do not store hidden chain-of-thought.",
    )
    cp.add_argument("--file", action="append")
    cp.add_argument("--validation", action="append")
    cp.add_argument("--risk", action="append")
    cp.add_argument("--next-action", action="append")
    cp.add_argument("--status", default="ready")
    cp.add_argument("--limit", type=int, default=8)
    cp.add_argument("--context-chars", type=int, default=2200)
    cp.set_defaults(func=cmd_handoff_agent_capsule_create)

    cp = capsule_sub.add_parser("resume", help="Print the latest or matching handoff agent capsule.")
    cp.add_argument("--query", help="BM25 query for selecting a capsule and adding recall context.")
    cp.add_argument("--path", help="Specific capsule path to read.")
    cp.add_argument("--limit", type=int, default=8)
    cp.add_argument("--chars", type=int, default=5000)
    cp.add_argument("--full", action="store_true")
    cp.add_argument("--no-variants", action="store_true", help="Hide generated query variants in added recall.")
    cp.set_defaults(func=cmd_handoff_agent_capsule_resume)

    cp = capsule_sub.add_parser("import", help="Import a capsule markdown file from another machine or tool.")
    cp.add_argument("--file", required=True)
    cp.add_argument("--title")
    cp.add_argument("--agent", default="agent")
    cp.set_defaults(func=cmd_handoff_agent_capsule_import)

    p = sub.add_parser("session", help="Create a working-session note.")
    p.add_argument("--task", required=True)
    p.add_argument("--scope")
    p.add_argument("--agent", default="codex")
    p.set_defaults(func=cmd_session)

    p = sub.add_parser("search", help="Search history markdown files with BM25S ranking.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true", help="Use exact substring matching instead of BM25S.")
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants.")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("exact", help="Exact substring search over history markdown files.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_exact)

    p = sub.add_parser("recent", help="List recent history records.")
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(func=cmd_recent)

    p = sub.add_parser("recall", help="Print context, latest daily log, recent records, and optional query hits.")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--context-chars", type=int, default=2800)
    p.add_argument("--daily-chars", type=int, default=1800)
    p.add_argument("--no-variants", action="store_true", help="Hide generated query variants in BM25 recall.")
    p.set_defaults(func=cmd_recall)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
