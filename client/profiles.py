#!/usr/bin/env python3
"""Non-secret, local profiles for the research-memory SSH client.

The file is intentionally small and dependency-free so both ``memctl`` and a
container wrapper can use it.  Profiles contain SSH *paths* and connection
metadata only; private-key material, passphrases, and tokens are never read or
written by this module.

Supported ``client.json`` shapes::

    {"host": "Local", "user": "memory-rpc"}

and the profile-aware extension::

    {
      "version": 1,
      "default_profile": "fab-gym-rw",
      "profiles": {
        "fab-gym-rw": {
          "project": "fab-gym",
          "host": "Local",
          "user": "memory-rpc",
          "identity_file": "~/.ssh/research-memory-fab-gym-rw"
        }
      }
    }

Flat connection values remain valid and are used as a base for a selected
profile.  This makes adding a profile to an existing client configuration a
non-destructive migration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


CONFIG_MAX_BYTES = 128 * 1024
PROFILE_VERSION = 1
PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PROJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

# These are deliberately the only fields persisted by profile commands.  In
# particular there is no field for a private key's contents, passphrase, or a
# bearer token.
CONNECTION_FIELDS = frozenset(
    {
        "host",
        "user",
        "identity_file",
        "port",
        "ssh_config",
        "known_hosts",
        "ssh_options",
        "timeout",
    }
)
PROFILE_FIELDS = CONNECTION_FIELDS | {"project"}
TOP_LEVEL_FIELDS = CONNECTION_FIELDS | {"version", "default_profile", "profiles"}


class ProfileError(RuntimeError):
    """A malformed or unsafe local profile configuration."""


def default_config_path() -> Path:
    """Return the conventional non-secret client configuration path."""

    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / "research-memory" / "client.json"
    return Path.home() / ".config" / "research-memory" / "client.json"


def config_path(config_path: str | None = None) -> tuple[Path, bool]:
    """Resolve a config path and whether its absence is an error.

    An explicit CLI path or ``MEMORY_CONFIG`` is intentional and must exist for
    reads.  The conventional path remains optional so old flag-only invocations
    keep working on a fresh machine.
    """

    explicit = config_path or os.environ.get("MEMORY_CONFIG")
    if explicit:
        return Path(explicit).expanduser(), True
    return default_config_path(), False


def _require_clean_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a non-empty string")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ProfileError(f"{field} contains an unsafe control character")
    return value.strip()


def validate_profile_name(value: Any) -> str:
    name = _require_clean_string(value, "profile name")
    if not PROFILE_RE.fullmatch(name):
        raise ProfileError(
            "profile name must be 1-64 characters: letters, numbers, dot, underscore, or hyphen"
        )
    return name


def _validate_project(value: Any) -> str:
    project = _require_clean_string(value, "profile project")
    if not PROJECT_RE.fullmatch(project):
        raise ProfileError(
            "profile project must be 1-64 characters: letters, numbers, dot, underscore, or hyphen"
        )
    return project


def _validate_connection_value(field: str, value: Any) -> None:
    """Check config shape without duplicating memctl's SSH policy checks."""

    if field in {"host", "user", "identity_file", "ssh_config", "known_hosts"}:
        _require_clean_string(value, field)
        return
    if field == "ssh_options":
        if not isinstance(value, list):
            raise ProfileError("ssh_options must be a JSON list")
        for option in value:
            _require_clean_string(option, "ssh_options entry")
        return
    if field in {"port", "timeout"}:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ProfileError(f"{field} must be a number or numeric string")
        if isinstance(value, str):
            _require_clean_string(value, field)
        return
    raise ProfileError(f"unsupported connection field: {field}")


def _validate_profile_mapping(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"profile '{name}' must be a JSON object")
    unknown = set(value) - PROFILE_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ProfileError(f"profile '{name}' has unsupported field(s): {names}")
    checked = dict(value)
    if "project" in checked:
        _validate_project(checked["project"])
    for field in CONNECTION_FIELDS & set(checked):
        _validate_connection_value(field, checked[field])
    return checked


def validate_config_document(value: Any) -> dict[str, Any]:
    """Return a shallow copy after checking the public config schema."""

    if not isinstance(value, dict):
        raise ProfileError("connection config must be a JSON object")
    unknown = set(value) - TOP_LEVEL_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ProfileError(f"connection config has unsupported field(s): {names}")

    checked = dict(value)
    version = checked.get("version")
    if version is not None and version != PROFILE_VERSION:
        raise ProfileError(f"unsupported profile config version: {version!r}")
    for field in CONNECTION_FIELDS & set(checked):
        _validate_connection_value(field, checked[field])

    raw_profiles = checked.get("profiles", {})
    if raw_profiles is None:
        raise ProfileError("profiles must be a JSON object")
    if not isinstance(raw_profiles, dict):
        raise ProfileError("profiles must be a JSON object")
    profiles: dict[str, Any] = {}
    for raw_name, raw_profile in raw_profiles.items():
        name = validate_profile_name(raw_name)
        profiles[name] = _validate_profile_mapping(raw_profile, name=name)
    if "profiles" in checked:
        checked["profiles"] = profiles

    default_name = checked.get("default_profile")
    if default_name is not None:
        default_name = validate_profile_name(default_name)
        if default_name not in profiles:
            raise ProfileError(f"default_profile does not name a configured profile: {default_name}")
        checked["default_profile"] = default_name
    return checked


def load_config(
    config_path_value: str | None = None, *, allow_missing: bool = False
) -> dict[str, Any]:
    """Load the optional profile/connection document.

    Explicit paths normally must exist.  ``allow_missing`` is used only by
    profile creation, where a user intentionally names a new local file.  A
    missing conventional path resolves to an empty document, which preserves
    the old command-line-only workflow.
    """

    path, explicit = config_path(config_path_value)
    if not path.exists():
        if explicit and not allow_missing:
            raise ProfileError(f"connection config does not exist: {path}")
        return {}
    if path.is_symlink() or not path.is_file():
        raise ProfileError(f"connection config is not a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"cannot read connection config: {path}: {exc}") from exc
    if len(text.encode("utf-8")) > CONFIG_MAX_BYTES:
        raise ProfileError("connection config is unexpectedly large")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileError(f"connection config is not valid JSON: {path}: {exc.msg}") from exc
    return validate_config_document(parsed)


def selected_profile_name(
    document: dict[str, Any], profile_name: str | None = None
) -> str | None:
    """Select CLI, environment, then document default profile in that order."""

    requested = profile_name or os.environ.get("MEMORY_PROFILE") or document.get("default_profile")
    if requested in (None, ""):
        return None
    name = validate_profile_name(requested)
    profiles = document.get("profiles", {})
    if name not in profiles:
        raise ProfileError(f"profile does not exist: {name}")
    return name


def resolve_profile_config(
    config_path_value: str | None = None, profile_name: str | None = None
) -> dict[str, Any]:
    """Return a flat, profile-resolved non-secret connection configuration.

    The return value includes ``project`` only when the selected profile has
    one.  CLI/environment precedence is intentionally handled by ``memctl``;
    this function only merges the persisted flat defaults and selected profile.
    """

    document = load_config(config_path_value)
    resolved = {field: document[field] for field in CONNECTION_FIELDS if field in document}
    name = selected_profile_name(document, profile_name)
    if name is None:
        return resolved
    profile = document["profiles"][name]
    for field in CONNECTION_FIELDS:
        if field in profile:
            resolved[field] = profile[field]
    if "project" in profile:
        resolved["project"] = profile["project"]
    return resolved


def get_profile(document: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a copy of a stored profile after validating its name."""

    checked_name = validate_profile_name(name)
    profiles = document.get("profiles", {})
    if checked_name not in profiles:
        raise ProfileError(f"profile does not exist: {checked_name}")
    return dict(profiles[checked_name])


def write_config(config_path_value: str | None, document: dict[str, Any]) -> Path:
    """Atomically write a validated config with owner-only file permissions."""

    checked = validate_config_document(document)
    path, _ = config_path(config_path_value)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ProfileError(f"connection config is not a regular file: {path}")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Newly created directories respect the mode above; do not unexpectedly
        # tighten an existing user's broader config parent here.
        payload = json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
    except OSError as exc:
        raise ProfileError(f"cannot write connection config {path}: {exc}") from exc
    return path


def add_profile(
    config_path_value: str | None,
    name: str,
    profile: dict[str, Any],
    *,
    set_default: bool = False,
    replace: bool = False,
) -> tuple[Path, dict[str, Any]]:
    """Add a profile without silently replacing an existing one."""

    checked_name = validate_profile_name(name)
    checked_profile = _validate_profile_mapping(profile, name=checked_name)
    document = load_config(config_path_value, allow_missing=True)
    profiles = dict(document.get("profiles", {}))
    if checked_name in profiles and not replace:
        raise ProfileError(f"profile already exists: {checked_name} (use --replace to update it)")
    profiles[checked_name] = checked_profile
    document["version"] = PROFILE_VERSION
    document["profiles"] = profiles
    if set_default or "default_profile" not in document:
        document["default_profile"] = checked_name
    path = write_config(config_path_value, document)
    return path, dict(checked_profile)


def set_default_profile(config_path_value: str | None, name: str) -> Path:
    document = load_config(config_path_value)
    checked_name = validate_profile_name(name)
    if checked_name not in document.get("profiles", {}):
        raise ProfileError(f"profile does not exist: {checked_name}")
    document["version"] = PROFILE_VERSION
    document["default_profile"] = checked_name
    return write_config(config_path_value, document)


def remove_profile(config_path_value: str | None, name: str) -> tuple[Path, bool]:
    document = load_config(config_path_value)
    checked_name = validate_profile_name(name)
    profiles = dict(document.get("profiles", {}))
    if checked_name not in profiles:
        raise ProfileError(f"profile does not exist: {checked_name}")
    del profiles[checked_name]
    document["version"] = PROFILE_VERSION
    document["profiles"] = profiles
    was_default = document.get("default_profile") == checked_name
    if was_default:
        document.pop("default_profile", None)
    path = write_config(config_path_value, document)
    return path, was_default


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _add_common_config_arguments(parser: argparse.ArgumentParser) -> None:
    # ``default=SUPPRESS`` lets the options work both before and after a
    # subcommand without an absent subparser option overwriting a global one.
    parser.add_argument("--config", metavar="FILE", default=argparse.SUPPRESS)
    parser.add_argument("--profile", metavar="NAME", default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve non-secret research-memory profiles")
    _add_common_config_arguments(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve", help="print a resolved profile as JSON")
    _add_common_config_arguments(resolve)
    get = commands.add_parser("get", help="print one resolved scalar field")
    _add_common_config_arguments(get)
    get.add_argument("--field", required=True, choices=sorted(CONNECTION_FIELDS | {"project"}))
    get.add_argument(
        "--optional",
        action="store_true",
        help="succeed with no output when the selected profile has no such field",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        resolved = resolve_profile_config(
            getattr(args, "config", None), getattr(args, "profile", None)
        )
        if args.command == "resolve":
            _json_print(resolved)
            return 0
        value = resolved.get(args.field)
        if value is None:
            if args.optional:
                return 0
            raise ProfileError(f"resolved profile has no value for: {args.field}")
        if isinstance(value, (dict, list)):
            raise ProfileError(f"field is not a scalar: {args.field}")
        print(value)
        return 0
    except ProfileError as exc:
        print(f"profiles: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
