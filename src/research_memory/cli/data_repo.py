"""Local data-only repository layout and non-secret client configuration."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import CliError

SCHEMA_VERSION = 1
SCHEMA_DIR = ".research-memory"
SCHEMA_FILE = "schema.json"
CONFIG_VERSION = 1
HISTORY_FOLDERS = (
    "daily",
    "changes",
    "decisions",
    "ideas",
    "experiments",
    "handoffs",
    "capsules",
    "sessions",
)


@dataclass(frozen=True)
class DataRepositoryConfig:
    path: Path
    repository: str
    visibility: str = "PRIVATE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "path": str(self.path),
            "repository": self.repository,
            "visibility": self.visibility,
        }


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "research-memory" / "config.json"
    return Path.home() / ".config" / "research-memory" / "config.json"


def schema_path(root: Path) -> Path:
    return root / SCHEMA_DIR / SCHEMA_FILE


def _write_new(path: Path, text: str) -> None:
    if path.is_symlink():
        raise CliError("unsafe_layout", f"Managed file must not be a symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise CliError("unsafe_layout", f"Managed path is not a file: {path}")
        return
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        raise CliError(
            "unsafe_layout", f"Managed file changed during initialization: {path}"
        )


def _ensure_managed_directory(path: Path) -> None:
    if path.is_symlink():
        raise CliError(
            "unsafe_layout", f"Managed directory must not be a symlink: {path}"
        )
    if path.exists():
        if not path.is_dir():
            raise CliError("unsafe_layout", f"Managed path is not a directory: {path}")
        return
    path.mkdir()


def _schema_document() -> str:
    return (
        json.dumps(
            {
                "format": "research-memory-history",
                "schema_version": SCHEMA_VERSION,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def initialize_data_repository(path: Path) -> Path:
    """Create the minimal data-only structure without overwriting user files."""

    raw_path = path.expanduser()
    if raw_path.is_symlink():
        raise CliError("unsafe_path", "The data repository path must not be a symlink.")
    root = raw_path.resolve()
    if root.exists() and not root.is_dir():
        raise CliError(
            "path_not_directory", f"Data repository path is not a directory: {root}"
        )
    if root.exists() and any(root.iterdir()):
        existing_schema = schema_path(root)
        if existing_schema.is_symlink() or not existing_schema.is_file():
            raise CliError(
                "directory_not_empty",
                f"Refusing to initialize a non-empty directory without a Research Memory schema: {root}",
                hint="Choose a new empty directory or pass the path of an existing data repository.",
            )
        read_schema(root)

    root.mkdir(parents=True, exist_ok=True)
    _ensure_managed_directory(root / SCHEMA_DIR)
    _ensure_managed_directory(root / "history")
    for folder in HISTORY_FOLDERS:
        _ensure_managed_directory(root / "history" / folder)
    _write_new(schema_path(root), _schema_document())
    _write_new(
        root / ".gitignore",
        """# Local search and operation state
.research-memory/index.sqlite3
.research-memory/index.sqlite3-*
.research-memory/cache/
.research-memory/operations/
.research-memory/operation.json

# Secrets and machine-local files
.env
.env.*
!.env.example
*.key
*.pem
.DS_Store
""",
    )
    _write_new(
        root / "README.md",
        """# Private Research History

This repository contains personal Markdown research records created by
`research-memory`. Keep the GitHub repository private.

Application source, credentials, local indexes, and runtime state do not belong
in this repository.
""",
    )
    _write_new(
        root / "history" / "CONTEXT.md",
        """# Project Context

## Research Goal

-

## Current Decisions

-

## Open Questions And Risks

-
""",
    )
    _write_new(
        root / "history" / "INDEX.md",
        """# Research History Index

Records are appended below by `research-memory record`.
""",
    )
    for folder in HISTORY_FOLDERS:
        _write_new(root / "history" / folder / ".gitkeep", "")
    validate_data_repository(root)
    return root


def read_schema(root: Path) -> dict[str, Any]:
    path = schema_path(root)
    if not path.is_file() or path.is_symlink():
        raise CliError(
            "schema_missing",
            f"Research Memory schema is missing: {path}",
            hint="Run `research-memory init --path PATH` in an empty directory.",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(
            "schema_invalid", f"Research Memory schema is invalid: {path}"
        ) from exc
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if (
        isinstance(version, bool)
        or version != SCHEMA_VERSION
        or payload.get("format") != "research-memory-history"
    ):
        raise CliError(
            "schema_unsupported",
            f"Expected schema version {SCHEMA_VERSION} in {path}.",
        )
    return payload


def validate_data_repository(root: Path) -> dict[str, Any]:
    """Validate every path that record/search may traverse or replace."""

    if root.is_symlink() or not root.is_dir():
        raise CliError(
            "unsafe_layout", f"Data repository must be a regular directory: {root}"
        )
    managed_directories = (
        root / SCHEMA_DIR,
        root / "history",
        *(root / "history" / folder for folder in HISTORY_FOLDERS),
    )
    for directory in managed_directories:
        if directory.is_symlink() or not directory.is_dir():
            raise CliError(
                "unsafe_layout",
                f"Managed directory is missing or unsafe: {directory}",
            )
    for path in (
        schema_path(root),
        root / "history" / "CONTEXT.md",
        root / "history" / "INDEX.md",
    ):
        if path.is_symlink() or not path.is_file():
            raise CliError(
                "unsafe_layout",
                f"Managed file is missing or unsafe: {path}",
            )
    return read_schema(root)


def ensure_config_destination_available(path: Path | None = None) -> Path:
    """Resolve a create-only config destination without changing the filesystem."""

    destination = (path or default_config_path()).expanduser()
    if destination.is_symlink():
        raise CliError(
            "unsafe_config", "Refusing to replace a symlinked configuration file."
        )
    if destination.exists():
        raise CliError(
            "config_exists",
            f"Refusing to overwrite an existing configuration file: {destination}",
            hint="Use the existing configuration or pass a new explicit --config path.",
        )
    return destination


def save_config(config: DataRepositoryConfig, path: Path | None = None) -> Path:
    """Atomically create owner-only, non-secret client state."""

    destination = ensure_config_destination_available(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".config-",
        suffix=".json",
        dir=str(destination.parent),
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise CliError(
                "config_exists",
                f"Refusing to overwrite an existing configuration file: {destination}",
            ) from exc
        temporary.unlink()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def load_config(
    path: Path | None = None, *, required: bool = True
) -> DataRepositoryConfig | None:
    source = (path or default_config_path()).expanduser()
    if not source.exists():
        if required:
            raise CliError(
                "config_missing",
                f"Research Memory configuration does not exist: {source}",
                hint="Run `research-memory repo create --private` or pass `--path`.",
            )
        return None
    if source.is_symlink() or not source.is_file():
        raise CliError(
            "unsafe_config", f"Configuration must be a regular file: {source}"
        )
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("config_invalid", f"Configuration is invalid: {source}") from exc
    version = payload.get("version") if isinstance(payload, dict) else None
    if isinstance(version, bool) or version != CONFIG_VERSION:
        raise CliError(
            "config_unsupported", f"Unsupported configuration format: {source}"
        )
    raw_path = payload.get("path")
    repository = payload.get("repository")
    visibility = payload.get("visibility", "")
    if not isinstance(raw_path, str) or not raw_path:
        raise CliError("config_invalid", f"Configuration path is missing: {source}")
    if not isinstance(repository, str) or "/" not in repository:
        raise CliError(
            "config_invalid", f"Configuration repository is invalid: {source}"
        )
    if visibility != "PRIVATE":
        raise CliError(
            "config_not_private",
            "Configured research repository is not marked PRIVATE.",
        )
    return DataRepositoryConfig(
        path=Path(raw_path).expanduser().resolve(),
        repository=repository,
        visibility=visibility,
    )


def resolve_data_repository(
    explicit_path: Path | None,
    config_path: Path | None = None,
) -> tuple[Path, DataRepositoryConfig | None]:
    if explicit_path is not None and config_path is None:
        config = None
    else:
        config = load_config(config_path, required=explicit_path is None)
    if explicit_path is not None:
        if explicit_path.expanduser().is_symlink():
            raise CliError(
                "unsafe_path", "The data repository path must not be a symlink."
            )
        root = explicit_path.expanduser().resolve()
        if config is not None and config.path != root:
            config = None
    else:
        assert config is not None
        root = config.path
    validate_data_repository(root)
    return root, config


def config_permissions(path: Path | None = None) -> int | None:
    source = (path or default_config_path()).expanduser()
    if not source.exists() or source.is_symlink():
        return None
    return stat.S_IMODE(source.stat().st_mode)
