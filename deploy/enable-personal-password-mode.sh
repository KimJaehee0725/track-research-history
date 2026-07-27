#!/usr/bin/env bash
set -euo pipefail

die() {
  printf 'enable-personal-password-mode: %s\n' "$*" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_CONFIG="${SCRIPT_DIR}/ssh/sshd_config.d/research-memory.conf"
TARGET_CONFIG="/etc/ssh/sshd_config.d/research-memory.conf"

[[ -f "${SOURCE_CONFIG}" ]] || die "missing SSH configuration template: ${SOURCE_CONFIG}"

if sudo test -f "${TARGET_CONFIG}"; then
  backup="${TARGET_CONFIG}.before-personal-password"
  sudo cp -a "${TARGET_CONFIG}" "${backup}"
  printf 'Previous SSH configuration backed up: %s\n' "${backup}"
fi

sudo install -m 0644 "${SOURCE_CONFIG}" "${TARGET_CONFIG}"
sudo sshd -t

printf 'Set the password for memory-rpc when prompted. It will not be printed or stored by this script.\n'
sudo passwd memory-rpc
sudo systemctl reload ssh

printf 'Personal password Research Memory mode is active.\n'
