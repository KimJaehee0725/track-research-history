#!/usr/bin/env python3
"""Install the same verified skill payload at explicit local discovery paths."""
from __future__ import annotations

import argparse
import errno
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
MOUNT_RENAME_ERRORS = {errno.EXDEV, errno.EBUSY}


def ignored_payload(directory: str, names: list[str]) -> list[str]:
    return [name for name in names if name in {"__pycache__", "runtime.env"} or name.endswith(".pyc")]


def atomic_publish(source: Path, destination: Path) -> None:
    """Publish a leaf on the destination filesystem without following old links."""
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.install-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        if source.is_symlink():
            temporary.unlink()
            temporary.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, temporary)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def rollback_in_place(transaction: dict) -> None:
    target, backup = transaction["target"], transaction["backup"]
    # Publish the previous installation marker after restoring its payload.
    entries = list(reversed(transaction["entries"]))
    entries.sort(key=lambda entry: entry[0] == "INSTALLATION.json")
    for relative, existed in entries:
        destination = target / relative
        if existed:
            atomic_publish(backup / relative, destination)
        elif destination.exists() or destination.is_symlink():
            destination.unlink()
    for directory in reversed(transaction["created_dirs"]):
        try:
            directory.rmdir()
        except OSError:
            pass


def install_in_place(target: Path, stage: Path, backup: Path) -> dict:
    """Fallback for mount roots that cannot be renamed; change managed leaves only."""
    files = [path.relative_to(stage).as_posix() for path in stage.rglob("*")
             if path.is_file() and "runtime.env" not in path.relative_to(stage).parts]
    files.sort(key=lambda name: (name == "INSTALLATION.json", name))
    # Never traverse a link into another checkout, and never replace a directory
    # containing unrelated files with a managed file.
    for relative in files:
        destination = target / relative
        for parent in destination.parents:
            if parent == target:
                break
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise ValueError(f"Cannot install through a non-directory or symlinked parent: {parent}")
        if destination.exists() and destination.is_dir() and not destination.is_symlink():
            raise ValueError(f"Cannot replace an existing directory with a managed file: {destination}")
    backup.mkdir()
    transaction = {"mode": "atomic-files", "target": target, "backup": backup, "entries": [], "created_dirs": []}
    try:
        for relative in files:
            destination = target / relative
            saved = backup / relative
            existed = destination.exists() or destination.is_symlink()
            if existed:
                saved.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_symlink():
                    saved.symlink_to(os.readlink(destination))
                else:
                    shutil.copy2(destination, saved)
            missing = []
            parent = destination.parent
            while parent != target and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                transaction["created_dirs"].append(directory)
            transaction["entries"].append((relative, existed))
            atomic_publish(stage / relative, destination)
        return transaction
    except BaseException:
        rollback_in_place(transaction)
        raise


def manifest(source: Path) -> dict:
    proc = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True)
    revision = proc.stdout.strip() if proc.returncode == 0 else "unversioned"
    capability = subprocess.run(["python3", str(source / "scripts/history.py"), "--capabilities"], capture_output=True, text=True, check=True)
    hashes = {}
    for item in PAYLOAD:
        base = source / item
        for path in ([base] if base.is_file() else sorted(base.rglob("*"))):
            if path.is_file() and not any(part in {"__pycache__", "runtime.env"} for part in path.parts) and path.suffix != ".pyc":
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
                        shutil.copytree(origin, destination, ignore=ignored_payload)
                    else:
                        shutil.copy2(origin, destination)
                (stage / "INSTALLATION.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                (stage / "REVISION").write_text(meta["source_revision"] + "\n", encoding="utf-8")
                if target.exists() or target.is_symlink():
                    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex[:12]}")
                    try:
                        os.replace(target, backup)
                    except OSError as exc:
                        if exc.errno not in MOUNT_RENAME_ERRORS or target.is_symlink() or not target.is_dir():
                            raise
                        transaction = install_in_place(target, stage, backup)
                        completed.append(transaction)
                        plan.update(mode=transaction["mode"], backup=str(backup))
                        continue
                try:
                    os.replace(stage, target)
                except BaseException as exc:
                    if backup:
                        os.replace(backup, target)
                    if isinstance(exc, OSError) and exc.errno in MOUNT_RENAME_ERRORS and target.is_dir() and not target.is_symlink():
                        transaction = install_in_place(target, stage, backup)
                        completed.append(transaction)
                        plan.update(mode=transaction["mode"], backup=str(backup))
                        continue
                    raise
                completed.append({"mode": "atomic-directory", "target": target, "backup": backup})
                plan.update(mode="atomic-directory", backup=str(backup) if backup else None)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
    except BaseException:
        for transaction in reversed(completed):
            target, backup = transaction["target"], transaction["backup"]
            if transaction["mode"] == "atomic-files":
                rollback_in_place(transaction)
            else:
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
