"""Project-scoped central research-memory storage primitives."""

__version__ = "0.1.0"

from .authz import ActorScope, ProjectAuthorizer
from .errors import (
    AlreadyExistsError,
    AuthorizationError,
    ConflictError,
    GitBackupError,
    MemoryError,
    NotFoundError,
    SecurityError,
    ValidationError,
)
from .rpc import JsonRpcDispatcher, dispatch_json_line
from .store import MemoryStore, NoteRecord, ProjectRecord, validate_note_path, validate_slug

__all__ = [
    "__version__",
    "ActorScope",
    "AlreadyExistsError",
    "AuthorizationError",
    "ConflictError",
    "GitBackupError",
    "JsonRpcDispatcher",
    "MemoryError",
    "MemoryStore",
    "NotFoundError",
    "NoteRecord",
    "ProjectAuthorizer",
    "ProjectRecord",
    "SecurityError",
    "ValidationError",
    "dispatch_json_line",
    "validate_note_path",
    "validate_slug",
]
