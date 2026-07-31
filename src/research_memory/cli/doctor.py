"""Deterministic safety diagnostics for a private research data repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .common import Check, CliError, CommandRunner
from .data_repo import (
    DataRepositoryConfig,
    config_permissions,
    default_config_path,
    load_config,
    read_schema,
    validate_data_repository,
)
from .github_repo import inspect_github_remote, repository_visibility

RISKY_TRACKED_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
}
RISKY_TRACKED_SUFFIXES = {
    ".db",
    ".key",
    ".pem",
    ".sqlite",
    ".sqlite3",
}
TRACKED_SECRET_PATTERN = (
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
)


@dataclass(frozen=True)
class DoctorReport:
    path: str | None
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "path": self.path,
            "checks": [check.to_dict() for check in self.checks],
        }


def _risky_tracked_path(value: str) -> bool:
    normalized = value.replace("\\", "/").strip("/")
    if not normalized:
        return False
    path = Path(normalized)
    name = path.name.casefold()
    if name in RISKY_TRACKED_NAMES or name.startswith(".env."):
        return True
    if path.suffix.casefold() in RISKY_TRACKED_SUFFIXES:
        return True
    return (
        normalized.startswith(".research-memory/")
        and normalized != ".research-memory/schema.json"
    )


def _configuration_check(
    explicit_path: Path | None,
    config_path: Path | None,
    checks: list[Check],
) -> tuple[Path | None, DataRepositoryConfig | None]:
    source = config_path or default_config_path()
    if explicit_path is not None and config_path is None:
        config = None
    else:
        try:
            config = load_config(config_path, required=explicit_path is None)
        except CliError as exc:
            checks.append(Check("config", "fail", exc.message))
            return (
                explicit_path.expanduser().resolve() if explicit_path else None
            ), None
    if config is None:
        message = (
            "Explicit data path supplied; saved configuration is not required."
            if explicit_path is not None and config_path is None
            else f"No saved configuration at {source}."
        )
        checks.append(Check("config", "warn", message))
    else:
        checks.append(
            Check("config", "pass", f"Configuration points to {config.repository}.")
        )
        mode = config_permissions(config_path)
        if mode is None:
            checks.append(
                Check(
                    "config_permissions", "fail", "Configuration is not a regular file."
                )
            )
        elif mode & 0o077:
            checks.append(
                Check(
                    "config_permissions",
                    "fail",
                    f"Configuration permissions are {mode:04o}; expected owner-only 0600.",
                )
            )
        else:
            checks.append(
                Check(
                    "config_permissions", "pass", f"Configuration mode is {mode:04o}."
                )
            )
    root = (
        explicit_path.expanduser().resolve()
        if explicit_path
        else (config.path if config else None)
    )
    if explicit_path and config and config.path != root:
        checks.append(
            Check(
                "configured_path",
                "warn",
                "Explicit path differs from the saved data repository; origin will be inspected directly.",
            )
        )
        config = None
    return root, config


def run_doctor(
    runner: CommandRunner,
    *,
    explicit_path: Path | None = None,
    config_path: Path | None = None,
) -> DoctorReport:
    checks: list[Check] = []
    if explicit_path is not None and explicit_path.expanduser().is_symlink():
        checks.append(
            Check(
                "data_path",
                "fail",
                f"Data repository path must not be a symlink: {explicit_path.expanduser()}",
            )
        )
        return DoctorReport(path=str(explicit_path.expanduser()), checks=tuple(checks))
    root, config = _configuration_check(explicit_path, config_path, checks)
    if root is None:
        checks.append(
            Check("data_path", "fail", "No data repository path is available.")
        )
        return DoctorReport(path=None, checks=tuple(checks))

    if root.is_symlink() or not root.is_dir():
        checks.append(
            Check(
                "data_path", "fail", f"Data repository directory is unavailable: {root}"
            )
        )
        return DoctorReport(path=str(root), checks=tuple(checks))
    checks.append(Check("data_path", "pass", f"Data repository exists: {root}"))

    try:
        schema = read_schema(root)
    except CliError as exc:
        checks.append(Check("schema", "fail", exc.message))
    else:
        checks.append(
            Check("schema", "pass", f"Schema version is {schema['schema_version']}.")
        )
    try:
        validate_data_repository(root)
    except CliError as exc:
        checks.append(Check("layout", "fail", exc.message))
    else:
        checks.append(
            Check(
                "layout",
                "pass",
                "Managed data paths are regular files and directories.",
            )
        )

    journal = root / ".research-memory" / "operation.json"
    if journal.exists() or journal.is_symlink():
        checks.append(
            Check(
                "operation_journal", "fail", f"Unfinished operation journal: {journal}"
            )
        )
    else:
        checks.append(
            Check("operation_journal", "pass", "No unfinished operation journal.")
        )

    if runner.which("git") is None:
        checks.append(Check("git", "fail", "Git is not installed."))
        return DoctorReport(path=str(root), checks=tuple(checks))
    inside = runner.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    if inside.returncode != 0 or not inside.stdout.strip():
        checks.append(Check("git_root", "fail", "Path is not a Git repository."))
        return DoctorReport(path=str(root), checks=tuple(checks))
    resolved_git_root = Path(inside.stdout.strip()).expanduser().resolve()
    if resolved_git_root != root:
        checks.append(
            Check(
                "git_root",
                "fail",
                f"Git root is {resolved_git_root}, not the configured data path.",
            )
        )
    else:
        checks.append(Check("git_root", "pass", "Git root matches the data path."))

    try:
        remote = inspect_github_remote(runner, root)
    except CliError as exc:
        repository = None
        checks.append(
            Check(
                "origin",
                "fail",
                exc.message,
            )
        )
    else:
        repository = remote.repository
    if repository and config and repository.casefold() != config.repository.casefold():
        checks.append(
            Check(
                "origin",
                "fail",
                f"Origin is {repository}, but configuration expects {config.repository}.",
            )
        )
    elif repository:
        checks.append(
            Check(
                "origin",
                "pass",
                f"Origin fetch and push URLs resolve to {repository}.",
            )
        )

    if runner.which("gh") is None:
        checks.append(Check("github_cli", "fail", "GitHub CLI is not installed."))
    else:
        auth = runner.run(["gh", "auth", "status", "--hostname", "github.com"])
        if auth.returncode != 0:
            checks.append(
                Check("github_auth", "fail", "GitHub CLI is not authenticated.")
            )
        else:
            checks.append(
                Check("github_auth", "pass", "GitHub CLI authentication is active.")
            )
            if repository:
                try:
                    visibility = repository_visibility(runner, repository)
                except CliError as exc:
                    checks.append(Check("visibility", "fail", exc.message))
                else:
                    status = "pass" if visibility == "PRIVATE" else "fail"
                    checks.append(
                        Check(
                            "visibility",
                            status,
                            f"{repository} visibility is {visibility}.",
                        )
                    )

    tracked = runner.run(["git", "-C", str(root), "ls-files", "-z"])
    if tracked.returncode != 0:
        checks.append(
            Check("tracked_files", "fail", "Could not inspect tracked files.")
        )
    else:
        risky = sorted(
            value for value in tracked.stdout.split("\0") if _risky_tracked_path(value)
        )
        if risky:
            checks.append(
                Check(
                    "tracked_files",
                    "fail",
                    "Tracked secret/index/runtime paths: " + ", ".join(risky),
                )
            )
        else:
            checks.append(
                Check("tracked_files", "pass", "No blocked tracked paths found.")
            )

    secret_scan = runner.run(
        [
            "git",
            "-C",
            str(root),
            "grep",
            "--cached",
            "-I",
            "-l",
            "-E",
            "-e",
            TRACKED_SECRET_PATTERN,
            "--",
            ".",
        ]
    )
    secret_paths = sorted(
        path for path in secret_scan.stdout.splitlines() if path.strip()
    )
    if secret_scan.returncode not in {0, 1}:
        checks.append(
            Check(
                "tracked_secrets",
                "fail",
                "Could not scan tracked text for credentials.",
            )
        )
    elif secret_paths:
        checks.append(
            Check(
                "tracked_secrets",
                "fail",
                "Tracked files contain credential-shaped text: "
                + ", ".join(secret_paths),
            )
        )
    else:
        checks.append(
            Check(
                "tracked_secrets",
                "pass",
                "No credential-shaped tracked text found.",
            )
        )

    dirty = runner.run(["git", "-C", str(root), "status", "--porcelain"])
    if dirty.returncode != 0:
        checks.append(
            Check("working_tree", "fail", "Could not inspect the Git working tree.")
        )
    elif dirty.stdout.strip():
        checks.append(
            Check("working_tree", "warn", "Working tree has uncommitted changes.")
        )
    else:
        checks.append(Check("working_tree", "pass", "Working tree is clean."))

    return DoctorReport(path=str(root), checks=tuple(checks))
