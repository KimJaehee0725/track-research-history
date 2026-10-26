from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.collab_behavior_smoke import HistoryCLI, file_snapshot

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("history_quality", ROOT / "scripts/history.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


class ContextQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cli = HistoryCLI(self.root)

    def test_readonly_capabilities_brief_and_lint_do_not_bootstrap(self):
        before = file_snapshot(self.root)
        cap = json.loads(self.cli.run("--capabilities").stdout)
        self.assertEqual("vendored-bm25s", cap["backend"])
        self.cli.run("start", "--brief")
        self.cli.run("lint")
        self.assertEqual(before, file_snapshot(self.root))

    def test_partial_correction_keeps_original_and_explicit_scope(self):
        self.cli.run("bootstrap")
        old = self.cli.emitted_path(self.cli.run("decision", "--title", "Original premise", "--decision", "Original statement"))
        previous = old.read_bytes()
        new = self.cli.emitted_path(self.cli.run("decision", "--title", "Correct premise", "--decision", "Corrected statement", "--corrects", str(old.relative_to(self.root)), "--scope", "v2.1"))
        meta = history.record_metadata(new)
        self.assertEqual(history.record_id_for(old), meta["corrects"])
        self.assertEqual("v2.1", meta["scope"])
        self.assertEqual(previous, old.read_bytes())
        errors, _ = history.lint_history(self.root, 12000)
        self.assertEqual([], errors)

    def test_duplicate_identity_and_conflicting_metadata_are_detected(self):
        folder = self.root / "history/decisions"
        folder.mkdir(parents=True)
        text = '---\ntype: decision\nrecord_id: dec-shared\nstatus: accepted\n---\n# Decision\n\nStatus: rejected\nRecord Id: dec-shared\n\n## Decision\n\nStatement\n'
        (folder / "0001-a.md").write_text(text)
        (folder / "0001-b.md").write_text(text)
        errors, warnings = history.lint_history(self.root, 12000)
        self.assertTrue(any("duplicate record id" in item for item in errors))
        self.assertTrue(any("disagree" in item for item in errors))
        self.assertTrue(any("ambiguous display number" in item for item in warnings))

    def test_missing_and_self_relations_fail(self):
        folder = self.root / "history/decisions"
        folder.mkdir(parents=True)
        (folder / "0001-a.md").write_text('---\ntype: decision\nrecord_id: dec-a\ncorrects: dec-missing\nsupersedes: dec-a\n---\n# Decision\n')
        errors, _ = history.lint_history(self.root, 12000)
        self.assertTrue(any("missing corrects target" in item for item in errors))
        self.assertTrue(any("self-referential" in item for item in errors))

    def test_generated_map_length_is_not_a_prose_warning(self):
        (self.root / "history").mkdir()
        (self.root / "history/PROJECT_MAP.md").write_text("---\ntype: project-map\n---\n# Map\n" + "navigation\n" * 1500)
        _, warnings = history.lint_history(self.root, 100)
        self.assertFalse(any("oversized" in item for item in warnings))

    def test_unresolved_archive_statuses_and_summary_risks(self):
        folder = self.root / "history/changes"
        folder.mkdir(parents=True)
        for status in ["blocked", "blocked-on-provider-env", "partial", "delivered for review"]:
            note = folder / ("2020-01-01-000000-" + status.replace(" ", "-") + ".md")
            note.write_text(f"# Change\nStatus: {status}\n\n## Why\n\n" + "context " * 200)
        self.assertEqual([], history.long_term_archive_candidates(self.root, ["changes"], 1, 0, min_saving=0))
        note = folder / "2020-01-02-000000-closed.md"
        note.write_text("# Change\nStatus: completed\n\n## Why\n\n" + "reason " * 200 + "\n\n## How\n\n" + "implementation " * 200 + "\n\n## Files\n\n" + "path " * 200 + "\n\n## Validation\n\nOutcome limited to seed 42.\n\n## Risks / Follow-Ups\n\nNOT validated on production data.")
        summary = "\n".join(history.summary_lines_for(note, 700))
        self.assertIn("NOT validated on production data", summary)
        self.assertIn("seed 42", summary)
        self.assertLessEqual(len(summary), 700)

    def test_finish_explicit_base_separates_committed_work_from_backlog(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], text=True, capture_output=True, check=True).stdout.strip()
        git("init", "-q")
        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        (self.root / "code.py").write_text("old\n")
        git("add", "code.py")
        git("commit", "-qm", "baseline")
        base = git("rev-parse", "HEAD")
        (self.root / "code.py").write_text("new\n")
        git("add", "code.py")
        git("commit", "-qm", "new work")
        sha = git("rev-parse", "HEAD")
        self.assertEqual([sha], history.unrecorded_commits_since(self.root, base))
        self.cli.run("bootstrap")
        self.cli.run("change", "--title", "Record work", "--commit", sha, "--no-git-status")
        self.assertEqual([], history.unrecorded_commits_since(self.root, base))


class InstallerTests(unittest.TestCase):
    def test_dry_run_and_install_two_targets_preserve_prior_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            codex = base / "codex/track-research-history"
            claude = base / "claude/track-research-history"
            old = base / "old"
            old.mkdir()
            (old / "old.txt").write_text("old source remains")
            claude.parent.mkdir()
            claude.symlink_to(old, target_is_directory=True)
            command = ["python3", str(ROOT / "scripts/install.py"), "--target", str(codex), "--target", str(claude)]
            subprocess.run([*command, "--dry-run"], capture_output=True, check=True)
            self.assertFalse(codex.exists())
            self.assertTrue(claude.is_symlink())
            plan = json.loads(subprocess.run(command, capture_output=True, text=True, check=True).stdout)
            self.assertEqual((codex / "INSTALLATION.json").read_bytes(), (claude / "INSTALLATION.json").read_bytes())
            self.assertEqual("old source remains", (old / "old.txt").read_text())
            self.assertTrue(Path(plan[1]["backup"]).is_symlink())
            self.assertTrue((codex / "scripts/vendor/bm25s/__init__.py").is_file())

    def test_install_refuses_source_overlap(self):
        result = subprocess.run(["python3", str(ROOT / "scripts/install.py"), "--target", str(ROOT), "--dry-run"], text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("overlap", result.stderr)


class RecordResolutionTests(unittest.TestCase):
    def test_external_and_ambiguous_record_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "notes.md"
            outside.write_text("# Unrelated notes\n")
            with self.assertRaises(SystemExit):
                history.find_record(root, str(outside))
            folder = root / "history/decisions"
            folder.mkdir(parents=True)
            for name in ["0001-one.md", "0002-two.md"]:
                (folder / name).write_text("# Decision\nRecord Id: dec-duplicate\n")
            with self.assertRaises(SystemExit):
                history.find_record(root, "dec-duplicate")

    def test_full_replacement_cycle_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "history/decisions"
            folder.mkdir(parents=True)
            for rid, other in [("a", "b"), ("b", "a")]:
                (folder / (rid + ".md")).write_text(f"---\ntype: decision\nrecord_id: dec-{rid}\nsupersedes: dec-{other}\n---\n# Decision\n")
            errors, _ = history.lint_history(root, 12000)
            self.assertTrue(any("cyclic supersedes" in error for error in errors))

    def test_finish_reports_untracked_durable_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            cli = HistoryCLI(root)
            cli.run("bootstrap")
            result = cli.run("finish", "--strict", check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("Untracked Durable History", result.stdout)
            self.assertIn("not in Git yet", result.stdout)

    def test_sha_without_history_is_routed_to_exact_git_lookup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=True).stdout.strip()
            git("init", "-q")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "example.py").write_text("pass\n")
            git("add", "example.py")
            git("commit", "-qm", "first")
            sha = git("rev-parse", "HEAD")
            data = json.loads(HistoryCLI(root).run("search", sha[:8], "--json").stdout)
            self.assertEqual([], data["results"])
            self.assertEqual(sha, data["git_commit"]["sha"])
            self.assertTrue(data["git_commit"]["ancestor_of_head"])
            self.assertIn("commits --commit", data["git_commit"]["next_command"])
