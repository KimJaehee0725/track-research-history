"""Small, explicit project-scoped authorization helper.

The ACL is deliberately independent from SSH.  An SSH forced-command wrapper
sets ``MEMORY_ACTOR`` from the authenticated key; request JSON never chooses
the actor.  The dispatcher calls :meth:`ProjectAuthorizer.authorize` before it
touches a project.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .errors import AuthorizationError, ValidationError


VALID_ACTIONS = frozenset({"read", "write", "delete", "admin", "list"})


@dataclass(frozen=True)
class ActorScope:
    """The projects and actions a single trusted actor may use."""

    projects: frozenset[str]
    actions: frozenset[str]


class ProjectAuthorizer:
    """Authorize a trusted key identity against a compact project ACL.

    ``acl`` accepts either ``ActorScope`` values or mappings such as::

        {"laptop-key": {"projects": ["alienlm"], "actions": ["read", "write"]}}

    ``*`` in ``projects`` grants every *already validated* project name.  An
    empty ACL means local development mode and permits all operations.
    """

    def __init__(self, acl: Mapping[str, ActorScope | Mapping[str, Iterable[str]]] | None = None):
        self._scopes: dict[str, ActorScope] = {}
        for actor, scope in (acl or {}).items():
            if not isinstance(actor, str) or not actor.strip():
                raise ValidationError("ACL actor names must be non-empty strings")
            if isinstance(scope, ActorScope):
                parsed = scope
            elif isinstance(scope, Mapping):
                projects = scope.get("projects", ())
                actions = scope.get("actions", ())
                parsed = ActorScope(frozenset(projects), frozenset(actions))
            else:
                raise ValidationError("ACL scopes must be mappings or ActorScope values")
            unknown = parsed.actions - VALID_ACTIONS
            if unknown:
                raise ValidationError(f"ACL contains unsupported actions: {sorted(unknown)!r}")
            self._scopes[actor] = parsed

    @property
    def enabled(self) -> bool:
        """Whether this authorizer enforces an ACL rather than local allow-all."""

        return bool(self._scopes)

    def authorize(self, actor: str, project: str | None, action: str) -> None:
        """Raise :class:`AuthorizationError` unless ``actor`` has the scope.

        ``admin`` action implies all actions.  ``list`` is allowed when an
        actor has at least one scope, so a caller can discover only projects
        that subsequent filtering allows.  The caller remains responsible for
        filtering list results by :meth:`can_access`.
        """

        if action not in VALID_ACTIONS:
            raise ValidationError(f"Unsupported authorization action: {action}")
        if not self.enabled:
            return
        scope = self._scopes.get(actor)
        if scope is None:
            raise AuthorizationError("actor is not authorized")
        if action == "list":
            return
        if "admin" not in scope.actions and action not in scope.actions:
            raise AuthorizationError("actor is not authorized for this action")
        if project is not None and "*" not in scope.projects and project not in scope.projects:
            raise AuthorizationError("actor is not authorized for this project")

    def can_access(self, actor: str, project: str, action: str = "read") -> bool:
        """Return whether ``actor`` can access a project without raising."""

        try:
            self.authorize(actor, project, action)
        except AuthorizationError:
            return False
        return True
