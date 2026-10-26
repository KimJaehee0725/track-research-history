from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tests.collab_behavior_smoke import HistoryCLI

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'history.py'
spec = importlib.util.spec_from_file_location('history_reliability', SCRIPT)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(['git', '-C', str(root), *args], text=True, capture_output=True)
    if proc.returncode:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


class ReliabilityTests(unittest.TestCase):
    def fixture(self, git_repo=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        cli = HistoryCLI(root)
        if git_repo:
            git(root, 'init', '-q')
            git(root, 'config', 'user.name', 'Reliability Fixture')
            git(root, 'config', 'user.email', 'fixture@example.invalid')
        return root, cli

    def initialized_git(self):
        root, cli = self.fixture(True)
        cli.run('bootstrap')
        (root / 'own.txt').write_text('baseline\n')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'Baseline')
        return root, cli

    def add_change(self, cli, title='Own task'):
        return cli.emitted_path(cli.run('change', '--title', title, '--why', title, '--no-git-status'))

    def test_same_filename_never_overwrites_and_ids_are_distinct(self):
        root, _ = self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            first = history.write_record(root, 'changes', '2026-01-01-000000-same.md', '# Change - First\n\nFirst evidence\n', 'change', 'same')
            second = history.write_record(root, 'changes', '2026-01-01-000000-same.md', '# Change - Second\n\nSecond evidence\n', 'change', 'same')
        self.assertNotEqual(first, second)
        self.assertTrue(first.name.startswith("2026-01-01-000000-"))
        self.assertTrue(second.name.startswith("2026-01-01-000000-"))
        self.assertIn('First evidence', first.read_text())
        self.assertIn('Second evidence', second.read_text())
        self.assertNotEqual(history.record_id_for(first), history.record_id_for(second))
        daily = next((root / 'history/daily').glob('*.md')).read_text()
        self.assertEqual(1, daily.count(first.name))
        self.assertEqual(1, daily.count(second.name))

    def test_concurrent_number_allocation_and_daily_updates_are_lossless(self):
        root, cli = self.fixture()
        def create(index):
            return cli.emitted_path(cli.run('idea', '--title', f'Concurrent finding {index}', '--problem', f'Evidence {index}'))
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(create, range(12)))
        self.assertEqual(12, len(set(paths)))
        self.assertEqual(12, len({p.name[:4] for p in paths}))
        self.assertEqual(12, len({history.record_id_for(p) for p in paths}))
        daily = next((root / 'history/daily').glob('*.md')).read_text()
        for index, path in enumerate(paths):
            self.assertIn(f'Evidence {index}', path.read_text())
            self.assertEqual(1, daily.count(path.name))
        self.assertEqual(12, len(list((root / 'history/ideas').glob('*.md'))))

    def test_exclusive_publication_preserves_existing_file(self):
        root, _ = self.fixture()
        target = root / 'note.md'
        target.write_text('Original evidence\n')
        with self.assertRaises(FileExistsError):
            history.atomic_write_text(target, 'Replacement', exclusive=True)
        self.assertEqual('Original evidence\n', target.read_text())
        self.assertEqual([target], list(root.iterdir()))

    def test_latest_uses_record_date_even_when_old_note_touched_later(self):
        root, cli = self.fixture()
        cli.run('bootstrap')
        old = root / 'history/daily/2026-10-18.md'
        recent = root / 'history/daily/2026-10-26.md'
        old.write_text('# Old\n')
        recent.write_text('# Recent\n')
        os.utime(old, (time.time() + 50000, time.time() + 50000))
        self.assertEqual(recent, history.latest_history_file(root, 'daily'))
        self.assertIn('Latest Daily: history/daily/2026-10-26.md', cli.run('start').stdout)

    def test_timezone_offsets_are_preserved_for_numbered_records(self):
        root, _ = self.fixture()
        earlier = root / '0001-first.md'
        later = root / '0002-second.md'
        earlier.write_text('# First\nDate: 2026-10-26 01:00 +0900\n\n## Decision\nA\n')
        later.write_text('# Second\nDate: 2026-10-25 18:00 +0000\n\n## Decision\nB\n')
        self.assertEqual(datetime(2026, 10, 25, 16, tzinfo=timezone.utc), history.record_datetime(earlier))
        self.assertGreater(history.record_sort_key(later), history.record_sort_key(earlier))

    def test_index_is_deterministic_and_does_not_rewrite_unchanged_content(self):
        root, cli = self.fixture()
        cli.run('bootstrap')
        old = self.add_change(cli, 'Old finding')
        before = (root / 'history/INDEX.md').read_bytes()
        modified = (root / 'history/INDEX.md').stat().st_mtime_ns
        os.utime(old, (time.time() + 50000, time.time() + 50000))
        cli.run('index')
        self.assertEqual(before, (root / 'history/INDEX.md').read_bytes())
        self.assertEqual(modified, (root / 'history/INDEX.md').stat().st_mtime_ns)

    def test_read_commands_do_not_bootstrap_missing_history(self):
        for command in [('search', '--exact', 'missing'), ('exact', 'missing'), ('recent',), ('recall',), ('start',)]:
            with self.subTest(command=command):
                root, cli = self.fixture()
                cli.run(*command)
                self.assertEqual([], list(root.iterdir()))

    def test_read_commands_do_not_touch_existing_history(self):
        root, cli = self.fixture()
        cli.run('bootstrap')
        self.add_change(cli)
        snapshot = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        for command in [('search', '--exact', 'Own'), ('exact', 'Own'), ('recent',), ('recall',), ('start',)]:
            cli.run(*command)
        after = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        self.assertEqual(snapshot, after)

    def test_commit_path_rejects_pre_staged_other_work_without_mutation(self):
        root, cli = self.initialized_git()
        record = self.add_change(cli)
        (root / 'own.txt').write_text('Own change\n')
        (root / 'other.txt').write_text('Other staged work\n')
        git(root, 'add', 'other.txt')
        before = git(root, 'rev-parse', 'HEAD'), git(root, 'diff', '--cached', '--binary')
        result = cli.run('commit', '--record', str(record.relative_to(root)), '--message', 'Own change', '--path', 'own.txt', check=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('outside --path', result.stderr)
        self.assertEqual(before, (git(root, 'rev-parse', 'HEAD'), git(root, 'diff', '--cached', '--binary')))

    def test_bookkeeping_does_not_commit_unrelated_history_draft(self):
        root, cli = self.initialized_git()
        record = self.add_change(cli)
        draft = root / 'history/ideas/unrelated-draft.md'
        draft.write_text('# Unrelated draft\n\nNot this task.\n')
        (root / 'own.txt').write_text('Own change\n')
        cli.run('commit', '--record', str(record.relative_to(root)), '--message', 'Own change', '--path', 'own.txt')
        self.assertEqual('', git(root, 'ls-files', '--', str(draft.relative_to(root))))
        self.assertIn('?? history/ideas/unrelated-draft.md', git(root, 'status', '--short', '--untracked-files=all'))
        work_files = git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD~1').splitlines()
        self.assertEqual({'own.txt', str(record.relative_to(root))}, set(work_files))
        bookkeeping_files = git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()
        self.assertNotIn(str(draft.relative_to(root)), bookkeeping_files)

    def test_commit_treats_wildcard_characters_in_explicit_filename_literally(self):
        root, cli = self.initialized_git()
        record = self.add_change(cli)
        filename = 'own [x] file.txt'
        (root / filename).write_text('Selected\n')
        (root / 'own x file.txt').write_text('Unrelated\n')
        cli.run('commit', '--record', str(record.relative_to(root)), '--message', 'Literal filename', '--path', filename)
        self.assertEqual(filename, git(root, 'ls-files', '--', filename))
        self.assertEqual('', git(root, 'ls-files', '--', 'own x file.txt'))

    def test_observation_metadata_is_not_a_paired_commit(self):
        root, cli = self.initialized_git()
        head = git(root, 'rev-parse', 'HEAD')
        record = self.add_change(cli)
        metadata = history.parse_metadata(record.read_text())
        self.assertEqual(head, metadata['git head'])
        self.assertEqual(root.name, metadata['repository'])
        self.assertTrue(metadata['git branch'])
        self.assertEqual([], history.record_commits(record))


if __name__ == '__main__':
    unittest.main()
