#!/usr/bin/env bash
set -euo pipefail

# Install the map-aware store for the host RPC runtime, rebuild every existing
# map, then refresh the Compose UI from the same checkout.

die() {
  printf 'enable-obsidian-graph: %s\n' "$*" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_DIR="${RESEARCH_MEMORY_RUNTIME_DIR:-/opt/research-memory}"

[[ -f "${REPOSITORY_ROOT}/src/research_memory/store.py" ]] || die "missing source store.py"
[[ -f "${REPOSITORY_ROOT}/server/refresh_project_maps.py" ]] || die "missing map refresh script"
[[ -x "${RUNTIME_DIR}/.venv/bin/python" ]] || die "missing RPC runtime: ${RUNTIME_DIR}"

sudo install -m 0644 \
  "${REPOSITORY_ROOT}/src/research_memory/store.py" \
  "${RUNTIME_DIR}/src/research_memory/store.py"
sudo install -m 0755 \
  "${REPOSITORY_ROOT}/server/refresh_project_maps.py" \
  "${RUNTIME_DIR}/server/refresh_project_maps.py"
sudo -u memory-rpc "${RUNTIME_DIR}/.venv/bin/python" \
  "${RUNTIME_DIR}/server/refresh_project_maps.py" \
  --data-dir /srv/research-memory

docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d --build
printf 'Obsidian project maps are active for RPC and UI writes.\n'
