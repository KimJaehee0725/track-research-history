"""Unified `research-memory` command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from research_memory import __version__

from .common import CliError, CommandRunner, SystemCommandRunner
from .data_repo import (
    initialize_data_repository,
    resolve_data_repository,
)
from .doctor import DoctorReport, run_doctor
from .github_repo import create_private_repository
from .records import record_note, search_records

MAX_RECORD_BYTES = 5 * 1024 * 1024


class _ArgumentParser(argparse.ArgumentParser):
    """Let the CLI render parse failures in the selected output format."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        raise CliError("argument_error", message)


def _add_leaf_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit one stable JSON document.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=argparse.SUPPRESS,
        help="Use an explicit non-secret client configuration file.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="research-memory",
        description="Create and safely use a private Markdown research-history repository.",
    )
    parser.set_defaults(json_output=False, config=None)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--config", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser(
        "init",
        help="Initialize a data-only Research Memory directory.",
    )
    initialize.add_argument("--path", type=Path, default=Path.cwd())
    _add_leaf_options(initialize)

    repo = subparsers.add_parser(
        "repo", help="Manage the private GitHub data repository."
    )
    repo_commands = repo.add_subparsers(dest="repo_command", required=True)
    create = repo_commands.add_parser(
        "create",
        help="Create a new private GitHub research-history repository.",
    )
    create.add_argument("--name", default="research-history")
    create.add_argument("--owner")
    create.add_argument("--path", type=Path)
    create.add_argument(
        "--private",
        action="store_true",
        required=True,
        help="Required safety acknowledgement; public creation is unsupported.",
    )
    create.add_argument(
        "--non-interactive",
        action="store_true",
        help="Compatibility flag; Git and GitHub prompts are always disabled.",
    )
    _add_leaf_options(create)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check privacy, Git, schema, tracked files, and local configuration.",
    )
    doctor.add_argument("--path", type=Path)
    _add_leaf_options(doctor)

    record = subparsers.add_parser(
        "record",
        help="Record Markdown only after verifying a private GitHub origin.",
    )
    record.add_argument("text", nargs="?")
    record.add_argument("--title")
    record.add_argument("--path", type=Path)
    record.add_argument("--no-push", action="store_true")
    record.add_argument(
        "--stdin",
        dest="read_stdin",
        action="store_true",
        help="Read the record body from standard input.",
    )
    record.add_argument(
        "--file",
        type=Path,
        help="Read the record body from a UTF-8 file.",
    )
    _add_leaf_options(record)

    search = subparsers.add_parser(
        "search",
        help="Search local Markdown records without changing the repository.",
    )
    search.add_argument("query")
    search.add_argument("--path", type=Path)
    search.add_argument("--limit", type=int, default=20)
    _add_leaf_options(search)
    return parser


def _emit_json(
    stream: TextIO,
    *,
    command: str,
    ok: bool,
    result: Any | None = None,
    error: dict[str, str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "command": command,
        "ok": ok,
    }
    if result is not None:
        payload["result"] = result
    if error is not None:
        payload["error"] = error
    stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _emit_human_success(stream: TextIO, command: str, result: Any) -> None:
    if command == "init":
        stream.write(f"Initialized data-only research history at {result['path']}\n")
    elif command == "repo.create":
        stream.write(
            f"Created private repository {result['repository']} at {result['path']}\n"
        )
    elif command == "record":
        action = "committed and pushed" if result["pushed"] else "committed locally"
        stream.write(f"Recorded {result['path']} ({action})\n")
    elif command == "search":
        stream.writelines(
            f"{item['path']}:{item['line']}: {item['excerpt']}\n" for item in result
        )
        if not result:
            stream.write("No matching records.\n")


def _emit_doctor(stream: TextIO, report: DoctorReport) -> None:
    stream.writelines(
        f"[{check.status.upper()}] {check.name}: {check.message}\n"
        for check in report.checks
    )
    stream.write(
        "Doctor result: " + ("healthy\n" if report.ok else "action required\n")
    )


def _command_label(argv: Sequence[str]) -> str:
    for index, value in enumerate(argv):
        if value == "repo":
            following = argv[index + 1] if index + 1 < len(argv) else "unknown"
            return f"repo.{following}"
        if value in {"init", "doctor", "record", "search"}:
            return value
    return "unknown"


def _record_text(args: argparse.Namespace, input_stream: TextIO) -> str:
    selected = sum(
        (
            args.text is not None,
            bool(args.read_stdin),
            args.file is not None,
        )
    )
    if selected != 1:
        raise CliError(
            "record_input_invalid",
            "Provide exactly one record body: positional TEXT, --stdin, or --file PATH.",
        )
    try:
        if args.read_stdin:
            value = input_stream.read(MAX_RECORD_BYTES + 1)
        elif args.file is not None:
            source = args.file.expanduser()
            flags = os.O_RDONLY
            try:
                if not stat.S_ISREG(source.lstat().st_mode):
                    raise CliError(
                        "record_file_unsafe",
                        f"Record input must be a regular file: {source}",
                    )
            except OSError as exc:
                raise CliError(
                    "record_file_unavailable",
                    f"Record input file is unavailable or unsafe: {source}",
                ) from exc
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            if hasattr(os, "O_NONBLOCK"):
                flags |= os.O_NONBLOCK
            try:
                descriptor = os.open(source, flags)
            except OSError as exc:
                raise CliError(
                    "record_file_unavailable",
                    f"Record input file is unavailable or unsafe: {source}",
                ) from exc
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise CliError(
                        "record_file_unsafe",
                        f"Record input must be a regular file: {source}",
                    )
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    raw = handle.read(MAX_RECORD_BYTES + 1)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if len(raw) > MAX_RECORD_BYTES:
                raise CliError(
                    "record_too_large",
                    f"Record input exceeds the {MAX_RECORD_BYTES}-byte limit.",
                )
            value = raw.decode("utf-8")
        else:
            assert args.text is not None
            value = args.text
        encoded_size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise CliError(
            "record_encoding_invalid", "Record input must be valid UTF-8."
        ) from exc
    if encoded_size > MAX_RECORD_BYTES:
        raise CliError(
            "record_too_large",
            f"Record input exceeds the {MAX_RECORD_BYTES}-byte limit.",
        )
    return value


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    parser = build_parser()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    input_stream = stdin or sys.stdin
    try:
        args = parser.parse_args(raw_argv)
    except CliError as exc:
        command = _command_label(raw_argv)
        if "--json" in raw_argv:
            _emit_json(output, command=command, ok=False, error=exc.to_dict())
        else:
            parser.print_usage(error_output)
            error_output.write(f"ERROR: {exc.message}\n")
        return 2

    active_runner = runner or SystemCommandRunner()
    command = args.command
    if command == "repo":
        command = f"repo.{args.repo_command}"

    try:
        if command == "init":
            root = initialize_data_repository(args.path)
            result: Any = {"path": str(root), "schema_version": 1}
        elif command == "repo.create":
            target = args.path or (Path.cwd() / args.name)
            result = create_private_repository(
                active_runner,
                name=args.name,
                target=target,
                owner=args.owner,
                config_path=args.config,
            )
        elif command == "doctor":
            report = run_doctor(
                active_runner,
                explicit_path=args.path,
                config_path=args.config,
            )
            if args.json_output:
                _emit_json(
                    output,
                    command=command,
                    ok=report.ok,
                    result=report.to_dict(),
                )
            else:
                _emit_doctor(output, report)
            return 0 if report.ok else 1
        elif command == "record":
            body = _record_text(args, input_stream)
            root, config = resolve_data_repository(args.path, args.config)
            result = record_note(
                active_runner,
                root=root,
                text=body,
                title=args.title,
                expected_repository=config.repository if config else None,
                push=not args.no_push,
            )
        elif command == "search":
            root, _ = resolve_data_repository(args.path, args.config)
            result = search_records(root, args.query, limit=args.limit)
        else:  # pragma: no cover - argparse owns this invariant.
            raise CliError("unsupported_command", f"Unsupported command: {command}")
    except CliError as exc:
        if args.json_output:
            _emit_json(
                output,
                command=command,
                ok=False,
                error=exc.to_dict(),
            )
        else:
            error_output.write(f"ERROR: {exc.message}\n")
            if exc.hint:
                error_output.write(f"Hint: {exc.hint}\n")
        return 1
    except (OSError, subprocess.SubprocessError) as exc:
        failure = CliError(
            "system_error",
            "A local command or filesystem operation failed.",
            hint=str(exc),
        )
        if args.json_output:
            _emit_json(output, command=command, ok=False, error=failure.to_dict())
        else:
            error_output.write(f"ERROR: {failure.message}\n")
            error_output.write(f"Hint: {failure.hint}\n")
        return 1

    if args.json_output:
        _emit_json(output, command=command, ok=True, result=result)
    else:
        _emit_human_success(output, command, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
