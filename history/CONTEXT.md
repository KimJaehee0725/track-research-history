# Project Context

Last updated: 2026-07-21

## Research Goal

- 개인 Linux 데스크탑을 SSH 기반 연구 메모리의 실시간 원본으로 두고, 새 컨테이너·노트북·연구실 서버에서 같은 프로젝트 기록을 안전하게 읽고 쓴다.

## Current Architecture Or Structure

- `/srv/research-memory/projects/<project>/vault`의 Markdown이 프로젝트별 원본이다.
- SQLite FTS5는 검색·revision·휴지통 메타데이터를, JSONL audit은 변경 행위를 보관한다.
- `client/memctl.py`는 개인 password 모드 또는 legacy SSH key를 통해 SSH forced command로 접근하고, `server/app.py`는 localhost 전용 관리 UI를 제공한다.
- private Git hub는 실시간 원본이 아니라 백업·이력 복제 경로로 유지한다.

## Current Decisions

- 프로젝트 ID와 Markdown 상대 경로는 서버에서 검증한다.
- 개인 password 모드는 `memory-rpc`의 password-only forced command로 모든 프로젝트에 접근하며, project 선택은 client 요청에서 한다. legacy key mode는 호환용으로 유지한다.
- Obsidian은 동일 Vault의 viewer/editor이며, 파일 삭제는 UI 또는 `memctl`만 사용한다.

## Active Ideas

- 직접 SFTP/SSHFS 편집의 재색인과 충돌 처리 UX를 실제 운영 서버에서 점검한다.
- private Git/NAS/offsite 백업 대상과 보존 기간을 서버 운영 환경에 맞춰 확정한다.

## Open Questions And Risks

- Linux 서버에서 서비스 계정, SSH forced-command public keys, loopback UI, private backup target을 설정한다.
- 각 프로젝트에 read/write 키를 발급하고 `memctl` 및 복구 smoke를 실행한다.

## Next Steps

-
