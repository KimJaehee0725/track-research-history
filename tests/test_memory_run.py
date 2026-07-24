"""Regression tests for profile-aware disposable container launchers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_RUN = ROOT / "client" / "memory-run"
CLIENT_DIR = ROOT / "client"


class MemoryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture = self.root / "docker-argv.json"
        self.key = self.root / "research-memory-demo"
        self.key.write_text("not-a-real-key-for-wrapper-test\n", encoding="utf-8")
        self.known_hosts = self.root / "known_hosts"
        self.known_hosts.write_text("example ssh-ed25519 AAAA\n", encoding="utf-8")
        self.ssh_config = self.root / "ssh_config"
        self.ssh_config.write_text("Host Local\n  HostName 127.0.0.1\n", encoding="utf-8")

        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake_docker = fake_bin / "docker"
        fake_docker.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['MEMORY_RUN_CAPTURE']).write_text(\n"
            "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        fake_docker.chmod(fake_docker.stat().st_mode | stat.S_IXUSR)
        self.environment = os.environ.copy()
        self.environment["PATH"] = str(fake_bin) + os.pathsep + self.environment["PATH"]
        self.environment["MEMORY_RUN_CAPTURE"] = str(self.capture)

    def run_memory(self, *arguments: str) -> list[str]:
        completed = subprocess.run(
            [str(MEMORY_RUN), *arguments],
            cwd=ROOT,
            env=self.environment,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return json.loads(self.capture.read_text(encoding="utf-8"))

    def test_profile_supplies_project_key_and_container_profile_selection(self) -> None:
        config = self.root / "profiles.json"
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "default_profile": "demo-rw",
                    "profiles": {
                        "demo-rw": {
                            "project": "demo-project",
                            "host": "Local",
                            "user": "memory-rpc",
                            "identity_file": str(self.key),
                            "known_hosts": str(self.known_hosts),
                            "ssh_config": str(self.ssh_config),
                            "ssh_options": ["IdentitiesOnly=yes"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        argv = self.run_memory(
            "--profile",
            "demo-rw",
            "--config",
            str(config),
            "--client-dir",
            str(CLIENT_DIR),
            "--",
            "example:image",
            "bash",
        )

        self.assertEqual(argv[0:2], ["run", "--rm"])
        self.assertIn("RESEARCH_MEMORY_PROJECT=demo-project", argv)
        self.assertIn("MEMORY_PROFILE=demo-rw", argv)
        self.assertIn("RESEARCH_MEMORY_PROFILE=demo-rw", argv)
        self.assertIn("MEMORY_CONFIG=/run/research-memory/client.json", argv)
        self.assertIn(
            f"type=bind,src={self.key.resolve()},dst=/run/research-memory/id_ed25519,readonly",
            argv,
        )
        self.assertIn(
            f"type=bind,src={config.resolve()},dst=/run/research-memory/client.json,readonly",
            argv,
        )
        self.assertIn(
            f"type=bind,src={self.known_hosts.resolve()},dst=/run/research-memory/known_hosts,readonly",
            argv,
        )
        self.assertIn("MEMORY_KNOWN_HOSTS=/run/research-memory/known_hosts", argv)
        self.assertIn(
            f"type=bind,src={self.ssh_config.resolve()},dst=/run/research-memory/ssh_config,readonly",
            argv,
        )
        self.assertIn("MEMORY_SSH_CONFIG=/run/research-memory/ssh_config", argv)
        self.assertEqual(argv[-2:], ["example:image", "bash"])

    def test_explicit_legacy_arguments_still_work_without_a_profile(self) -> None:
        argv = self.run_memory(
            "--project",
            "demo-project",
            "--identity",
            str(self.key),
            "--host",
            "Local",
            "--known-hosts",
            str(self.known_hosts),
            "--client-dir",
            str(CLIENT_DIR),
            "--",
            "example:image",
        )

        self.assertIn("RESEARCH_MEMORY_PROJECT=demo-project", argv)
        self.assertIn("MEMORY_HOST=Local", argv)
        self.assertNotIn("MEMORY_PROFILE=demo-rw", argv)
        self.assertEqual(argv[-1], "example:image")

    def test_profile_without_optional_ssh_files_remains_usable(self) -> None:
        config = self.root / "minimal-profiles.json"
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": {
                        "minimal-rw": {
                            "project": "demo-project",
                            "host": "Local",
                            "identity_file": str(self.key),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        argv = self.run_memory(
            "--profile",
            "minimal-rw",
            "--config",
            str(config),
            "--client-dir",
            str(CLIENT_DIR),
            "--",
            "example:image",
        )

        self.assertIn("RESEARCH_MEMORY_PROJECT=demo-project", argv)
        self.assertNotIn("MEMORY_KNOWN_HOSTS=/run/research-memory/known_hosts", argv)
        self.assertNotIn("MEMORY_SSH_CONFIG=/run/research-memory/ssh_config", argv)


if __name__ == "__main__":
    unittest.main()
