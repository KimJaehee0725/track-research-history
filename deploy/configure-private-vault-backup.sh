#!/usr/bin/env bash
set -euo pipefail

# Run this on the memory server from a real terminal. The GitHub token is read
# with terminal echo disabled and is never accepted as an argument or printed.

die() {
  printf 'configure-private-vault-backup: %s\n' "$*" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${RESEARCH_MEMORY_RUNTIME_DIR:-/opt/research-memory}"
DATA_DIR="${MEMORY_DATA_DIR:-/srv/research-memory}"
BACKUP_REMOTE="${MEMORY_BACKUP_REMOTE:-https://github.com/KimJaehee0725/track-research-history-private.git}"
BACKUP_BRANCH="${MEMORY_BACKUP_BRANCH:-memory-vaults}"
GITHUB_USER="${GITHUB_USER:-KimJaehee0725}"
SYNC_SOURCE="${SCRIPT_DIR}/sync-memory-vaults.sh"
SERVICE_SOURCE="${SCRIPT_DIR}/systemd/research-memory-vault-backup.service"
TIMER_SOURCE="${SCRIPT_DIR}/systemd/research-memory-vault-backup.timer"

[[ -x "${SYNC_SOURCE}" ]] || die "missing sync script: ${SYNC_SOURCE}"
[[ -f "${SERVICE_SOURCE}" && -f "${TIMER_SOURCE}" ]] || die "missing systemd unit template"
[[ -d "${DATA_DIR}/projects" ]] || die "missing projects directory: ${DATA_DIR}/projects"
[[ "${BACKUP_REMOTE}" == https://github.com/* ]] || die "BACKUP_REMOTE must be a GitHub HTTPS URL"
[[ "${BACKUP_BRANCH}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "invalid BACKUP_BRANCH"

read -r -s -p 'New GitHub token (hidden input): ' github_token
printf '\n'
[[ -n "${github_token}" ]] || die "GitHub token cannot be empty"

sudo install -d -o memory-rpc -g memory-rpc -m 0700 /home/memory-rpc
printf 'https://%s:%s@github.com\n' "${GITHUB_USER}" "${github_token}" | \
  sudo -u memory-rpc -H sh -c 'umask 077; cat > "$HOME/.git-credentials"; chmod 0600 "$HOME/.git-credentials"'
unset github_token

sudo -u memory-rpc -H git config --global credential.helper 'store --file ~/.git-credentials'
# GitHub authenticates an account at the host level.  The credential entry
# intentionally has no repository path, so Git must not require one when it
# looks up the stored token for the aggregate backup repository.
sudo -u memory-rpc -H git config --global credential.useHttpPath false

if ! sudo -u memory-rpc -H git ls-remote "${BACKUP_REMOTE}" >/dev/null; then
  die "could not authenticate to the private backup remote; check the token's repository Contents read/write permission"
fi

sudo install -d -o root -g root -m 0755 /etc/research-memory
printf 'MEMORY_DATA_DIR=%s\nMEMORY_BACKUP_REMOTE=%s\nMEMORY_BACKUP_BRANCH=%s\n' \
  "${DATA_DIR}" "${BACKUP_REMOTE}" "${BACKUP_BRANCH}" | \
  sudo tee /etc/research-memory/vault-backup.env >/dev/null
sudo chown root:root /etc/research-memory/vault-backup.env
sudo chmod 0644 /etc/research-memory/vault-backup.env

sudo install -d -o root -g root -m 0755 "${RUNTIME_DIR}/deploy"
sudo install -m 0755 "${SYNC_SOURCE}" "${RUNTIME_DIR}/deploy/sync-memory-vaults.sh"
sudo install -m 0644 "${SERVICE_SOURCE}" /etc/systemd/system/research-memory-vault-backup.service
sudo install -m 0644 "${TIMER_SOURCE}" /etc/systemd/system/research-memory-vault-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now research-memory-vault-backup.timer
sudo systemctl start research-memory-vault-backup.service

printf 'Private vault backup is configured. The timer runs every 15 minutes.\n'
