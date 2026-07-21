#!/usr/bin/env python3
"""Restricted JSON-lines RPC endpoint for an SSH ``command=`` key.

``sshd`` runs this process as the forced command; the program deliberately
ignores ``SSH_ORIGINAL_COMMAND`` and never invokes a shell or a subprocess.
Each input line must be one JSON object and produces one JSON object on stdout.
Policy is fixed by the forced-command arguments in ``authorized_keys``, not by
the client request.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Iterable, Mapping


# A direct-file invocation (the most robust form for ``authorized_keys``)
# needs the repository's ``src`` package on sys.path.  This is a known static
# installation location derived from this file, not a client-controlled path.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from research_memory.store import MemoryStore


DEFAULT_DATA_DIR = "/srv/research-memory"
# memctl permits a 5 MiB Markdown body; leave room for the JSON envelope.
MAX_REQUEST_BYTES = 6 * 1_024 * 1_024
PROJECT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

READ_OPERATIONS = {
    "ping",
    "list_projects",
    "get_project",
    "list_notes",
    "get_note",
    "search",
}
WRITE_OPERATIONS = {
    "create_project",
    "delete_project",
    "restore_project",
    "create_note",
    "update_note",
    "upsert_note",
    "delete_note",
    "restore_note",
}
ALL_OPERATIONS = READ_OPERATIONS | WRITE_OPERATIONS


class RpcError(Exception):
    """An expected request failure that can be safely sent to the client."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve project-scoped Research Memory JSON-lines RPC over SSH.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("MEMORY_DATA_DIR", DEFAULT_DATA_DIR),
        help="MemoryStore data root. The forced command should set this explicitly.",
    )
    parser.add_argument(
        "--allow-project",
        action="append",
        default=[],
        metavar="PROJECT_ID",
        help="Permit this project. Repeat only in a server-owned forced command.",
    )
    parser.add_argument(
        "--allow-all-projects",
        action="store_true",
        help="Allow all projects. Use only for a local administrative key.",
    )
    parser.add_argument(
        "--permission",
        choices=("read", "write"),
        default="read",
        help="The maximum mutation permission for this key.",
    )
    parser.add_argument(
        "--actor",
        default="ssh-rpc",
        help="Server-owned audit identity for this forced command.",
    )
    parser.add_argument(
        "--max-request-bytes",
        type=int,
        default=MAX_REQUEST_BYTES,
        help="Maximum accepted bytes per JSON line.",
    )
    args = parser.parse_args(argv)
    if args.max_request_bytes < 1:
        parser.error("--max-request-bytes must be positive")
    if args.allow_all_projects and args.allow_project:
        parser.error("use either --allow-all-projects or --allow-project, not both")
    if not args.allow_all_projects and not args.allow_project:
        parser.error("at least one --allow-project is required")
    invalid_projects = [
        project for project in args.allow_project if not PROJECT_ID_RE.fullmatch(project)
    ]
    if invalid_projects:
        parser.error("--allow-project values must be stable project IDs")
    if not args.actor.strip() or any(character in args.actor for character in "\r\n\x00"):
        parser.error("--actor must be a non-empty single-line identifier")
    args.actor = args.actor.strip()
    return args


def _record_value(record: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(record, Mapping) and name in record:
            return record[name]
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _project_id(record: Any) -> str:
    return str(_record_value(record, "project_id", "id", "slug", default=""))


def _json_value(value: Any) -> Any:
    """Convert store records to deterministic, JSON-safe protocol output."""

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_value(to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _bool(request: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = request.get(name, default)
    if not isinstance(value, bool):
        raise RpcError("invalid_request", f"{name} must be a boolean")
    return value


def _text(
    request: Mapping[str, Any],
    name: str,
    *,
    required: bool = True,
    strip: bool = True,
) -> str | None:
    value = request.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise RpcError("invalid_request", f"{name} must be a string")
    checked = value.strip() if strip else value
    if required and not checked:
        raise RpcError("invalid_request", f"{name} is required")
    return checked if strip else value


def _requested_project(request: Mapping[str, Any]) -> str:
    project_id = _text(request, "project_id")
    assert project_id is not None
    return project_id


def _require_project(policy: argparse.Namespace, project_id: str) -> None:
    if not policy.allow_all_projects and project_id not in set(policy.allow_project):
        raise RpcError("forbidden", "This SSH key is not allowed to access that project")


def _require_write(policy: argparse.Namespace, operation: str) -> None:
    if operation in WRITE_OPERATIONS and policy.permission != "write":
        raise RpcError("forbidden", "This SSH key has read-only permission")


def _store_call(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return callable_(*args, **kwargs)
    except RpcError:
        raise
    except (KeyError, LookupError) as exc:
        raise RpcError("not_found", "The requested memory record was not found") from exc
    except ValueError as exc:
        raise RpcError("invalid_request", str(exc) or "Invalid memory request") from exc
    except Exception as exc:
        name = exc.__class__.__name__.lower()
        if "notfound" in name or "not_found" in name:
            raise RpcError("not_found", "The requested memory record was not found") from exc
        if "conflict" in name or "revision" in name:
            raise RpcError("conflict", "The record changed elsewhere; read it and retry") from exc
        if "alreadyexists" in name or "already_exists" in name:
            raise RpcError("conflict", "A record with that ID already exists") from exc
        if "validation" in name:
            raise RpcError("invalid_request", str(exc) or "Invalid memory request") from exc
        # Do not disclose server paths, implementation types, or tracebacks to
        # an untrusted SSH client.
        raise RpcError("store_error", "The memory store could not complete this request") from exc


def _filter_projects(policy: argparse.Namespace, projects: Iterable[Any]) -> list[Any]:
    if policy.allow_all_projects:
        return list(projects)
    allowed = set(policy.allow_project)
    return [project for project in projects if _project_id(project) in allowed]


def _limit(request: Mapping[str, Any], name: str, default: int) -> int:
    value = request.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise RpcError("invalid_request", f"{name} must be an integer between 1 and 1000")
    return value


def _note_title(note_id: str, body: str) -> str:
    """Provide a stable title for protocol writes that only carry Markdown."""

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and stripped[2:].strip():
            return stripped[2:].strip()[:256]
    stem = PurePosixPath(note_id).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:256] or "Untitled note"


def _normal_text(params: Mapping[str, Any], name: str, *, required: bool = True) -> str | None:
    """Read a protocol parameter without allowing it to alter top-level scope."""

    return _text(params, name, required=required)


def _param_bool(params: Mapping[str, Any], name: str, default: bool = False) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise RpcError("invalid_request", f"params.{name} must be a boolean")
    return value


def normalize_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize protocol-v1 envelopes to the internal, explicit dispatch form.

    The public wire contract is ``{version, op, project, params}``.  The
    older flat vocabulary remains accepted for a transition period, but no
    client-controlled method names or keyword dictionaries are ever forwarded
    to :class:`MemoryStore`.
    """

    operation = request.get("op")
    if not isinstance(operation, str):
        raise RpcError("invalid_request", "op must be a string")

    # Keep the original RPC vocabulary usable for local diagnostics.  Client
    # traffic is identified by its protocol version or dotted operation name.
    if "version" not in request and "." not in operation:
        return dict(request)

    version = request.get("version")
    if version != 1:
        raise RpcError("unsupported_version", "version must be 1")
    params = request.get("params", {})
    if not isinstance(params, Mapping):
        raise RpcError("invalid_request", "params must be an object")

    project = request.get("project")
    if operation != "project.list":
        if not isinstance(project, str) or not project.strip():
            raise RpcError("invalid_request", "project must be a non-empty string")
        project = project.strip()
    elif project is not None:
        raise RpcError("invalid_request", "project.list does not accept project")

    if operation == "project.list":
        return {"op": "list_projects", "include_deleted": _param_bool(params, "include_deleted")}
    if operation == "project.init":
        enable_git = params.get("enable_git")
        if enable_git is not None and not isinstance(enable_git, bool):
            raise RpcError("invalid_request", "enable_git must be a boolean")
        return {
            "op": "create_project",
            "project_id": project,
            "title": _normal_text(params, "title", required=False),
            # Core metadata owns any optional description handling.  Keeping
            # this field in the normalized form avoids interpreting it as a
            # callable or a filesystem path in the transport layer.
            "description": _normal_text(params, "description", required=False),
            "enable_git": enable_git,
        }
    if operation == "note.list":
        return {
            "op": "list_notes",
            "project_id": project,
            "prefix": _normal_text(params, "prefix", required=False),
            "limit": _limit(params, "limit", 100),
            "include_deleted": _param_bool(params, "include_deleted"),
        }
    if operation == "note.read":
        return {
            "op": "get_note",
            "project_id": project,
            "note_id": _normal_text(params, "path"),
            "include_deleted": _param_bool(params, "include_deleted"),
        }
    if operation == "note.write":
        content = params.get("content")
        if not isinstance(content, str) or "\x00" in content:
            raise RpcError("invalid_request", "content must be a NUL-free string")
        expected_revision = params.get("if_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "if_revision must be a string or integer")
        return {
            "op": "upsert_note",
            "project_id": project,
            "note_id": _normal_text(params, "path"),
            "body": content,
            "title": _normal_text(params, "title", required=False),
            "expected_revision": expected_revision,
        }
    if operation == "note.delete":
        expected_revision = params.get("if_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "if_revision must be a string or integer")
        return {
            "op": "delete_note",
            "project_id": project,
            "note_id": _normal_text(params, "path"),
            "expected_revision": expected_revision,
        }
    if operation == "note.restore":
        expected_revision = params.get("if_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "if_revision must be a string or integer")
        return {
            "op": "restore_note",
            "project_id": project,
            "trash_id": _normal_text(params, "trash_id"),
            "expected_revision": expected_revision,
        }
    if operation == "note.search":
        return {
            "op": "search",
            "project_id": project,
            "query": _normal_text(params, "query"),
            "limit": _limit(params, "limit", 20),
            "include_deleted": _param_bool(params, "include_deleted"),
        }
    raise RpcError("invalid_request", "op must name a supported protocol operation")


def dispatch(store: MemoryStore, policy: argparse.Namespace, request: Mapping[str, Any]) -> Any:
    """Run one explicitly-whitelisted operation against ``MemoryStore``."""

    request = normalize_request(request)
    operation = request.get("op")
    if not isinstance(operation, str) or operation not in ALL_OPERATIONS:
        raise RpcError("invalid_request", "op must name a supported operation")
    _require_write(policy, operation)

    if operation == "ping":
        return {"service": "research-memory-rpc", "permission": policy.permission}

    if operation == "list_projects":
        projects = _store_call(
            store.list_projects,
            include_deleted=_bool(request, "include_deleted"),
        )
        return _filter_projects(policy, projects)

    project_id = _requested_project(request)
    _require_project(policy, project_id)

    if operation == "get_project":
        return _store_call(
            store.get_project,
            project_id,
            include_deleted=_bool(request, "include_deleted"),
        )

    if operation == "create_project":
        title = _text(request, "title", required=False)
        description = _text(request, "description", required=False)
        enable_git = request.get("enable_git")
        if enable_git is not None and not isinstance(enable_git, bool):
            raise RpcError("invalid_request", "enable_git must be a boolean")
        kwargs: dict[str, Any] = {"title": title}
        if description is not None:
            kwargs["description"] = description
        if enable_git is not None:
            kwargs["enable_git"] = enable_git
        return _store_call(store.create_project, project_id, **kwargs)

    if operation == "delete_project":
        confirmation = _text(request, "confirmation")
        if confirmation != project_id:
            raise RpcError("invalid_request", "confirmation must exactly match project_id")
        return _store_call(store.delete_project, project_id)

    if operation == "restore_project":
        return _store_call(store.restore_project, project_id)

    if operation == "list_notes":
        notes = _store_call(
            store.list_notes,
            project_id,
            include_deleted=_bool(request, "include_deleted"),
        )
        prefix = _text(request, "prefix", required=False)
        if prefix:
            notes = [
                note
                for note in notes
                if str(_record_value(note, "id", "note_id", default="")).startswith(prefix)
            ]
        return list(notes)[: _limit(request, "limit", 100)]

    if operation == "get_note":
        note_id = _text(request, "note_id")
        assert note_id is not None
        return _store_call(
            store.get_note,
            project_id,
            note_id,
            include_deleted=_bool(request, "include_deleted"),
        )

    if operation == "create_note":
        note_id = _text(request, "note_id")
        title = _text(request, "title")
        body = _text(request, "body", required=False, strip=False) or ""
        assert note_id is not None and title is not None
        return _store_call(store.create_note, project_id, note_id, title, body)

    if operation == "update_note":
        note_id = _text(request, "note_id")
        title = _text(request, "title")
        body = _text(request, "body", required=False, strip=False) or ""
        expected_revision = request.get("expected_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "expected_revision must be a string or integer")
        assert note_id is not None and title is not None
        return _store_call(
            store.update_note,
            project_id,
            note_id,
            title=title,
            body=body,
            expected_revision=expected_revision,
        )

    if operation == "delete_note":
        note_id = _text(request, "note_id")
        assert note_id is not None
        expected_revision = request.get("expected_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "expected_revision must be a string or integer")
        return _store_call(
            store.delete_note,
            project_id,
            note_id,
            expected_revision=expected_revision,
        )

    if operation == "restore_note":
        expected_revision = request.get("expected_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "expected_revision must be a string or integer")
        trash_id = _text(request, "trash_id", required=False)
        if trash_id is not None:
            return _store_call(
                store.restore_note,
                project_id,
                trash_id=trash_id,
                expected_revision=expected_revision,
            )
        note_id = _text(request, "note_id")
        assert note_id is not None
        return _store_call(
            store.restore_note,
            project_id,
            note_id,
            expected_revision=expected_revision,
        )

    if operation == "upsert_note":
        note_id = _text(request, "note_id")
        body = _text(request, "body", required=False, strip=False) or ""
        requested_title = _text(request, "title", required=False)
        expected_revision = request.get("expected_revision")
        if expected_revision is not None and not isinstance(expected_revision, (str, int)):
            raise RpcError("invalid_request", "expected_revision must be a string or integer")
        assert note_id is not None
        try:
            existing = _store_call(store.get_note, project_id, note_id)
        except RpcError as exc:
            if exc.code != "not_found":
                raise
            return _store_call(
                store.create_note,
                project_id,
                note_id,
                requested_title or _note_title(note_id, body),
                body,
                expected_revision=expected_revision if expected_revision is not None else 0,
            )
        title = requested_title or str(
            _record_value(existing, "title", default=_note_title(note_id, body))
        )
        return _store_call(
            store.update_note,
            project_id,
            note_id,
            title,
            body,
            expected_revision=expected_revision,
        )

    if operation == "search":
        query = _text(request, "query")
        assert query is not None
        return _store_call(
            store.search,
            project_id,
            query,
            limit=_limit(request, "limit", 20),
            include_deleted=_bool(request, "include_deleted"),
        )

    raise AssertionError(f"unhandled operation: {operation}")


def _emit(payload: Mapping[str, Any]) -> None:
    """Write exactly one protocol record and no human-oriented stdout text."""

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def serve(stdin: Any, store: MemoryStore, policy: argparse.Namespace) -> int:
    """Serve JSON-lines until SSH closes stdin; never execute client commands."""

    for raw_line in stdin:
        encoded = raw_line.encode("utf-8", errors="replace")
        if len(encoded) > policy.max_request_bytes:
            _emit(
                {
                    "ok": False,
                    "error": {
                        "code": "request_too_large",
                        "message": "JSON line exceeds the configured limit",
                    },
                }
            )
            continue
        try:
            request = json.loads(raw_line)
            if not isinstance(request, Mapping):
                raise RpcError("invalid_request", "Each JSON line must be an object")
            result = dispatch(store, policy, request)
            _emit({"ok": True, "result": _json_value(result)})
        except json.JSONDecodeError:
            _emit(
                {
                    "ok": False,
                    "error": {"code": "invalid_json", "message": "Input must be valid JSON"},
                }
            )
        except RpcError as exc:
            _emit({"ok": False, "error": {"code": exc.code, "message": exc.message}})
    return 0


def main(argv: list[str] | None = None) -> int:
    policy = parse_args(argv)
    try:
        store = MemoryStore(data_dir=Path(policy.data_dir).expanduser(), actor=policy.actor)
    except Exception:
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "startup_failed",
                    "message": "The memory store could not be opened",
                },
            }
        )
        return 78
    return serve(sys.stdin, store, policy)


if __name__ == "__main__":  # pragma: no cover - exercised as a forced command
    raise SystemExit(main())
