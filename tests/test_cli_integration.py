from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.collab_behavior_smoke import HistoryCLI, file_snapshot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/history.py"
spec = importlib.util.spec_from_file_location("history_cli_integration", SCRIPT)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


class CLIIntegrationTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        return root, HistoryCLI(root)

    def decision(self, cli, status):
        return cli.emitted_path(cli.run("decision", "--title", f"Zebra {status}", "--decision", f"Zebra policy {status}", "--status", status))

    def test_status_filter_is_applied_in_search_start_and_recall(self):
        root, cli = self.fixture()
        accepted = self.decision(cli, "accepted")
        rejected = self.decision(cli, "rejected")
        before = file_snapshot(root)
        for command in [("search", "Zebra"), ("start", "--query", "Zebra"), ("recall", "--query", "Zebra")]:
            with self.subTest(command=command):
                result = json.loads(cli.run(*command, "--status", "accepted", "--json").stdout)
                paths = [item["path"] for item in result["results"]]
                self.assertIn(str(accepted.relative_to(root)), paths)
                self.assertNotIn(str(rejected.relative_to(root)), paths)
                self.assertTrue(all(item["metadata"]["status"] == "accepted" for item in result["results"]))
        self.assertEqual(before, file_snapshot(root))

    def test_chunks_per_file_option_reaches_search_and_recall(self):
        root, cli = self.fixture()
        folder = root / "history/changes"
        folder.mkdir(parents=True)
        (folder / "2026-01-01-000000-zebra.md").write_text("---\ntype: change\nstatus: completed\n---\n# Zebra\n\n## First\n\nZebra initial implementation.\n\n## Second\n\nZebra independent validation.\n", encoding="utf-8")
        for command in [("search", "Zebra"), ("recall", "--query", "Zebra")]:
            with self.subTest(command=command):
                default = json.loads(cli.run(*command, "--json").stdout)
                expanded = json.loads(cli.run(*command, "--chunks-per-file", "2", "--json").stdout)
                self.assertEqual(1, len(default["results"]))
                self.assertEqual(2, len(expanded["results"]))
                self.assertEqual(2, len({result["heading"] for result in expanded["results"]}))

    def test_exact_json_is_valid_and_rejects_unsupported_filters(self):
        root, cli = self.fixture()
        note = self.decision(cli, "accepted")
        payload = json.loads(cli.run("search", "Zebra policy", "--exact", "--json").stdout)
        self.assertEqual("exact", payload["mode"])
        self.assertTrue(any(str(note.relative_to(root)) in item for item in payload["results"]))
        missing = json.loads(cli.run("search", "nonexistent_phrase", "--exact", "--json").stdout)
        self.assertEqual([], missing["results"])
        for option in [("--kind", "decisions"), ("--status", "accepted"), ("--scope", "history/decisions")]:
            with self.subTest(option=option):
                result = cli.run("search", "Zebra", "--exact", *option, "--json", check=False)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("search --exact does not support", result.stderr)

    def test_all_read_and_dry_run_commands_preserve_empty_root(self):
        commands = [
            ("start", "--brief"), ("recall",), ("recall", "--json"),
            ("search", "missing"), ("search", "missing", "--exact", "--json"),
            ("exact", "missing"), ("recent",), ("lint",), ("finish",),
            ("handoff-agent-capsule", "resume"), ("collab", "recall"), ("collab", "status"),
            ("collab", "archive", "--dry-run"), ("archive", "plan"), ("archive", "status"),
            ("archive", "run", "--dry-run"), ("archive", "adopt", "--dry-run"), ("archive", "migrate", "--dry-run"),
        ]
        for command in commands:
            with self.subTest(command=command):
                root, cli = self.fixture()
                before = file_snapshot(root)
                cli.run(*command)
                self.assertEqual(before, file_snapshot(root))
                self.assertEqual([], list(root.iterdir()))

    def test_collab_recall_preserves_existing_generated_files(self):
        root, cli = self.fixture()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        before = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
        cli.run("collab", "recall", "--task", "task-alpha", "--workstream", "eval", "--query", "benchmark")
        after = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_timestamp_years_are_not_numbered_record_collisions(self):
        root, cli = self.fixture()
        for title in ["First change", "Second change"]:
            cli.run("change", "--title", title, "--why", "Finding", "--no-git-status")
        for title in ["First capsule", "Second capsule"]:
            cli.run("handoff-agent-capsule", "create", "--task", title)
        _, warnings = history.lint_history(root, 12000)
        self.assertFalse(any("display number changes/" in warning or "display number capsules/" in warning for warning in warnings))
        decisions = root / "history/decisions"
        (decisions / "0001-first.md").write_text("---\ntype: decision\n---\n# First\n")
        (decisions / "0001-second.md").write_text("---\ntype: decision\n---\n# Second\n")
        _, warnings = history.lint_history(root, 12000)
        self.assertTrue(any("display number decisions/0001" in warning for warning in warnings))

    def test_observation_metadata_survives_search_serialization(self):
        root, cli = self.fixture()
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=True).stdout.strip()
        git("init", "-q")
        git("config", "user.name", "CLI Fixture")
        git("config", "user.email", "fixture@example.invalid")
        (root / "base.txt").write_text("baseline\n")
        git("add", "base.txt")
        git("commit", "-qm", "Baseline")
        head = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
        self.decision(cli, "accepted")
        payload = json.loads(cli.run("search", "Zebra", "--json").stdout)
        metadata = payload["results"][0]["metadata"]
        self.assertEqual(root.name, metadata["repo"])
        self.assertEqual(branch, metadata["branch"])
        self.assertEqual(head, metadata["head"])

    def test_archive_index_is_deterministic_and_unchanged_write_is_avoided(self):
        root, _ = self.fixture()
        folder = root / "history-archive/2020-01/changes"
        folder.mkdir(parents=True)
        (folder / "2020-01-01-000000-evidence.md").write_text("# Archived change\nDate: 2020-01-01\n\n## Why\nPreserved evidence.\n")
        with patch.object(history, "display_time", return_value="2026-10-26 10:00 +0900"):
            index = history.build_archive_index(root)
        before = index.read_bytes(), index.stat().st_mtime_ns
        with patch.object(history, "display_time", return_value="2026-10-26 10:01 +0900"):
            history.build_archive_index(root)
        self.assertEqual(before, (index.read_bytes(), index.stat().st_mtime_ns))

    def test_auto_root_detection_preserves_trailing_whitespace(self):
        root, _ = self.fixture()
        repository = root / "repository with space "
        repository.mkdir()
        subprocess.run(["git", "-C", str(repository), "init", "-q"], capture_output=True, check=True)
        result = subprocess.run(["python3", str(SCRIPT), "start", "--json"], cwd=repository, text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(str(repository), payload["repository"]["root"])
        self.assertEqual([], [p for p in repository.iterdir() if p.name != ".git"])


if __name__ == "__main__":
    unittest.main()
