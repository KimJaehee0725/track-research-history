#!/usr/bin/env python3
"""Small SSH client for the research-memory RPC service.

The client deliberately has no third-party dependencies.  It sends one JSON
request on standard input to the fixed SSH forced command ``memory-rpc`` and
expects one JSON response on standard output.  SSH keys and host names stay in
the caller's config/environment; this program never stores credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # ``python client/memctl.py`` and ``python -m client.memctl`` both work.
    from profiles import (
        ProfileError,
        add_profile,
        config_path as profile_config_path,
        default_config_path as profile_default_config_path,
        get_profile,
        load_config,
        remove_profile,
        resolve_profile_config,
        set_default_profile,
        validate_profile_name,
    )
except ImportError:  # pragma: no cover - exercised by module-style consumers.
    from client.profiles import (  # type: ignore[no-redef]
        ProfileError,
        add_profile,
        config_path as profile_config_path,
        default_config_path as profile_default_config_path,
        get_profile,
        load_config,
        remove_profile,
        resolve_profile_config,
        set_default_profile,
        validate_profile_name,
    )


PROTOCOL_VERSION = 1
REMOTE_COMMAND = "memory-rpc"
# Keep individual Markdown writes comfortably below the server's 6 MiB JSON
# line ceiling. Large artifacts belong in the project attachment/experiment
# workflow rather than a single SSH RPC request.
MAX_NOTE_BYTES = 900 * 1024
PROJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,252}\Z")
USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")
SSH_OPTION_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*=")
TRASH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ClientError(RuntimeError):
    """An input, configuration, or transport error raised by the client."""


@dataclass(frozen=True)
class Connection:
    host: str
    user: str | None
    identity_file: str | None
    port: int | None
    ssh_config: str | None
    known_hosts: str | None
    ssh_options: tuple[str, ...]
    timeout: float


def json_dump(value: Any, *, stream: Any = sys.stdout, pretty: bool = False) -> None:
    kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    print(json.dumps(value, **kwargs), file=stream)


def default_config_path() -> Path:
    """Compatibility wrapper for callers that imported this helper from memctl."""

    return profile_default_config_path()


def read_config(path_value: str | None) -> dict[str, Any]:
    """Read a flat-compatible config without selecting a profile.

    Normal commands use :func:`resolve_profile_config` instead.  Keeping this
    wrapper makes external callers of the previous small client API continue
    to receive the raw connection document.
    """

    try:
        return load_config(path_value)
    except ProfileError as exc:
        raise ClientError(str(exc)) from exc


def config_value(
    cli_value: Any,
    env_name: str,
    config: dict[str, Any],
    config_name: str,
    default: Any = None,
) -> Any:
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_name)
    if env_value not in (None, ""):
        return env_value
    return config.get(config_name, default)


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClientError(f"{field} must be a non-empty string")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ClientError(f"{field} contains an unsafe control character")
    return value.strip()


def validate_host(value: Any) -> str:
    host = require_string(value, "host")
    if not HOST_RE.fullmatch(host) or host.startswith("-"):
        raise ClientError("host must be an SSH host alias, hostname, or IP address")
    return host


def validate_user(value: Any) -> str:
    user = require_string(value, "SSH user")
    if not USER_RE.fullmatch(user):
        raise ClientError("SSH user contains unsupported characters")
    return user


def validate_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ClientError("SSH port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ClientError("SSH port must be between 1 and 65535")
    return port


def validate_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ClientError("timeout must be a positive number of seconds") from exc
    if not 0 < timeout <= 3600:
        raise ClientError("timeout must be between 0 and 3600 seconds")
    return timeout


def validate_ssh_option(value: Any) -> str:
    option = require_string(value, "SSH option")
    if len(option) > 2048 or not SSH_OPTION_RE.match(option):
        raise ClientError("SSH options must use the form Name=value")
    return option


def read_ssh_options(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str, ...]:
    values: list[Any] = []
    configured = config.get("ssh_options", [])
    if configured is not None:
        if not isinstance(configured, list):
            raise ClientError("ssh_options in the config must be a JSON list")
        values.extend(configured)

    environment = os.environ.get("MEMORY_SSH_OPTIONS")
    if environment:
        try:
            parsed = json.loads(environment)
        except json.JSONDecodeError as exc:
            raise ClientError("MEMORY_SSH_OPTIONS must be a JSON list") from exc
        if not isinstance(parsed, list):
            raise ClientError("MEMORY_SSH_OPTIONS must be a JSON list")
        values.extend(parsed)

    if args.ssh_option:
        values.extend(args.ssh_option)

    options = [validate_ssh_option(value) for value in values]
    names = {option.split("=", 1)[0].lower() for option in options}
    if not args.interactive and "batchmode" not in names:
        options.append("BatchMode=yes")
    return tuple(options)


def optional_path(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    path = Path(require_string(value, field)).expanduser()
    return str(path)


def resolve_connection(
    args: argparse.Namespace, config: dict[str, Any] | None = None
) -> Connection:
    if config is None:
        try:
            config = resolve_profile_config(args.config, getattr(args, "profile", None))
        except ProfileError as exc:
            raise ClientError(str(exc)) from exc
    host_value = config_value(args.host, "MEMORY_HOST", config, "host")
    if host_value is None:
        raise ClientError("server host is required (--host, MEMORY_HOST, or config host)")

    user_value = config_value(args.user, "MEMORY_USER", config, "user")
    identity_value = config_value(
        args.identity, "MEMORY_IDENTITY_FILE", config, "identity_file"
    )
    port_value = config_value(args.port, "MEMORY_PORT", config, "port")
    ssh_config_value = config_value(
        args.ssh_config, "MEMORY_SSH_CONFIG", config, "ssh_config"
    )
    known_hosts_value = config_value(
        args.known_hosts, "MEMORY_KNOWN_HOSTS", config, "known_hosts"
    )
    timeout_value = config_value(args.timeout, "MEMORY_TIMEOUT", config, "timeout", 30)

    return Connection(
        host=validate_host(host_value),
        user=validate_user(user_value) if user_value not in (None, "") else None,
        identity_file=optional_path(identity_value, "identity file"),
        port=validate_port(port_value) if port_value not in (None, "") else None,
        ssh_config=optional_path(ssh_config_value, "SSH config"),
        known_hosts=optional_path(known_hosts_value, "known_hosts file"),
        ssh_options=read_ssh_options(args, config),
        timeout=validate_timeout(timeout_value),
    )


def validate_project(value: str) -> str:
    if not PROJECT_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "project must be 1-64 characters: letters, numbers, dot, underscore, or hyphen"
        )
    return value


def validate_note_path(value: str) -> str:
    if not value or len(value) > 240 or "\x00" in value or "\\" in value:
        raise argparse.ArgumentTypeError("path must be a short relative POSIX path")
    if value.startswith("/") or value.endswith("/"):
        raise argparse.ArgumentTypeError("path must be relative and cannot end with a slash")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise argparse.ArgumentTypeError("path cannot contain empty, '.' or '..' components")
    if not value.endswith(".md"):
        raise argparse.ArgumentTypeError("note paths must end in .md")
    return value


def note_path_argument(value: str) -> str:
    return validate_note_path(value)


def validate_trash_id(value: str) -> str:
    if not TRASH_ID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("trash ID contains unsupported characters")
    return value


def positive_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= limit <= 1000:
        raise argparse.ArgumentTypeError("limit must be between 1 and 1000")
    return limit


def revision_argument(value: str) -> str:
    if not value or len(value) > 256 or any(char in value for char in "\r\n\x00"):
        raise argparse.ArgumentTypeError("revision is malformed")
    return value


def text_argument(value: str, field: str, maximum: int) -> str:
    if not value or len(value) > maximum or "\x00" in value:
        raise argparse.ArgumentTypeError(f"{field} must be 1-{maximum} characters without NUL")
    return value


def title_argument(value: str) -> str:
    return text_argument(value, "title", 256)


def description_argument(value: str) -> str:
    return text_argument(value, "description", 2000)


def query_argument(value: str) -> str:
    return text_argument(value, "query", 4096)


def read_note_input(args: argparse.Namespace) -> str:
    if args.stdin:
        raw = sys.stdin.buffer.read(MAX_NOTE_BYTES + 1)
        source = "standard input"
    else:
        source_path = Path(args.file).expanduser()
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ClientError(f"cannot read note input {source_path}: {exc}") from exc
        source = str(source_path)
    if len(raw) > MAX_NOTE_BYTES:
        raise ClientError(f"note input from {source} exceeds {MAX_NOTE_BYTES} bytes")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClientError(f"note input from {source} must be UTF-8") from exc
    if "\x00" in content:
        raise ClientError("note input cannot contain NUL bytes")
    return content


def profile_name_argument(value: str) -> str:
    try:
        return validate_profile_name(value)
    except ProfileError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _validated_project(value: Any, *, source: str) -> str:
    try:
        return validate_project(str(value))
    except argparse.ArgumentTypeError as exc:
        raise ClientError(f"{source}: {exc}") from exc


def _validated_note_path(value: Any, *, source: str) -> str:
    try:
        return validate_note_path(str(value))
    except argparse.ArgumentTypeError as exc:
        raise ClientError(f"{source}: {exc}") from exc


def _validated_query(value: Any, *, source: str) -> str:
    try:
        return query_argument(str(value))
    except argparse.ArgumentTypeError as exc:
        raise ClientError(f"{source}: {exc}") from exc


def _validated_trash_id(value: Any, *, source: str) -> str:
    try:
        return validate_trash_id(str(value))
    except argparse.ArgumentTypeError as exc:
        raise ClientError(f"{source}: {exc}") from exc


def normalize_note_arguments(args: argparse.Namespace, profile_project: Any) -> None:
    """Resolve optional note project positionals without changing legacy calls.

    A selected profile may provide a default project.  In that case one target
    means a note path/query; two targets retain the historic explicit
    ``PROJECT PATH`` / ``PROJECT QUERY`` form.  Without a profile, only the
    original explicit forms are accepted.
    """

    if args.command != "note":
        return
    default_project = (
        _validated_project(profile_project, source="profile project")
        if profile_project not in (None, "")
        else None
    )
    if args.note_command == "list":
        if args.project is None:
            if default_project is None:
                raise ClientError(
                    "project is required unless a selected profile supplies a default project"
                )
            args.project = default_project
        return

    targets = args.targets
    if len(targets) == 1:
        if default_project is None:
            raise ClientError(
                "project is required unless a selected profile supplies a default project"
            )
        args.project = default_project
        payload = targets[0]
    elif len(targets) == 2:
        args.project = _validated_project(targets[0], source="project")
        payload = targets[1]
    else:
        raise ClientError(
            "use PROJECT plus the target, or a single target with a selected profile"
        )

    if args.note_command in {"read", "write", "delete"}:
        args.path = _validated_note_path(payload, source="note path")
    elif args.note_command == "restore":
        args.trash_id = _validated_trash_id(payload, source="trash ID")
    elif args.note_command == "search":
        args.query = _validated_query(payload, source="search query")
    else:  # pragma: no cover - argparse keeps this unreachable.
        raise ClientError("unknown note command")


def profile_values_from_args(args: argparse.Namespace) -> dict[str, Any]:
    """Build a persisted profile from validated, non-secret CLI options."""

    values: dict[str, Any] = {"project": args.project}
    if args.host is not None:
        values["host"] = validate_host(args.host)
    if args.user is not None:
        values["user"] = validate_user(args.user)
    if args.identity_file is not None:
        values["identity_file"] = optional_path(args.identity_file, "identity file")
    if args.port is not None:
        values["port"] = validate_port(args.port)
    if args.ssh_config is not None:
        values["ssh_config"] = optional_path(args.ssh_config, "SSH config")
    if args.known_hosts is not None:
        values["known_hosts"] = optional_path(args.known_hosts, "known_hosts file")
    if args.ssh_option:
        values["ssh_options"] = [validate_ssh_option(value) for value in args.ssh_option]
    if args.timeout is not None:
        values["timeout"] = validate_timeout(args.timeout)
    return values


def profile_response(args: argparse.Namespace) -> dict[str, Any]:
    """Handle local profile management without contacting the SSH server."""

    try:
        path, _ = profile_config_path(args.config)
        if args.profile_command == "list":
            document = load_config(args.config)
            default_name = document.get("default_profile")
            items = [
                {
                    "name": name,
                    "project": profile.get("project"),
                    "is_default": name == default_name,
                }
                for name, profile in sorted(document.get("profiles", {}).items())
            ]
            return {
                "ok": True,
                "result": {
                    "config": str(path),
                    "default_profile": default_name,
                    "profiles": items,
                },
            }
        if args.profile_command == "show":
            document = load_config(args.config)
            profile = get_profile(document, args.name)
            return {
                "ok": True,
                "result": {
                    "config": str(path),
                    "name": args.name,
                    "is_default": document.get("default_profile") == args.name,
                    "profile": profile,
                    "resolved": resolve_profile_config(args.config, args.name),
                },
            }
        if args.profile_command == "add":
            stored_path, profile = add_profile(
                args.config,
                args.name,
                profile_values_from_args(args),
                set_default=args.set_default,
                replace=args.replace,
            )
            return {
                "ok": True,
                "result": {
                    "config": str(stored_path),
                    "name": args.name,
                    "profile": profile,
                    "default_profile": load_config(args.config).get("default_profile"),
                },
            }
        if args.profile_command == "use":
            stored_path = set_default_profile(args.config, args.name)
            return {
                "ok": True,
                "result": {"config": str(stored_path), "default_profile": args.name},
            }
        if args.profile_command == "remove":
            stored_path, was_default = remove_profile(args.config, args.name)
            return {
                "ok": True,
                "result": {
                    "config": str(stored_path),
                    "removed": args.name,
                    "cleared_default": was_default,
                },
            }
    except ProfileError as exc:
        raise ClientError(str(exc)) from exc
    raise ClientError("unknown profile command")


def request_for(args: argparse.Namespace) -> dict[str, Any]:
    request: dict[str, Any] = {"version": PROTOCOL_VERSION, "params": {}}
    params: dict[str, Any] = request["params"]

    if args.command == "project":
        if args.project_command == "list":
            request["op"] = "project.list"
        else:
            request.update({"op": "project.init", "project": args.project})
            if args.title is not None:
                params["title"] = args.title
            if args.description is not None:
                params["description"] = args.description
            if args.enable_git:
                params["enable_git"] = True
        return request

    request["project"] = args.project
    if args.note_command == "list":
        request["op"] = "note.list"
        if args.include_deleted:
            params["include_deleted"] = True
    elif args.note_command == "read":
        request["op"] = "note.read"
        params["path"] = args.path
        if args.include_deleted:
            params["include_deleted"] = True
    elif args.note_command == "write":
        request["op"] = "note.write"
        params["path"] = args.path
        params["content"] = read_note_input(args)
        if args.title is not None:
            params["title"] = args.title
        if args.if_revision is not None:
            params["if_revision"] = args.if_revision
    elif args.note_command == "delete":
        request["op"] = "note.delete"
        params["path"] = args.path
        if args.if_revision is not None:
            params["if_revision"] = args.if_revision
    elif args.note_command == "restore":
        request["op"] = "note.restore"
        params["trash_id"] = args.trash_id
        if args.if_revision is not None:
            params["if_revision"] = args.if_revision
    elif args.note_command == "search":
        request["op"] = "note.search"
        params["query"] = args.query
        params["limit"] = args.limit
        if args.include_deleted:
            params["include_deleted"] = True
    else:  # argparse keeps this unreachable; it makes future additions fail closed.
        raise ClientError("unknown command")
    return request


def ssh_command(connection: Connection) -> list[str]:
    command = ["ssh"]
    if connection.ssh_config:
        command.extend(["-F", connection.ssh_config])
    if connection.port:
        command.extend(["-p", str(connection.port)])
    if connection.identity_file:
        command.extend(["-i", connection.identity_file])
    if connection.known_hosts:
        command.extend(["-o", f"UserKnownHostsFile={connection.known_hosts}"])
    for option in connection.ssh_options:
        command.extend(["-o", option])
    target = f"{connection.user}@{connection.host}" if connection.user else connection.host
    command.extend([target, REMOTE_COMMAND])
    return command


def safe_dry_run_request(request: dict[str, Any]) -> dict[str, Any]:
    """Do not echo a note body into terminal history/logs during dry runs."""

    copied = json.loads(json.dumps(request))
    params = copied.get("params")
    if isinstance(params, dict) and "content" in params:
        content = params.pop("content")
        if isinstance(content, str):
            encoded = content.encode("utf-8")
            params["content_summary"] = {
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
    return copied


def call_remote(
    request: dict[str, Any], connection: Connection, *, dry_run: bool
) -> tuple[dict[str, Any], int]:
    command = ssh_command(connection)
    if dry_run:
        return (
            {
                "ok": True,
                "dry_run": True,
                "ssh_command": command,
                "request": safe_dry_run_request(request),
            },
            0,
        )

    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        completed = subprocess.run(
            command,
            input=payload,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=connection.timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClientError("the 'ssh' command is not available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClientError(f"SSH RPC timed out after {connection.timeout:g} seconds") from exc
    except OSError as exc:
        raise ClientError(f"cannot start SSH RPC: {exc}") from exc

    raw_response = completed.stdout.strip()
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise ClientError(f"SSH RPC failed with exit code {completed.returncode}{suffix}")
    if not raw_response:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise ClientError(f"SSH RPC returned no JSON response{suffix}")
    try:
        response = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ClientError("SSH RPC did not return one valid JSON response") from exc
    if not isinstance(response, dict):
        raise ClientError("SSH RPC response must be a JSON object")
    return response, 1 if response.get("ok") is False else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send one JSON request through SSH to the research-memory server. "
            "Connection flags must appear before the command."
        )
    )
    parser.add_argument("--config", metavar="FILE", help="non-secret JSON connection config")
    parser.add_argument(
        "--profile",
        metavar="NAME",
        type=profile_name_argument,
        help="connection/profile name (otherwise MEMORY_PROFILE or the configured default)",
    )
    parser.add_argument("--host", help="SSH host alias, hostname, or IP address")
    parser.add_argument("--user", help="SSH user (separate from the host alias)")
    parser.add_argument("--identity", metavar="FILE", help="SSH private-key file path")
    parser.add_argument("--port", help="SSH port")
    parser.add_argument("--ssh-config", metavar="FILE", help="OpenSSH config file passed with ssh -F")
    parser.add_argument("--known-hosts", metavar="FILE", help="known_hosts file for host verification")
    parser.add_argument(
        "--ssh-option",
        action="append",
        metavar="NAME=VALUE",
        help="additional safe OpenSSH option; may be repeated",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="allow interactive SSH authentication instead of BatchMode=yes",
    )
    parser.add_argument("--timeout", help="SSH RPC timeout in seconds (default: 30)")
    parser.add_argument("--result-only", action="store_true", help="print only response.result")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    parser.add_argument(
        "--dry-run", action="store_true", help="show the safe request and SSH argv without connecting"
    )
    parser.add_argument("--version", action="version", version="memctl protocol 1")

    commands = parser.add_subparsers(dest="command", required=True)

    profile = commands.add_parser("profile", help="manage local non-secret connection profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("list", help="list locally configured profiles")
    profile_show = profile_commands.add_parser("show", help="show one local profile and resolution")
    profile_show.add_argument("name", type=profile_name_argument)
    profile_use = profile_commands.add_parser("use", help="set the default local profile")
    profile_use.add_argument("name", type=profile_name_argument)
    profile_remove = profile_commands.add_parser("remove", help="remove one local profile")
    profile_remove.add_argument("name", type=profile_name_argument)
    profile_add = profile_commands.add_parser("add", help="add a local profile (never stores key data)")
    profile_add.add_argument("name", type=profile_name_argument)
    profile_add.add_argument("--project", required=True, type=validate_project)
    profile_add.add_argument("--host", help="SSH host alias, hostname, or IP address")
    profile_add.add_argument("--user", help="SSH user (separate from the host alias)")
    profile_add.add_argument("--identity", dest="identity_file", metavar="FILE", help="SSH key path")
    profile_add.add_argument("--port", help="SSH port")
    profile_add.add_argument("--ssh-config", metavar="FILE", help="OpenSSH config file path")
    profile_add.add_argument("--known-hosts", metavar="FILE", help="known_hosts file path")
    profile_add.add_argument(
        "--ssh-option", action="append", metavar="NAME=VALUE", help="safe OpenSSH option"
    )
    profile_add.add_argument("--timeout", help="SSH RPC timeout in seconds")
    profile_add.add_argument("--set-default", action="store_true", help="select this profile by default")
    profile_add.add_argument("--replace", action="store_true", help="replace an existing profile")

    project = commands.add_parser("project", help="create or list projects")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    project_commands.add_parser("list", help="list accessible projects")
    project_init = project_commands.add_parser("init", help="create a project")
    project_init.add_argument("project", type=validate_project)
    project_init.add_argument("--title", type=title_argument)
    project_init.add_argument("--description", type=description_argument)
    project_init.add_argument(
        "--enable-git",
        action="store_true",
        help="initialize a server-local Git snapshot history for this project",
    )

    note = commands.add_parser("note", help="read and manage Markdown notes")
    note_commands = note.add_subparsers(dest="note_command", required=True)

    note_list = note_commands.add_parser("list", help="list notes in a project")
    note_list.add_argument(
        "project",
        nargs="?",
        type=validate_project,
        help="project (optional when the selected profile supplies one)",
    )
    note_list.add_argument("--include-deleted", action="store_true", help="also list trashed notes")

    note_read = note_commands.add_parser("read", help="read one Markdown note")
    note_read.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="PROJECT PATH, or PATH with a selected profile",
    )
    note_read.add_argument("--include-deleted", action="store_true", help="also read a trashed note")

    note_write = note_commands.add_parser("write", help="write UTF-8 Markdown from a file or stdin")
    note_write.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="PROJECT PATH, or PATH with a selected profile",
    )
    input_group = note_write.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file", metavar="FILE", help="UTF-8 Markdown file")
    input_group.add_argument("--stdin", action="store_true", help="read UTF-8 Markdown from stdin")
    note_write.add_argument("--title", type=title_argument, help="optional display title")
    note_write.add_argument("--if-revision", type=revision_argument, help="expected current revision")

    note_delete = note_commands.add_parser("delete", help="move a note to server-side trash")
    note_delete.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="PROJECT PATH, or PATH with a selected profile",
    )
    note_delete.add_argument("--if-revision", type=revision_argument, help="expected current revision")

    note_restore = note_commands.add_parser("restore", help="restore one server-side trash item")
    note_restore.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="PROJECT TRASH_ID, or TRASH_ID with a selected profile",
    )
    note_restore.add_argument("--if-revision", type=revision_argument, help="expected trash revision")

    note_search = note_commands.add_parser("search", help="full-text search within one project")
    note_search.add_argument(
        "targets",
        nargs="+",
        metavar="TARGET",
        help="PROJECT QUERY, or QUERY with a selected profile",
    )
    note_search.add_argument("--limit", type=positive_limit, default=20)
    note_search.add_argument("--include-deleted", action="store_true", help="also search trashed notes")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "profile":
            response = profile_response(args)
            output: Any = response.get("result", response) if args.result_only else response
            json_dump(output, pretty=args.pretty)
            return 0
        try:
            config = resolve_profile_config(args.config, args.profile)
        except ProfileError as exc:
            raise ClientError(str(exc)) from exc
        normalize_note_arguments(args, config.get("project"))
        request = request_for(args)
        connection = resolve_connection(args, config)
        response, exit_code = call_remote(request, connection, dry_run=args.dry_run)
        output: Any = response.get("result", response) if args.result_only else response
        json_dump(output, pretty=args.pretty)
        return exit_code
    except ClientError as exc:
        json_dump(
            {"ok": False, "error": {"code": "client_error", "message": str(exc)}},
            stream=sys.stderr,
            pretty=args.pretty,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
