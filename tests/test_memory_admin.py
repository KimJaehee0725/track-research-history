"""Regression tests for the restricted SSH-key administration helper."""

from __future__ import annotations

import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import pwd
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import admin  # noqa: E402


def public_key_line(comment: str = "test-key", *, material: bytes = b"x" * 32) -> str:
    key_type = b"ssh-ed25519"
    public_material = material
    blob = (
        len(key_type).to_bytes(4, byteorder="big")
        + key_type
        + len(public_material).to_bytes(4, byteorder="big")
        + public_material
    )
    encoded = base64.b64encode(blob).decode("ascii").rstrip("=")
    return f"ssh-ed25519 {encoded} {comment}"


class MemoryAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.authorized_keys = self.root / "authorized_keys"
        self.public_key = self.root / "fab-gym.pub"
        self.public_key.write_text(public_key_line("macbook-fab-gym-rw") + "\n", encoding="ascii")

    def grant(self, *, actor: str = "macbook-fab-gym-rw", project: str = "fab-gym") -> admin.ManagedKey:
        return admin.grant_key(
            self.authorized_keys,
            project=project,
            permission="write",
            actor=actor,
            public_key=admin.read_public_key(self.public_key),
            account=pwd.getpwuid(os.geteuid()).pw_name,
        )

    def test_grant_writes_restricted_rpc_policy_and_preserves_unrelated_lines(self) -> None:
        unrelated = "# operator-maintained entry\nssh-ed25519 AAAAB3NzaC1yc2EAAAADAQABAAABAQ operator\n"
        self.authorized_keys.write_text(unrelated, encoding="utf-8")

        granted = self.grant()
        text = self.authorized_keys.read_text(encoding="utf-8")

        self.assertTrue(text.startswith(unrelated))
        self.assertIn(
            "# research-memory-key-v1 project=fab-gym permission=write "
            "actor=macbook-fab-gym-rw fingerprint=SHA256:",
            text,
        )
        self.assertIn(
            'restrict,command="/opt/research-memory/.venv/bin/python '
            "/opt/research-memory/server/rpc.py --data-dir /srv/research-memory "
            "--allow-project fab-gym --permission write --actor macbook-fab-gym-rw\"",
            text,
        )
        self.assertEqual(granted.project, "fab-gym")
        self.assertEqual(
            [entry.actor for entry in admin.list_managed_keys(self.authorized_keys)],
            ["macbook-fab-gym-rw"],
        )

    def test_revoke_removes_only_complete_managed_blocks(self) -> None:
        self.authorized_keys.write_text(
            "# unmanaged marker-like line must remain\n"
            "# research-memory-key-v1 project=fab-gym permission=write actor=bad fingerprint=SHA256:abc\n"
            "not-a-managed-key\n",
            encoding="utf-8",
        )
        first = self.grant(actor="laptop-fab-gym-rw")
        second_key = self.root / "other.pub"
        second_key.write_text(
            public_key_line("laptop-time-cot-rw", material=b"y" * 32) + "\n",
            encoding="ascii",
        )
        second = admin.grant_key(
            self.authorized_keys,
            project="time-cot",
            permission="write",
            actor="laptop-time-cot-rw",
            public_key=admin.read_public_key(second_key),
            account=pwd.getpwuid(os.geteuid()).pw_name,
        )

        removed = admin.revoke_keys(
            self.authorized_keys,
            actor="laptop-fab-gym-rw",
            project="fab-gym",
            account=pwd.getpwuid(os.geteuid()).pw_name,
        )
        text = self.authorized_keys.read_text(encoding="utf-8")

        self.assertEqual(removed, [first])
        self.assertIn("unmanaged marker-like line must remain", text)
        self.assertIn("actor=bad", text)
        self.assertNotIn("actor=laptop-fab-gym-rw", text)
        self.assertIn("actor=laptop-time-cot-rw", text)
        self.assertEqual(admin.list_managed_keys(self.authorized_keys), [second])

    def test_rejects_unsafe_or_malformed_public_key_input(self) -> None:
        for contents in (
            "command=\"id\" " + public_key_line(),
            public_key_line() + "\n" + public_key_line("second"),
            "ssh-ed25519 not-base64 comment",
        ):
            with self.subTest(contents=contents[:30]):
                candidate = self.root / f"bad-{len(contents)}.pub"
                candidate.write_text(contents, encoding="ascii")
                with self.assertRaises(admin.AdminError):
                    admin.read_public_key(candidate)

        with self.assertRaises(admin.AdminError):
            admin.validate_project("../../all-projects")
        with self.assertRaises(admin.AdminError):
            admin.validate_actor("actor with spaces")
        with self.assertRaises(admin.AdminError):
            admin.render_forced_command(
                project="fab-gym",
                permission="write",
                actor="macbook",
                runtime_root='/opt/research-memory" --allow-all-projects',
                data_dir="/srv/research-memory",
            )

    def test_duplicate_public_key_is_rejected_even_when_existing_line_is_unmanaged(self) -> None:
        public = admin.read_public_key(self.public_key)
        self.authorized_keys.write_text(
            f"ssh-ed25519 {public.encoded} unrelated-existing-entry\n", encoding="ascii"
        )

        with self.assertRaisesRegex(admin.AdminError, "already present"):
            self.grant()

    def test_cli_accepts_path_options_after_key_command_and_emits_json(self) -> None:
        account = pwd.getpwuid(os.geteuid()).pw_name
        output = io.StringIO()
        with redirect_stdout(output):
            result = admin.main(
                [
                    "key",
                    "grant",
                    "--authorized-keys",
                    str(self.authorized_keys),
                    "--account",
                    account,
                    "--project",
                    "fab-gym",
                    "--permission",
                    "write",
                    "--actor",
                    "macbook-fab-gym-rw",
                    "--public-key",
                    str(self.public_key),
                ]
            )
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "granted")

        output = io.StringIO()
        with redirect_stdout(output):
            result = admin.main(
                [
                    "key",
                    "list",
                    "--authorized-keys",
                    str(self.authorized_keys),
                    "--project",
                    "fab-gym",
                ]
            )
        self.assertEqual(result, 0)
        listed = json.loads(output.getvalue())
        self.assertEqual([item["actor"] for item in listed["keys"]], ["macbook-fab-gym-rw"])


if __name__ == "__main__":
    unittest.main()
