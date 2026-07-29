#!/usr/bin/env python3
"""Refresh derived Obsidian project-map.md files for every active project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
for candidate in (SOURCE_ROOT, REPOSITORY_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from research_memory.store import MemoryStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("MEMORY_DATA_DIR", "/srv/research-memory"))
    args = parser.parse_args()
    store = MemoryStore(args.data_dir, actor="obsidian-map-refresh")
    projects = store.list_projects()
    for project in projects:
        store.rebuild_project_map(project.project_id)
    print(f"Refreshed Obsidian maps for {len(projects)} project(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
