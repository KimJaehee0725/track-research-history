"""Small in-process dispatcher for the public JSON SSH protocol.

The deployed SSH command uses :mod:`server.rpc` for transport policy.  This
module exposes the same envelope to embedded callers and tests without a shell
or a network dependency.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .authz import ProjectAuthorizer
from .errors import (
    AlreadyExistsError,
    AuthorizationError,
    ConflictError,
    MemoryError,
    NotFoundError,
    ValidationError,
)
from .store import MemoryStore


class JsonRpcDispatcher:
    def __init__(
        self,
        store: MemoryStore,
        *,
        authorizer: ProjectAuthorizer | None = None,
        actor: str = "local",
    ) -> None:
        self.store = store
        self.authorizer = authorizer or ProjectAuthorizer()
        self.actor = actor

    def _authorize(self, project: str | None, action: str) -> None:
        self.authorizer.authorize(self.actor, project, action)

    @staticmethod
    def _bool(params: Mapping[str, Any], name: str, default: bool = False) -> bool:
        value = params.get(name, default)
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be a boolean")
        return value

    @staticmethod
    def _limit(
        params: Mapping[str, Any], name: str = "limit", default: int = 20
    ) -> int:
        value = params.get(name, default)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 1000
        ):
            raise ValidationError(f"{name} must be an integer between 1 and 1000")
        return value

    def dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("version") != 1:
            raise ValidationError("version must be 1")
        op = request.get("op")
        params = request.get("params", {})
        if not isinstance(op, str) or not isinstance(params, Mapping):
            raise ValidationError("op must be a string and params must be an object")
        project = request.get("project")
        if op != "project.list" and not isinstance(project, str):
            raise ValidationError("project is required")
        if op == "project.list":
            self._authorize(None, "list")
            records = self.store.list_projects(
                include_deleted=self._bool(params, "include_deleted")
            )
            return {
                "ok": True,
                "result": [
                    record.to_dict()
                    for record in records
                    if self.authorizer.can_access(self.actor, record.project_id)
                ],
            }
        assert isinstance(project, str)
        if op == "project.init":
            self._authorize(project, "write")
            record = self.store.create_project(
                project,
                title=params.get("title"),
                description=params.get("description"),
                enable_git=self._bool(params, "enable_git"),
            )
        elif op == "note.list":
            self._authorize(project, "read")
            prefix = params.get("prefix")
            if prefix is not None and not isinstance(prefix, str):
                raise ValidationError("prefix must be a string")
            limit = self._limit(params, default=100)
            records = self.store.list_notes(
                project, include_deleted=self._bool(params, "include_deleted")
            )
            record = [
                item.to_dict()
                for item in records
                if prefix is None or item.note_id.startswith(prefix)
            ][:limit]
            return {"ok": True, "result": record}
        elif op == "note.read":
            self._authorize(project, "read")
            record = self.store.get_note(
                project,
                str(params.get("path", "")),
                include_deleted=self._bool(params, "include_deleted"),
            )
        elif op == "note.write":
            self._authorize(project, "write")
            path, content = params.get("path"), params.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise ValidationError("path and content are required strings")
            try:
                old = self.store.get_note(project, path)
            except NotFoundError:
                record = self.store.create_note(
                    project,
                    path,
                    str(params.get("title") or path),
                    content,
                    params.get("if_revision", 0),
                )
            else:
                record = self.store.update_note(
                    project,
                    path,
                    str(params.get("title") or old.title),
                    content,
                    params.get("if_revision"),
                )
        elif op == "note.delete":
            self._authorize(project, "write")
            record = self.store.delete_note(
                project, str(params.get("path", "")), params.get("if_revision")
            )
        elif op == "note.restore":
            self._authorize(project, "write")
            record = self.store.restore_note(
                project,
                trash_id=str(params.get("trash_id", "")),
                expected_revision=params.get("if_revision"),
            )
        elif op == "note.search":
            self._authorize(project, "read")
            query = params.get("query")
            if not isinstance(query, str):
                raise ValidationError("query is required")
            records = self.store.search(
                project,
                query,
                limit=self._limit(params),
                include_deleted=self._bool(params, "include_deleted"),
            )
            return {"ok": True, "result": [item.to_dict() for item in records]}
        else:
            raise ValidationError("unsupported op")
        return {"ok": True, "result": record.to_dict()}


def dispatch_json_line(dispatcher: JsonRpcDispatcher, line: str) -> str:
    """Return exactly one JSON response for one input line."""

    try:
        request = json.loads(line)
        if not isinstance(request, Mapping):
            raise ValidationError("request must be an object")
        response = dispatcher.dispatch(request)
    except AuthorizationError as exc:
        response = {"ok": False, "error": {"code": "forbidden", "message": str(exc)}}
    except NotFoundError as exc:
        response = {"ok": False, "error": {"code": "not_found", "message": str(exc)}}
    except (AlreadyExistsError, ConflictError) as exc:
        response = {"ok": False, "error": {"code": "conflict", "message": str(exc)}}
    except ValidationError as exc:
        response = {
            "ok": False,
            "error": {"code": "invalid_request", "message": str(exc)},
        }
    except MemoryError:
        response = {
            "ok": False,
            "error": {
                "code": "store_error",
                "message": "The memory store could not complete this request",
            },
        }
    except (TypeError, ValueError) as exc:
        response = {
            "ok": False,
            "error": {"code": "invalid_request", "message": str(exc)},
        }
    except Exception:
        response = {
            "ok": False,
            "error": {
                "code": "store_error",
                "message": "The memory store could not complete this request",
            },
        }
    return json.dumps(response, ensure_ascii=False, separators=(",", ":"))
