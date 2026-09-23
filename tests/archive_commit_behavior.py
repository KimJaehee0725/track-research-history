#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.collab_behavior_smoke import HistoryCLI


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


class ArchiveAndCommitPairingTests(unittest.TestCase):
    maxDiff = None

    def with_cli(self, git_repo: bool = False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        if git_repo:
            git(root, "init")
            git(root, "config", "user.email", "tester@example.com")
            git(root, "config", "user.name", "Tester")
        return root, HistoryCLI(root)

    def add_change(self, cli: HistoryCLI, title: str, why: str = "why", how: str = "how") -> Path:
        return cli.emitted_path(
            cli.run("change", "--title", title, "--why", why, "--how", how, "--no-git-status")
        )

    def add_long_change(self, cli: HistoryCLI, title: str, marker: str) -> Path:
        filler = " ".join(f"detail-{idx} about the export pipeline and its validation" for idx in range(40))
        return cli.emitted_path(
            cli.run(
                "change",
                "--title",
                title,
                "--why",
                f"{marker} {filler}",
                "--how",
                filler,
                "--validation",
                filler,
                "--no-git-status",
            )
        )

    # --- long-term archive -------------------------------------------------

    def test_archive_run_keeps_summary_stub_and_moves_full_text(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        old = self.add_long_change(cli, "Old reward shaping export", "OLD_RECORD_BODY_MARKER")
        self.add_long_change(cli, "Recent reward shaping export", "RECENT_RECORD_BODY_MARKER")

        out = cli.run("archive", "run", "--older-than-days", "0", "--keep-recent", "1").stdout
        self.assertIn("Archived Count: 1", out)

        archived = list((root / "history-archive").rglob(old.name))
        self.assertEqual(1, len(archived), out)
        archived_text = archived[0].read_text(encoding="utf-8")
        self.assertIn("OLD_RECORD_BODY_MARKER", archived_text)
        self.assertIn("Archived: yes", archived_text)
        self.assertIn(f"Archive Stub: history/changes/{old.name}", archived_text)

        self.assertTrue(old.exists(), "the stub must stay in history/")
        stub = old.read_text(encoding="utf-8")
        self.assertIn("Archive State: stub", stub)
        self.assertIn("## Summary", stub)
        self.assertIn("OLD_RECORD_BODY_MARKER", stub)
        self.assertIn(f"Archived To: {archived[0].relative_to(root).as_posix()}", stub)
        self.assertLess(len(stub), len(archived_text))

        index = (root / "history" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("summary stubs", index)
        self.assertTrue((root / "history-archive" / "INDEX.md").exists())

    def test_archive_skips_recent_and_open_records(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        cli.run("idea", "--title", "Open idea stays put", "--problem", "p", "--hypothesis", "h")
        self.add_long_change(cli, "First change", "FIRST_MARKER")
        self.add_long_change(cli, "Second change", "SECOND_MARKER")

        plan = cli.run(
            "archive",
            "plan",
            "--include",
            "changes,ideas",
            "--older-than-days",
            "0",
            "--keep-recent",
            "1",
            "--min-saving",
            "0",
        ).stdout
        self.assertIn("Candidate Count: 1", plan)
        self.assertIn("first-change", plan)
        self.assertNotIn("open-idea-stays-put", plan)

        with_open = cli.run(
            "archive",
            "plan",
            "--include",
            "changes,ideas",
            "--older-than-days",
            "0",
            "--keep-recent",
            "0",
            "--min-saving",
            "0",
            "--include-open",
        ).stdout
        self.assertIn("open-idea-stays-put", with_open)

    def test_archive_restore_round_trips_the_record(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        record = self.add_long_change(cli, "Restore me", "RESTORE_BODY_MARKER")
        before = record.read_text(encoding="utf-8")

        cli.run("archive", "run", "--older-than-days", "0", "--keep-recent", "0")
        self.assertIn("Archive State: stub", record.read_text(encoding="utf-8"))

        out = cli.run("archive", "restore", "--record", "restore-me").stdout
        self.assertIn("restored", out)
        restored = record.read_text(encoding="utf-8")
        self.assertIn("RESTORE_BODY_MARKER", restored)
        self.assertNotIn("Archive State: stub", restored)
        self.assertNotIn("Archived: yes", restored)
        self.assertEqual(before.strip(), restored.strip())
        leftovers = [
            path
            for path in (root / "history-archive").rglob("*.md")
            if path.name not in {"INDEX.md", "README.md"}
        ]
        self.assertEqual([], leftovers)

    def test_search_excludes_archived_text_until_include_archive(self) -> None:
        _, cli = self.with_cli()
        cli.run("bootstrap")
        self.add_long_change(cli, "Archive search smoke", "ARCHIVEONLYBODYMARKER")
        cli.run("archive", "run", "--older-than-days", "0", "--keep-recent", "0")

        default_hits = cli.run("exact", "ARCHIVEONLYBODYMARKER").stdout
        self.assertIn("history/changes/", default_hits)
        self.assertNotIn("history-archive/", default_hits)

        archive_hits = cli.run("exact", "ARCHIVEONLYBODYMARKER", "--include-archive").stdout
        self.assertIn("history-archive/", archive_hits)

    def test_archive_skips_records_whose_stub_would_not_save(self) -> None:
        _, cli = self.with_cli()
        cli.run("bootstrap")
        self.add_change(cli, "Tiny change")

        default_plan = cli.run("archive", "plan", "--older-than-days", "0", "--keep-recent", "0").stdout
        self.assertIn("Candidate Count: 0", default_plan)
        self.assertIn("would not be meaningfully smaller", default_plan)

        forced = cli.run(
            "archive", "plan", "--older-than-days", "0", "--keep-recent", "0", "--min-saving", "0"
        ).stdout
        self.assertIn("tiny-change", forced)

    def test_adopt_reports_when_a_history_is_already_cheap(self) -> None:
        _, cli = self.with_cli()
        cli.run("bootstrap")
        for idx in range(3):
            self.add_change(cli, f"Small record {idx}")

        out = cli.run("archive", "adopt", "--older-than-days", "0").stdout
        self.assertIn("archived: 0 record(s)", out)
        self.assertIn("already as cheap to recall", out)
        self.assertIn("would not be meaningfully smaller", out)
        self.assertNotIn("Next:", out)

    def test_archive_skips_records_linked_from_curated_context(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        record = self.add_long_change(cli, "Linked from context", "LINKED_MARKER")
        context = root / "history" / "CONTEXT.md"
        context.write_text(
            context.read_text(encoding="utf-8")
            + f"\n- still relevant: [[changes/{record.stem}]]\n",
            encoding="utf-8",
        )

        plan = cli.run("archive", "plan", "--older-than-days", "0", "--keep-recent", "0").stdout
        self.assertIn("Candidate Count: 0", plan)

        forced = cli.run(
            "archive", "plan", "--older-than-days", "0", "--keep-recent", "0", "--include-referenced"
        ).stdout
        self.assertIn(record.stem, forced)

    def test_adopt_bulk_archives_a_legacy_history_in_one_pass(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        old_records = []
        for idx in range(3):
            record = self.add_long_change(cli, f"Legacy record {idx}", f"LEGACY_MARKER_{idx}")
            stamp = f"2026-01-0{idx + 1}-120000"
            moved = record.with_name(f"{stamp}-legacy-record-{idx}.md")
            moved.write_text(
                record.read_text(encoding="utf-8").replace("date: ", "date: 2026-01-01 #"),
                encoding="utf-8",
            )
            record.unlink()
            old_records.append(moved)
        fresh = self.add_long_change(cli, "Fresh record", "FRESH_MARKER")
        legacy_dir = root / "history" / "archive" / "inbox" / "2026-01"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "old-inbox.md").write_text("# Inbox Summary - old\n\nDate: 2026-01-01\n", encoding="utf-8")

        plan = cli.run("archive", "adopt", "--dry-run").stdout
        self.assertIn("Candidate Count: 3", plan)
        self.assertIn("Nothing was changed", plan)
        self.assertTrue(old_records[0].read_text(encoding="utf-8").count("LEGACY_MARKER_0"))
        self.assertTrue((legacy_dir / "old-inbox.md").exists())

        out = cli.run("archive", "adopt").stdout
        self.assertIn("archived: 3 record(s)", out)
        self.assertIn("reduction:", out)

        for idx, record in enumerate(old_records):
            stub = record.read_text(encoding="utf-8")
            self.assertIn("Archive State: stub", stub)
            self.assertIn(f"LEGACY_MARKER_{idx}", stub)
            self.assertEqual(1, len(list((root / "history-archive").rglob(record.name))))
        self.assertNotIn("Archive State: stub", fresh.read_text(encoding="utf-8"))
        self.assertFalse((root / "history" / "archive").exists())
        self.assertEqual(1, len(list((root / "history-archive").rglob("old-inbox.md"))))

        again = cli.run("archive", "adopt").stdout
        self.assertIn("summary stub(s) already exist", again)
        self.assertIn("archived: 0 record(s)", again)

    def test_default_run_is_conservative_where_adopt_is_not(self) -> None:
        _, cli = self.with_cli()
        cli.run("bootstrap")
        for idx in range(3):
            self.add_long_change(cli, f"Old record {idx}", f"OLD_MARKER_{idx}")

        # The default policy keeps the newest 20 per kind, so a small legacy history is untouched.
        conservative = cli.run("archive", "plan", "--older-than-days", "0").stdout
        self.assertIn("Candidate Count: 0", conservative)

        bulk = cli.run("archive", "adopt", "--older-than-days", "0", "--dry-run").stdout
        self.assertIn("Candidate Count: 3", bulk)

    def test_archive_migrate_moves_legacy_folder(self) -> None:
        root, cli = self.with_cli()
        cli.run("bootstrap")
        legacy = root / "history" / "archive" / "daily" / "2026-01"
        legacy.mkdir(parents=True)
        legacy_record = legacy / "2026-01-02.md"
        legacy_record.write_text("# Daily Log - 2026-01-02\n\nDate: 2026-01-02\n", encoding="utf-8")

        out = cli.run("archive", "migrate").stdout
        self.assertIn("Migrated Count: 1", out)
        self.assertFalse(legacy_record.exists())
        self.assertTrue((root / "history-archive" / "2026-01" / "daily" / "2026-01-02.md").exists())

    # --- commit pairing ----------------------------------------------------

    def test_commit_pairs_record_with_commit_and_trailer(self) -> None:
        root, cli = self.with_cli(git_repo=True)
        cli.run("bootstrap")
        record = self.add_change(cli, "Pair with commit")
        (root / "app.py").write_text("print('hello')\n", encoding="utf-8")

        out = cli.run("commit", "--record", "pair-with-commit", "-m", "Add app", "--all").stdout
        self.assertIn("# Paired Commit", out)

        record_id = "chg-" + record.stem
        log = git(root, "log", "--format=%H%n%B")
        self.assertIn(f"History-Record: {record_id}", log)

        sha = git(root, "log", "--format=%H", "--grep=Add app", "-1")[:12]
        text = record.read_text(encoding="utf-8")
        self.assertIn(f"Commits: {sha}", text)
        self.assertIn("## Commits", text)
        self.assertIn(sha, text)

        self.assertEqual("", git(root, "status", "--porcelain"))

        shown = cli.run("commits", "--record", record_id).stdout
        self.assertIn(sha, shown)
        self.assertIn("Add app", shown)

        reverse = cli.run("commits", "--commit", sha).stdout
        self.assertIn(f"trailer: {record_id}", reverse)
        self.assertIn("app.py", reverse)

    def test_link_commit_pairs_an_existing_commit(self) -> None:
        root, cli = self.with_cli(git_repo=True)
        cli.run("bootstrap")
        record = self.add_change(cli, "Link existing commit")
        (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-m", "Hand made commit")
        sha = git(root, "rev-parse", "HEAD")[:12]

        out = cli.run("link-commit", "--record", "link-existing-commit").stdout
        self.assertIn("Linked: 1", out)
        self.assertIn(sha, record.read_text(encoding="utf-8"))

        again = cli.run("link-commit", "--record", "link-existing-commit").stdout
        self.assertIn("already lists", again)

    def test_sync_commits_backfills_from_trailer(self) -> None:
        root, cli = self.with_cli(git_repo=True)
        cli.run("bootstrap")
        record = self.add_change(cli, "Backfill from trailer")
        record_id = "chg-" + record.stem
        (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-m", f"Hand made commit\n\nHistory-Record: {record_id}")
        sha = git(root, "rev-parse", "HEAD")[:12]

        self.assertNotIn(sha, record.read_text(encoding="utf-8"))
        out = cli.run("sync-commits").stdout
        self.assertIn("Linked: 1", out)
        self.assertIn(sha, record.read_text(encoding="utf-8"))

    def test_archive_stub_keeps_commit_pairing(self) -> None:
        root, cli = self.with_cli(git_repo=True)
        cli.run("bootstrap")
        record = self.add_long_change(cli, "Keep pairing in stub", "PAIRING_MARKER")
        (root / "app.py").write_text("print('hello')\n", encoding="utf-8")
        cli.run("commit", "--record", "keep-pairing-in-stub", "-m", "Add app", "--all")
        sha = git(root, "log", "--format=%H", "--grep=Add app", "-1")[:12]

        cli.run("archive", "run", "--older-than-days", "0", "--keep-recent", "0")
        stub = record.read_text(encoding="utf-8")
        self.assertIn("Archive State: stub", stub)
        self.assertIn(sha, stub)
        self.assertIn(f"git show {sha}", stub)

    def test_finish_reports_unpaired_records_and_archive_pressure(self) -> None:
        root, cli = self.with_cli(git_repo=True)
        cli.run("bootstrap")
        record = self.add_change(cli, "Unpaired change")
        git(root, "add", "-A")
        git(root, "commit", "-m", "initial")

        out = cli.run("finish").stdout
        self.assertIn("## Commit Pairing", out)
        self.assertIn("unpaired:", out)
        self.assertIn(record.name, out)
        self.assertIn("## Archive Pressure", out)


if __name__ == "__main__":
    unittest.main()
