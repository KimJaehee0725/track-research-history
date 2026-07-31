"""Filesystem-backed, project-isolated research memory storage.

Markdown files remain the durable, human-readable artifact.  SQLite keeps only
the metadata needed for revisions, recoverable deletion, and FTS5 search.  All
public mutations take an advisory process lock plus a SQLite write transaction
so independent SSH RPC processes do not silently overwrite each other.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, Iterator
import uuid

from .errors import (
    AlreadyExistsError,
    ConflictError,
    NotFoundError,
    SecurityError,
    ValidationError,
)
from .git_backup import GitBackupError, commit_project_snapshot, initialize_project_git


PROJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
TRASH_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,160}\Z")
MAX_NOTE_BYTES = 5 * 1024 * 1024
MAX_TITLE_CHARS = 256
MAX_DESCRIPTION_CHARS = 4_000
PROJECT_MAP_NOTE_ID = "project-map.md"


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_slug(value: str, *, label: str = "project_id") -> str:
    """Return a safe project identifier or raise a public validation error."""

    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    checked = value.strip()
    if checked in {"", ".", ".."} or not PROJECT_RE.fullmatch(checked):
        raise ValidationError(
            f"{label} must be 1-64 URL-safe characters (letters, numbers, '.', '_' or '-')"
        )
    return checked


def validate_note_path(value: str) -> str:
    """Validate a project-relative Markdown path without touching the disk."""

    if not isinstance(value, str):
        raise ValidationError("note path must be a string")
    if not value or len(value) > 480 or "\x00" in value or "\\" in value:
        raise ValidationError("note path must be a short relative POSIX path")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValidationError("note path cannot contain empty, '.' or '..' components")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not value.endswith(".md"):
        raise ValidationError("note path must be a relative .md path")
    normalized = candidate.as_posix()
    if normalized == PROJECT_MAP_NOTE_ID:
        raise ValidationError(f"{PROJECT_MAP_NOTE_ID} is a reserved derived file")
    return normalized


def _text(value: str | None, label: str, maximum: int, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise ValidationError(f"{label} is required")
        return ""
    if not isinstance(value, str) or "\x00" in value:
        raise ValidationError(f"{label} must be text without NUL bytes")
    checked = value.strip()
    if required and not checked:
        raise ValidationError(f"{label} is required")
    if len(checked) > maximum:
        raise ValidationError(f"{label} must be at most {maximum} characters")
    return checked


def _title_from_markdown(path: str, body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and stripped[2:].strip():
            return stripped[2:].strip()[:MAX_TITLE_CHARS]
    stem = PurePosixPath(path).stem.replace("_", " ").replace("-", " ").strip()
    return stem[:MAX_TITLE_CHARS] or "Untitled note"


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    title: str
    description: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    trash_id: str | None = None

    @property
    def id(self) -> str:
        return self.project_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "id": self.project_id,
            "title": self.title,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "trash_id": self.trash_id,
        }


@dataclass(frozen=True)
class NoteRecord:
    note_id: str
    project_id: str
    title: str
    body: str
    revision: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    trash_id: str | None = None

    @property
    def id(self) -> str:
        return self.note_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "id": self.note_id,
            "project_id": self.project_id,
            "title": self.title,
            "body": self.body,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "trash_id": self.trash_id,
        }


class MemoryStore:
    """Own project Markdown vaults, metadata, FTS5 index, and recoverable trash."""

    def __init__(self, data_dir: str | Path, *, actor: str = "system") -> None:
        requested_data_dir = Path(data_dir).expanduser()
        requested_data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = requested_data_dir.resolve()
        if not isinstance(actor, str) or not actor.strip() or any(
            character in actor for character in "\r\n\x00"
        ):
            raise ValidationError("actor must be a non-empty single-line identifier")
        self.actor = actor.strip()[:256]
        self.projects_dir = self.data_dir / "projects"
        self.audit_dir = self.data_dir / "audit"
        self.trash_dir = self.data_dir / "trash"
        self.backups_dir = self.data_dir / "backups"
        self.database_path = self.data_dir / "registry.sqlite3"
        self.lock_path = self.data_dir / ".store.lock"
        for directory in (
            self.projects_dir,
            self.audit_dir,
            self.trash_dir,
            self.backups_dir,
        ):
            self._ensure_managed_directory(directory)
        for managed_file in (self.database_path, self.lock_path):
            if managed_file.is_symlink():
                raise SecurityError(f"managed path cannot be a symlink: {managed_file.name}")
        self._fts_enabled = False
        with self._locked():
            self._initialize_database()

    def _ensure_managed_directory(self, directory: Path) -> None:
        """Create one service-owned root without following a pre-existing link."""

        if directory.is_symlink():
            raise SecurityError(f"managed directory cannot be a symlink: {directory.name}")
        if directory.exists():
            if not directory.is_dir():
                raise SecurityError(f"managed path is not a directory: {directory.name}")
        else:
            directory.mkdir()
        resolved = directory.resolve()
        if resolved == self.data_dir or self.data_dir not in resolved.parents:
            raise SecurityError(f"managed directory escapes data root: {directory.name}")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Serialize filesystem and SQLite mutations across local processes."""

        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise SecurityError("store lock path is unsafe or unavailable") from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _connect(self) -> sqlite3.Connection:
        if self.database_path.is_symlink():
            raise SecurityError("registry database cannot be a symlink")
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_database(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    trash_id TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    project_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    trash_id TEXT,
                    PRIMARY KEY (project_id, note_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS notes_project_active ON notes(project_id, deleted_at)"
            )
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
                    USING fts5(project_id UNINDEXED, note_id UNINDEXED, title, body)
                    """
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                # Python builds without FTS5 still retain correct storage and
                # use the small-vault substring fallback in ``search``.
                self._fts_enabled = False
            # ``project-map.md`` is derived state, never a user note.  Remove
            # rows produced by older releases that briefly allowed the ID.
            connection.execute(
                "DELETE FROM notes WHERE note_id = ?",
                (PROJECT_MAP_NOTE_ID,),
            )
            if self._fts_enabled:
                connection.execute(
                    "DELETE FROM notes_fts WHERE note_id = ?",
                    (PROJECT_MAP_NOTE_ID,),
                )
            # Rebuild every active derived map at startup. Besides keeping the
            # file synchronized after an upgrade, this replaces a legacy or
            # externally modified map with trusted derived state.
            active_projects = connection.execute(
                "SELECT project_id FROM projects WHERE deleted_at IS NULL"
            ).fetchall()
            for row in active_projects:
                project_id = str(row["project_id"])
                if self._project_dir(project_id).is_dir():
                    self._write_project_map(connection, project_id)
        finally:
            connection.close()

    def _project_dir(self, project_id: str) -> Path:
        checked = validate_slug(project_id)
        path = self.projects_dir / checked
        if path.exists() and path.is_symlink():
            raise SecurityError("project directory cannot be a symlink")
        return path

    def _vault_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "vault"

    def _note_file(self, project_id: str, note_id: str) -> Path:
        safe_note_id = validate_note_path(note_id)
        vault = self._vault_dir(project_id)
        path = vault.joinpath(*PurePosixPath(safe_note_id).parts)
        vault_resolved = vault.resolve()
        resolved = path.resolve(strict=False)
        if resolved != vault_resolved and vault_resolved not in resolved.parents:
            raise SecurityError("note path escapes the project vault")
        parent = path.parent
        while parent != vault.parent:
            if parent.exists() and parent.is_symlink():
                raise SecurityError("note path traverses a symlink")
            if parent == vault:
                break
            parent = parent.parent
        return path

    @staticmethod
    def _open_regular_file(root: Path, *parts: str) -> int:
        """Open one root-relative regular file without following any symlink."""

        if not parts or not hasattr(os, "O_NOFOLLOW"):
            raise SecurityError("no-follow file access is unavailable")
        for part in parts:
            if (
                not isinstance(part, str)
                or part in {"", ".", ".."}
                or "/" in part
                or "\\" in part
                or "\x00" in part
            ):
                raise SecurityError("managed file path contains an unsafe component")

        directory_flags = (
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
        )
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        directory_descriptors: list[int] = []
        file_descriptor: int | None = None
        try:
            directory_descriptor = os.open(root, directory_flags)
            directory_descriptors.append(directory_descriptor)
            if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                raise SecurityError("managed file root is not a directory")
            for part in parts[:-1]:
                directory_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                directory_descriptors.append(directory_descriptor)
                if not stat.S_ISDIR(os.fstat(directory_descriptor).st_mode):
                    raise SecurityError("managed path component is not a directory")
            file_descriptor = os.open(
                parts[-1],
                file_flags,
                dir_fd=directory_descriptor,
            )
            file_status = os.fstat(file_descriptor)
            if not stat.S_ISREG(file_status.st_mode):
                raise SecurityError("managed note payload is not a regular file")
            if file_status.st_size > MAX_NOTE_BYTES:
                raise SecurityError("managed note payload exceeds the size limit")
            result = file_descriptor
            file_descriptor = None
            return result
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise SecurityError("managed file path is unsafe or unavailable") from exc
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            for descriptor in reversed(directory_descriptors):
                os.close(descriptor)

    @classmethod
    def _read_regular_text(cls, root: Path, *parts: str) -> str:
        descriptor = cls._open_regular_file(root, *parts)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            return stream.read()

    @staticmethod
    def _assert_safe_project_tree(project_dir: Path) -> None:
        """Reject project trees containing links before moving the tree."""

        if project_dir.is_symlink():
            raise SecurityError("project directory cannot be a symlink")
        if not project_dir.is_dir():
            raise NotFoundError("project directory was not found")

        def fail_walk(exc: OSError) -> None:
            raise SecurityError("project tree could not be inspected safely") from exc

        for root, directories, files in os.walk(
            project_dir,
            topdown=True,
            followlinks=False,
            onerror=fail_walk,
        ):
            for name in directories + files:
                if (Path(root) / name).is_symlink():
                    raise SecurityError("project tree cannot contain symlinks")

    @staticmethod
    def _hash(body: str) -> str:
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _atomic_write(self, destination: Path, body: str) -> None:
        encoded = body.encode("utf-8")
        if len(encoded) > MAX_NOTE_BYTES:
            raise ValidationError(f"note body exceeds {MAX_NOTE_BYTES} bytes")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise SecurityError("note parent cannot be a symlink")
        handle, temporary_name = tempfile.mkstemp(prefix=".memory-", dir=destination.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            project_id=row["project_id"],
            title=row["title"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
            trash_id=row["trash_id"],
        )

    def _note_from_row(self, row: sqlite3.Row, body: str = "") -> NoteRecord:
        return NoteRecord(
            note_id=row["note_id"],
            project_id=row["project_id"],
            title=row["title"],
            body=body,
            revision=int(row["revision"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
            trash_id=row["trash_id"],
        )

    @staticmethod
    def _stored_trash_id(value: Any) -> str:
        if not isinstance(value, str) or not TRASH_ID_RE.fullmatch(value):
            raise SecurityError("stored trash identifier is unsafe")
        return value

    def _note_body_from_row(
        self,
        project_id: str,
        project: sqlite3.Row,
        row: sqlite3.Row,
    ) -> str:
        note_id = validate_note_path(str(row["note_id"]))
        note_parts = PurePosixPath(note_id).parts
        if row["deleted_at"] is not None:
            trash_id = self._stored_trash_id(row["trash_id"])
            return self._read_regular_text(self.trash_dir, trash_id, "note.md")
        if project["deleted_at"] is not None:
            trash_id = self._stored_trash_id(project["trash_id"])
            return self._read_regular_text(
                self.trash_dir,
                trash_id,
                "project",
                "vault",
                *note_parts,
            )
        return self._read_regular_text(
            self._vault_dir(project_id),
            *note_parts,
        )

    def _append_audit(self, event: str, **details: Any) -> None:
        payload = {"at": _timestamp(), "actor": self.actor, "event": event, **details}
        daily_name = f"{payload['at'][:10]}.jsonl"
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        normal_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            normal_flags |= os.O_NOFOLLOW

        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            audit_descriptor = os.open(self.audit_dir, directory_flags)
        except OSError:
            return

        def write_record(filename: str, flags: int) -> bool:
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    filename,
                    flags,
                    0o600,
                    dir_fd=audit_descriptor,
                )
                remaining = memoryview(encoded)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("audit write made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
                return True
            except OSError:
                return False
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

        try:
            if write_record(daily_name, normal_flags):
                return

            # Mutations have usually committed before their audit event is
            # emitted. A poisoned daily path must not turn a successful
            # mutation into a false failure. A unique O_EXCL fallback retains
            # the event without following the unsafe path.
            fallback_name = (
                f"fallback-{payload['at'][:10]}-{uuid.uuid4().hex}.jsonl"
            )
            fallback_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                fallback_flags |= os.O_NOFOLLOW
            write_record(fallback_name, fallback_flags)
        finally:
            try:
                os.close(audit_descriptor)
            except OSError:
                pass

    def _snapshot_project(self, project_id: str, event: str) -> None:
        """Make a best-effort local Git snapshot when this project enabled it.

        Markdown durability never depends on Git.  A missing executable,
        identity, or transient local Git error is recorded as an audit event
        rather than rolling back a successful storage transaction.
        """

        project_dir = self._project_dir(project_id)
        if not (project_dir / ".git").is_dir():
            return
        try:
            revision = commit_project_snapshot(project_dir, event)
        except GitBackupError:
            self._append_audit("project.git_snapshot_failed", project_id=project_id)
            return
        if revision:
            self._append_audit("project.git_snapshot", project_id=project_id, git_revision=revision)

    def _write_project_manifest(self, project_id: str, title: str, description: str) -> None:
        project_dir = self._project_dir(project_id)
        manifest = "\n".join(
            (
                f"project_id: {json.dumps(project_id, ensure_ascii=False)}",
                f"title: {json.dumps(title, ensure_ascii=False)}",
                f"description: {json.dumps(description, ensure_ascii=False)}",
                "",
            )
        )
        self._atomic_write(project_dir / "project.yaml", manifest)

    def _write_project_map(self, connection: sqlite3.Connection, project_id: str) -> None:
        """Regenerate the Obsidian-facing hub note for one active project.

        The map is deliberately derived rather than a normal memory note: it
        is not searchable, editable through RPC, or independently deleted.
        Its wiki links make the project graph useful without changing a
        researcher's original Markdown body.
        """

        project = self._active_project_row(connection, project_id)
        rows = connection.execute(
            """
            SELECT note_id, title FROM notes
            WHERE project_id = ? AND deleted_at IS NULL AND note_id != ?
            ORDER BY note_id COLLATE NOCASE
            """,
            (project_id, PROJECT_MAP_NOTE_ID),
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            parent = PurePosixPath(str(row["note_id"])).parent.as_posix()
            groups.setdefault("Notes" if parent == "." else parent, []).append(row)

        lines = [
            "---",
            "type: project-map",
            f"project_id: {json.dumps(project_id, ensure_ascii=False)}",
            f"title: {json.dumps(str(project['title']), ensure_ascii=False)}",
            "tags: [research-memory, project-map]",
            "---",
            "",
            f"# {project['title']}",
            "",
            "이 문서는 Research Memory가 자동 생성하는 Obsidian 프로젝트 허브입니다.",
            "수정·삭제하지 말고, 실제 메모리는 UI 또는 `memctl`로 관리하세요.",
        ]
        if not groups:
            lines.extend(("", "아직 기록된 메모리가 없습니다."))
        for group, notes in groups.items():
            lines.extend(("", f"## {group}"))
            for row in notes:
                target = str(row["note_id"])
                if target.endswith(".md"):
                    target = target[:-3]
                label = str(row["title"]).replace("[", "").replace("]", "").replace("|", " ")
                lines.append(f"- [[{target}|{label}]]")
        lines.append("")
        vault = self._vault_dir(project_id)
        body = "\n".join(lines)
        try:
            existing = self._read_regular_text(vault, PROJECT_MAP_NOTE_ID)
        except (
            FileNotFoundError,
            UnicodeDecodeError,
            SecurityError,
        ):
            existing = None
        if existing != body:
            self._atomic_write(vault / PROJECT_MAP_NOTE_ID, body)

    def rebuild_project_map(self, project_id: str) -> None:
        """Refresh one project's derived Obsidian map after a deployment."""

        checked = validate_slug(project_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._active_project_row(connection, checked)
                self._refresh_external(connection, checked)
                self._write_project_map(connection, checked)
                connection.commit()
                self._snapshot_project(checked, "memory: refresh Obsidian project map")
                self._append_audit("project.obsidian_map_refreshed", project_id=checked)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _expected_revision(value: int | str | None, current: int) -> None:
        if value is None:
            return
        try:
            expected = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("expected_revision must be an integer") from exc
        if expected != current:
            raise ConflictError("the record changed elsewhere")

    def _active_project_row(self, connection: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        checked = validate_slug(project_id)
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (checked,)
        ).fetchone()
        if row is None or row["deleted_at"] is not None:
            raise NotFoundError("project was not found")
        if not self._project_dir(checked).is_dir():
            raise NotFoundError("project vault was not found")
        return row

    def _upsert_fts(
        self, connection: sqlite3.Connection, project_id: str, note_id: str, title: str, body: str
    ) -> None:
        if not self._fts_enabled:
            return
        connection.execute(
            "DELETE FROM notes_fts WHERE project_id = ? AND note_id = ?", (project_id, note_id)
        )
        connection.execute(
            "INSERT INTO notes_fts(project_id, note_id, title, body) VALUES (?, ?, ?, ?)",
            (project_id, note_id, title, body),
        )

    def _remove_fts(self, connection: sqlite3.Connection, project_id: str, note_id: str) -> None:
        if self._fts_enabled:
            connection.execute(
                "DELETE FROM notes_fts WHERE project_id = ? AND note_id = ?", (project_id, note_id)
            )

    def _refresh_external(self, connection: sqlite3.Connection, project_id: str) -> None:
        """Index direct Obsidian/SFTP edits without making them canonical APIs.

        This intentionally does not treat an externally deleted file as a
        normal delete: only the store can create a recoverable trash item.
        Missing files are removed from search until an administrator recovers
        them from backup or Git history.
        """

        vault = self._vault_dir(project_id)
        if vault.is_symlink():
            raise SecurityError("project vault cannot be a symlink")
        if not vault.is_dir():
            return
        seen: set[str] = set()
        for path in vault.rglob("*.md"):
            if path.is_symlink():
                continue
            try:
                note_id = validate_note_path(path.relative_to(vault).as_posix())
                body = self._read_regular_text(
                    vault,
                    *PurePosixPath(note_id).parts,
                )
            except (
                FileNotFoundError,
                UnicodeDecodeError,
                ValidationError,
                SecurityError,
            ):
                continue
            if note_id == PROJECT_MAP_NOTE_ID:
                continue
            if len(body.encode("utf-8")) > MAX_NOTE_BYTES:
                continue
            seen.add(note_id)
            digest = self._hash(body)
            row = connection.execute(
                "SELECT * FROM notes WHERE project_id = ? AND note_id = ?", (project_id, note_id)
            ).fetchone()
            now = _timestamp()
            if row is None:
                title = _title_from_markdown(note_id, body)
                connection.execute(
                    """
                    INSERT INTO notes(project_id, note_id, title, revision, content_hash, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (project_id, note_id, title, digest, now, now),
                )
                self._upsert_fts(connection, project_id, note_id, title, body)
                self._append_audit("note.external_discovered", project_id=project_id, note_id=note_id)
            elif row["deleted_at"] is None and row["content_hash"] != digest:
                title = _title_from_markdown(note_id, body)
                connection.execute(
                    """
                    UPDATE notes SET title = ?, revision = ?, content_hash = ?, updated_at = ?
                    WHERE project_id = ? AND note_id = ?
                    """,
                    (title, int(row["revision"]) + 1, digest, now, project_id, note_id),
                )
                self._upsert_fts(connection, project_id, note_id, title, body)
                self._append_audit("note.external_modified", project_id=project_id, note_id=note_id)
        active_rows = connection.execute(
            "SELECT note_id FROM notes WHERE project_id = ? AND deleted_at IS NULL", (project_id,)
        ).fetchall()
        for row in active_rows:
            if row["note_id"] not in seen:
                self._remove_fts(connection, project_id, row["note_id"])

    def create_project(
        self,
        project_id: str,
        title: str | None = None,
        description: str | None = None,
        enable_git: bool = False,
    ) -> ProjectRecord:
        checked = validate_slug(project_id)
        checked_title = _text(title or checked, "title", MAX_TITLE_CHARS, required=True)
        checked_description = _text(description, "description", MAX_DESCRIPTION_CHARS)
        if not isinstance(enable_git, bool):
            raise ValidationError("enable_git must be a boolean")
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT project_id FROM projects WHERE project_id = ?", (checked,)
                ).fetchone()
                if existing is not None:
                    raise AlreadyExistsError("project already exists; restore it instead if it is in trash")
                project_dir = self._project_dir(checked)
                if project_dir.exists():
                    raise AlreadyExistsError("a project directory already exists")
                project_dir.mkdir(mode=0o700)
                (project_dir / "vault").mkdir(mode=0o700)
                self._write_project_manifest(checked, checked_title, checked_description)
                if enable_git:
                    try:
                        initialize_project_git(project_dir)
                    except GitBackupError:
                        # Git is a local backup convenience, never a reason to
                        # reject durable Markdown storage.
                        pass
                now = _timestamp()
                connection.execute(
                    """
                    INSERT INTO projects(project_id, title, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (checked, checked_title, checked_description, now, now),
                )
                self._write_project_map(connection, checked)
                connection.commit()
                self._snapshot_project(checked, "memory: initialize project")
                self._append_audit("project.created", project_id=checked)
                return ProjectRecord(checked, checked_title, checked_description, now, now)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def list_projects(self, include_deleted: bool = False) -> list[ProjectRecord]:
        with self._locked():
            connection = self._connect()
            try:
                query = "SELECT * FROM projects"
                if not include_deleted:
                    query += " WHERE deleted_at IS NULL"
                query += " ORDER BY project_id COLLATE NOCASE"
                return [self._project_from_row(row) for row in connection.execute(query).fetchall()]
            finally:
                connection.close()

    def get_project(self, project_id: str, include_deleted: bool = False) -> ProjectRecord:
        checked = validate_slug(project_id)
        with self._locked():
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (checked,)
                ).fetchone()
                if row is None or (row["deleted_at"] is not None and not include_deleted):
                    raise NotFoundError("project was not found")
                return self._project_from_row(row)
            finally:
                connection.close()

    def delete_project(self, project_id: str) -> ProjectRecord:
        checked = validate_slug(project_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._active_project_row(connection, checked)
                project_dir = self._project_dir(checked)
                self._assert_safe_project_tree(project_dir)
                trash_id = f"project-{checked}-{uuid.uuid4().hex[:16]}"
                trash_root = self.trash_dir / trash_id
                trash_root.mkdir(mode=0o700)
                self._snapshot_project(checked, "memory: project moved to trash")
                os.replace(project_dir, trash_root / "project")
                now = _timestamp()
                connection.execute(
                    "UPDATE projects SET deleted_at = ?, updated_at = ?, trash_id = ? WHERE project_id = ?",
                    (now, now, trash_id, checked),
                )
                connection.commit()
                self._append_audit("project.deleted", project_id=checked, trash_id=trash_id)
                return ProjectRecord(checked, row["title"], row["description"], row["created_at"], now, now, trash_id)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def restore_project(self, project_id: str) -> ProjectRecord:
        checked = validate_slug(project_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM projects WHERE project_id = ?", (checked,)
                ).fetchone()
                if row is None or row["deleted_at"] is None or not row["trash_id"]:
                    raise NotFoundError("deleted project was not found")
                stored_trash_id = self._stored_trash_id(row["trash_id"])
                source = self.trash_dir / stored_trash_id / "project"
                destination = self._project_dir(checked)
                if source.is_symlink():
                    raise SecurityError("project trash payload cannot be a symlink")
                if not source.is_dir():
                    raise NotFoundError("project trash payload was not found")
                self._assert_safe_project_tree(source)
                if destination.exists():
                    raise ConflictError("an active project directory already exists")
                os.replace(source, destination)
                now = _timestamp()
                connection.execute(
                    "UPDATE projects SET deleted_at = NULL, trash_id = NULL, updated_at = ? WHERE project_id = ?",
                    (now, checked),
                )
                self._write_project_map(connection, checked)
                connection.commit()
                self._append_audit("project.restored", project_id=checked)
                return ProjectRecord(checked, row["title"], row["description"], row["created_at"], now)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def create_note(
        self,
        project_id: str,
        note_id: str,
        title: str,
        body: str,
        expected_revision: int | str | None = 0,
    ) -> NoteRecord:
        checked_project = validate_slug(project_id)
        checked_note = validate_note_path(note_id)
        checked_title = _text(title, "title", MAX_TITLE_CHARS, required=True)
        if not isinstance(body, str) or "\x00" in body:
            raise ValidationError("note body must be text without NUL bytes")
        self._expected_revision(expected_revision, 0)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._active_project_row(connection, checked_project)
                existing = connection.execute(
                    "SELECT * FROM notes WHERE project_id = ? AND note_id = ?", (checked_project, checked_note)
                ).fetchone()
                if existing is not None:
                    raise AlreadyExistsError("note already exists; restore it instead if it is in trash")
                path = self._note_file(checked_project, checked_note)
                if path.exists():
                    raise AlreadyExistsError("a note file already exists")
                self._atomic_write(path, body)
                now = _timestamp()
                digest = self._hash(body)
                connection.execute(
                    """
                    INSERT INTO notes(project_id, note_id, title, revision, content_hash, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (checked_project, checked_note, checked_title, digest, now, now),
                )
                self._upsert_fts(connection, checked_project, checked_note, checked_title, body)
                self._write_project_map(connection, checked_project)
                connection.commit()
                self._snapshot_project(checked_project, f"memory: create {checked_note}")
                self._append_audit("note.created", project_id=checked_project, note_id=checked_note)
                return NoteRecord(checked_note, checked_project, checked_title, body, 1, now, now)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def update_note(
        self,
        project_id: str,
        note_id: str,
        title: str,
        body: str,
        expected_revision: int | str | None = None,
    ) -> NoteRecord:
        checked_project = validate_slug(project_id)
        checked_note = validate_note_path(note_id)
        checked_title = _text(title, "title", MAX_TITLE_CHARS, required=True)
        if not isinstance(body, str) or "\x00" in body:
            raise ValidationError("note body must be text without NUL bytes")
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._active_project_row(connection, checked_project)
                self._refresh_external(connection, checked_project)
                row = connection.execute(
                    "SELECT * FROM notes WHERE project_id = ? AND note_id = ?", (checked_project, checked_note)
                ).fetchone()
                if row is None or row["deleted_at"] is not None:
                    raise NotFoundError("note was not found")
                self._expected_revision(expected_revision, int(row["revision"]))
                path = self._note_file(checked_project, checked_note)
                if not path.is_file():
                    raise NotFoundError("note file was not found")
                self._atomic_write(path, body)
                now = _timestamp()
                revision = int(row["revision"]) + 1
                digest = self._hash(body)
                connection.execute(
                    """
                    UPDATE notes SET title = ?, revision = ?, content_hash = ?, updated_at = ?
                    WHERE project_id = ? AND note_id = ?
                    """,
                    (checked_title, revision, digest, now, checked_project, checked_note),
                )
                self._upsert_fts(connection, checked_project, checked_note, checked_title, body)
                self._write_project_map(connection, checked_project)
                connection.commit()
                self._snapshot_project(checked_project, f"memory: update {checked_note}")
                self._append_audit("note.updated", project_id=checked_project, note_id=checked_note)
                return NoteRecord(checked_note, checked_project, checked_title, body, revision, row["created_at"], now)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def get_note(self, project_id: str, note_id: str, include_deleted: bool = False) -> NoteRecord:
        checked_project = validate_slug(project_id)
        checked_note = validate_note_path(note_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if include_deleted:
                    project = connection.execute(
                        "SELECT * FROM projects WHERE project_id = ?", (checked_project,)
                    ).fetchone()
                    if project is None:
                        raise NotFoundError("project was not found")
                else:
                    self._active_project_row(connection, checked_project)
                self._refresh_external(connection, checked_project)
                row = connection.execute(
                    "SELECT * FROM notes WHERE project_id = ? AND note_id = ?", (checked_project, checked_note)
                ).fetchone()
                if row is None or (row["deleted_at"] is not None and not include_deleted):
                    raise NotFoundError("note was not found")
                if row["deleted_at"] is not None:
                    return self._note_from_row(row)
                try:
                    body = self._read_regular_text(
                        self._vault_dir(checked_project),
                        *PurePosixPath(checked_note).parts,
                    )
                except FileNotFoundError:
                    raise NotFoundError("note file was not found")
                connection.commit()
                return self._note_from_row(row, body)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def list_notes(self, project_id: str, include_deleted: bool = False) -> list[NoteRecord]:
        checked_project = validate_slug(project_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if include_deleted:
                    project = connection.execute(
                        "SELECT * FROM projects WHERE project_id = ?", (checked_project,)
                    ).fetchone()
                    if project is None:
                        raise NotFoundError("project was not found")
                else:
                    self._active_project_row(connection, checked_project)
                self._refresh_external(connection, checked_project)
                query = "SELECT * FROM notes WHERE project_id = ?"
                if not include_deleted:
                    query += " AND deleted_at IS NULL"
                query += " ORDER BY note_id COLLATE NOCASE"
                rows = connection.execute(query, (checked_project,)).fetchall()
                records: list[NoteRecord] = []
                for row in rows:
                    if row["deleted_at"] is None:
                        try:
                            descriptor = self._open_regular_file(
                                self._vault_dir(checked_project),
                                *PurePosixPath(str(row["note_id"])).parts,
                            )
                        except FileNotFoundError:
                            continue
                        else:
                            os.close(descriptor)
                    records.append(self._note_from_row(row))
                connection.commit()
                return records
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def delete_note(
        self,
        project_id: str,
        note_id: str,
        expected_revision: int | str | None = None,
    ) -> NoteRecord:
        checked_project = validate_slug(project_id)
        checked_note = validate_note_path(note_id)
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._active_project_row(connection, checked_project)
                self._refresh_external(connection, checked_project)
                row = connection.execute(
                    "SELECT * FROM notes WHERE project_id = ? AND note_id = ?", (checked_project, checked_note)
                ).fetchone()
                if row is None or row["deleted_at"] is not None:
                    raise NotFoundError("note was not found")
                self._expected_revision(expected_revision, int(row["revision"]))
                source = self._note_file(checked_project, checked_note)
                if not source.is_file():
                    raise NotFoundError("note file was not found")
                trash_id = f"note-{checked_project}-{uuid.uuid4().hex[:16]}"
                trash_root = self.trash_dir / trash_id
                trash_root.mkdir(mode=0o700)
                os.replace(source, trash_root / "note.md")
                metadata = {
                    "project_id": checked_project,
                    "note_id": checked_note,
                    "title": row["title"],
                    "revision": int(row["revision"]),
                }
                self._atomic_write(trash_root / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
                now = _timestamp()
                revision = int(row["revision"]) + 1
                connection.execute(
                    """
                    UPDATE notes SET deleted_at = ?, updated_at = ?, trash_id = ?, revision = ?
                    WHERE project_id = ? AND note_id = ?
                    """,
                    (now, now, trash_id, revision, checked_project, checked_note),
                )
                self._remove_fts(connection, checked_project, checked_note)
                self._write_project_map(connection, checked_project)
                connection.commit()
                self._snapshot_project(checked_project, f"memory: delete {checked_note}")
                self._append_audit("note.deleted", project_id=checked_project, note_id=checked_note, trash_id=trash_id)
                return NoteRecord(checked_note, checked_project, row["title"], "", revision, row["created_at"], now, now, trash_id)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def restore_note(
        self,
        project_id: str,
        note_id: str | None = None,
        *,
        trash_id: str | None = None,
        expected_revision: int | str | None = None,
    ) -> NoteRecord:
        checked_project = validate_slug(project_id)
        if note_id is not None:
            checked_note = validate_note_path(note_id)
        else:
            checked_note = None
        if trash_id is not None and (
            not isinstance(trash_id, str) or not TRASH_ID_RE.fullmatch(trash_id)
        ):
            raise ValidationError("trash_id contains unsupported characters")
        if checked_note is None and trash_id is None:
            raise ValidationError("note_id or trash_id is required")
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._active_project_row(connection, checked_project)
                if trash_id is not None:
                    row = connection.execute(
                        "SELECT * FROM notes WHERE project_id = ? AND trash_id = ? AND deleted_at IS NOT NULL",
                        (checked_project, trash_id),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT * FROM notes WHERE project_id = ? AND note_id = ? AND deleted_at IS NOT NULL",
                        (checked_project, checked_note),
                    ).fetchone()
                if row is None or not row["trash_id"]:
                    raise NotFoundError("deleted note was not found")
                self._expected_revision(expected_revision, int(row["revision"]))
                stored_trash_id = self._stored_trash_id(row["trash_id"])
                source = self.trash_dir / stored_trash_id / "note.md"
                destination = self._note_file(checked_project, row["note_id"])
                try:
                    body = self._read_regular_text(
                        self.trash_dir,
                        stored_trash_id,
                        "note.md",
                    )
                except FileNotFoundError:
                    raise NotFoundError("note trash payload was not found")
                if destination.exists():
                    raise ConflictError("an active note file already exists")
                self._atomic_write(destination, body)
                source.unlink(missing_ok=True)
                now = _timestamp()
                revision = int(row["revision"]) + 1
                connection.execute(
                    """
                    UPDATE notes SET deleted_at = NULL, trash_id = NULL, revision = ?, content_hash = ?, updated_at = ?
                    WHERE project_id = ? AND note_id = ?
                    """,
                    (revision, self._hash(body), now, checked_project, row["note_id"]),
                )
                self._upsert_fts(connection, checked_project, row["note_id"], row["title"], body)
                self._write_project_map(connection, checked_project)
                connection.commit()
                self._snapshot_project(checked_project, f"memory: restore {row['note_id']}")
                self._append_audit("note.restored", project_id=checked_project, note_id=row["note_id"])
                return NoteRecord(row["note_id"], checked_project, row["title"], body, revision, row["created_at"], now)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def search(
        self,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
        include_deleted: bool = False,
    ) -> list[NoteRecord]:
        checked_project = validate_slug(project_id)
        checked_query = _text(query, "query", 4096, required=True)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValidationError("limit must be an integer between 1 and 1000")
        with self._locked():
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if include_deleted:
                    project = connection.execute(
                        "SELECT * FROM projects WHERE project_id = ?", (checked_project,)
                    ).fetchone()
                    if project is None:
                        raise NotFoundError("project was not found")
                else:
                    project = self._active_project_row(connection, checked_project)
                self._refresh_external(connection, checked_project)
                rows: list[sqlite3.Row]
                tokens = re.findall(r"[\w가-힣]+", checked_query, flags=re.UNICODE)
                if self._fts_enabled and tokens and not include_deleted:
                    expression = " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
                    try:
                        rows = connection.execute(
                            """
                            SELECT n.* FROM notes_fts f
                            JOIN notes n ON n.project_id = f.project_id AND n.note_id = f.note_id
                            WHERE f.project_id = ? AND notes_fts MATCH ? AND n.deleted_at IS NULL
                            ORDER BY bm25(notes_fts) LIMIT ?
                            """,
                            (checked_project, expression, limit),
                        ).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                else:
                    rows = []
                if not rows:
                    candidate_query = "SELECT * FROM notes WHERE project_id = ?"
                    if not include_deleted:
                        candidate_query += " AND deleted_at IS NULL"
                    candidate_query += " ORDER BY updated_at DESC"
                    candidates = connection.execute(candidate_query, (checked_project,)).fetchall()
                    needle = checked_query.casefold()
                    rows = []
                    for row in candidates:
                        try:
                            body = self._note_body_from_row(
                                checked_project,
                                project,
                                row,
                            )
                        except FileNotFoundError:
                            continue
                        if needle in (row["title"] + "\n" + body).casefold():
                            rows.append(row)
                            if len(rows) >= limit:
                                break
                records: list[NoteRecord] = []
                for row in rows[:limit]:
                    try:
                        body = self._note_body_from_row(
                            checked_project,
                            project,
                            row,
                        )
                    except FileNotFoundError:
                        continue
                    records.append(self._note_from_row(row, body))
                connection.commit()
                return records
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
