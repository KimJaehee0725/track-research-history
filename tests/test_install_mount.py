from __future__ import annotations

import errno
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("history_install_mount", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MountInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        for folder in ["scripts", "agents", "references"]:
            (self.source / folder).mkdir(parents=True)
        for name in ["SKILL.md", "README.md", "scripts/tool.py", "agents/openai.yaml", "references/layout.md"]:
            (self.source / name).write_text("new " + name + "\n")
        (self.source / "scripts/history.py").write_text("import json\nprint(json.dumps({'backend': 'vendored-bm25s'}))\n")
        # Synthetic fixture: guards below ensure this local-only file is never read/copied.
        (self.source / "scripts/runtime.env").write_text("fixture only\n")

    def old_target(self, name):
        target = self.base / name
        (target / "scripts").mkdir(parents=True)
        for leaf in ["SKILL.md", "README.md", "REVISION", "INSTALLATION.json", "scripts/tool.py", "unrelated.txt"]:
            (target / leaf).write_text("old " + leaf + "\n")
        (target / "runtime.env").write_text("fixture only\n")
        return target

    def snapshot(self, target):
        return {path.relative_to(target).as_posix(): ("symlink", os.readlink(path)) if path.is_symlink() else ("file", path.read_bytes())
                for path in target.rglob("*") if path.is_file() and path.name != "runtime.env"}

    def guarded_copy(self, original):
        def copy(source, destination, *args, **kwargs):
            if Path(source).name == "runtime.env":
                raise AssertionError("runtime.env must not be copied")
            return original(source, destination, *args, **kwargs)
        return copy

    def test_mount_fallback_is_atomic_per_file_marker_last_and_backup_scoped(self):
        for error in [errno.EXDEV, errno.EBUSY]:
            with self.subTest(error=error):
                target = self.old_target(f"mounted-{error}")
                identity = target.stat().st_ino
                local_identity = (target / "runtime.env").stat()
                real_replace, real_copy = os.replace, shutil.copy2
                publishes = []
                def replace(source, destination):
                    if Path(source) == target:
                        raise OSError(error, "mount root cannot be renamed")
                    if Path(destination).is_relative_to(target):
                        publishes.append(Path(destination).relative_to(target).as_posix())
                    return real_replace(source, destination)
                original_read = Path.read_bytes
                def read(path):
                    if path.name == "runtime.env":
                        raise AssertionError("runtime.env must not be read")
                    return original_read(path)
                with patch.object(installer.os, "replace", side_effect=replace), patch.object(installer.shutil, "copy2", side_effect=self.guarded_copy(real_copy)), patch.object(Path, "read_bytes", read):
                    plan = installer.install(self.source, [target])[0]
                self.assertEqual("atomic-files", plan["mode"])
                self.assertEqual(identity, target.stat().st_ino)
                self.assertEqual("new SKILL.md\n", (target / "SKILL.md").read_text())
                self.assertEqual("old unrelated.txt\n", (target / "unrelated.txt").read_text())
                self.assertEqual(local_identity.st_ino, (target / "runtime.env").stat().st_ino)
                self.assertEqual(local_identity.st_mtime_ns, (target / "runtime.env").stat().st_mtime_ns)
                backup = Path(plan["backup"])
                self.assertEqual("old SKILL.md\n", (backup / "SKILL.md").read_text())
                self.assertFalse((backup / "unrelated.txt").exists())
                self.assertEqual([], list(backup.rglob("runtime.env")))
                self.assertEqual("INSTALLATION.json", publishes[-1])
                self.assertNotIn("scripts/runtime.env", json.loads((target / "INSTALLATION.json").read_text())["sha256"])

    def test_mid_update_failure_restores_mount_without_removing_root(self):
        target = self.old_target("mounted-failure")
        before, identity = self.snapshot(target), target.stat().st_ino
        real_replace, real_rmtree = os.replace, shutil.rmtree
        failed = False
        def replace(source, destination):
            nonlocal failed
            if Path(source) == target:
                raise OSError(errno.EXDEV, "mount root")
            if Path(destination) == target / "SKILL.md" and not failed:
                failed = True
                raise OSError(errno.EIO, "forced file publish failure")
            return real_replace(source, destination)
        def rmtree(path, *args, **kwargs):
            if Path(path) == target:
                raise AssertionError("mounted root must never be removed")
            return real_rmtree(path, *args, **kwargs)
        with patch.object(installer.os, "replace", side_effect=replace), patch.object(installer.shutil, "rmtree", side_effect=rmtree):
            with self.assertRaisesRegex(OSError, "forced file publish"):
                installer.install(self.source, [target])
        self.assertEqual(identity, target.stat().st_ino)
        self.assertEqual(before, self.snapshot(target))
        self.assertFalse((target / "agents").exists())

    def test_later_target_failure_rolls_back_completed_mount(self):
        first, second = self.old_target("first-mount"), self.old_target("second-target")
        first_before, second_before = self.snapshot(first), self.snapshot(second)
        first_inode = first.stat().st_ino
        real_replace = os.replace
        def replace(source, destination):
            if Path(source) == first:
                raise OSError(errno.EBUSY, "mount root")
            if Path(source) == second:
                raise OSError(errno.EACCES, "forced permission failure")
            return real_replace(source, destination)
        with patch.object(installer.os, "replace", side_effect=replace):
            with self.assertRaisesRegex(OSError, "forced permission"):
                installer.install(self.source, [first, second])
        self.assertEqual(first_inode, first.stat().st_ino)
        self.assertEqual(first_before, self.snapshot(first))
        self.assertEqual(second_before, self.snapshot(second))

    def test_later_mount_failure_restores_prior_root_and_leaf_symlinks(self):
        original = self.base / "original-source"
        original.mkdir()
        (original / "old.md").write_text("original source remains\n")
        first = self.base / "first-link"
        first.symlink_to(original, target_is_directory=True)
        second = self.old_target("second-mount")
        external = self.base / "external-skill.md"
        external.write_text("external source remains\n")
        (second / "SKILL.md").unlink()
        (second / "SKILL.md").symlink_to(external)
        before = self.snapshot(second)
        real_replace = os.replace
        failed = False
        def replace(source, destination):
            nonlocal failed
            if Path(source) == second:
                raise OSError(errno.EXDEV, "mount root")
            if Path(destination) == second / "scripts/tool.py" and not failed:
                failed = True
                raise OSError(errno.EIO, "forced late failure")
            return real_replace(source, destination)
        with patch.object(installer.os, "replace", side_effect=replace):
            with self.assertRaisesRegex(OSError, "forced late"):
                installer.install(self.source, [first, second])
        self.assertTrue(first.is_symlink())
        self.assertEqual(original, first.resolve())
        self.assertEqual("original source remains\n", (original / "old.md").read_text())
        self.assertEqual("external source remains\n", external.read_text())
        self.assertEqual(before, self.snapshot(second))

    def test_permission_failure_does_not_attempt_mount_fallback(self):
        target = self.old_target("permission-failure")
        before = self.snapshot(target)
        real_replace = os.replace
        def replace(source, destination):
            if Path(source) == target:
                raise OSError(errno.EROFS, "read-only filesystem")
            return real_replace(source, destination)
        with patch.object(installer.os, "replace", side_effect=replace), patch.object(installer, "install_in_place") as fallback:
            with self.assertRaisesRegex(OSError, "read-only"):
                installer.install(self.source, [target])
            fallback.assert_not_called()
        self.assertEqual(before, self.snapshot(target))

    def test_symlinked_parent_is_rejected_without_touching_external_directory(self):
        target = self.old_target("linked-parent")
        (target / "scripts/tool.py").unlink()
        (target / "scripts").rmdir()
        external = self.base / "external-scripts"
        external.mkdir()
        (external / "tool.py").write_text("external unchanged\n")
        (target / "scripts").symlink_to(external, target_is_directory=True)
        real_replace = os.replace
        def replace(source, destination):
            if Path(source) == target:
                raise OSError(errno.EXDEV, "mount root")
            return real_replace(source, destination)
        before = self.snapshot(target)
        with patch.object(installer.os, "replace", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "symlinked parent"):
                installer.install(self.source, [target])
        self.assertTrue((target / "scripts").is_symlink())
        self.assertEqual("external unchanged\n", (external / "tool.py").read_text())
        self.assertEqual(before, self.snapshot(target))


if __name__ == "__main__":
    unittest.main()
