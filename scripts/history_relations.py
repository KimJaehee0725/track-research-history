"""Attach explicit record corrections as context, without inventing search hits."""
from __future__ import annotations

from collections import defaultdict, deque

PREFIXES = {"changes": "chg", "change": "chg", "decisions": "dec", "decision": "dec", "ideas": "idea", "idea": "idea", "experiments": "exp", "experiment": "exp", "capsules": "cap", "handoffs": "hnd", "sessions": "ses"}


def _identity(doc: dict) -> str:
    stem = doc["path"].rsplit("/", 1)[-1].removesuffix(".md")
    return doc.get("record_id") or PREFIXES.get(doc.get("kind", ""), "rec") + "-" + stem


def _snippet(chunks: list[dict]) -> tuple[str, int]:
    ordered = sorted(chunks, key=lambda doc: (doc.get("heading", "").lower() not in {"decision", "results", "risks / follow-ups"}, int(doc.get("line_start", 1))))
    for doc in ordered:
        for offset, line in enumerate(doc.get("text", "").splitlines()):
            if line.strip() and not line.lstrip().startswith(("#", "---", "```")):
                return line.strip()[:240], int(doc.get("line_start", 1)) + offset
    return "Open this related record for its scope and evidence.", 1


def attach_relations(payload: dict, all_docs: list[dict], scoped_paths: set[str], *, max_related: int = 4) -> dict:
    by_path: dict[str, list[dict]] = defaultdict(list)
    by_id: dict[str, set[str]] = defaultdict(set)
    for doc in all_docs:
        by_path[doc["path"]].append(doc)
        by_id[_identity(doc)].add(doc["path"])
    edges: dict[str, set[tuple[str, str]]] = defaultdict(set)
    inverse = {"corrects": "corrected_by", "supersedes": "superseded_by", "superseded_by": "supersedes"}
    for path, chunks in by_path.items():
        doc = chunks[0]
        for relation, reverse in inverse.items():
            for target in str(doc.get(relation, "")).split(","):
                target = target.strip()
                targets = {target} if target in by_path else by_id.get(target, set())
                active_targets = {candidate for candidate in targets if candidate.startswith("history/")}
                if len(active_targets) == 1:
                    targets = active_targets  # Prefer a live stub over its archived full text.
                if len(targets) == 1:
                    target_path = next(iter(targets))
                    if target_path != path:
                        edges[path].add((target_path, relation))
                        edges[target_path].add((path, reverse))
    has_correction = False
    truncated = False
    for hit in payload.get("results", []):
        related = []
        seen = {hit["path"]}
        queue = deque([(hit["path"], 0)])
        while queue:
            origin, depth = queue.popleft()
            if depth >= 2:
                continue
            for path, relation in sorted(edges.get(origin, [])):
                if path in seen:
                    continue
                seen.add(path)
                if len(related) >= max_related:
                    truncated = True
                    continue
                chunks = by_path[path]
                doc = chunks[0]
                excerpt, line = _snippet(chunks)
                related.append({"path": path, "record_id": _identity(doc), "relation": relation,
                                "via": origin, "status": doc.get("status", doc.get("approval", "unknown")),
                                "line": line, "excerpt": excerpt,
                                "outside_filters": path not in scoped_paths,
                                "source": "explicit-record-relation"})
                has_correction |= relation in {"corrected_by", "superseded_by"}
                queue.append((path, depth + 1))
        hit["related_records"] = related
    if has_correction:
        note = {"code": "related_correction", "message": "Matched records have explicit incoming correction/replacement links; read that context before relying on the old statement."}
        payload.setdefault("diagnostics", []).append(note)
        payload.setdefault("reflection", []).append(note["message"])
    if truncated:
        note = {"code": "relations_truncated", "message": "Related-record budget reached; inspect explicit links for further corrections."}
        payload.setdefault("diagnostics", []).append(note)
        payload.setdefault("reflection", []).append(note["message"])
    return payload
