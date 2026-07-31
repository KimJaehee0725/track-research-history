"""Regression coverage for the self-hosted project memory core."""

from __future__ import annotations

from datetime import datetime, timezone
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
    NotFoundError,
    SecurityError,
    ValidationError,
    dispatch_json_line,
    validate_note_path,
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

    def test_project_map_links_active_notes_and_is_not_a_memory_note(self) -> None:
        self.store.create_note(
            "alienlm",
            "context/current-state.md",
            "Current state",
            "# Current state\n\nTracked by the project map.",
        )
        map_path = Path(self.temporary.name) / "projects" / "alienlm" / "vault" / "project-map.md"
        project_map = map_path.read_text(encoding="utf-8")
        self.assertIn("[[context/current-state|Current state]]", project_map)
        self.assertNotIn("project-map.md", [note.note_id for note in self.store.list_notes("alienlm")])

        self.store.delete_note("alienlm", "context/current-state.md")
        self.assertNotIn("[[context/current-state|Current state]]", map_path.read_text(encoding="utf-8"))

        self.store.restore_note("alienlm", "context/current-state.md")
        self.assertIn("[[context/current-state|Current state]]", map_path.read_text(encoding="utf-8"))

    def test_external_markdown_edit_is_reindexed(self) -> None:
        note = self.store.create_note("alienlm", "notes/direct.md", "Direct", "# Direct\nold text")
        path = Path(self.temporary.name) / "projects" / "alienlm" / "vault" / "notes" / "direct.md"
        path.write_text("# Direct\nnew Obsidian text", encoding="utf-8")

        found = self.store.search("alienlm", "Obsidian")
        self.assertEqual(found[0].note_id, "notes/direct.md")
        self.assertGreater(self.store.get_note("alienlm", "notes/direct.md").revision, note.revision)

    def test_unsafe_paths_are_rejected_before_file_access(self) -> None:
        for note_id in (
            "../outside.md",
            "/tmp/outside.md",
            "notes/../outside.md",
            "notes\\outside.md",
            "./note.md",
            "notes//note.md",
            "notes/./note.md",
        ):
            with self.subTest(note_id=note_id), self.assertRaises((ValidationError, SecurityError)):
                self.store.create_note("alienlm", note_id, "Bad", "body")
        self.assertFalse((Path(self.temporary.name) / "outside.md").exists())

    def test_managed_service_directories_cannot_be_symlinks(self) -> None:
        with TemporaryDirectory() as root_name, TemporaryDirectory() as external_name:
            root = Path(root_name)
            external = Path(external_name)
            (root / "projects").symlink_to(external, target_is_directory=True)
            with self.assertRaises(SecurityError):
                MemoryStore(root)
            self.assertEqual(list(external.iterdir()), [])

    def test_audit_symlink_uses_safe_fallback_without_false_failure(self) -> None:
        with TemporaryDirectory() as root_name, TemporaryDirectory() as external_name:
            root = Path(root_name)
            external = Path(external_name) / "outside.txt"
            external.write_text("sentinel\n", encoding="utf-8")
            audit = root / "audit"
            audit.mkdir()
            day = datetime.now(timezone.utc).date().isoformat()
            (audit / f"{day}.jsonl").symlink_to(external)

            store = MemoryStore(root)
            created = store.create_project("demo")

            self.assertEqual(created.project_id, "demo")
            self.assertEqual(external.read_text(encoding="utf-8"), "sentinel\n")
            fallbacks = list(audit.glob("fallback-*.jsonl"))
            self.assertEqual(len(fallbacks), 1)
            self.assertIn(
                '"event": "project.created"',
                fallbacks[0].read_text(encoding="utf-8"),
            )

    def test_project_map_is_reserved_derived_state(self) -> None:
        with self.assertRaisesRegex(ValidationError, "reserved"):
            self.store.create_note(
                "alienlm",
                "project-map.md",
                "User-controlled map",
                "# This must not replace the derived project map",
            )
        with self.assertRaisesRegex(ValidationError, "reserved"):
            validate_note_path("project-map.md")

    def test_startup_regenerates_derived_project_map(self) -> None:
        map_path = (
            Path(self.temporary.name)
            / "projects"
            / "alienlm"
            / "vault"
            / "project-map.md"
        )
        map_path.write_text("# USER CONTROLLED LEGACY MAP\n", encoding="utf-8")

        MemoryStore(self.temporary.name)

        rebuilt = map_path.read_text(encoding="utf-8")
        self.assertNotIn("USER CONTROLLED LEGACY MAP", rebuilt)
        self.assertIn("type: project-map", rebuilt)

    def test_project_delete_rejects_symlink_in_vault_tree(self) -> None:
        with TemporaryDirectory() as external_name:
            external = Path(external_name) / "secret.md"
            external.write_text("secret", encoding="utf-8")
            self.store.create_note("alienlm", "notes/link.md", "Link", "safe")
            note_path = (
                Path(self.temporary.name)
                / "projects"
                / "alienlm"
                / "vault"
                / "notes"
                / "link.md"
            )
            note_path.unlink()
            note_path.symlink_to(external)

            with self.assertRaises(SecurityError):
                self.store.delete_project("alienlm")

            self.assertEqual(self.store.get_project("alienlm").project_id, "alienlm")
            self.assertEqual(external.read_text(encoding="utf-8"), "secret")

    def test_deleted_project_search_and_restore_reject_symlink_payload(self) -> None:
        with TemporaryDirectory() as external_name:
            external = Path(external_name) / "secret.md"
            external.write_text("DELETED_PROJECT_SECRET", encoding="utf-8")
            self.store.create_note("alienlm", "notes/link.md", "Link", "safe")
            deleted = self.store.delete_project("alienlm")
            payload = (
                Path(self.temporary.name)
                / "trash"
                / str(deleted.trash_id)
                / "project"
                / "vault"
                / "notes"
                / "link.md"
            )
            payload.unlink()
            payload.symlink_to(external)

            with self.assertRaises(SecurityError):
                self.store.search(
                    "alienlm",
                    "DELETED_PROJECT_SECRET",
                    include_deleted=True,
                )
            with self.assertRaises(SecurityError):
                self.store.restore_project("alienlm")
            self.assertFalse(
                (Path(self.temporary.name) / "projects" / "alienlm").exists()
            )

    def test_note_restore_rejects_symlink_payload(self) -> None:
        with TemporaryDirectory() as external_name:
            external = Path(external_name) / "secret.md"
            external.write_text("RESTORE_SECRET", encoding="utf-8")
            self.store.create_note("alienlm", "notes/link.md", "Link", "safe")
            deleted = self.store.delete_note("alienlm", "notes/link.md")
            payload = (
                Path(self.temporary.name)
                / "trash"
                / str(deleted.trash_id)
                / "note.md"
            )
            payload.unlink()
            payload.symlink_to(external)

            with self.assertRaises(SecurityError):
                self.store.restore_note("alienlm", trash_id=deleted.trash_id)
            self.assertEqual(self.store.list_notes("alienlm"), [])

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

    def test_embedded_rpc_rejects_string_boolean_and_limit(self) -> None:
        dispatcher = JsonRpcDispatcher(self.store)
        for request in (
            {
                "version": 1,
                "op": "project.init",
                "project": "string-false",
                "params": {"enable_git": "false"},
            },
            {
                "version": 1,
                "op": "note.search",
                "project": "alienlm",
                "params": {"query": "x", "limit": "20"},
            },
            {
                "version": 1,
                "op": "note.list",
                "project": "alienlm",
                "params": {"limit": "1"},
            },
        ):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                dispatcher.dispatch(request)
        self.assertFalse(
            Path(self.temporary.name, "projects", "string-false").exists()
        )

    def test_embedded_rpc_only_creates_on_not_found(self) -> None:
        class FailingStore:
            def __init__(self) -> None:
                self.create_called = False

            def get_note(self, *_: object, **__: object) -> object:
                raise ConflictError("storage conflict")

            def create_note(self, *_: object, **__: object) -> object:
                self.create_called = True
                raise AssertionError("create_note must not be called")

        store = FailingStore()
        dispatcher = JsonRpcDispatcher(store)  # type: ignore[arg-type]
        with self.assertRaises(ConflictError):
            dispatcher.dispatch(
                {
                    "version": 1,
                    "op": "note.write",
                    "project": "alienlm",
                    "params": {"path": "notes/rpc.md", "content": "body"},
                }
            )
        self.assertFalse(store.create_called)

    def test_embedded_rpc_honors_note_list_limit(self) -> None:
        for index in range(3):
            self.store.create_note(
                "alienlm",
                f"notes/list-{index}.md",
                f"List {index}",
                "body",
            )
        response = JsonRpcDispatcher(self.store).dispatch(
            {
                "version": 1,
                "op": "note.list",
                "project": "alienlm",
                "params": {"limit": 1},
            }
        )
        self.assertEqual(len(response["result"]), 1)

    def test_embedded_rpc_sanitizes_unexpected_store_failure(self) -> None:
        class FailingStore:
            def __init__(self, failure: Exception) -> None:
                self.failure = failure

            def get_note(self, *_: object, **__: object) -> object:
                raise self.failure

        for failure in (
            OSError("/private/server/secret"),
            SecurityError("unsafe server symlink"),
        ):
            response = json.loads(
                dispatch_json_line(
                    JsonRpcDispatcher(FailingStore(failure)),  # type: ignore[arg-type]
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
            with self.subTest(failure=failure):
                self.assertEqual(response["error"]["code"], "store_error")
                self.assertNotIn(str(failure), json.dumps(response))

    def test_embedded_rpc_reports_not_found_separately(self) -> None:
        response = json.loads(
            dispatch_json_line(
                JsonRpcDispatcher(self.store),
                json.dumps(
                    {
                        "version": 1,
                        "op": "note.read",
                        "project": "alienlm",
                        "params": {"path": "notes/missing.md"},
                    }
                ),
            )
        )
        self.assertEqual(response["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
