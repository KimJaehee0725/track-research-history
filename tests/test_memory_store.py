"""Regression coverage for the self-hosted project memory core."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from research_memory import (  # noqa: E402
    ConflictError,
    JsonRpcDispatcher,
    MemoryStore,
    SecurityError,
    ValidationError,
    dispatch_json_line,
)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = MemoryStore(self.temporary.name)
        self.store.create_project("alienlm", title="AlienLM", description="Recovery notes")

    def test_nested_note_revision_search_delete_and_restore(self) -> None:
        created = self.store.create_note(
            "alienlm",
            "notes/experiment-01.md",
            "Experiment 01",
            "# Experiment 01\n\nRecovery budget is 32 starts.",
        )
        self.assertEqual(created.revision, 1)
        self.assertEqual(self.store.get_note("alienlm", "notes/experiment-01.md").title, "Experiment 01")

        with self.assertRaises(ConflictError):
            self.store.update_note(
                "alienlm",
                "notes/experiment-01.md",
                "Experiment 01",
                "stale update",
                expected_revision=0,
            )

        updated = self.store.update_note(
            "alienlm",
            "notes/experiment-01.md",
            "Experiment 01 revised",
            "# Experiment 01\n\nRecovery budget is 64 starts.",
            expected_revision=1,
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(
            [item.note_id for item in self.store.search("alienlm", "budget 64")],
            ["notes/experiment-01.md"],
        )

        deleted = self.store.delete_note(
            "alienlm", "notes/experiment-01.md", expected_revision=2
        )
        self.assertTrue(deleted.trash_id)
        self.assertEqual(self.store.list_notes("alienlm"), [])
        restored = self.store.restore_note("alienlm", trash_id=deleted.trash_id)
        self.assertEqual(restored.revision, 4)
        self.assertIn("64 starts", self.store.get_note("alienlm", "notes/experiment-01.md").body)

    def test_external_markdown_edit_is_reindexed(self) -> None:
        note = self.store.create_note("alienlm", "notes/direct.md", "Direct", "# Direct\nold text")
        path = Path(self.temporary.name) / "projects" / "alienlm" / "vault" / "notes" / "direct.md"
        path.write_text("# Direct\nnew Obsidian text", encoding="utf-8")

        found = self.store.search("alienlm", "Obsidian")
        self.assertEqual(found[0].note_id, "notes/direct.md")
        self.assertGreater(self.store.get_note("alienlm", "notes/direct.md").revision, note.revision)

    def test_unsafe_paths_are_rejected_before_file_access(self) -> None:
        for note_id in ("../outside.md", "/tmp/outside.md", "notes/../outside.md", "notes\\outside.md"):
            with self.subTest(note_id=note_id), self.assertRaises((ValidationError, SecurityError)):
                self.store.create_note("alienlm", note_id, "Bad", "body")
        self.assertFalse((Path(self.temporary.name) / "outside.md").exists())

    def test_project_trash_preserves_every_note(self) -> None:
        self.store.create_note("alienlm", "notes/keep.md", "Keep", "important")
        deleted = self.store.delete_project("alienlm")
        self.assertTrue(deleted.trash_id)
        self.assertEqual(self.store.list_projects(), [])
        restored = self.store.restore_project("alienlm")
        self.assertEqual(restored.project_id, "alienlm")
        self.assertEqual(self.store.get_note("alienlm", "notes/keep.md").body, "important")

    def test_deleted_content_is_searchable_only_when_explicitly_requested(self) -> None:
        self.store.create_note("alienlm", "notes/trash.md", "Trash", "recoverable needle")
        self.store.delete_note("alienlm", "notes/trash.md")
        self.assertEqual(self.store.search("alienlm", "needle"), [])
        self.assertEqual(
            [record.note_id for record in self.store.search("alienlm", "needle", include_deleted=True)],
            ["notes/trash.md"],
        )

        self.store.restore_note("alienlm", "notes/trash.md")
        self.store.delete_project("alienlm")
        self.assertEqual(
            [record.note_id for record in self.store.search("alienlm", "needle", include_deleted=True)],
            ["notes/trash.md"],
        )

    def test_canonical_rpc_envelope_round_trip(self) -> None:
        dispatcher = JsonRpcDispatcher(self.store)
        response = json.loads(
            dispatch_json_line(
                dispatcher,
                json.dumps(
                    {
                        "version": 1,
                        "op": "note.write",
                        "project": "alienlm",
                        "params": {"path": "notes/rpc.md", "content": "# RPC\nworks"},
                    }
                ),
            )
        )
        self.assertTrue(response["ok"])
        read = json.loads(
            dispatch_json_line(
                dispatcher,
                json.dumps(
                    {
                        "version": 1,
                        "op": "note.read",
                        "project": "alienlm",
                        "params": {"path": "notes/rpc.md"},
                    }
                ),
            )
        )
        self.assertEqual(read["result"]["body"], "# RPC\nworks")

    def test_server_normalizer_keeps_explicit_deleted_scope(self) -> None:
        from server.rpc import normalize_request

        normalized = normalize_request(
            {
                "version": 1,
                "op": "note.search",
                "project": "alienlm",
                "params": {"query": "needle", "include_deleted": True},
            }
        )
        self.assertTrue(normalized["include_deleted"])


if __name__ == "__main__":
    unittest.main()
