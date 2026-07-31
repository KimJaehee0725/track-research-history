"""Safe creation and verification of private GitHub data repositories."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .common import (
    CliError,
    CommandRunner,
    require_executable,
    require_success,
)
from .data_repo import (
    DataRepositoryConfig,
    ensure_config_destination_available,
    initialize_data_repository,
    save_config,
)

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")


def _validate_owner_and_name(owner: str, name: str) -> tuple[str, str]:
    checked_owner = owner.strip()
    checked_name = name.strip()
    if not OWNER_RE.fullmatch(checked_owner):
        raise CliError("invalid_owner", "GitHub owner contains unsupported characters.")
    if not REPOSITORY_RE.fullmatch(checked_name) or checked_name in {".", ".."}:
        raise CliError("invalid_repository_name", "GitHub repository name is invalid.")
    return checked_owner, checked_name


def parse_github_repository(remote: str) -> str | None:
    """Return OWNER/NAME only for credential-free, encrypted GitHub remotes."""

    value = remote.strip()
    if not value:
        return None
    path = ""
    if value.startswith("git@github.com:"):
        path = value.split(":", 1)[1]
    elif value.startswith(("ssh://", "https://")):
        try:
            parsed = urlparse(value)
            hostname = parsed.hostname
        except ValueError:
            return None
        if (hostname or "").lower() != "github.com":
            return None
        if parsed.password is not None or parsed.query or parsed.fragment:
            return None
        if parsed.scheme == "https" and parsed.username is not None:
            return None
        if parsed.scheme == "ssh" and parsed.username != "git":
            return None
        path = parsed.path.lstrip("/")
    else:
        return None
    path = re.sub(r"\.git\Z", "", path).strip("/")
    pieces = path.split("/")
    if len(pieces) != 2:
        return None
    try:
        owner, name = _validate_owner_and_name(pieces[0], pieces[1])
    except CliError:
        return None
    return f"{owner}/{name}"


@dataclass(frozen=True)
class GitHubRemote:
    """Verified effective fetch and push destinations for one GitHub repository."""

    repository: str
    fetch_urls: tuple[str, ...]
    push_urls: tuple[str, ...]

    @property
    def push_url(self) -> str:
        return self.push_urls[0]


def _run_git(
    runner: CommandRunner,
    root: Path,
    *args: str,
    code: str,
    message: str,
    hint: str | None = None,
):
    completed = runner.run(["git", "-C", str(root), *args])
    return require_success(completed, code=code, message=message, hint=hint)


def _write_operation_journal(root: Path, repository: str, stage: str) -> Path:
    path = root / ".research-memory" / "operation.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".operation-",
        suffix=".json",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "operation": "repo.create",
                    "repository": repository,
                    "path": str(root),
                    "stage": stage,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def require_github_authentication(runner: CommandRunner) -> None:
    require_executable(
        runner,
        "gh",
        hint="Install GitHub CLI from https://cli.github.com/ and retry.",
    )
    completed = runner.run(["gh", "auth", "status", "--hostname", "github.com"])
    require_success(
        completed,
        code="github_not_authenticated",
        message="GitHub CLI is not authenticated for github.com.",
        hint="Run `gh auth login` and retry.",
    )


def repository_visibility(runner: CommandRunner, repository: str) -> str:
    completed = runner.run(
        [
            "gh",
            "repo",
            "view",
            repository,
            "--json",
            "visibility",
            "--jq",
            ".visibility",
        ]
    )
    require_success(
        completed,
        code="github_repository_unavailable",
        message=f"Could not inspect GitHub repository visibility: {repository}",
        hint="Check `gh auth status` and confirm that the repository exists.",
    )
    visibility = completed.stdout.strip().upper()
    if visibility not in {"PRIVATE", "PUBLIC", "INTERNAL"}:
        raise CliError(
            "github_visibility_invalid",
            f"GitHub returned an unexpected visibility for {repository}.",
        )
    return visibility


def _effective_origin_urls(
    runner: CommandRunner,
    root: Path,
    *,
    push: bool,
) -> tuple[str, ...]:
    mode = ["--push"] if push else []
    completed = runner.run(
        [
            "git",
            "-C",
            str(root),
            "remote",
            "get-url",
            *mode,
            "--all",
            "origin",
        ]
    )
    urls = tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())
    if completed.returncode != 0 or not urls:
        kind = "push URL" if push else "fetch URL"
        raise CliError(
            "origin_missing",
            f"Git origin {kind} is not configured for the data repository: {root}",
        )
    return urls


def inspect_github_remote(runner: CommandRunner, root: Path) -> GitHubRemote:
    """Validate every effective origin URL and require one shared GitHub slug."""

    rewrites = runner.run(
        [
            "git",
            "-C",
            str(root),
            "config",
            "--name-only",
            "--get-regexp",
            r"^url\.",
        ]
    )
    if rewrites.returncode not in {0, 1}:
        raise CliError(
            "git_config_unavailable",
            "Could not inspect Git URL rewrite configuration.",
        )
    rewrite_keys = sorted(
        {
            key.strip()
            for key in rewrites.stdout.splitlines()
            if key.strip().casefold().endswith((".insteadof", ".pushinsteadof"))
        }
    )
    if rewrite_keys:
        raise CliError(
            "git_url_rewrite_unsupported",
            "Git URL insteadOf/pushInsteadOf rewrites are not allowed for a research data repository.",
            hint="Remove the URL rewrite configuration and use an explicit credential-free GitHub origin.",
        )

    fetch_urls = _effective_origin_urls(runner, root, push=False)
    push_urls = _effective_origin_urls(runner, root, push=True)
    parsed: list[str] = []
    for url in (*fetch_urls, *push_urls):
        repository = parse_github_repository(url)
        if repository is None:
            raise CliError(
                "origin_not_github",
                "Every effective origin fetch and push URL must be a credential-free HTTPS or SSH github.com URL.",
            )
        parsed.append(repository)
    unique = {repository.casefold() for repository in parsed}
    if len(unique) != 1:
        raise CliError(
            "origin_push_mismatch",
            "Origin fetch and push URLs do not resolve to the same GitHub repository.",
            hint="Remove unexpected remote.origin.pushurl values before recording.",
        )
    return GitHubRemote(
        repository=parsed[0],
        fetch_urls=fetch_urls,
        push_urls=push_urls,
    )


def verify_private_repository(
    runner: CommandRunner,
    root: Path,
    *,
    expected_repository: str | None = None,
) -> GitHubRemote:
    require_executable(
        runner,
        "git",
        hint="Install Git and retry.",
    )
    require_github_authentication(runner)
    remote = inspect_github_remote(runner, root)
    if (
        expected_repository
        and remote.repository.casefold() != expected_repository.casefold()
    ):
        raise CliError(
            "origin_mismatch",
            f"Configured repository is {expected_repository}, but origin is {remote.repository}.",
            hint="Do not replace origin implicitly; select the intended data repository.",
        )
    visibility = repository_visibility(runner, remote.repository)
    if visibility != "PRIVATE":
        raise CliError(
            "public_repository",
            f"{remote.repository} is {visibility}. Personal research history cannot be written.",
            hint="Make the repository private and rerun `research-memory doctor`.",
        )
    return remote


def create_private_repository(
    runner: CommandRunner,
    *,
    name: str,
    target: Path,
    owner: str | None,
    config_path: Path | None,
) -> dict[str, str]:
    """Create a fresh local data repository, push it, and verify PRIVATE."""

    if target.exists() or target.is_symlink():
        raise CliError(
            "target_exists",
            f"Refusing to overwrite an existing path: {target}",
            hint="Choose a new `--path` or inspect the existing directory manually.",
        )
    config_destination = ensure_config_destination_available(config_path)
    resolved_target = target.expanduser().resolve()
    resolved_config = config_destination.resolve()
    if resolved_config == resolved_target or resolved_target in resolved_config.parents:
        raise CliError(
            "config_inside_repository",
            "Client configuration must be stored outside the research data repository.",
            hint="Omit --config or choose a path outside the new --path.",
        )
    require_executable(runner, "git", hint="Install Git and retry.")
    require_github_authentication(runner)
    identity_context = Path(tempfile.gettempdir()).resolve()
    for identity_name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        identity = runner.run(
            ["git", "var", identity_name],
            cwd=identity_context,
        )
        require_success(
            identity,
            code="git_identity_missing",
            message="Git author and committer identity are not configured globally.",
            hint="Configure `git config --global user.name` and `user.email`, then retry.",
        )
    if owner is None:
        completed = runner.run(["gh", "api", "user", "--jq", ".login"])
        require_success(
            completed,
            code="github_owner_unavailable",
            message="Could not determine the active GitHub account.",
            hint="Pass `--owner OWNER` explicitly.",
        )
        owner = completed.stdout.strip()
    checked_owner, checked_name = _validate_owner_and_name(owner, name)
    repository = f"{checked_owner}/{checked_name}"

    root = initialize_data_repository(target)
    journal = _write_operation_journal(root, repository, "initialized")
    _run_git(
        runner,
        root,
        "init",
        code="git_init_failed",
        message=f"Could not initialize Git repository: {root}",
    )
    _write_operation_journal(root, repository, "git-initialized")
    _run_git(
        runner,
        root,
        "checkout",
        "-B",
        "main",
        code="git_branch_failed",
        message="Could not create the initial main branch.",
    )
    top_level = _run_git(
        runner,
        root,
        "rev-parse",
        "--show-toplevel",
        code="git_root_unavailable",
        message="Could not verify the data repository Git root.",
    ).stdout.strip()
    try:
        exact_root = Path(top_level).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise CliError(
            "git_root_invalid", "Git returned an invalid repository root."
        ) from exc
    if exact_root != root:
        raise CliError(
            "git_root_mismatch",
            f"Git resolved {exact_root}, not the intended data repository {root}.",
        )
    existing_origin = runner.run(
        ["git", "-C", str(root), "config", "--get", "remote.origin.url"]
    )
    if existing_origin.returncode == 0 and existing_origin.stdout.strip():
        raise CliError(
            "origin_exists",
            "Refusing to replace an existing Git origin.",
        )
    _run_git(
        runner,
        root,
        "add",
        "--",
        ".",
        code="git_add_failed",
        message="Could not stage the initial data-repository structure.",
    )
    _run_git(
        runner,
        root,
        "-c",
        "commit.gpgSign=false",
        "commit",
        "-m",
        "Initialize private research history",
        code="git_commit_failed",
        message="Could not create the initial Git commit.",
        hint="The local directory and operation journal were preserved for inspection.",
    )
    _write_operation_journal(root, repository, "initial-commit")
    created = runner.run(
        [
            "gh",
            "repo",
            "create",
            repository,
            "--private",
            "--source",
            str(root),
            "--remote",
            "origin",
        ]
    )
    require_success(
        created,
        code="github_create_failed",
        message=f"GitHub repository creation failed: {repository}",
        hint="The local directory was preserved. Inspect it before retrying.",
    )
    _write_operation_journal(root, repository, "github-created")
    visibility = repository_visibility(runner, repository)
    if visibility != "PRIVATE":
        raise CliError(
            "visibility_verification_failed",
            f"Created repository did not verify as PRIVATE: {repository} ({visibility})",
            hint="Do not record research data until the repository is private.",
        )
    actual_remote = inspect_github_remote(runner, root)
    if actual_remote.repository.casefold() != repository.casefold():
        raise CliError(
            "origin_mismatch",
            f"GitHub created {repository}, but local origin does not match it.",
            hint="Inspect the preserved local repository; origin was not rewritten.",
        )
    pushed = runner.run(
        [
            "git",
            "-C",
            str(root),
            "push",
            actual_remote.push_url,
            "HEAD:refs/heads/main",
        ]
    )
    require_success(
        pushed,
        code="git_push_failed",
        message="The private repository was created, but the initial push failed.",
        hint="The local directory and private GitHub repository were preserved.",
    )

    written_config = save_config(
        DataRepositoryConfig(path=root, repository=repository),
        config_path,
    )
    journal.unlink()
    return {
        "path": str(root),
        "repository": repository,
        "visibility": visibility,
        "config": str(written_config),
    }
