#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(REPO_ROOT / "scripts" / "history.py")


class HistoryCLI:
    def __init__(self, root: Path):
        self.root = root

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["python3", SCRIPT, "--root", str(self.root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                "history.py command failed\n"
                f"command: python3 {SCRIPT} --root {self.root} {' '.join(args)}\n"
                f"returncode: {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc

    def emitted_path(self, proc: subprocess.CompletedProcess[str]) -> Path:
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            raise AssertionError(f"expected command to emit a path, got stdout={proc.stdout!r}")
        return self.root / lines[-1]

    def submit_summary(
        self,
        *,
        task: str = "task-alpha",
        workstream: str = "eval",
        title: str,
        summary: str,
        claim: str | None = None,
        evidence: str | None = None,
        proposed_decision: str | None = None,
        person: str = "worker-2",
        agent: str = "codex",
    ) -> Path:
        args = [
            "collab",
            "submit-summary",
            "--task",
            task,
            "--workstream",
            workstream,
            "--person",
            person,
            "--agent",
            agent,
            "--title",
            title,
            "--summary",
            summary,
        ]
        if claim:
            args.extend(["--claim", claim])
        if evidence:
            args.extend(["--evidence", evidence])
        if proposed_decision:
            args.extend(["--proposed-decision", proposed_decision])
        return self.emitted_path(self.run(*args))


class CollabBehaviorSmokeTests(unittest.TestCase):
    maxDiff = None

    def with_cli(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        return root, HistoryCLI(root)

    def test_existing_smoke_flow_and_inbox_recall_boundary(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")

        self.assertTrue((root / "history" / "canonical" / "overview.md").exists())
        self.assertTrue((root / "history" / "tasks" / "task-alpha" / "context.md").exists())
        self.assertTrue((root / "history" / "tasks" / "task-alpha" / "workstreams" / "eval.md").exists())

        decision_inbox = cli.submit_summary(
            title="Decision promotion smoke",
            summary="Decision source summary for the smoke test.",
            proposed_decision="Adopt accepted decision smoke behavior.",
        )
        decision_target = cli.emitted_path(
            cli.run(
                "collab",
                "promote",
                "--inbox",
                str(decision_inbox),
                "--target",
                "decision",
                "--maintainer",
                "maintainer",
                "--decision",
                "Accepted decision smoke marker.",
            )
        )
        self.assertTrue(decision_target.exists())
        self.assertIn("Accepted decision smoke marker.", decision_target.read_text(encoding="utf-8"))

        workstream_inbox = cli.submit_summary(
            title="Workstream promotion smoke",
            summary="Workstream source summary for the smoke test.",
        )
        workstream_target = cli.emitted_path(
            cli.run(
                "collab",
                "promote",
                "--inbox",
                str(workstream_inbox),
                "--target",
                "workstream",
                "--maintainer",
                "maintainer",
                "--note",
                "Accepted workstream smoke marker.",
            )
        )
        self.assertTrue(workstream_target.exists())
        self.assertIn("Accepted workstream smoke marker.", workstream_target.read_text(encoding="utf-8"))

        pending_marker = "PENDING_INBOX_SMOKE_MARKER"
        cli.submit_summary(
            title=f"Pending inbox smoke {pending_marker}",
            summary=f"Pending summary carries {pending_marker}.",
        )

        default_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            "pending summary",
            "--no-variants",
        ).stdout
        self.assertNotIn(pending_marker, default_recall)

        inbox_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            "pending summary",
            "--include-inbox",
            "--no-variants",
        ).stdout
        self.assertIn(pending_marker, inbox_recall)

    def test_rejected_decision_is_not_reported_as_accepted_collab_decision(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        accepted_marker = "ACCEPTED_DECISION_SMOKE_MARKER"
        rejected_marker = "REJECTED_DECISION_SMOKE_MARKER"

        cli.run(
            "decision",
            "--title",
            f"Accepted collab decision {accepted_marker}",
            "--status",
            "accepted",
            "--context",
            "Accepted decision context.",
            "--decision",
            "Keep this accepted decision visible.",
        )
        cli.run(
            "decision",
            "--title",
            f"Rejected collab decision {rejected_marker}",
            "--status",
            "rejected",
            "--context",
            "Rejected decision context.",
            "--decision",
            "This rejected decision must not be treated as accepted.",
        )

        recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            "accepted decisions",
            "--no-variants",
        ).stdout

        self.assertIn(accepted_marker, recall)
        self.assertNotIn(rejected_marker, recall)

    def test_promote_rejects_arbitrary_external_markdown_file(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        external_marker = "EXTERNAL_MARKDOWN_SHOULD_NOT_PROMOTE"
        external = root / "external-summary.md"
        external.write_text(
            "\n".join(
                [
                    "# External Markdown",
                    "",
                    "Task: task-alpha",
                    "Workstream: eval",
                    "Approval Status: submitted",
                    "",
                    "## Summary",
                    "",
                    external_marker,
                    "",
                ]
            ),
            encoding="utf-8",
        )

        proc = cli.run(
            "collab",
            "promote",
            "--inbox",
            str(external),
            "--target",
            "workstream",
            "--maintainer",
            "maintainer",
            check=False,
        )

        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("inbox", (proc.stdout + proc.stderr).lower())
        workstream = root / "history" / "tasks" / "task-alpha" / "workstreams" / "eval.md"
        self.assertNotIn(external_marker, workstream.read_text(encoding="utf-8"))

    def test_note_promotion_only_adds_note_without_submitted_sections(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        note = "CURATED_NOTE_ONLY_MARKER"
        submitted_claim = "SUBMITTED_CLAIM_MUST_STAY_OUT"
        submitted_evidence = "SUBMITTED_EVIDENCE_MUST_STAY_OUT"
        submitted_decision = "SUBMITTED_DECISION_MUST_STAY_OUT"
        inbox = cli.submit_summary(
            title="Note only promotion smoke",
            summary="Submitted summary should not be copied when note is present.",
            claim=submitted_claim,
            evidence=submitted_evidence,
            proposed_decision=submitted_decision,
        )

        target = cli.emitted_path(
            cli.run(
                "collab",
                "promote",
                "--inbox",
                str(inbox),
                "--target",
                "workstream",
                "--maintainer",
                "maintainer",
                "--note",
                note,
            )
        )
        text = target.read_text(encoding="utf-8")

        self.assertIn(note, text)
        self.assertNotIn(submitted_claim, text)
        self.assertNotIn(submitted_evidence, text)
        self.assertNotIn(submitted_decision, text)

    def test_include_submitted_sections_promotes_claims_and_evidence_with_note(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        note = "CURATED_NOTE_WITH_SUBMITTED_SECTIONS_MARKER"
        submitted_claim = "INCLUDED_SUBMITTED_CLAIM_MARKER"
        submitted_evidence = "INCLUDED_SUBMITTED_EVIDENCE_MARKER"
        submitted_decision = "INCLUDED_SUBMITTED_DECISION_MARKER"
        inbox = cli.submit_summary(
            title="Include submitted sections smoke",
            summary="Submitted summary may be copied only when explicitly requested.",
            claim=submitted_claim,
            evidence=submitted_evidence,
            proposed_decision=submitted_decision,
        )

        target = cli.emitted_path(
            cli.run(
                "collab",
                "promote",
                "--inbox",
                str(inbox),
                "--target",
                "workstream",
                "--maintainer",
                "maintainer",
                "--note",
                note,
                "--include-submitted-sections",
            )
        )
        text = target.read_text(encoding="utf-8")

        self.assertIn(note, text)
        self.assertIn(submitted_claim, text)
        self.assertIn(submitted_evidence, text)
        self.assertIn(submitted_decision, text)

    def test_handoff_and_capsule_metadata_are_in_scoped_collab_recall(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        handoff = cli.emitted_path(
            cli.run(
                "handoff",
                "--title",
                "Metadata handoff smoke",
                "--task",
                "task-alpha",
                "--workstream",
                "eval",
                "--summary",
                "HANDOFF_METADATA_RECALL_MARKER",
            )
        )
        capsule = cli.emitted_path(
            cli.run(
                "handoff-agent-capsule",
                "create",
                "--task",
                "Metadata capsule smoke",
                "--collab-task",
                "task-alpha",
                "--workstream",
                "eval",
                "--current-state",
                "CAPSULE_METADATA_RECALL_MARKER",
            )
        )
        self.assertIn("Task: task-alpha", handoff.read_text(encoding="utf-8"))
        self.assertIn("Workstream: eval", handoff.read_text(encoding="utf-8"))
        self.assertIn("Task: task-alpha", capsule.read_text(encoding="utf-8"))
        self.assertIn("Workstream: eval", capsule.read_text(encoding="utf-8"))

        recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            "handoff capsule metadata recall",
            "--limit",
            "10",
            "--no-variants",
        ).stdout

        self.assertIn(str(handoff.relative_to(cli.root)), recall)
        self.assertIn(str(capsule.relative_to(cli.root)), recall)

    def test_collab_status_reports_pending_inbox_count_and_stale_summary(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "status-task", "--workstream", "eval")
        cli.submit_summary(
            task="status-task",
            workstream="eval",
            title="Pending status smoke",
            summary="Pending inbox item for status smoke.",
        )
        promoted = cli.submit_summary(
            task="status-task",
            workstream="eval",
            title="Accepted unarchived status smoke",
            summary="Accepted inbox item for status smoke.",
        )
        cli.run(
            "collab",
            "promote",
            "--inbox",
            str(promoted),
            "--target",
            "workstream",
            "--maintainer",
            "maintainer",
            "--note",
            "Accepted status smoke note.",
        )
        old_timestamp = time.time() - (3 * 24 * 60 * 60)
        task_context = root / "history" / "tasks" / "status-task" / "context.md"
        os.utime(task_context, (old_timestamp, old_timestamp))

        status = cli.run("collab", "status", "--stale-days", "1").stdout
        normalized = status.lower()

        self.assertIn("## pending inbox", normalized)
        self.assertRegex(normalized, re.compile(r"\|\s*status-task\s*\|\s*eval\s*\|\s*1\s*\|"))
        self.assertIn("## accepted but unarchived inbox", normalized)
        self.assertRegex(normalized, re.compile(r"\|\s*status-task\s*\|\s*eval\s*\|\s*1\s*\|"))
        self.assertIn("## archive candidates", normalized)
        self.assertIn("accepted-unarchived-status-smoke", normalized)
        self.assertIn("stale", normalized)
        self.assertIn("status-task", normalized)
        self.assertRegex(normalized, re.compile(r"status-task[^\n]*yes|yes[^\n]*status-task"))
        self.assertIn("unscoped_records:", normalized)

    def test_archive_dry_run_does_not_modify_promoted_inbox(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        inbox = cli.submit_summary(
            title="Archive dry run smoke",
            summary="ARCHIVE_DRY_RUN_MARKER",
        )
        cli.run(
            "collab",
            "promote",
            "--inbox",
            str(inbox),
            "--target",
            "workstream",
            "--maintainer",
            "maintainer",
            "--note",
            "Accepted dry-run note.",
        )
        before = inbox.read_text(encoding="utf-8")
        proc = cli.run("collab", "archive", "--dry-run")

        self.assertTrue(inbox.exists())
        self.assertEqual(before, inbox.read_text(encoding="utf-8"))
        self.assertIn(str(inbox.relative_to(cli.root)), proc.stdout)
        self.assertFalse(any((cli.root / "history" / "archive" / "inbox").rglob(inbox.name)))

    def test_archive_moves_promoted_inbox_and_leaves_pending(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        promoted = cli.submit_summary(
            title="Archive move smoke",
            summary="ARCHIVE_MOVE_PROMOTED_MARKER",
        )
        pending = cli.submit_summary(
            title="Archive pending smoke",
            summary="ARCHIVE_PENDING_MARKER",
        )
        cli.run(
            "collab",
            "promote",
            "--inbox",
            str(promoted),
            "--target",
            "workstream",
            "--maintainer",
            "maintainer",
            "--note",
            "Accepted archive move note.",
        )

        cli.run("collab", "archive")

        archived = list((root / "history" / "archive" / "inbox").rglob(promoted.name))
        self.assertEqual(1, len(archived))
        self.assertFalse(promoted.exists())
        self.assertTrue(pending.exists())
        archived_text = archived[0].read_text(encoding="utf-8")
        self.assertIn("Archived: yes", archived_text)
        self.assertIn("Archived From: history/inbox/", archived_text)
        self.assertIn("Promoted To: history/tasks/task-alpha/workstreams/eval.md", archived_text)

    def test_default_recall_excludes_archive_and_include_archive_finds_it(self) -> None:
        _, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        marker = "ARCHIVED_ONLY_RECALL_MARKER"
        inbox = cli.submit_summary(
            title="Archive recall smoke",
            summary=f"Archived source carries {marker}.",
        )
        cli.run(
            "collab",
            "promote",
            "--inbox",
            str(inbox),
            "--target",
            "workstream",
            "--maintainer",
            "maintainer",
            "--note",
            "Curated note intentionally omits the archived-only marker.",
        )
        cli.run("collab", "archive")

        default_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            marker,
            "--no-variants",
        ).stdout
        self.assertNotIn("history/archive/", default_recall)
        self.assertNotIn("archive_status=archived", default_recall)
        self.assertIn("Archive Included: no", default_recall)

        archive_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-alpha",
            "--workstream",
            "eval",
            "--query",
            marker,
            "--include-archive",
            "--no-variants",
        ).stdout
        self.assertIn(marker, archive_recall)
        self.assertIn("Archive Included: yes", archive_recall)
        self.assertIn("archive_status=archived", archive_recall)

    def test_archive_include_daily_and_sessions_requires_age_filter(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task", "task-alpha", "--workstream", "eval")
        daily = root / "history" / "daily" / "2026-01-02.md"
        daily.write_text("# Daily Log - 2026-01-02\n\n## Focus\n\nold daily\n", encoding="utf-8")
        session = root / "history" / "sessions" / "2026-01-02-000000-agent-old-session.md"
        session.write_text("# Session - Old\n\nDate: 2026-01-02\n\n## Scope\n\nold session\n", encoding="utf-8")
        recent = root / "history" / "sessions" / "recent-session.md"
        recent.write_text("# Session - Recent\n\nDate: today\n\n## Scope\n\nrecent session\n", encoding="utf-8")
        old_timestamp = time.time() - (10 * 24 * 60 * 60)
        os.utime(daily, (old_timestamp, old_timestamp))
        os.utime(session, (old_timestamp, old_timestamp))

        no_age = cli.run("collab", "archive", "--include", "daily,sessions", "--dry-run").stdout
        self.assertIn("no archive candidates", no_age.lower())

        cli.run("collab", "archive", "--include", "daily,sessions", "--older-than-days", "1")

        self.assertFalse(daily.exists())
        self.assertFalse(session.exists())
        self.assertTrue(recent.exists())
        self.assertEqual(1, len(list((root / "history" / "archive" / "daily").rglob(daily.name))))
        self.assertEqual(1, len(list((root / "history" / "archive" / "sessions").rglob(session.name))))

    def test_scale_smoke_with_many_inbox_and_archived_records(self) -> None:
        root, cli = self.with_cli()
        cli.run("collab", "bootstrap", "--task-count", "15", "--default-workstreams")
        inbox_dir = root / "history" / "inbox"
        archive_dir = root / "history" / "archive" / "inbox" / "2026-05"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(500):
            task = f"task-{(idx % 15) + 1:02d}"
            workstream = ["data", "eval", "model", "writeup"][idx % 4]
            agent = f"agent-{(idx % 20) + 1:02d}"
            (inbox_dir / f"2026-05-08-{idx:06d}-{task}-{workstream}-{agent}-pending.md").write_text(
                "\n".join(
                    [
                        f"# Inbox Summary - {task} / {workstream} - pending {idx}",
                        "",
                        "Date: 2026-05-08 00:00 +0000",
                        f"Task: {task}",
                        f"Workstream: {workstream}",
                        f"Agent: {agent}",
                        "Approval Status: submitted",
                        "Promoted To: -",
                        "Archived: no",
                        "Archived Date: -",
                        "",
                        "## Summary",
                        "",
                        f"Pending scale summary {idx}.",
                    ]
                ),
                encoding="utf-8",
            )
            archived_marker = "ARCHIVE_SCALE_MARKER" if idx == 327 else "archived scale summary"
            (archive_dir / f"2026-05-01-{idx:06d}-{task}-{workstream}-{agent}-archived.md").write_text(
                "\n".join(
                    [
                        f"# Inbox Summary - {task} / {workstream} - archived {idx}",
                        "",
                        "Date: 2026-05-01 00:00 +0000",
                        f"Task: {task}",
                        f"Workstream: {workstream}",
                        f"Agent: {agent}",
                        "Approval Status: accepted",
                        "Promoted To: history/canonical/overview.md",
                        "Archived: yes",
                        "Archived Date: 2026-05-08 00:00 +0000",
                        "Archived From: history/inbox/source.md",
                        "",
                        "## Summary",
                        "",
                        archived_marker,
                    ]
                ),
                encoding="utf-8",
            )

        start = time.perf_counter()
        status = cli.run("collab", "status").stdout
        default_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-13",
            "--workstream",
            "writeup",
            "--query",
            "ARCHIVE_SCALE_MARKER",
            "--no-variants",
        ).stdout
        archive_recall = cli.run(
            "collab",
            "recall",
            "--task",
            "task-13",
            "--workstream",
            "writeup",
            "--query",
            "ARCHIVE_SCALE_MARKER",
            "--include-archive",
            "--no-variants",
        ).stdout
        elapsed = time.perf_counter() - start

        self.assertIn("pending_inbox: 500", status)
        self.assertIn("| archive |", status)
        self.assertNotIn("history/archive/", default_recall)
        self.assertNotIn("archive_status=archived", default_recall)
        self.assertIn("ARCHIVE_SCALE_MARKER", archive_recall)
        self.assertIn("archive_status=archived", archive_recall)
        self.assertLess(elapsed, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
