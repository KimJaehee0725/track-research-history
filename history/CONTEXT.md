# Project Context

Last updated: 2026-10-27

## 목표와 저장소

연구 변경·결정·실험·인계를 각 프로젝트의 Git 추적 `history/` Markdown에 보관한다. 이 체크아웃은 스킬 원본이며 현재 버전은 0.6.0이다.

## 현재 구현

- `scripts/history.py`: 읽기 전용 start/recall/search, 기록·커밋 연결, lint/finish, 보관과 협업 CLI.
- `scripts/history_git.py`: 선택 Git ref의 파일→커밋→기록 탐색. 명시 연결·동시 변경·경로 후보를 구분한다.
- `scripts/history_relations.py`: 검색어를 반복하지 않는 직접 정정/대체 기록도 별도 문맥으로 노출한다.
- 순위 검색은 vendored BM25S+NumPy만 사용한다. SQLite/중앙 서비스/별도 vault는 사용하지 않는다.
- 기록 쓰기는 작업트리별 잠금·원자적 저장·고유ID를 사용한다. 기본 recall은 쓰지 않으며 `recall --update`만 과거 갱신 동작이다.
- `scripts/install.py --target ...`은 동일 payload·revision·hash를 Codex/Claude에 설치하고 기존 경로를 백업한다.

## 검증과 제한

전체105테스트, 고정26질의 비교, 실제 FabGym 검색·Git 탐색, 독립 임시저장소 작업흐름과 mutation audit를 통과했다. 작은 질의 평가를 일반 의미검색 성능으로 확대하지 않는다. 한글 조사·동의어·의미적 한영 대응, Git rename/merge/revert/squash 해석에는 한계가 있으며 근거 범위와 진단을 확인한다. POSIX fcntl과 NumPy가 필요하다.

## 운영 원칙

사용자의 작업 언어로 기록하고 비밀·개인 원문·숨은 추론은 남기지 않는다. CONTEXT는 현재 요약으로 유지하며 정정은 명시 링크로 연결한다. archive 원문은 `history-archive/`에 보존하고 복원 가능해야 한다. push/PR·전역 설치는 해당 작업에서 승인된 범위로만 수행한다.

## 근거

- [[changes/2026-10-27-001521-git-bm25s-history-1d392c630fd9442b]]
- [[decisions/0004-history-summary-stub-commit-pairing]]
