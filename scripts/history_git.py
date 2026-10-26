"""Read-only, ref-scoped file provenance using Git's own object database.

History text is read from the selected commit, never the current checkout. Exact
references and structural/path candidates stay distinct; none proves causality.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import selectors
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


MAX_COMMITS = 100
MAX_RECORDS = 2000
MAX_RECORD_BYTES = 256_000
MAX_TOTAL_RECORD_BYTES = 16_000_000
MAX_RELATIONS = 8
MAX_DIFF_CHARS = 8000
MAX_TITLE_CHARS = 240
MAX_RECORD_ID_CHARS = 256
MAX_STATUS_CHARS = 80


class GitTraceError(ValueError):
    """An invalid scope or a failed Git query, with no fallback to another ref."""


def _git(root: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "--literal-pathspecs", *args],
            input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitTraceError(f"Git provenance query failed: {exc}") from exc
    if proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GitTraceError(f"Git provenance query failed: {detail[:500]}")
    return proc.stdout


def _text(root: Path, *args: str) -> str:
    return _git(root, *args).decode("utf-8", "replace").strip()


def _path_text(root: Path, *args: str) -> str:
    """Git path outputs end in one newline; surrounding whitespace is data."""
    return _git(root, *args).decode("utf-8", "replace").removesuffix("\n")


def _display(text: str, limit: int) -> tuple[str, bool]:
    """Single-line display text, with explicit bounded control-character escapes."""
    escaped = "".join(
        {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(
            char, f"\\x{ord(char):02x}" if ord(char) < 32 or ord(char) == 127 else char,
        )
        for char in text
    )
    return escaped[:limit], len(escaped) > limit


def _git_bounded(root: Path, *args: str, max_bytes: int) -> tuple[bytes, bool]:
    """Stop Git once the output budget is exceeded, rather than buffering a patch."""
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    output = bytearray()
    truncated = False
    with tempfile.TemporaryFile() as stderr:
        try:
            proc = subprocess.Popen(
                ["git", "-C", str(root), "--literal-pathspecs", *args],
                stdout=subprocess.PIPE, stderr=stderr, env=env,
            )
        except OSError as exc:
            raise GitTraceError(f"Git provenance query failed: {exc}") from exc
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 30
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GitTraceError("Git provenance patch query timed out.")
                    if not selector.select(remaining):
                        raise GitTraceError("Git provenance patch query timed out.")
                    chunk = os.read(proc.stdout.fileno(), min(8192, max_bytes + 1 - len(output)))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > max_bytes:
                        truncated = True
                        proc.kill()
                        break
            proc.wait(timeout=5)
            if proc.returncode and not truncated:
                stderr.seek(0)
                detail = stderr.read(500).decode("utf-8", "replace").strip()
                raise GitTraceError(f"Git provenance patch query failed: {detail}")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stdout:
                proc.stdout.close()
    return bytes(output[:max_bytes]), truncated


def _resolve(root: Path, ref: str) -> str:
    try:
        return _text(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    except GitTraceError as exc:
        raise GitTraceError(f"Unknown or ambiguous commit ref: {ref}") from exc


def _path(root: Path, path: str) -> str:
    if not path or "\x00" in path:
        raise GitTraceError("A non-empty repository-relative file path is required.")
    if os.path.isabs(path):
        path = os.path.relpath(path, root)
    path = posixpath.normpath(path)
    if path in {".", ".."} or path.startswith("../"):
        raise GitTraceError("File path must be inside the selected repository.")
    if any(part == "runtime.env" for part in path.split("/")):
        raise GitTraceError("runtime.env is local-only and cannot be inspected.")
    return path


def _changed_paths(root: Path, sha: str) -> tuple[set[str], list[tuple[str, str]], list[dict]]:
    parents = _text(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    paths: set[str] = set()
    renames: list[tuple[str, str]] = []
    comparisons = []
    for parent in parents or [None]:
        revisions = [parent, sha] if parent else [sha]
        raw = _git(root, "diff-tree", "--root", "--no-commit-id", "--name-status", "-r", "-M", "-z", *revisions)
        fields = raw.decode("utf-8", "replace").split("\x00")
        parent_paths: set[str] = set()
        idx = 0
        while idx < len(fields) and fields[idx]:
            status = fields[idx]
            idx += 1
            count = 2 if status.startswith(("R", "C")) else 1
            names = fields[idx:idx + count]
            idx += count
            parent_paths.update(names)
            if status.startswith("R") and len(names) == 2:
                renames.append((names[0], names[1]))
        paths.update(parent_paths)
        comparisons.append({"parent": parent, "paths": parent_paths})
    return paths, renames, comparisons


def _records(root: Path, ref: str, history: Any) -> tuple[list[dict], list[str]]:
    raw = _git(root, "ls-tree", "-rlz", ref, "--", "history/", "history-archive/")
    entries: list[tuple[str, str, int]] = []
    warnings: list[str] = []
    total = 0
    for item in raw.split(b"\x00"):
        if not item:
            continue
        header, name_bytes = item.split(b"\t", 1)
        mode, kind, oid, size = header.split()
        name = name_bytes.decode("utf-8", "replace")
        parts = name.split("/")
        if (kind != b"blob" or mode == b"120000" or not name.endswith(".md")
                or "templates" in parts or any(part.startswith(".") for part in parts)
                or parts[-1] in {"INDEX.md", "PROJECT_MAP.md", "README.md"}):
            continue
        length = int(size)
        if length > MAX_RECORD_BYTES or total + length > MAX_TOTAL_RECORD_BYTES or len(entries) >= MAX_RECORDS:
            warnings.append("record_scan_truncated")
            continue
        entries.append((name, oid.decode(), length))
        total += length
    if not entries:
        return [], sorted(set(warnings))
    objects = list(dict.fromkeys(oid for _, oid, _ in entries))
    data = _git(root, "cat-file", "--batch", input_bytes=("\n".join(objects) + "\n").encode())
    contents: dict[str, str] = {}
    cursor = 0
    for _ in objects:
        end = data.index(b"\n", cursor)
        oid, kind, size = data[cursor:end].split()
        cursor = end + 1
        length = int(size)
        contents[oid.decode()] = data[cursor:cursor + length].decode("utf-8", "replace")
        cursor += length + 1
    records = []
    for name, oid, _ in entries:
        text = contents[oid]
        meta = history.parse_metadata(text)
        heading = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), name)
        kind = str(meta.get("type") or Path(name).parent.name)
        record_id = meta.get("record id") or history.compose_record_id(kind, Path(name).stem)
        commit_text = meta.get("commits", "") + "\n" + history.extract_section(text, "Commits")
        commits = list(dict.fromkeys(re.findall(r"\b[0-9a-fA-F]{7,40}\b", commit_text)))
        records.append({"path": name, "record_id": record_id, "title": heading,
                        "status": meta.get("status") or meta.get("approval status") or "unknown",
                        "date": meta.get("date", ""), "text": text, "commit_refs": commits})
    return records, sorted(set(warnings))


def _evidence(record: dict, relation: str, ref: str, *, needle: str | None = None,
              source: str = "record", commit_line: int | None = None) -> dict:
    text = record["text"]
    lines = text.splitlines()
    offset = text.find(needle) if needle else -1
    number = text.count("\n", 0, offset) + 1 if offset >= 0 else 1
    # Prefer the explanatory body over frontmatter and repeated metadata.
    if not needle:
        in_body = False
        for idx, line in enumerate(lines, 1):
            if line.startswith("## "):
                in_body = True
            elif in_body and line.strip() not in {"", "-", "```"} and not line.startswith("#"):
                number = idx
                break
    if offset >= 0:
        # A literal filename can contain a newline. Keep the complete match in the
        # excerpt and calculate its source line before escaping display controls.
        excerpt_start = max(text.rfind("\n", 0, offset) + 1, offset - 80)
        excerpt_end = text.find("\n", offset + len(needle))
        excerpt = text[excerpt_start:excerpt_end if excerpt_end >= 0 else len(text)]
    else:
        excerpt = lines[number - 1] if lines else ""
    fields = {"path": record["path"]}
    truncated = []
    for key, limit in (("record_id", MAX_RECORD_ID_CHARS), ("title", MAX_TITLE_CHARS),
                       ("status", MAX_STATUS_CHARS), ("excerpt", 360)):
        fields[key], clipped = _display(excerpt if key == "excerpt" else record[key], limit)
        if clipped:
            truncated.append(key)
    return fields | {
        "relation": relation, "record_ref": ref, "source": source,
        "line": number, "display_truncated": truncated,
        **({"commit_message_line": commit_line} if commit_line else {}),
    }


def _dirty(root: Path, path: str) -> list[dict]:
    fields = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", path).decode("utf-8", "replace").split("\x00")
    result = []
    idx = 0
    while idx < len(fields) and fields[idx]:
        item = fields[idx]
        idx += 1
        entry = {"index_status": item[0], "worktree_status": item[1], "path": item[3:]}
        if item[0] in "RC" or item[1] in "RC":
            if idx < len(fields):
                entry["original_path"] = fields[idx]
                idx += 1
        result.append(entry)
    return result


def file_provenance(root: Path, path: str, history: Any, *, ref: str = "HEAD",
                    limit: int = 12, follow: bool = False, diff: bool = False) -> dict:
    if not 1 <= limit <= MAX_COMMITS:
        raise GitTraceError(f"--limit must be between 1 and {MAX_COMMITS}.")
    root = Path(_path_text(root, "rev-parse", "--show-toplevel"))
    path = _path(root, path)
    sha = _resolve(root, ref)
    worktree_head = _resolve(root, "HEAD")
    tree_entry = _git(root, "ls-tree", "-z", sha, "--", path)
    if tree_entry and tree_entry.split(b"\t", 1)[0].split()[1] != b"blob":
        raise GitTraceError("--file must select one file, not a directory.")
    log_args = ["log", f"-{limit + 1}", "--format=%H"]
    if follow:
        log_args.append("--follow")
    hashes = _text(root, *log_args, sha, "--", path).splitlines()
    if not hashes:
        raise GitTraceError(f"No file history for {path!r} in ref {ref!r}.")
    warnings = []
    if len(hashes) > limit:
        warnings.append("commit_history_truncated")
    hashes = hashes[:limit]
    aliases = {path}
    safety_aliases = {path}
    changes = {}
    for commit in hashes:
        paths, renames, comparisons = _changed_paths(root, commit)
        changes[commit] = {"paths": paths, "comparisons": comparisons}
        for old, new in renames:
            if new in safety_aliases or old in safety_aliases:
                safety_aliases.update((old, new))
                if follow:
                    aliases.add(old)
    if diff:
        # A rename patch can read its old source even without --follow. Validate
        # every connected historical name before executing any content query.
        for alias in safety_aliases:
            _path(root, alias)
    records, record_warnings = _records(root, sha, history)
    warnings.extend(record_warnings)
    by_id = {record["record_id"]: record for record in records}
    by_path = {record["path"]: record for record in records}
    commits = []
    for commit in hashes:
        raw_meta = _git(root, "show", "-s", "--format=%H%x00%P%x00%aI%x00%s%x00%B", commit).decode("utf-8", "replace")
        full_sha, parents, when, subject, body = raw_meta.split("\x00", 4)
        relations: dict[str, dict] = {}
        for record in records:
            matched = next((item for item in record["commit_refs"] if full_sha.startswith(item.lower())), None)
            if matched:
                # Verify short references resolve uniquely; prefix text alone is not pairing proof.
                try:
                    resolved = _resolve(root, matched)
                except GitTraceError:
                    continue
                if resolved == full_sha:
                    relations[record["path"]] = _evidence(record, "explicit", sha, needle=matched, source="record-commits")
            elif record["path"] in changes[commit]["paths"]:
                same_parent = [comparison["parent"] for comparison in changes[commit]["comparisons"]
                               if record["path"] in comparison["paths"]
                               and any(alias in comparison["paths"] for alias in aliases)]
                if same_parent:
                    evidence = _evidence(record, "co-change", sha, source="same-commit-paths")
                    evidence["comparison_parents"] = same_parent
                    relations[record["path"]] = evidence
        unresolved = []
        unresolved_id_truncated = False
        for idx, line in enumerate(body.splitlines(), 1):
            match = re.match(r"^History-Record:\s*(\S+)\s*$", line, re.IGNORECASE)
            if not match:
                continue
            record = by_id.get(match.group(1))
            if record:
                relations[record["path"]] = _evidence(record, "explicit", sha, source="commit-trailer", commit_line=idx)
            else:
                display_id, clipped = _display(match.group(1), MAX_RECORD_ID_CHARS)
                unresolved.append(display_id)
                unresolved_id_truncated = unresolved_id_truncated or clipped
        ranked = sorted(relations.values(), key=lambda entry: (
            entry["relation"] != "explicit", not entry["path"].startswith("history/"), entry["path"],
        ))
        # A long-term archive stub and its full text can carry the same identity.
        seen_records = set()
        unique_relations = []
        for entry in ranked:
            identity = by_path[entry["path"]]["record_id"]
            if identity not in seen_records:
                unique_relations.append(entry)
                seen_records.add(identity)
        ranked = unique_relations
        display_subject, subject_truncated = _display(subject, MAX_TITLE_CHARS)
        result = {"sha": full_sha, "parents": parents.split(), "date": when,
                  "subject": display_subject, "subject_truncated": subject_truncated, "ancestor_of_ref": True,
                  "change_comparison": "each-parent" if parents else "empty-tree",
                  "records": ranked[:MAX_RELATIONS], "records_truncated": len(ranked) > MAX_RELATIONS,
                  "unresolved_record_ids": unresolved[:MAX_RELATIONS],
                  "unresolved_record_ids_truncated": unresolved_id_truncated or len(unresolved) > MAX_RELATIONS}
        if diff:
            raw_patch, patch_truncated = _git_bounded(
                root, "show", "-m", "--format=", "--no-ext-diff", "--no-textconv", "--find-renames", "--unified=3", commit, "--", *sorted(aliases),
                max_bytes=MAX_DIFF_CHARS * 4,
            )
            patch = raw_patch.decode("utf-8", "replace")
            result["diff"] = patch[:MAX_DIFF_CHARS]
            result["diff_truncated"] = patch_truncated or len(patch) > MAX_DIFF_CHARS
        commits.append(result)
    candidates = []
    candidate_ids = set()
    for record in sorted(records, key=lambda item: (item["date"], item["path"]), reverse=True):
        matched = next((name for name in sorted(aliases) if re.search(r"(?<![\w./-])" + re.escape(name) + r"(?![\w./-])", record["text"])), None)
        if matched and record["record_id"] not in candidate_ids:
            candidates.append(_evidence(record, "path-candidate", sha, needle=matched, source="literal-path-mention"))
            candidate_ids.add(record["record_id"])
    if len(candidates) > MAX_RELATIONS:
        warnings.append("path_candidates_truncated")
    common = _path_text(root, "rev-parse", "--git-common-dir")
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = root / common_path
    return {"repository": str(root), "common_git_dir": str(common_path.resolve()),
            "ref": ref, "resolved_ref": sha, "worktree_head": worktree_head,
            "worktree_branch": _text(root, "branch", "--show-current") or None,
            "file": path, "file_present_at_ref": bool(tree_entry), "follow": follow, "aliases": sorted(aliases),
            "commits": commits, "path_candidates": candidates[:MAX_RELATIONS],
            "worktree_changes": _dirty(root, path), "diagnostics": sorted(set(warnings)),
            "notes": ["Records are read from the selected ref, not the working tree.",
                      "Co-change and path-candidate evidence does not establish why a commit was made.",
                      "Co-change compares file and record paths against the same parent; merge comparisons are per-parent.",
                      "Ancestry does not imply current effect: a later revert may undo a change.",
                      "Rename following is Git's heuristic; merge history may be simplified. Squashed/cherry-picked commits are not equated."]}


def print_file_provenance(payload: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("# File Provenance\n")
    print(f"Repository: {payload['repository']}")
    print(f"Common Git Directory: {payload['common_git_dir']}")
    print(f"Ref: {payload['ref']} -> {payload['resolved_ref']}")
    print(f"Worktree HEAD: {payload['worktree_head']} ({payload['worktree_branch'] or 'detached'})")
    print(f"File: {payload['file']}\n")
    if not payload["file_present_at_ref"]:
        print("File is absent at selected ref; tracing its recorded history.\n")
    if len(payload["aliases"]) > 1:
        print(f"Historical path aliases: {', '.join(payload['aliases'])}\n")
    for commit in payload["commits"]:
        print(f"- {commit['sha']} {commit['date']} {commit['subject']}")
        if commit["subject_truncated"]:
            print("  subject truncated")
        print(f"  parents: {', '.join(commit['parents']) or '(root)'}; ancestor_of_ref=yes")
        for record in commit["records"]:
            print(f"  [{record['relation']}] {record['path']}:{record['line']} — {record['excerpt']}")
            if record["display_truncated"]:
                print(f"  display truncated: {', '.join(record['display_truncated'])}")
            if record.get("comparison_parents"):
                print(f"  comparison parents: {', '.join(parent or '(empty tree)' for parent in record['comparison_parents'])}")
        if not commit["records"]:
            print("  no explicit or co-change record in selected ref")
        for record_id in commit["unresolved_record_ids"]:
            print(f"  trailer record absent from selected ref: {record_id}")
        if commit["unresolved_record_ids_truncated"]:
            print("  unresolved record identities truncated")
        if commit["records_truncated"]:
            print("  related records truncated")
        if "diff" in commit:
            print("\n```diff\n" + commit["diff"] + "\n```\n")
            if commit["diff_truncated"]:
                print("  diff truncated")
    print("\n## File-level candidates (not attributed to an individual commit)\n")
    for record in payload["path_candidates"]:
        print(f"- [path-candidate] {record['path']}:{record['line']} — {record['excerpt']}")
        if record["display_truncated"]:
            print(f"  display truncated: {', '.join(record['display_truncated'])}")
    if not payload["path_candidates"]:
        print("- none")
    print("\n## Current working tree (separate from selected ref)\n")
    for entry in payload["worktree_changes"]:
        print(f"- {entry['index_status']}{entry['worktree_status']} {entry['path']}")
    if not payload["worktree_changes"]:
        print("- no changes for this path")
    for note in payload["notes"]:
        print(f"- {note}")
    for diagnostic in payload["diagnostics"]:
        print(f"- diagnostic: {diagnostic}")
