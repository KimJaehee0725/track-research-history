"""Exception types used by the central research-memory service.

The exceptions intentionally carry no filesystem paths.  Callers can map them
to stable API/RPC error codes without accidentally exposing server layout.
"""

from __future__ import annotations


class MemoryError(Exception):
    """Base class for expected memory-service failures."""


class ValidationError(MemoryError):
    """Raised when a caller supplied an invalid identifier or payload."""


class NotFoundError(MemoryError):
    """Raised when a requested active project or note does not exist."""


class AlreadyExistsError(MemoryError):
    """Raised when creation would overwrite an existing active record."""


class ConflictError(MemoryError):
    """Raised when optimistic revision checking detects a stale update."""


class SecurityError(MemoryError):
    """Raised when a path would escape its configured project vault."""


class AuthorizationError(MemoryError):
    """Raised when a trusted actor lacks the needed project scope."""


class GitBackupError(MemoryError):
    """Raised only by explicit optional Git backup helpers."""
