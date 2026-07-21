# 보안, 키 교체, 백업 및 복구

연구 메모리 서버의 중요한 자산은 Markdown 파일만이 아닙니다. 프로젝트 권한, revision, 검색 인덱스, 감사 로그, 휴지통도 함께 보존해야 합니다. 이 문서는 운영자가 수행할 최소 보안·복구 절차를 정리합니다.

## 접근 키 원칙

- 키는 **장비 × 프로젝트 × 권한** 단위로 분리합니다. 예: `laptop-alienlm-read`, `lab-gpu-alienlm-write`.
- 컨테이너에는 `memory-run --identity`로 필요한 개인 키 하나만 read-only mount합니다.
- `authorized_keys`의 forced command에는 `--allow-project`와 `--permission read|write`를 명시합니다.
- UI 터널용 관리자 SSH 키와 RPC 키는 다른 계정 또는 다른 키여야 합니다.
- 개인 키, passphrase, API token, 실제 노트 본문은 Git, 이미지 레이어, `.env`, CI 로그에 넣지 않습니다.
- `known_hosts` 검증을 유지합니다. 서버 키가 바뀌었다면 기존 항목을 무작정 지우지 말고 서버 관리자에게 새 지문을 확인합니다.

## 키 교체 절차

키 유출 의심 여부와 관계없이 정기적으로 교체합니다. 새 키가 검증되기 전 기존 키를 삭제하면 작업 중인 컨테이너가 모두 끊길 수 있으므로 아래 순서를 지킵니다.

```bash
# 1. 새 장비별/프로젝트별 키 생성
ssh-keygen -t ed25519 -f ~/.ssh/research-memory-alienlm-2026q3 -C "laptop-alienlm-write-2026q3"
chmod 600 ~/.ssh/research-memory-alienlm-2026q3

# 2. 새 공개 키를 서버 authorized_keys에 기존 키와 함께 추가
#    forced command, --allow-project, --permission을 다시 확인

# 3. 새 키로 read와 write를 모두 테스트
client/memctl.py --host research-memory.example.edu --user memory-rpc \
  --identity ~/.ssh/research-memory-alienlm-2026q3 project list

# 4. 모든 필요한 장비가 새 키로 전환된 뒤 기존 공개 키 줄을 제거
```

유출이 의심되면 2–3단계를 건너뛰고 해당 공개 키를 즉시 제거한 뒤, 감사 기록에서 그 키가 사용된 프로젝트와 시간대를 확인합니다. 키 파일을 삭제하는 것만으로는 서버 접근이 철회되지 않습니다.

## 백업 정책

최소한 다음 세 겹을 권장합니다.

1. 서버 로컬의 짧은 보존 스냅샷: 실수 복구용.
2. 다른 물리 디스크/NAS: 디스크 고장 대비.
3. 별도 private Git remote 또는 암호화된 오프사이트 백업: 서버 분실·화재 대비.

백업 범위는 `/srv/research-memory/projects/`, `registry.sqlite3`, `audit/`, `trash/`, 그리고 필요한 설정의 **비밀이 아닌 부분**입니다. SQLite 파일을 단순 복사하기 전에 서비스가 쓰는 중인지 확인합니다. 운영 중 백업은 SQLite online backup API 또는 `sqlite3 .backup`으로 일관된 DB 사본을 만든 다음 Vault와 감사 로그를 스냅샷합니다.

예시 흐름입니다. 실제 경로와 백업 대상은 서버 환경에 맞게 고정하고, 임시 백업 파일 권한은 `0700`으로 제한합니다.

```bash
BACKUP_ROOT=/srv/research-memory/backups/$(date +%F)
sudo install -d -o memory-rpc -g memory-rpc -m 0700 "$BACKUP_ROOT"
sudo -u memory-rpc sqlite3 /srv/research-memory/registry.sqlite3 \
  ".backup '$BACKUP_ROOT/registry.sqlite3'"
sudo -u memory-rpc rsync -a --delete \
  /srv/research-memory/projects/ "$BACKUP_ROOT/projects/"
sudo -u memory-rpc rsync -a /srv/research-memory/audit/ "$BACKUP_ROOT/audit/"
sudo -u memory-rpc rsync -a /srv/research-memory/trash/ "$BACKUP_ROOT/trash/"
```

`rsync --delete`는 **백업 날짜 디렉터리 안에서만** 실행하고, 대상 경로가 올바른지 확인한 후 사용합니다. 이 명령을 `/srv/research-memory`나 홈 디렉터리에 직접 적용하지 않습니다.

private Git 백업은 코드 레포와 분리합니다. backup remote URL에 토큰을 넣지 말고 SSH deploy key, credential helper, 또는 암호화된 백업 도구를 사용합니다. 연구실 규정상 외부 반출이 제한된 데이터는 GitHub 대신 승인된 NAS/기관 저장소를 사용합니다.

## 복구 테스트

백업은 복원 검증 전까지 신뢰하지 않습니다. 적어도 분기마다 별도 경로 또는 격리 VM에서 다음을 수행합니다.

1. 운영 서버가 아닌 빈 디렉터리에 최근 백업을 복사합니다.
2. Vault 수, 일부 Markdown 해시, SQLite 무결성을 확인합니다.
3. 테스트용 `MEMORY_DATA_DIR`로 UI/RPC를 기동하고 프로젝트 목록·검색·휴지통 복구를 확인합니다.
4. 테스트 데이터와 임시 키를 정리하고, 성공/실패 시점과 결과를 감사 기록 또는 운영 로그에 남깁니다.

실제 운영 복구가 필요할 때는 먼저 현재 `/srv/research-memory`를 별도 스냅샷으로 보존한 뒤 서비스를 멈추고 복원합니다. 기존 디렉터리를 즉시 삭제하거나 덮어쓰지 마세요. 원인 분석과 롤백 여지를 남기는 것이 우선입니다.
