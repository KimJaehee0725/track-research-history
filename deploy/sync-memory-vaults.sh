#!/usr/bin/env bash
set -euo pipefail

# Publish the canonical Markdown vaults to one private Git backup branch.
# This script deliberately excludes each project's local .git directory: the
# backup branch is an aggregate snapshot history, not a collection of nested
# repositories.

die() {
  printf 'sync-memory-vaults: %s\n' "$*" >&2
  exit 2
}

DATA_DIR="${MEMORY_DATA_DIR:-/srv/research-memory}"
BACKUP_REMOTE="${MEMORY_BACKUP_REMOTE:-}"
BACKUP_BRANCH="${MEMORY_BACKUP_BRANCH:-memory-vaults}"

[[ -d "${DATA_DIR}/projects" ]] || die "missing projects directory: ${DATA_DIR}/projects"
[[ "${BACKUP_REMOTE}" == https://github.com/* ]] || die "MEMORY_BACKUP_REMOTE must be a GitHub HTTPS URL"
[[ "${BACKUP_BRANCH}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "invalid MEMORY_BACKUP_BRANCH"

backup_dir="$(mktemp -d "${TMPDIR:-/tmp}/research-memory-vaults.XXXXXX")"
cleanup() {
  rm -rf -- "${backup_dir}"
}
trap cleanup EXIT

git -C "${backup_dir}" init --quiet
git -C "${backup_dir}" config user.name "Research Memory Backup"
git -C "${backup_dir}" config user.email "research-memory-backup@local"
git -C "${backup_dir}" remote add origin "${BACKUP_REMOTE}"

if git -C "${backup_dir}" ls-remote --exit-code origin "refs/heads/${BACKUP_BRANCH}" >/dev/null 2>&1; then
  git -C "${backup_dir}" fetch --quiet origin "refs/heads/${BACKUP_BRANCH}"
  git -C "${backup_dir}" checkout --quiet -B "${BACKUP_BRANCH}" FETCH_HEAD
else
  git -C "${backup_dir}" checkout --quiet --orphan "${BACKUP_BRANCH}"
fi

# The branch is dedicated to vaults. Refuse to turn a source-code branch into
# a backup branch if it contains tracked files outside projects/.
if git -C "${backup_dir}" ls-files -- ':!projects/**' | grep -q .; then
  die "backup branch contains files outside projects/"
fi

mkdir -p "${backup_dir}/projects"
rsync -a --delete --exclude='.git/' "${DATA_DIR}/projects/" "${backup_dir}/projects/"
git -C "${backup_dir}" add -A -- projects

if git -C "${backup_dir}" diff --cached --quiet; then
  printf 'Research Memory backup is already current.\n'
  exit 0
fi

git -C "${backup_dir}" commit --quiet -m "Backup Research Memory vaults"
git -C "${backup_dir}" push origin "HEAD:refs/heads/${BACKUP_BRANCH}"
printf 'Research Memory backup updated: %s\n' "${BACKUP_BRANCH}"
