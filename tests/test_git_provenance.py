from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "history.py"


class GitProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="history-provenance-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Provenance Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("src/target.py", "initial = 1\n")
        self.initial = self.commit("Initial implementation")

    def git(self, *args):
        proc = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(0, proc.returncode, proc.stderr)
        return proc.stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def record(self, name="0001-test", *, path="src/target.py", commits="", extra=""):
        content = f"""---
type: change
title: "Relevant implementation"
date: "2026-10-26 10:00 +0900"
record_id: chg-{name}
status: completed
---
# Change - Relevant implementation

Record Id: chg-{name}
Commits: {commits or '-'}

## Why

Preserve deterministic execution for `{path}`.

## Commits

{commits or '-'}
{extra}
"""
        name = f"history/changes/{name}.md"
        self.write(name, content)
        return name

    def cli(self, *args, check=True):
        proc = subprocess.run(["python3", str(SCRIPT), "--root", str(self.root), "commits", *args], capture_output=True, text=True)
        if check:
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        return proc

    def trace(self, path="src/target.py", *args):
        return json.loads(self.cli("--file", path, "--json", *args).stdout)

    def test_explicit_pair_is_full_sha_and_preserves_body_evidence(self):
        record = self.record(commits=self.initial[:12])
        self.commit("Record rationale separately")
        payload = self.trace()
        change = payload["commits"][0]
        self.assertEqual(self.initial, change["sha"])
        self.assertEqual(40, len(change["sha"]))
        self.assertTrue(change["ancestor_of_ref"])
        self.assertEqual(record, change["records"][0]["path"])
        self.assertEqual("explicit", change["records"][0]["relation"])
        self.assertEqual("record-commits", change["records"][0]["source"])

    def test_path_candidate_is_not_attributed_to_an_individual_commit(self):
        record = self.record()
        self.commit("Record rationale after the implementation")
        payload = self.trace()
        self.assertEqual([], payload["commits"][0]["records"])
        candidate = payload["path_candidates"][0]
        self.assertEqual(record, candidate["path"])
        self.assertEqual("path-candidate", candidate["relation"])
        self.assertIn("deterministic execution", candidate["excerpt"])
        self.assertIn("src/target.py", (self.root / record).read_text().splitlines()[candidate["line"] - 1])

    def test_cochange_is_structural_not_explicit(self):
        self.write("src/target.py", "initial = 2\n")
        self.record()
        self.commit("Update source and write rationale together")
        relation = self.trace()["commits"][0]["records"][0]
        self.assertEqual("co-change", relation["relation"])
        self.assertIn("deterministic execution", relation["excerpt"])

    def test_trailer_connection_takes_precedence_over_cochange(self):
        self.write("src/target.py", "initial = 2\n")
        self.record()
        self.commit("Implement update\n\nHistory-Record: chg-0001-test")
        relation = self.trace()["commits"][0]["records"][0]
        self.assertEqual("explicit", relation["relation"])
        self.assertEqual("commit-trailer", relation["source"])
        self.assertGreater(relation["commit_message_line"], 1)

    def test_old_ref_never_reads_newer_or_uncommitted_records(self):
        record = self.record(commits=self.initial)
        self.commit("Rationale appears in later ref")
        self.write(record, (self.root / record).read_text() + "\nUNCOMMITTED_PRIVATE_MARKER\n")
        payload = self.trace("src/target.py", "--ref", self.initial)
        self.assertEqual(self.initial, payload["resolved_ref"])
        self.assertEqual([], payload["path_candidates"])
        self.assertEqual([], payload["commits"][0]["records"])
        self.assertNotIn("UNCOMMITTED_PRIVATE_MARKER", json.dumps(payload))

    def test_ref_scope_does_not_include_other_branch_commits(self):
        branch = self.git("branch", "--show-current")
        self.git("checkout", "-qb", "other")
        self.write("src/target.py", "only_other = True\n")
        other = self.commit("Other branch only")
        self.git("checkout", "-q", branch)
        payload = self.trace()
        self.assertNotIn(other, [entry["sha"] for entry in payload["commits"]])
        payload = self.trace("src/target.py", "--ref", "other")
        self.assertEqual(other, payload["resolved_ref"])
        self.assertNotEqual(payload["resolved_ref"], payload["worktree_head"])

    def test_follow_rename_retains_old_path_candidates(self):
        self.record(path="src/target.py")
        self.commit("Record old path")
        self.git("mv", "src/target.py", "src/renamed.py")
        self.commit("Rename implementation")
        payload = self.trace("src/renamed.py", "--follow")
        self.assertIn("src/target.py", payload["aliases"])
        self.assertIn(self.initial, [entry["sha"] for entry in payload["commits"]])
        self.assertTrue(payload["path_candidates"])

    def test_deleted_file_can_be_traced(self):
        self.git("rm", "-q", "src/target.py")
        removed = self.commit("Remove obsolete implementation")
        payload = self.trace()
        self.assertEqual(removed, payload["commits"][0]["sha"])
        self.assertIn(self.initial, [entry["sha"] for entry in payload["commits"]])

    def test_pathspec_metacharacters_are_literal(self):
        self.write("src/unit[1]*.py", "specific = 1\n")
        target = self.commit("Add literal metacharacter file")
        self.write("src/unit1-other.py", "unrelated = 1\n")
        unrelated = self.commit("Add pathspec decoy")
        payload = self.trace("src/unit[1]*.py")
        self.assertEqual([target], [entry["sha"] for entry in payload["commits"]])
        self.assertNotIn(unrelated, [entry["sha"] for entry in payload["commits"]])

    def test_spaces_tabs_and_newlines_are_preserved_in_paths(self):
        path = "src/odd \tname\n.py"
        self.write(path, "value = 1\n")
        target = self.commit("Add unusual file name")
        payload = self.trace(path)
        self.assertEqual(path, payload["file"])
        self.assertEqual(target, payload["commits"][0]["sha"])

    def test_dirty_state_is_separate_and_command_is_readonly(self):
        self.write("src/target.py", "uncommitted = True\n")
        before = self.git("status", "--porcelain")
        payload = self.trace()
        self.assertEqual(self.initial, payload["commits"][0]["sha"])
        self.assertEqual("M", payload["worktree_changes"][0]["worktree_status"])
        self.assertEqual(before, self.git("status", "--porcelain"))
        self.assertFalse((self.root / "history").exists())

    def test_limit_and_diff_are_bounded_and_truncation_explicit(self):
        self.write("src/target.py", "\n".join(f"value_{idx} = {idx}" for idx in range(3000)))
        self.commit("Large implementation update")
        payload = self.trace("src/target.py", "--limit", "1", "--diff")
        self.assertEqual(1, len(payload["commits"]))
        self.assertLessEqual(len(payload["commits"][0]["diff"]), 8000)
        self.assertTrue(payload["commits"][0]["diff_truncated"])
        self.assertIn("commit_history_truncated", payload["diagnostics"])

    def test_bad_ref_path_and_flags_are_rejected_without_fallback(self):
        for args in [("--file", "src/target.py", "--ref", "not-a-ref"),
                     ("--file", "no-such-file.py"), ("--file", "src"),
                     ("--file", "../elsewhere.py"), ("--file", "runtime.env"),
                     ("--file", "src/target.py", "--limit", "0"),
                     ("--file", "src/target.py", "--limit", "101"),
                     ("--file", "src/target.py", "--record", "something"),
                     ("--ref", "HEAD"), ("--json",)]:
            with self.subTest(args=args):
                self.assertNotEqual(0, self.cli(*args, check=False).returncode)

    def test_legacy_commit_lookup_remains_available(self):
        proc = self.cli("--commit", self.initial)
        self.assertIn("Initial implementation", proc.stdout)
        self.assertIn("src/target.py", proc.stdout)

    def test_archive_counterpart_does_not_duplicate_a_record_identity(self):
        record = self.record(commits=self.initial)
        self.write("history-archive/2026-10/changes/0001-test.md", (self.root / record).read_text())
        self.commit("Keep a stub and archived full text")
        payload = self.trace()
        self.assertEqual(1, len(payload["commits"][0]["records"]))
        self.assertEqual(record, payload["commits"][0]["records"][0]["path"])
        self.assertEqual(1, len(payload["path_candidates"]))

    def test_oversized_record_is_skipped_with_explicit_partial_scan(self):
        self.write("history/changes/large.md", "# Very large note\n" + "src/target.py " * 25_000)
        self.commit("Add an oversized history record")
        payload = self.trace()
        self.assertIn("record_scan_truncated", payload["diagnostics"])
        self.assertFalse(payload["path_candidates"])

    def test_revert_is_not_reported_as_active_effect(self):
        self.write("src/target.py", "value = 2\n")
        changed = self.commit("Change value")
        self.git("revert", "--no-edit", changed)
        payload = self.trace()
        self.assertIn(changed, [entry["sha"] for entry in payload["commits"]])
        self.assertTrue(any("revert" in note for note in payload["notes"]))
        self.assertNotIn("active", payload["commits"][1])

    def test_renamed_runtime_file_is_rejected_before_patch_with_or_without_follow(self):
        self.write("runtime.env", "SYNTHETIC_PROVENANCE_GUARD_MARKER\n")
        self.commit("Add synthetic forbidden filename fixture")
        self.git("mv", "runtime.env", "safe.txt")
        self.commit("Rename synthetic fixture")
        for extra in [(), ("--follow",)]:
            with self.subTest(extra=extra):
                proc = self.cli("--file", "safe.txt", "--diff", "--json", *extra, check=False)
                self.assertNotEqual(0, proc.returncode)
                self.assertIn("runtime.env", proc.stderr)
                self.assertNotIn("SYNTHETIC_PROVENANCE_GUARD_MARKER", proc.stdout + proc.stderr)

    def test_merge_cochange_uses_same_parent_comparisons(self):
        branch = self.git("branch", "--show-current")
        self.git("checkout", "-qb", "feature")
        self.write("src/target.py", "initial = 3\n")
        feature = self.commit("Feature changes target")
        self.git("checkout", "-q", branch)
        self.write("src/target.py", "initial = 2\n")
        main = self.commit("Main changes target differently")
        proc = subprocess.run(["git", "-C", str(self.root), "merge", "--no-commit", "--no-ff", "feature"], capture_output=True, text=True)
        self.assertEqual(1, proc.returncode)
        self.write("src/target.py", "initial = 7\n")
        record = self.record()
        merged = self.commit("Resolve target and record merge rationale")
        payload = self.trace()
        change = payload["commits"][0]
        self.assertEqual(merged, change["sha"])
        self.assertEqual("each-parent", change["change_comparison"])
        relation = next(item for item in change["records"] if item["path"] == record)
        self.assertEqual("co-change", relation["relation"])
        self.assertEqual({main, feature}, set(relation["comparison_parents"]))

    def test_newline_path_evidence_reports_source_line_and_escaped_excerpt(self):
        path = "src/odd\nname.py"
        self.write(path, "specific = 1\n")
        self.commit("Add a newline filename")
        record = self.record(path=path)
        self.commit("Record multiline path literally")
        candidate = self.trace(path)["path_candidates"][0]
        text = (self.root / record).read_text()
        expected = text.count("\n", 0, text.index(path)) + 1
        self.assertEqual(expected, candidate["line"])
        self.assertGreater(candidate["line"], 1)
        self.assertIn("odd\\nname.py", candidate["excerpt"])
        self.assertNotIn("\n", candidate["excerpt"])
        self.assertLessEqual(len(candidate["excerpt"]), 360)

    def test_long_titles_ids_and_subjects_are_clamped_with_diagnostics(self):
        long_title = "title" * 16_000
        long_id = "id" * 40_000
        self.write("history/changes/long-display.md", f"---\ntype: change\nrecord_id: {long_id}\n---\n# {long_title}\n\n## Why\n\nExplain src/target.py without flooding output.\n")
        self.write("src/target.py", "initial = 2\n")
        self.commit("subject" * 10_000)
        proc = self.cli("--file", "src/target.py", "--json")
        self.assertLess(len(proc.stdout), 15_000)
        payload = json.loads(proc.stdout)
        change = payload["commits"][0]
        self.assertLessEqual(len(change["subject"]), 240)
        self.assertTrue(change["subject_truncated"])
        relation = change["records"][0]
        self.assertLessEqual(len(relation["title"]), 240)
        self.assertLessEqual(len(relation["record_id"]), 256)
        self.assertIn("title", relation["display_truncated"])
        self.assertIn("record_id", relation["display_truncated"])

    def test_repository_root_ending_in_space_is_preserved(self):
        self.root = self.root / "repo "
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Trailing Space Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.write("src/target.py", "initial = 1\n")
        self.commit("Initialize repository whose name ends in whitespace")
        payload = self.trace()
        self.assertEqual(str(self.root), payload["repository"])
        self.assertEqual(str(self.root / ".git"), payload["common_git_dir"])


if __name__ == "__main__":
    unittest.main()
