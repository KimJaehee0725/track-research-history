"""Regression coverage for the installable private-repository onboarding CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from research_memory.cli.common import CliError, SystemCommandRunner
from research_memory.cli.data_repo import (
    DataRepositoryConfig,
    initialize_data_repository,
    read_schema,
    resolve_data_repository,
    save_config,
)
from research_memory.cli.doctor import run_doctor
from research_memory.cli.github_repo import (
    create_private_repository,
    parse_github_repository,
)
from research_memory.cli.main import main
from research_memory.cli.records import record_note, search_records


class FakeRunner:
    """Small stateful Git/GitHub fake with no shell or network calls."""

    def __init__(
        self,
        *,
        owner: str = "octocat",
        visibility: str = "PRIVATE",
        origin: str | None = None,
        push_urls: tuple[str, ...] | None = None,
        url_rewrites: tuple[str, ...] = (),
        tracked: tuple[str, ...] = (),
        secret_matches: tuple[str, ...] = (),
        dirty: str = "",
        auth_ok: bool = True,
        identity_ok: bool = True,
        available: tuple[str, ...] = ("git", "gh"),
    ) -> None:
        self.owner = owner
        self.visibility = visibility
        self.origin = origin
        self.push_urls = push_urls
        self.url_rewrites = url_rewrites
        self.tracked = tracked
        self.secret_matches = secret_matches
        self.dirty = dirty
        self.auth_ok = auth_ok
        self.identity_ok = identity_ok
        self.available = set(available)
        self.commands: list[tuple[list[str], Path | None]] = []
        self.git_root: Path | None = None

    def which(self, executable: str) -> str | None:
        return f"/fake/{executable}" if executable in self.available else None

    def run(
        self,
        args: list[str] | tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = list(args)
        self.commands.append((command, cwd))
        if command[:4] == ["gh", "auth", "status", "--hostname"]:
            return subprocess.CompletedProcess(
                command, 0 if self.auth_ok else 1, "", ""
            )
        if command[:4] == ["gh", "api", "user", "--jq"]:
            return subprocess.CompletedProcess(command, 0, self.owner + "\n", "")
        if command[:3] == ["gh", "repo", "create"]:
            repository = command[3]
            self.origin = f"git@github.com:{repository}.git"
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(command, 0, self.visibility + "\n", "")
        if command in (
            ["git", "var", "GIT_AUTHOR_IDENT"],
            ["git", "var", "GIT_COMMITTER_IDENT"],
        ):
            return subprocess.CompletedProcess(
                command,
                0 if self.identity_ok else 128,
                "Test User <test@example.invalid>\n" if self.identity_ok else "",
                "",
            )
        if len(command) >= 4 and command[:2] == ["git", "-C"]:
            root = Path(command[2]).resolve()
            git_args = command[3:]
            if git_args == ["init"]:
                self.git_root = root
            if git_args == ["rev-parse", "--show-toplevel"]:
                resolved = self.git_root or root
                return subprocess.CompletedProcess(command, 0, str(resolved) + "\n", "")
            if git_args == ["config", "--get", "remote.origin.url"]:
                return subprocess.CompletedProcess(
                    command,
                    0 if self.origin else 1,
                    (self.origin + "\n") if self.origin else "",
                    "",
                )
            if git_args == ["remote", "get-url", "--all", "origin"]:
                return subprocess.CompletedProcess(
                    command,
                    0 if self.origin else 2,
                    (self.origin + "\n") if self.origin else "",
                    "",
                )
            if git_args == ["remote", "get-url", "--push", "--all", "origin"]:
                urls = (
                    self.push_urls
                    if self.push_urls is not None
                    else ((self.origin,) if self.origin else ())
                )
                return subprocess.CompletedProcess(
                    command,
                    0 if urls else 2,
                    "".join(f"{url}\n" for url in urls),
                    "",
                )
            if git_args == [
                "config",
                "--name-only",
                "--get-regexp",
                r"^url\.",
            ]:
                value = "".join(f"{key}\n" for key in self.url_rewrites)
                return subprocess.CompletedProcess(
                    command,
                    0 if self.url_rewrites else 1,
                    value,
                    "",
                )
            if git_args == ["ls-files", "-z"]:
                value = "\0".join(self.tracked)
                if value:
                    value += "\0"
                return subprocess.CompletedProcess(command, 0, value, "")
            if git_args and git_args[0] == "grep":
                value = "\n".join(self.secret_matches)
                if value:
                    value += "\n"
                return subprocess.CompletedProcess(
                    command,
                    0 if self.secret_matches else 1,
                    value,
                    "",
                )
            if git_args == ["status", "--porcelain"]:
                return subprocess.CompletedProcess(command, 0, self.dirty, "")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")


class LocalGitGitHubFake:
    """Run real local Git while replacing every GitHub CLI operation."""

    def __init__(self, *, push_sink: Path | None = None) -> None:
        self.push_sink = push_sink

    def which(self, executable: str) -> str | None:
        if executable == "gh":
            return "/fake/gh"
        return shutil.which(executable)

    def run(
        self,
        args: list[str] | tuple[str, ...],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = list(args)
        if command[:4] == ["gh", "auth", "status", "--hostname"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["gh", "api", "user", "--jq"]:
            return subprocess.CompletedProcess(command, 0, "octocat\n", "")
        if command[:3] == ["gh", "repo", "create"]:
            repository = command[3]
            source = Path(command[command.index("--source") + 1])
            return subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "remote",
                    "add",
                    "origin",
                    f"git@github.com:{repository}.git",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        if command[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(command, 0, "PRIVATE\n", "")
        if (
            len(command) > 5
            and command[:2] == ["git", "-C"]
            and command[3] == "push"
            and "github.com" in command[4]
        ):
            if self.push_sink is None:
                return subprocess.CompletedProcess(command, 0, "", "")
            command[4] = str(self.push_sink)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_NAME": "Research Memory Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Research Memory Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            }
        )
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )


class DataRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_init_creates_only_data_layout_and_is_idempotent(self) -> None:
        root = initialize_data_repository(self.base / "history-data")
        self.assertEqual(read_schema(root)["schema_version"], 1)
        self.assertTrue((root / "history" / "CONTEXT.md").is_file())
        self.assertTrue((root / "history" / "daily" / ".gitkeep").is_file())
        self.assertFalse((root / "server").exists())
        self.assertFalse((root / "client").exists())

        context = root / "history" / "CONTEXT.md"
        context.write_text("# User context\n", encoding="utf-8")
        initialize_data_repository(root)
        self.assertEqual(context.read_text(encoding="utf-8"), "# User context\n")

    def test_init_refuses_nonempty_directory_and_dangling_symlink(self) -> None:
        occupied = self.base / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(CliError, "non-empty"):
            initialize_data_repository(occupied)
        self.assertEqual((occupied / "keep.txt").read_text(encoding="utf-8"), "keep")

        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "missing", target_is_directory=True)
        with self.assertRaisesRegex(CliError, "symlink"):
            initialize_data_repository(dangling)

    def test_schema_rejects_boolean_version(self) -> None:
        root = initialize_data_repository(self.base / "data")
        (root / ".research-memory" / "schema.json").write_text(
            '{"format":"research-memory-history","schema_version":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CliError, "Expected schema version"):
            read_schema(root)

    def test_explicit_path_ignores_invalid_default_config(self) -> None:
        root = initialize_data_repository(self.base / "explicit")
        xdg = self.base / "xdg"
        default = xdg / "research-memory" / "config.json"
        default.parent.mkdir(parents=True)
        default.write_text("{not-json\n", encoding="utf-8")
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}):
            resolved, config = resolve_data_repository(root)
        self.assertEqual(resolved, root)
        self.assertIsNone(config)

    def test_init_refuses_symlinked_schema_in_nonempty_directory(self) -> None:
        root = self.base / "symlink-schema"
        schema_directory = root / ".research-memory"
        schema_directory.mkdir(parents=True)
        external = self.base / "external-schema.json"
        external.write_text(
            '{"format":"research-memory-history","schema_version":1}\n',
            encoding="utf-8",
        )
        (schema_directory / "schema.json").symlink_to(external)
        with self.assertRaisesRegex(CliError, "non-empty"):
            initialize_data_repository(root)
        self.assertFalse((root / "history").exists())

    def test_system_runner_disables_interactive_git_prompts(self) -> None:
        completed = subprocess.CompletedProcess(["git", "status"], 0, "", "")
        with patch(
            "research_memory.cli.common.subprocess.run",
            return_value=completed,
        ) as run:
            SystemCommandRunner().run(["git", "status"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "Never")
        self.assertIn("BatchMode=yes", kwargs["env"]["GIT_SSH_COMMAND"])
        self.assertIn("StrictHostKeyChecking=yes", kwargs["env"]["GIT_SSH_COMMAND"])
        self.assertEqual(kwargs["env"]["SSH_ASKPASS_REQUIRE"], "never")


class GitHubRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_remote_parser_normalizes_https_and_ssh(self) -> None:
        self.assertEqual(
            parse_github_repository("git@github.com:Owner/research-history.git"),
            "Owner/research-history",
        )
        self.assertEqual(
            parse_github_repository("https://github.com/Owner/research-history.git"),
            "Owner/research-history",
        )
        self.assertIsNone(parse_github_repository("https://example.com/Owner/repo.git"))
        self.assertIsNone(
            parse_github_repository("http://github.com/Owner/research-history.git")
        )
        self.assertIsNone(
            parse_github_repository(
                "https://token@github.com/Owner/research-history.git"
            )
        )
        self.assertIsNone(
            parse_github_repository(
                "https://github.com/Owner/research-history.git?credential=1"
            )
        )

    def test_repo_create_passes_private_and_verifies_visibility(self) -> None:
        runner = FakeRunner()
        target = self.base / "data"
        config_path = self.base / "config.json"
        result = create_private_repository(
            runner,
            name="research-history",
            target=target,
            owner=None,
            config_path=config_path,
        )

        create_command = next(
            command
            for command, _ in runner.commands
            if command[:3] == ["gh", "repo", "create"]
        )
        self.assertEqual(
            create_command,
            [
                "gh",
                "repo",
                "create",
                "octocat/research-history",
                "--private",
                "--source",
                str(target.resolve()),
                "--remote",
                "origin",
            ],
        )
        self.assertEqual(result["visibility"], "PRIVATE")
        self.assertFalse((target / ".research-memory" / "operation.json").exists())
        self.assertEqual(os.stat(config_path).st_mode & 0o777, 0o600)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["repository"], "octocat/research-history")
        identity_calls = [
            (command, cwd)
            for command, cwd in runner.commands
            if command[:2] == ["git", "var"]
        ]
        self.assertEqual(
            {command[-1] for command, _ in identity_calls},
            {"GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"},
        )
        self.assertTrue(
            all(cwd == Path(gettempdir()).resolve() for _, cwd in identity_calls)
        )

    def test_public_visibility_fails_without_writing_config(self) -> None:
        runner = FakeRunner(visibility="PUBLIC")
        config_path = self.base / "config.json"
        with self.assertRaisesRegex(CliError, "did not verify as PRIVATE"):
            create_private_repository(
                runner,
                name="research-history",
                target=self.base / "data",
                owner="octocat",
                config_path=config_path,
            )
        self.assertFalse(config_path.exists())
        self.assertTrue(
            (self.base / "data" / ".research-memory" / "operation.json").is_file()
        )

    def test_repo_create_validates_effective_push_url_before_initial_push(self) -> None:
        runner = FakeRunner(push_urls=("git@github.com:octocat/unexpected-sink.git",))
        with self.assertRaisesRegex(CliError, "do not resolve to the same"):
            create_private_repository(
                runner,
                name="research-history",
                target=self.base / "data",
                owner="octocat",
                config_path=self.base / "config.json",
            )
        self.assertFalse(
            any(
                len(command) > 3
                and command[:2] == ["git", "-C"]
                and command[3] == "push"
                for command, _ in runner.commands
            )
        )

    def test_repo_create_rejects_git_url_rewrites_before_initial_push(self) -> None:
        runner = FakeRunner(url_rewrites=("url.ssh://git@github.com/.pushinsteadof",))
        with self.assertRaisesRegex(CliError, "rewrites are not allowed"):
            create_private_repository(
                runner,
                name="research-history",
                target=self.base / "data",
                owner="octocat",
                config_path=self.base / "config.json",
            )
        self.assertFalse(
            any(
                len(command) > 3
                and command[:2] == ["git", "-C"]
                and command[3] == "push"
                for command, _ in runner.commands
            )
        )

    def test_existing_config_is_preserved_before_any_mutation(self) -> None:
        config_path = self.base / "existing-config.json"
        config_path.write_text("user-owned\n", encoding="utf-8")
        target = self.base / "never-created"
        runner = FakeRunner()
        with self.assertRaisesRegex(CliError, "Refusing to overwrite"):
            create_private_repository(
                runner,
                name="research-history",
                target=target,
                owner="octocat",
                config_path=config_path,
            )
        self.assertEqual(config_path.read_text(encoding="utf-8"), "user-owned\n")
        self.assertFalse(target.exists())
        self.assertEqual(runner.commands, [])

    def test_config_inside_new_data_repository_is_rejected_preflight(self) -> None:
        target = self.base / "data"
        runner = FakeRunner()
        with self.assertRaisesRegex(CliError, "outside"):
            create_private_repository(
                runner,
                name="research-history",
                target=target,
                owner="octocat",
                config_path=target / "client-config.json",
            )
        self.assertFalse(target.exists())
        self.assertEqual(runner.commands, [])

    def test_existing_target_is_preserved_and_never_pushed(self) -> None:
        target = self.base / "existing"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        runner = FakeRunner()
        with self.assertRaisesRegex(CliError, "Refusing to overwrite"):
            create_private_repository(
                runner,
                name="research-history",
                target=target,
                owner="octocat",
                config_path=self.base / "config.json",
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertFalse(
            any(
                command[:3] == ["gh", "repo", "create"]
                for command, _ in runner.commands
            )
        )

    def test_auth_failure_happens_before_filesystem_mutation(self) -> None:
        runner = FakeRunner(auth_ok=False)
        target = self.base / "data"
        with self.assertRaisesRegex(CliError, "not authenticated"):
            create_private_repository(
                runner,
                name="research-history",
                target=target,
                owner="octocat",
                config_path=self.base / "config.json",
            )
        self.assertFalse(target.exists())

    def test_git_identity_failure_happens_before_filesystem_mutation(self) -> None:
        runner = FakeRunner(identity_ok=False)
        target = self.base / "data"
        with self.assertRaisesRegex(CliError, "identity"):
            create_private_repository(
                runner,
                name="research-history",
                target=target,
                owner="octocat",
                config_path=self.base / "config.json",
            )
        self.assertFalse(target.exists())

    def test_repo_create_runs_against_a_real_local_git_repository(self) -> None:
        target = self.base / "real-git"
        config_path = self.base / "real-git-config.json"
        remote = self.base / "private-remote.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote)],
            check=True,
            capture_output=True,
            text=True,
        )
        runner = LocalGitGitHubFake(push_sink=remote)
        result = create_private_repository(
            runner,
            name="research-history",
            target=target,
            owner="octocat",
            config_path=config_path,
        )
        self.assertEqual(result["visibility"], "PRIVATE")
        self.assertTrue((target / ".git").is_dir())
        self.assertFalse((target / ".research-memory" / "operation.json").exists())
        status = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(status.stdout, "")
        doctor = run_doctor(
            runner,
            explicit_path=target,
            config_path=config_path,
        )
        self.assertTrue(doctor.ok)
        record = record_note(
            runner,
            root=target.resolve(),
            text="end-to-end local result",
            title="Local lifecycle",
            expected_repository="octocat/research-history",
        )
        self.assertTrue(Path(record["path"]).is_file())
        self.assertEqual(
            search_records(target.resolve(), "end-to-end")[0]["path"],
            str(Path(record["path"]).relative_to(target.resolve())),
        )
        revisions = subprocess.run(
            ["git", "--git-dir", str(remote), "rev-list", "--count", "refs/heads/main"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(revisions.stdout.strip(), "2")


class DoctorAndRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = initialize_data_repository(self.base / "data")
        self.config_path = self.base / "config.json"
        save_config(
            DataRepositoryConfig(
                path=self.root,
                repository="octocat/research-history",
            ),
            self.config_path,
        )

    def _initialize_real_git(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), "init", "-b", "main"],
            check=True,
            capture_output=True,
            text=True,
        )
        for key, value in (
            ("user.name", "Research Memory Test"),
            ("user.email", "test@example.invalid"),
        ):
            subprocess.run(
                ["git", "-C", str(self.root), "config", key, value],
                check=True,
            )
        subprocess.run(
            ["git", "-C", str(self.root), "add", "--", "."],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-m",
                "initial",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "remote",
                "add",
                "origin",
                "git@github.com:octocat/research-history.git",
            ],
            check=True,
        )

    def test_healthy_doctor_reports_private_clean_repository(self) -> None:
        runner = FakeRunner(
            origin="git@github.com:octocat/research-history.git",
            tracked=(
                ".gitignore",
                ".research-memory/schema.json",
                "history/CONTEXT.md",
                "history/INDEX.md",
            ),
        )
        report = run_doctor(
            runner,
            explicit_path=self.root,
            config_path=self.config_path,
        )
        self.assertTrue(report.ok)
        self.assertTrue(all(check.status == "pass" for check in report.checks))

    def test_doctor_detects_wrong_origin_and_tracked_secret(self) -> None:
        runner = FakeRunner(
            origin="git@github.com:octocat/wrong.git",
            tracked=(".env", ".research-memory/schema.json"),
            secret_matches=("history/daily/leaked-token.md",),
        )
        report = run_doctor(
            runner,
            explicit_path=self.root,
            config_path=self.config_path,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertEqual(by_name["origin"].status, "fail")
        self.assertEqual(by_name["tracked_files"].status, "fail")
        self.assertEqual(by_name["tracked_secrets"].status, "fail")
        self.assertFalse(report.ok)

    def test_doctor_and_record_reject_mismatched_push_destination(self) -> None:
        runner = FakeRunner(
            origin="git@github.com:octocat/research-history.git",
            push_urls=("git@github.com:octocat/public-sink.git",),
        )
        before = sorted((self.root / "history" / "daily").iterdir())
        report = run_doctor(
            runner,
            explicit_path=self.root,
            config_path=self.config_path,
        )
        self.assertEqual(
            {check.name: check for check in report.checks}["origin"].status,
            "fail",
        )
        with self.assertRaisesRegex(CliError, "do not resolve to the same"):
            record_note(
                runner,
                root=self.root,
                text="must not reach the sink",
                title=None,
                expected_repository="octocat/research-history",
            )
        self.assertEqual(sorted((self.root / "history" / "daily").iterdir()), before)

    def test_real_git_pushurl_is_rejected_before_record_write(self) -> None:
        self._initialize_real_git()
        sink = self.base / "unrelated.git"
        subprocess.run(
            ["git", "init", "--bare", str(sink)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "remote",
                "set-url",
                "--push",
                "origin",
                str(sink),
            ],
            check=True,
        )
        before = sorted((self.root / "history" / "daily").iterdir())
        with self.assertRaisesRegex(CliError, "credential-free"):
            record_note(
                LocalGitGitHubFake(),
                root=self.root,
                text="private payload",
                title=None,
                expected_repository="octocat/research-history",
            )
        self.assertEqual(sorted((self.root / "history" / "daily").iterdir()), before)

    def test_chained_git_url_rewrites_are_rejected_before_record_write(self) -> None:
        self._initialize_real_git()
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "remote",
                "set-url",
                "origin",
                "https://github.com/octocat/research-history.git",
            ],
            check=True,
        )
        for key, value in (
            (
                "url.ssh://git@github.com/.pushInsteadOf",
                "https://github.com/",
            ),
            (
                f"url.file://{self.base}/sink/.insteadOf",
                "ssh://git@github.com/",
            ),
        ):
            subprocess.run(
                ["git", "-C", str(self.root), "config", key, value],
                check=True,
            )
        before = sorted((self.root / "history" / "daily").iterdir())
        with self.assertRaisesRegex(CliError, "rewrites are not allowed"):
            record_note(
                LocalGitGitHubFake(),
                root=self.root,
                text="must not be rewritten",
                title=None,
                expected_repository="octocat/research-history",
            )
        self.assertEqual(sorted((self.root / "history" / "daily").iterdir()), before)

    def test_doctor_scans_index_even_after_worktree_secret_is_scrubbed(self) -> None:
        self._initialize_real_git()
        secret = self.root / "history" / "daily" / "credential.md"
        secret.write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nindexed-secret\n",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "add",
                "--",
                str(secret.relative_to(self.root)),
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "commit.gpgSign=false",
                "commit",
                "-m",
                "seed indexed secret",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        secret.write_text("working tree scrubbed\n", encoding="utf-8")
        report = run_doctor(
            LocalGitGitHubFake(),
            explicit_path=self.root,
            config_path=self.config_path,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertEqual(by_name["tracked_secrets"].status, "fail")
        self.assertIn("credential.md", by_name["tracked_secrets"].message)

    def test_doctor_detects_unsafe_config_mode_and_operation_journal(self) -> None:
        self.config_path.chmod(0o644)
        journal = self.root / ".research-memory" / "operation.json"
        journal.write_text('{"operation":"repo.create"}\n', encoding="utf-8")
        report = run_doctor(
            FakeRunner(origin="git@github.com:octocat/research-history.git"),
            explicit_path=self.root,
            config_path=self.config_path,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertEqual(by_name["config_permissions"].status, "fail")
        self.assertEqual(by_name["operation_journal"].status, "fail")
        self.assertFalse(report.ok)

    def test_doctor_reports_operation_journal_even_without_git(self) -> None:
        journal = self.root / ".research-memory" / "operation.json"
        journal.write_text('{"operation":"repo.create"}\n', encoding="utf-8")
        report = run_doctor(
            FakeRunner(available=("gh",)),
            explicit_path=self.root,
            config_path=self.config_path,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertEqual(by_name["operation_journal"].status, "fail")
        self.assertEqual(by_name["git"].status, "fail")

    def test_record_rejects_public_repository_before_writing(self) -> None:
        runner = FakeRunner(
            origin="git@github.com:octocat/research-history.git",
            visibility="PUBLIC",
        )
        before = sorted((self.root / "history" / "daily").iterdir())
        with self.assertRaisesRegex(CliError, "cannot be written"):
            record_note(
                runner,
                root=self.root,
                text="Private result",
                title=None,
                expected_repository="octocat/research-history",
            )
        self.assertEqual(sorted((self.root / "history" / "daily").iterdir()), before)

    def test_record_writes_commits_and_searches(self) -> None:
        runner = FakeRunner(origin="git@github.com:octocat/research-history.git")
        result = record_note(
            runner,
            root=self.root,
            text="Ablation improved recovery by two points.",
            title="Recovery ablation",
            expected_repository="octocat/research-history",
            now=datetime(2026, 7, 30, 12, 34, 56, tzinfo=timezone.utc),
        )
        note = Path(result["path"])
        self.assertTrue(note.is_file())
        self.assertIn("Ablation improved", note.read_text(encoding="utf-8"))
        self.assertEqual(
            search_records(self.root, "two points")[0]["path"],
            str(note.relative_to(self.root)),
        )
        self.assertTrue(
            any(
                command[3:5] == ["push", "git@github.com:octocat/research-history.git"]
                for command, _ in runner.commands
            )
        )

    def test_record_rejects_symlinked_managed_directory_before_commands(self) -> None:
        daily = self.root / "history" / "daily"
        (daily / ".gitkeep").unlink()
        daily.rmdir()
        external = self.base / "external-daily"
        external.mkdir()
        daily.symlink_to(external, target_is_directory=True)
        runner = FakeRunner(origin="git@github.com:octocat/research-history.git")
        with self.assertRaisesRegex(CliError, "Managed directory"):
            record_note(
                runner,
                root=self.root,
                text="must remain inside root",
                title=None,
                expected_repository="octocat/research-history",
            )
        self.assertEqual(list(external.iterdir()), [])
        self.assertEqual(runner.commands, [])

    def test_json_error_is_one_stable_document(self) -> None:
        output = StringIO()
        error_output = StringIO()
        code = main(
            [
                "repo",
                "create",
                "--private",
                "--owner",
                "octocat",
                "--path",
                str(self.root),
                "--config",
                str(self.config_path),
                "--json",
            ],
            runner=FakeRunner(),
            stdout=output,
            stderr=error_output,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["command"], "repo.create")
        self.assertEqual(payload["error"]["code"], "target_exists")
        self.assertEqual(error_output.getvalue(), "")

    def test_json_argument_error_is_one_stable_document(self) -> None:
        output = StringIO()
        error_output = StringIO()
        code = main(
            ["record", "--json"],
            stdout=output,
            stderr=error_output,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["command"], "record")
        self.assertEqual(payload["error"]["code"], "record_input_invalid")
        self.assertEqual(error_output.getvalue(), "")

    def test_json_parse_error_is_one_stable_document(self) -> None:
        output = StringIO()
        error_output = StringIO()
        code = main(
            ["repo", "create", "--json"],
            stdout=output,
            stderr=error_output,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["command"], "repo.create")
        self.assertEqual(payload["error"]["code"], "argument_error")
        self.assertEqual(error_output.getvalue(), "")

    def test_invalid_utf8_stdin_is_a_stable_json_error(self) -> None:
        output = StringIO()
        error_output = StringIO()
        invalid_stdin = TextIOWrapper(BytesIO(b"\xff"), encoding="utf-8")
        code = main(
            ["record", "--stdin", "--json"],
            stdout=output,
            stderr=error_output,
            stdin=invalid_stdin,
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "record_encoding_invalid")
        self.assertEqual(error_output.getvalue(), "")

    def test_record_file_rejects_symlink_before_repository_access(self) -> None:
        source = self.base / "body.md"
        source.write_text("private file body\n", encoding="utf-8")
        link = self.base / "body-link.md"
        link.symlink_to(source)
        output = StringIO()
        code = main(
            ["record", "--file", str(link), "--json"],
            stdout=output,
            stderr=StringIO(),
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"]["code"], "record_file_unsafe")

    def test_record_accepts_stdin_without_process_argument_body(self) -> None:
        runner = FakeRunner(origin="git@github.com:octocat/research-history.git")
        output = StringIO()
        code = main(
            [
                "record",
                "--stdin",
                "--title",
                "stdin note",
                "--no-push",
                "--path",
                str(self.root),
                "--config",
                str(self.config_path),
                "--json",
            ],
            runner=runner,
            stdout=output,
            stdin=StringIO("sensitive stdin result"),
        )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        note = Path(payload["result"]["path"])
        self.assertIn("sensitive stdin result", note.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
