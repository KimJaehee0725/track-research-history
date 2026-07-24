"""Regression coverage for memctl's local profile convenience layer."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"
if str(CLIENT) not in sys.path:
    sys.path.insert(0, str(CLIENT))

import profiles  # noqa: E402


class ClientProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "client.json"

    def invoke_memctl(
        self, *args: str, environment: dict[str, str] | None = None
    ) -> tuple[int, dict[str, object], str]:
        env = os.environ.copy()
        if environment:
            env.update(environment)
        completed = subprocess.run(
            [sys.executable, str(CLIENT / "memctl.py"), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        output = completed.stdout.strip()
        self.assertTrue(output, f"expected JSON output; stderr={completed.stderr!r}")
        return completed.returncode, json.loads(output), completed.stderr

    def add_default_profile(self, name: str = "fab-gym-rw") -> None:
        code, response, stderr = self.invoke_memctl(
            "--config",
            str(self.config),
            "profile",
            "add",
            name,
            "--project",
            "fab-gym",
            "--host",
            "Local",
            "--user",
            "memory-rpc",
            "--identity",
            "~/.ssh/research-memory-fab-gym-rw",
            "--known-hosts",
            "~/.ssh/known_hosts",
            "--set-default",
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(response["ok"])

    def dry_run(
        self, *command: str, environment: dict[str, str] | None = None
    ) -> dict[str, object]:
        code, response, stderr = self.invoke_memctl(
            "--config", str(self.config), "--dry-run", *command, environment=environment
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(response["ok"])
        self.assertTrue(response["dry_run"])
        return response

    def assert_request(self, response: dict[str, object], op: str, params: dict[str, object]) -> None:
        request = response["request"]
        self.assertIsInstance(request, dict)
        self.assertEqual(request["op"], op)
        self.assertEqual(request["project"], "fab-gym")
        self.assertEqual(request["params"], params)

    def test_profile_add_sets_default_uses_owner_only_file_and_no_key_material(self) -> None:
        self.add_default_profile()

        document = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["default_profile"], "fab-gym-rw")
        profile = document["profiles"]["fab-gym-rw"]
        self.assertEqual(profile["project"], "fab-gym")
        self.assertEqual(profile["identity_file"], str(Path("~/.ssh/research-memory-fab-gym-rw").expanduser()))
        self.assertNotIn("private_key", profile)
        self.assertNotIn("passphrase", profile)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

        resolved = profiles.resolve_profile_config(str(self.config), "fab-gym-rw")
        self.assertEqual(resolved["host"], "Local")
        self.assertEqual(resolved["project"], "fab-gym")

    def test_default_profile_omits_project_for_every_note_operation(self) -> None:
        self.add_default_profile()
        note_file = self.root / "today.md"
        note_file.write_text("# Today\n", encoding="utf-8")

        self.assert_request(self.dry_run("note", "list"), "note.list", {})
        self.assert_request(
            self.dry_run("note", "read", "setup/connection.md"),
            "note.read",
            {"path": "setup/connection.md"},
        )
        write = self.dry_run("note", "write", "setup/today.md", "--file", str(note_file))
        write_request = write["request"]
        self.assertIsInstance(write_request, dict)
        self.assertEqual(write_request["op"], "note.write")
        self.assertEqual(write_request["project"], "fab-gym")
        self.assertEqual(write_request["params"]["path"], "setup/today.md")
        self.assertIn("content_summary", write_request["params"])
        self.assert_request(
            self.dry_run("note", "delete", "setup/today.md"),
            "note.delete",
            {"path": "setup/today.md"},
        )
        self.assert_request(
            self.dry_run("note", "restore", "trash-01"),
            "note.restore",
            {"trash_id": "trash-01"},
        )
        explicit_restore = self.dry_run("note", "restore", "alienlm", "trash-02")
        explicit_restore_request = explicit_restore["request"]
        self.assertIsInstance(explicit_restore_request, dict)
        self.assertEqual(explicit_restore_request["project"], "alienlm")
        self.assertEqual(explicit_restore_request["params"], {"trash_id": "trash-02"})
        self.assert_request(
            self.dry_run("note", "search", "SSH RPC"),
            "note.search",
            {"query": "SSH RPC", "limit": 20},
        )

    def test_explicit_project_and_existing_flat_config_remain_compatible(self) -> None:
        self.config.write_text(
            json.dumps(
                {
                    "host": "Local",
                    "user": "memory-rpc",
                    "identity_file": "~/.ssh/flat-key",
                    "known_hosts": "~/.ssh/known_hosts",
                }
            ),
            encoding="utf-8",
        )
        response = self.dry_run("note", "read", "alienlm", "notes/legacy.md")
        request = response["request"]
        self.assertIsInstance(request, dict)
        self.assertEqual(request["project"], "alienlm")
        self.assertEqual(request["params"], {"path": "notes/legacy.md"})

        command = response["ssh_command"]
        self.assertIsInstance(command, list)
        self.assertIn("memory-rpc@Local", command)
        self.assertIn(str(Path("~/.ssh/flat-key").expanduser()), command)

    def test_memory_profile_overrides_document_default_and_profile_cli_supports_after_command_flags(self) -> None:
        profiles.add_profile(
            str(self.config),
            "alienlm-ro",
            {"project": "alienlm", "host": "AlienHost"},
            set_default=True,
        )
        profiles.add_profile(
            str(self.config),
            "fab-gym-rw",
            {"project": "fab-gym", "host": "Local"},
        )
        response = self.dry_run(
            "note", "read", "setup/connection.md", environment={"MEMORY_PROFILE": "fab-gym-rw"}
        )
        request = response["request"]
        self.assertIsInstance(request, dict)
        self.assertEqual(request["project"], "fab-gym")

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = profiles.main(
                ["resolve", "--config", str(self.config), "--profile", "alienlm-ro"]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue()), {"host": "AlienHost", "project": "alienlm"})

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = profiles.main(
                ["get", "--config", str(self.config), "--profile", "fab-gym-rw", "--field", "project"]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(stdout.getvalue().strip(), "fab-gym")

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = profiles.main(
                [
                    "get",
                    "--config",
                    str(self.config),
                    "--profile",
                    "fab-gym-rw",
                    "--field",
                    "known_hosts",
                    "--optional",
                ]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_profile_lifecycle_and_rejects_unknown_secret_like_fields(self) -> None:
        self.add_default_profile()
        code, listed, stderr = self.invoke_memctl("--config", str(self.config), "profile", "list")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(listed["result"]["profiles"], [{"is_default": True, "name": "fab-gym-rw", "project": "fab-gym"}])

        code, shown, stderr = self.invoke_memctl(
            "--config", str(self.config), "profile", "show", "fab-gym-rw"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(shown["result"]["resolved"]["project"], "fab-gym")

        profiles.add_profile(
            str(self.config), "alienlm-rw", {"project": "alienlm", "host": "AlienHost"}
        )
        code, selected, stderr = self.invoke_memctl(
            "--config", str(self.config), "profile", "use", "alienlm-rw"
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(selected["result"]["default_profile"], "alienlm-rw")
        code, removed, stderr = self.invoke_memctl(
            "--config", str(self.config), "profile", "remove", "alienlm-rw"
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(removed["result"]["cleared_default"])

        with self.assertRaises(profiles.ProfileError):
            profiles.validate_config_document(
                {"profiles": {"unsafe": {"project": "fab-gym", "private_key": "secret"}}}
            )


if __name__ == "__main__":
    unittest.main()
