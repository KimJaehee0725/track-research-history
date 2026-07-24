#!/usr/bin/env python3
"""Safely manage project-scoped SSH RPC keys on the memory server.

This command is intended to run on the server through ``sudo``.  It owns only
entries that it writes: each entry has a marker comment followed immediately by
one restricted ``authorized_keys`` line.  Other administrators' lines are
preserved byte-for-byte apart from the normal final newline added when a file
is changed.

The helper deliberately accepts public-key *files*, not arbitrary key lines,
and never executes a client-controlled command.  Its generated policy matches
``server/rpc.py``: one project, a read/write ceiling, and a stable audit actor.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shlex
import stat
import sys
import tempfile
from typing import Iterator, Sequence


DEFAULT_AUTHORIZED_KEYS = "/home/memory-rpc/.ssh/authorized_keys"
DEFAULT_RUNTIME_ROOT = "/opt/research-memory"
DEFAULT_DATA_DIR = "/srv/research-memory"
DEFAULT_ACCOUNT = "memory-rpc"

PROJECT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
ACTOR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SAFE_SERVER_PATH_RE = re.compile(r"/[A-Za-z0-9._/+:-]*\Z")
MARKER_RE = re.compile(
    r"# research-memory-key-v1 "
    r"project=(?P<project>[A-Za-z0-9][A-Za-z0-9._-]{0,63}) "
    r"permission=(?P<permission>read|write) "
    r"actor=(?P<actor>[A-Za-z0-9][A-Za-z0-9._-]{0,127}) "
    r"fingerprint=(?P<fingerprint>SHA256:[A-Za-z0-9+/]+)\Z"
)
ALLOWED_KEY_TYPES = frozenset(
    {
        "ssh-ed25519",
        "sk-ssh-ed25519@openssh.com",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
        "sk-ecdsa-sha2-nistp256@openssh.com",
        # ``ssh-rsa`` is the public-key format name.  Modern OpenSSH can use
        # RSA SHA-2 signatures for this format; legacy SHA-1 acceptance is a
        # separate sshd policy decision.
        "ssh-rsa",
    }
)


class AdminError(ValueError):
    """A configuration or input error safe to show to a server administrator."""


@dataclass(frozen=True)
class PublicKey:
    key_type: str
    encoded: str
    blob: bytes
    comment: str

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(self.blob).digest()
        return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class ManagedKey:
    project: str
    permission: str
    actor: str
    fingerprint: str
    key_type: str
    comment: str


def _validate_identifier(value: str, *, field: str, pattern: re.Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise AdminError(
            f"{field} must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_', or '-'"
        )
    return value


def validate_project(value: str) -> str:
    return _validate_identifier(value, field="project", pattern=PROJECT_ID_RE)


def validate_actor(value: str) -> str:
    return _validate_identifier(value, field="actor", pattern=ACTOR_RE)


def validate_permission(value: str) -> str:
    if value not in {"read", "write"}:
        raise AdminError("permission must be either 'read' or 'write'")
    return value


def validate_server_path(value: str, *, field: str) -> str:
    """Accept only an absolute, shell-safe deployment path.

    These paths are placed inside the SSH ``command=\"...\"`` option.  The
    intentionally conservative alphabet keeps the generated forced command
    simple and prevents an administrator typo from becoming shell syntax.
    """

    if not SAFE_SERVER_PATH_RE.fullmatch(value):
        raise AdminError(f"{field} must be an absolute shell-safe POSIX path")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise AdminError(f"{field} must be an absolute path without '..'")
    return str(path)


def _validate_comment(value: str) -> str:
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise AdminError("public-key comments must contain printable ASCII only")
    return value


def _decode_key_blob(key_type: str, encoded: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", encoded):
        raise AdminError("public key has invalid base64 data")
    try:
        blob = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise AdminError("public key has invalid base64 data") from exc

    if len(blob) < 5:
        raise AdminError("public key blob is too short")
    type_length = int.from_bytes(blob[:4], byteorder="big")
    type_end = 4 + type_length
    if type_length == 0 or type_end >= len(blob):
        raise AdminError("public key blob has an invalid type field")
    try:
        embedded_type = blob[4:type_end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise AdminError("public key blob has an invalid type field") from exc
    if embedded_type != key_type:
        raise AdminError("public key type does not match its encoded key blob")
    return blob


def parse_public_key_line(line: str) -> PublicKey:
    """Parse one plain OpenSSH public-key line, without authorized-key options."""

    if "\x00" in line or "\r" in line or "\n" in line:
        raise AdminError("public key must be exactly one safe text line")
    if not line.strip():
        raise AdminError("public key is empty")
    fields = line.strip().split(maxsplit=2)
    if len(fields) < 2:
        raise AdminError("public key must contain a key type and base64 data")
    key_type, encoded = fields[:2]
    if key_type not in ALLOWED_KEY_TYPES:
        raise AdminError(
            "public key type is not supported; use ed25519, security-key, ECDSA, or RSA"
        )
    comment = _validate_comment(fields[2] if len(fields) == 3 else "")
    blob = _decode_key_blob(key_type, encoded)
    canonical = base64.b64encode(blob).decode("ascii").rstrip("=")
    return PublicKey(key_type=key_type, encoded=canonical, blob=blob, comment=comment)


def read_public_key(path: str | Path) -> PublicKey:
    public_path = Path(path)
    try:
        raw = public_path.read_bytes()
    except OSError as exc:
        raise AdminError(f"could not read public key file {public_path}: {exc.strerror or exc}") from exc
    if not raw or len(raw) > 16 * 1024:
        raise AdminError("public key file must contain one line no longer than 16 KiB")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AdminError("public key file must be ASCII OpenSSH public-key text") from exc
    if "\x00" in text or "\r" in text:
        raise AdminError("public key file must contain one LF-terminated line at most")
    lines = text.splitlines()
    if len(lines) != 1:
        raise AdminError("public key file must contain exactly one public-key line")
    return parse_public_key_line(lines[0])


def render_forced_command(
    *,
    project: str,
    permission: str,
    actor: str,
    runtime_root: str,
    data_dir: str,
) -> str:
    """Return the fixed command consumed by the SSH ``command=`` restriction."""

    project = validate_project(project)
    permission = validate_permission(permission)
    actor = validate_actor(actor)
    runtime_root = validate_server_path(runtime_root, field="runtime root")
    data_dir = validate_server_path(data_dir, field="data directory")
    python_path = f"{runtime_root}/.venv/bin/python"
    rpc_path = f"{runtime_root}/server/rpc.py"
    return (
        f"{python_path} {rpc_path} --data-dir {data_dir} "
        f"--allow-project {project} --permission {permission} --actor {actor}"
    )


def _marker(*, project: str, permission: str, actor: str, fingerprint: str) -> str:
    return (
        "# research-memory-key-v1 "
        f"project={project} permission={permission} actor={actor} fingerprint={fingerprint}"
    )


def render_managed_entry(
    *,
    project: str,
    permission: str,
    actor: str,
    public_key: PublicKey,
    runtime_root: str,
    data_dir: str,
) -> str:
    """Render the two-line managed block added to ``authorized_keys``."""

    command = render_forced_command(
        project=project,
        permission=permission,
        actor=actor,
        runtime_root=runtime_root,
        data_dir=data_dir,
    )
    comment = public_key.comment or f"research-memory-{actor}"
    line = f'restrict,command="{command}" {public_key.key_type} {public_key.encoded} {comment}'
    return "\n".join(
        (
            _marker(
                project=project,
                permission=permission,
                actor=actor,
                fingerprint=public_key.fingerprint,
            ),
            line,
        )
    )


def _marker_metadata(line: str) -> tuple[str, str, str, str] | None:
    match = MARKER_RE.fullmatch(line)
    if match is None:
        return None
    return (
        match.group("project"),
        match.group("permission"),
        match.group("actor"),
        match.group("fingerprint"),
    )


def _parse_managed_line(
    line: str,
    *,
    project: str,
    permission: str,
    actor: str,
    fingerprint: str,
) -> ManagedKey | None:
    """Recognize only blocks that have the exact restricted RPC policy shape."""

    prefix = 'restrict,command="'
    if not line.startswith(prefix):
        return None
    command_end = line.find('"', len(prefix))
    if command_end < 0:
        return None
    command = line[len(prefix) : command_end]
    key_line = line[command_end + 1 :].strip()
    try:
        command_tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(command_tokens) != 10:
        return None
    if not (
        command_tokens[0].endswith("/.venv/bin/python")
        and command_tokens[1].endswith("/server/rpc.py")
        and command_tokens[2] == "--data-dir"
        and command_tokens[4] == "--allow-project"
        and command_tokens[5] == project
        and command_tokens[6] == "--permission"
        and command_tokens[7] == permission
        and command_tokens[8] == "--actor"
        and command_tokens[9] == actor
    ):
        return None
    try:
        validate_server_path(command_tokens[0][: -len("/.venv/bin/python")], field="runtime root")
        validate_server_path(command_tokens[1][: -len("/server/rpc.py")], field="runtime root")
        validate_server_path(command_tokens[3], field="data directory")
        public_key = parse_public_key_line(key_line)
    except AdminError:
        return None
    if public_key.fingerprint != fingerprint:
        return None
    return ManagedKey(
        project=project,
        permission=permission,
        actor=actor,
        fingerprint=fingerprint,
        key_type=public_key.key_type,
        comment=public_key.comment,
    )


def _managed_blocks(lines: Sequence[str]) -> list[tuple[int, ManagedKey]]:
    """Return recognizable marker/key pairs without treating other lines as ours."""

    blocks: list[tuple[int, ManagedKey]] = []
    for index, marker_line in enumerate(lines[:-1]):
        metadata = _marker_metadata(marker_line)
        if metadata is None:
            continue
        project, permission, actor, fingerprint = metadata
        managed = _parse_managed_line(
            lines[index + 1],
            project=project,
            permission=permission,
            actor=actor,
            fingerprint=fingerprint,
        )
        if managed is not None:
            blocks.append((index, managed))
    return blocks


def list_managed_keys(authorized_keys: str | Path) -> list[ManagedKey]:
    path = Path(authorized_keys)
    with _authorized_keys_lock(path, shared=True):
        text = _read_authorized_keys(path)
        return [managed for _, managed in _managed_blocks(text.splitlines())]


def _iter_public_key_fingerprints(lines: Sequence[str]) -> Iterator[str]:
    """Find public-key blobs in arbitrary existing entries to prevent shadowing.

    A duplicated public key can cause sshd to select a pre-existing, less
    restrictive line.  This intentionally does not try to interpret arbitrary
    options; it only detects a supported key type immediately followed by a
    syntactically valid blob.
    """

    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        tokens = line.split()
        for index, token in enumerate(tokens[:-1]):
            if token not in ALLOWED_KEY_TYPES:
                continue
            try:
                candidate = parse_public_key_line(f"{token} {tokens[index + 1]}")
            except AdminError:
                continue
            yield candidate.fingerprint
            break


def _validate_authorized_keys_path(path: Path) -> None:
    parent = path.parent
    try:
        parent_stat = parent.lstat()
    except OSError as exc:
        raise AdminError(f"authorized_keys parent directory does not exist: {parent}") from exc
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise AdminError("authorized_keys parent must be a real directory")
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AdminError(f"could not inspect authorized_keys: {exc.strerror or exc}") from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise AdminError("authorized_keys must be a regular file, not a symlink or device")


@contextmanager
def _authorized_keys_lock(path: Path, *, shared: bool = False) -> Iterator[None]:
    """Serialize reads and atomic updates without granting the RPC user writes."""

    _validate_authorized_keys_path(path)
    lock_path = path.parent / f".{path.name}.research-memory.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise AdminError(f"could not lock authorized_keys: {exc.strerror or exc}") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_authorized_keys(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError as exc:
        raise AdminError("authorized_keys must be UTF-8 or ASCII text before this helper edits it") from exc
    except OSError as exc:
        raise AdminError(f"could not read authorized_keys: {exc.strerror or exc}") from exc


def _creation_owner(account: str) -> tuple[int, int]:
    try:
        record = pwd.getpwnam(account)
    except KeyError as exc:
        raise AdminError(
            f"authorized_keys does not exist and service account {account!r} was not found"
        ) from exc
    return record.pw_uid, record.pw_gid


def _write_authorized_keys(path: Path, text: str, *, account: str) -> None:
    """Atomically replace the file while preserving an existing file's owner/mode."""

    _validate_authorized_keys_path(path)
    try:
        existing = path.stat()
    except FileNotFoundError:
        owner_uid, owner_gid = _creation_owner(account)
        mode = 0o600
    except OSError as exc:
        raise AdminError(f"could not inspect authorized_keys: {exc.strerror or exc}") from exc
    else:
        owner_uid, owner_gid = existing.st_uid, existing.st_gid
        mode = stat.S_IMODE(existing.st_mode)

    if os.geteuid() != 0 and (owner_uid != os.geteuid() or owner_gid != os.getegid()):
        raise AdminError("run this helper with sudo so authorized_keys ownership is preserved")

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.research-memory-", dir=path.parent
        )
    except OSError as exc:
        raise AdminError(f"could not create authorized_keys update: {exc.strerror or exc}") from exc
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        if os.geteuid() == 0:
            os.fchown(descriptor, owner_uid, owner_gid)
        payload = text.encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("could not write authorized_keys update")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise AdminError(f"could not atomically update authorized_keys: {exc.strerror or exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_entry(existing: str, entry: str) -> str:
    if not existing:
        return entry + "\n"
    separator = "" if existing.endswith("\n\n") else "\n"
    if not existing.endswith("\n"):
        separator = "\n\n"
    return existing + separator + entry + "\n"


def grant_key(
    authorized_keys: str | Path,
    *,
    project: str,
    permission: str,
    actor: str,
    public_key: PublicKey,
    runtime_root: str = DEFAULT_RUNTIME_ROOT,
    data_dir: str = DEFAULT_DATA_DIR,
    account: str = DEFAULT_ACCOUNT,
) -> ManagedKey:
    """Add one constrained key after checking for ambiguous duplicate material."""

    project = validate_project(project)
    permission = validate_permission(permission)
    actor = validate_actor(actor)
    runtime_root = validate_server_path(runtime_root, field="runtime root")
    data_dir = validate_server_path(data_dir, field="data directory")
    path = Path(authorized_keys)
    with _authorized_keys_lock(path):
        existing = _read_authorized_keys(path)
        lines = existing.splitlines()
        managed = _managed_blocks(lines)
        for _, item in managed:
            if item.project == project and item.actor == actor:
                raise AdminError(
                    f"a managed key already exists for project={project!r} and actor={actor!r}; "
                    "revoke it before granting a replacement"
                )
        if public_key.fingerprint in set(_iter_public_key_fingerprints(lines)):
            raise AdminError(
                "this public key is already present in authorized_keys; remove the existing "
                "entry before granting it a new forced-command policy"
            )
        entry = render_managed_entry(
            project=project,
            permission=permission,
            actor=actor,
            public_key=public_key,
            runtime_root=runtime_root,
            data_dir=data_dir,
        )
        _write_authorized_keys(path, _append_entry(existing, entry), account=account)
    return ManagedKey(
        project=project,
        permission=permission,
        actor=actor,
        fingerprint=public_key.fingerprint,
        key_type=public_key.key_type,
        comment=public_key.comment or f"research-memory-{actor}",
    )


def revoke_keys(
    authorized_keys: str | Path,
    *,
    actor: str,
    project: str | None = None,
    account: str = DEFAULT_ACCOUNT,
) -> list[ManagedKey]:
    """Remove only complete marker/key pairs owned by this helper."""

    actor = validate_actor(actor)
    if project is not None:
        project = validate_project(project)
    path = Path(authorized_keys)
    with _authorized_keys_lock(path):
        existing = _read_authorized_keys(path)
        if not existing:
            return []
        lines = existing.splitlines()
        recognized = {index: item for index, item in _managed_blocks(lines)}
        kept: list[str] = []
        removed: list[ManagedKey] = []
        index = 0
        while index < len(lines):
            item = recognized.get(index)
            if item is not None and item.actor == actor and (project is None or item.project == project):
                removed.append(item)
                index += 2
                continue
            kept.append(lines[index])
            index += 1
        if removed:
            updated = "\n".join(kept)
            if updated:
                updated += "\n"
            _write_authorized_keys(path, updated, account=account)
        return removed


def _entry_dict(entry: ManagedKey) -> dict[str, str]:
    return asdict(entry)


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--authorized-keys",
        default=DEFAULT_AUTHORIZED_KEYS,
        help=f"authorized_keys file (default: {DEFAULT_AUTHORIZED_KEYS})",
    )
    parser.add_argument(
        "--runtime-root",
        default=DEFAULT_RUNTIME_ROOT,
        help=f"deployed repository root (default: {DEFAULT_RUNTIME_ROOT})",
    )
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        help=f"MemoryStore data root (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--account",
        default=DEFAULT_ACCOUNT,
        help=(
            "owner for a newly created authorized_keys file; existing owner and mode are preserved "
            f"(default: {DEFAULT_ACCOUNT})"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage restricted project-scoped SSH keys for Research Memory.",
    )
    resources = parser.add_subparsers(dest="resource", required=True)
    key_parser = resources.add_parser("key", help="grant, list, or revoke SSH RPC keys")
    commands = key_parser.add_subparsers(dest="command", required=True)

    grant = commands.add_parser("grant", help="add one project-scoped forced-command key")
    _add_common_options(grant)
    grant.add_argument("--project", required=True, help="single project ID allowed by this key")
    grant.add_argument("--permission", required=True, choices=("read", "write"))
    grant.add_argument("--actor", required=True, help="stable audit actor for this key")
    grant.add_argument("--public-key", required=True, help="path to one OpenSSH .pub file")

    list_parser = commands.add_parser("list", help="list keys managed by this helper")
    _add_common_options(list_parser)
    list_parser.add_argument("--project", help="only show one project")
    list_parser.add_argument("--permission", choices=("read", "write"), help="only show one permission")
    list_parser.add_argument("--actor", help="only show one audit actor")

    revoke = commands.add_parser("revoke", help="revoke managed keys for an actor")
    _add_common_options(revoke)
    revoke.add_argument("--actor", required=True, help="audit actor to revoke")
    revoke.add_argument("--project", help="limit revocation to one project")
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "grant":
            entry = grant_key(
                args.authorized_keys,
                project=args.project,
                permission=args.permission,
                actor=args.actor,
                public_key=read_public_key(args.public_key),
                runtime_root=args.runtime_root,
                data_dir=args.data_dir,
                account=args.account,
            )
            _emit({"ok": True, "action": "granted", "key": _entry_dict(entry)})
            return 0

        if args.command == "list":
            entries = list_managed_keys(args.authorized_keys)
            project = validate_project(args.project) if args.project else None
            permission = validate_permission(args.permission) if args.permission else None
            actor = validate_actor(args.actor) if args.actor else None
            filtered = [
                entry
                for entry in entries
                if (project is None or entry.project == project)
                and (permission is None or entry.permission == permission)
                and (actor is None or entry.actor == actor)
            ]
            _emit({"ok": True, "keys": [_entry_dict(entry) for entry in filtered]})
            return 0

        if args.command == "revoke":
            removed = revoke_keys(
                args.authorized_keys,
                actor=args.actor,
                project=args.project,
                account=args.account,
            )
            _emit(
                {
                    "ok": True,
                    "action": "revoked",
                    "removed": len(removed),
                    "keys": [_entry_dict(entry) for entry in removed],
                }
            )
            return 0
        raise AssertionError(f"unexpected key command: {args.command}")
    except AdminError as exc:
        print(f"research-memory-admin: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
