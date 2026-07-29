# Private Git vault backup

`memory-vaults` 브랜치는 서버의 모든 프로젝트 Markdown을 한 Git 트리에
백업한다. 이 브랜치에는 다음 경로만 들어간다.

```text
projects/<project-id>/project.yaml
projects/<project-id>/vault/**/*.md
```

프로젝트 내부의 로컬 `.git` 디렉터리, SQLite 검색 인덱스, 감사 로그, 휴지통,
SSH 키와 비밀번호는 올리지 않는다. 서버 `/srv/research-memory`가 실시간 원본이고,
이 브랜치는 복구 가능한 offsite 백업이다.

## 최초 설정

GitHub에서 `track-research-history-private`에만 `Contents: Read and write` 권한을
갖는 fine-grained token을 만든다. 토큰을 대화, 명령행 인수, 환경 파일에 쓰지 않는다.
서버의 실제 SSH 터미널에서 다음을 실행하고, 숨김 프롬프트에만 토큰을 입력한다.

```bash
cd /workspace/track-research-history
bash deploy/configure-private-vault-backup.sh
```

도우미는 토큰을 `memory-rpc` 계정만 읽을 수 있는 Git credential store에 저장하고,
원격 인증을 즉시 확인한 뒤 15분마다 실행되는
`research-memory-vault-backup.timer`를 활성화한다. 첫 실행은 즉시 수행한다.

## 상태 확인과 수동 동기화

```bash
sudo systemctl status research-memory-vault-backup.timer --no-pager
sudo systemctl start research-memory-vault-backup.service
sudo journalctl -u research-memory-vault-backup.service -n 30 --no-pager
```

토큰을 교체하려면 같은 설정 도우미를 다시 실행한다. 토큰이 노출되었다면 GitHub에서
먼저 폐기한 뒤 새 토큰으로 교체한다.
