# Obsidian 및 SFTP로 프로젝트 메모리 보기

서버의 프로젝트 Vault는 사람이 읽을 수 있는 Markdown입니다. Obsidian은 이 Markdown을 탐색하고 편집하는 도구일 뿐, 캐시·플러그인 DB·Obsidian Sync를 원본으로 사용하지 않습니다. 원본은 항상 `/srv/research-memory/projects/<project>/vault`와 서버의 revision/감사 기록입니다.

## 권장 사용 방식

| 목적 | 권장 경로 | 이유 |
| --- | --- | --- |
| 검색, 생성, 삭제, 복구 | 관리 UI 또는 `memctl` | revision, 프로젝트 권한, 휴지통, 감사 기록을 지킴 |
| 사람이 읽기, 링크/그래프 탐색 | read-only SSHFS 또는 SFTP | 서버 Markdown을 그대로 봄 |
| 직접 Markdown 편집 | 별도 프로젝트 전용 SFTP 키 + 재색인 절차 | 파일시스템 변경을 서버 인덱스와 동기화할 수 있음 |

특히 Finder/파일 탐색기에서 파일을 직접 삭제하면 서버 휴지통을 우회합니다. 삭제와 복구는 UI 또는 `memctl`로 수행합니다.

## SSHFS: 로컬 Vault로 열기

SSHFS용 계정/키는 `memory-rpc` forced-command 키와 분리합니다. 최소 권한 SFTP 계정이 해당 프로젝트 Vault만 보도록 서버에서 제한한 뒤, 로컬에서 마운트합니다.

macOS 예시입니다. macFUSE와 sshfs가 이미 설치되어 있다는 전제입니다.

```bash
mkdir -p "$HOME/ResearchMemory/alienlm"
sshfs \
  -o IdentityFile="$HOME/.ssh/memory-vault-alienlm" \
  -o UserKnownHostsFile="$HOME/.ssh/known_hosts" \
  -o StrictHostKeyChecking=yes \
  -o reconnect -o ServerAliveInterval=15 \
  memory-vault@research-memory.example.edu:/srv/research-memory/projects/alienlm/vault \
  "$HOME/ResearchMemory/alienlm"
```

Obsidian에서 **Open folder as vault**를 선택해 `~/ResearchMemory/alienlm`을 엽니다. 읽기 전용으로 운영할 때는 서버 SFTP 권한도 read-only로 만들고, Obsidian의 자동 생성 플러그인·워크스페이스 파일이 원격 Vault를 바꾸지 않도록 주의합니다.

마운트를 해제한 뒤에는 Obsidian을 종료합니다.

```bash
umount "$HOME/ResearchMemory/alienlm"  # Linux
# macOS에서는: diskutil unmount "$HOME/ResearchMemory/alienlm"
```

## SFTP 플러그인: 마운트 없이 조회하기

SSHFS가 어려우면 Obsidian의 SFTP 지원 플러그인 또는 일반 SFTP 클라이언트를 사용해 같은 Vault 경로를 연결할 수 있습니다.

- Host: 서버 SSH hostname 또는 alias
- User: 프로젝트 전용 SFTP 계정
- Remote path: `/srv/research-memory/projects/<project>/vault`
- Identity file: 프로젝트 전용 SFTP 키
- Host verification: 기존 `known_hosts`를 사용하고, 최초 키 지문은 서버 관리자에게 별도 채널로 확인

플러그인 설정 파일에 개인 키 내용이나 비밀번호를 저장하지 않습니다. 키 파일 경로만 지정하고, 플러그인이 지원하면 OS SSH agent 또는 system keychain을 사용합니다.

## 직접 편집을 허용할 때

Obsidian으로 직접 저장하는 변경은 RPC를 거치지 않을 수 있습니다. 이 모드는 다음 조건을 만족할 때만 활성화합니다.

1. 프로젝트 전용 SFTP 계정/키를 사용한다.
2. 서버의 vault watcher 또는 정해진 재색인 작업이 Markdown 변경을 검색 인덱스에 반영한다.
3. watcher가 만든 감사 기록과 Git/백업 상태를 확인한다.
4. 파일 삭제는 UI/`memctl`만 사용한다.

이 네 조건을 아직 운영하지 않는 동안에는 Obsidian을 read-only 조회 도구로 사용하고, 작성·수정은 UI 또는 `memctl`로 합니다. 이렇게 하면 여러 컨테이너와 사람이 동시에 작업할 때 revision 충돌을 명시적으로 처리할 수 있습니다.

## 기타 도구

VS Code Remote SSH, Joplin, 일반 Markdown 편집기에도 같은 원칙을 적용합니다. 도구의 자체 동기화 기능은 보조 복사본일 뿐이며, 서버 Vault와 백업을 대체하지 않습니다. 하나의 프로젝트만 볼 수 있는 키를 사용하고, 도구가 숨김 설정 폴더나 대량 파일 삭제를 만들지 않는지 처음에는 작은 테스트 Vault에서 확인합니다.
