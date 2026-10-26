#!/usr/bin/env python3
"""Install the same verified skill payload at explicit local discovery paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
PAYLOAD = ("SKILL.md", "README.md", "agents", "references", "scripts")


def manifest(source: Path) -> dict:
    proc = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True)
    revision = proc.stdout.strip() if proc.returncode == 0 else "unversioned"
    capability = subprocess.run(["python3", str(source / "scripts/history.py"), "--capabilities"], capture_output=True, text=True, check=True)
    hashes = {}
    for item in PAYLOAD:
        base = source / item
        for path in ([base] if base.is_file() else sorted(base.rglob("*"))):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                hashes[path.relative_to(source).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"source_revision": revision, "capabilities": json.loads(capability.stdout), "sha256": hashes}


def install(source: Path, targets: list[Path], dry_run: bool = False) -> list[dict]:
    source = source.resolve()
    targets = [Path(os.path.abspath(path.expanduser())) for path in targets]
    if len(set(targets)) != len(targets):
        raise ValueError("Installation targets must be distinct")
    for target in targets:
        if target.resolve() == source or source.is_relative_to(target.resolve()) or target.resolve().is_relative_to(source):
            raise ValueError("An installation target must not overlap the source checkout")
        if target.exists() and not target.is_symlink() and (target / ".git").exists():
            raise ValueError(f"Refusing to replace a Git checkout: {target}")
        if any(target != other and (target.is_relative_to(other) or other.is_relative_to(target)) for other in targets):
            raise ValueError("Installation targets must not overlap")
    meta = manifest(source)
    plans = [{"target": str(target), "source_revision": meta["source_revision"], "dry_run": dry_run} for target in targets]
    if dry_run:
        return plans
    completed = []
    try:
        for target, plan in zip(targets, plans):
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target.parent))
            backup = None
            try:
                for item in PAYLOAD:
                    origin = source / item
                    destination = stage / item
                    if origin.is_dir():
                        shutil.copytree(origin, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                    else:
                        shutil.copy2(origin, destination)
                (stage / "INSTALLATION.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                (stage / "REVISION").write_text(meta["source_revision"] + "\n", encoding="utf-8")
                if target.exists() or target.is_symlink():
                    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex[:12]}")
                    os.replace(target, backup)
                try:
                    os.replace(stage, target)
                except BaseException:
                    if backup:
                        os.replace(backup, target)
                    raise
                completed.append((target, backup))
                plan["backup"] = str(backup) if backup else None
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
    except BaseException:
        for target, backup in reversed(completed):
            shutil.rmtree(target)
            if backup:
                os.replace(backup, target)
        raise
    return plans


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, action="append", required=True, help="Explicit Codex/Claude skill discovery directory (repeatable).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install(SOURCE, args.target, args.dry_run), ensure_ascii=False, indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Install failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
