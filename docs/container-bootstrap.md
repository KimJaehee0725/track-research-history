# 새 컨테이너에서 프로젝트 메모리 사용하기

컨테이너는 생성될 때마다 최신 서버 메모리를 읽고 쓸 수 있어야 하지만, 이미지·Dockerfile·Git 저장소에는 SSH 개인 키를 넣으면 안 됩니다. `client/memory-run`은 사용자가 명시한 **프로젝트 범위 키 하나만** 컨테이너에 읽기 전용으로 마운트합니다.

## 준비: 장비별 프로필

각 노트북 또는 연구실 서버에서 프로젝트별 SSH 키를 만들고, 연결 정보와 프로젝트 ID를 로컬 프로필에 한 번만 등록합니다.

```bash
client/memctl.py profile add alienlm-rw \
  --project alienlm \
  --host memory-server-alias \
  --user memory-rpc \
  --identity "$HOME/.ssh/research-memory-alienlm" \
  --known-hosts "$HOME/.ssh/known_hosts" \
  --set-default
```

프로필 파일은 기본적으로 `~/.config/research-memory/client.json`에 생성됩니다. 설정에는 키 **경로**만 넣고 키 본문, passphrase, 토큰을 넣지 않습니다. 기존 단일 연결 JSON 또는 환경 변수를 쓰는 자동화는 계속 지원하며, [examples/memory-client.env.example](../examples/memory-client.env.example)를 참고할 수 있습니다.

정상 연결을 먼저 호스트에서 확인합니다.

```bash
client/memctl.py project list
client/memctl.py note list
```

기본 프로필이 아닌 프로젝트는 `client/memctl.py --profile other-project-rw ...`처럼 명시합니다. 일반 응답은 JSON이며, 자동화에서 결과 값만 필요하면 `--result-only`를 붙입니다.

## `memctl` 명령

모든 호출은 SSH를 통해 한 줄의 JSON 요청을 보내고 한 JSON 응답을 받습니다. 서버가 인식하는 논리 연산은 아래와 같습니다.

| 사용자 명령 | RPC 연산 | 용도 |
| --- | --- | --- |
| `project init PROJECT` | `project.init` | 프로젝트 생성 |
| `project list` | `project.list` | 접근 가능한 프로젝트 나열 |
| `note list PROJECT` | `note.list` | 프로젝트 노트 나열 |
| `note read PROJECT PATH` | `note.read` | Markdown 노트와 revision 읽기 |
| `note write PROJECT PATH` | `note.write` | 파일/표준입력 내용 생성 또는 갱신 |
| `note delete PROJECT PATH` | `note.delete` | 서버 휴지통으로 이동 |
| `note restore PROJECT TRASH_ID` | `note.restore` | 휴지통 항목 복구 |
| `note search PROJECT QUERY` | `note.search` | 프로젝트 내부 검색 |

기본 프로필이 선택되어 있으면 표의 `PROJECT`는 모두 생략할 수 있습니다. 예를 들어 `note restore TRASH_ID`와 `note search QUERY`도 현재 프로필 프로젝트 안에서 실행됩니다. 명시형 `PROJECT`을 함께 쓰면 기존 스크립트와 호환됩니다.

노트 내용은 명령행 인자가 아니라 파일 또는 표준입력으로만 보냅니다. 따라서 셸 히스토리에 연구 내용이 남지 않습니다.

```bash
# 새 노트 또는 기존 노트를 upsert합니다.
client/memctl.py note write notes/experiment-01.md --file ./experiment-01.md

# 표준입력도 가능합니다.
printf '# Meeting\n\n- next: run baseline\n' | \
  client/memctl.py note write notes/meeting-2026-07-21.md --stdin

# 충돌을 막으려면 read 결과의 revision을 다음 write에 전달합니다.
client/memctl.py note write notes/experiment-01.md --file ./experiment-01.md \
  --if-revision REVISION_FROM_READ

client/memctl.py note search "recovery attacker budget" --limit 10
```

`--dry-run`은 네트워크 연결 없이 요청 형식과 SSH argv를 보여 줍니다. 노트 본문은 출력하지 않고 바이트 수와 해시만 표시하므로 배포 스크립트 점검에 안전합니다.

## 일회성 컨테이너 실행

대상 이미지에는 Python 3와 OpenSSH client가 있어야 합니다. 아래는 작업 디렉터리를 컨테이너에 추가로 마운트하고 interactive shell을 여는 예시입니다.

```bash
client/memory-run \
  --profile alienlm-rw \
  --docker-arg -v --docker-arg "$PWD:/workspace" \
  --docker-arg -w --docker-arg /workspace \
  --tty -- \
  your-image:tag bash
```

컨테이너 안에서는 다음 환경 변수가 자동으로 존재합니다.

```text
RESEARCH_MEMORY_PROJECT=alienlm
RESEARCH_MEMORY_MEMCTL=/opt/research-memory-client/memctl.py
MEMORY_IDENTITY_FILE=/run/research-memory/id_ed25519
```

따라서 이미지 내부 작업은 경로를 하드코딩하지 않고 다음처럼 호출합니다.

```bash
python "$RESEARCH_MEMORY_MEMCTL" note list
python "$RESEARCH_MEMORY_MEMCTL" note search "ablation"
```

기본적으로 컨테이너는 종료 시 `--rm`으로 제거됩니다. 디버깅이 필요할 때만 `--keep`을 사용합니다. GPU, 작업 디렉터리, 이름 같은 Docker 옵션은 `--docker-arg`를 반복해 명시적으로 전달합니다. 쉘 문자열을 `eval`하지 않으므로 공백이 있는 경로도 인용하면 안전하게 전달됩니다.

## 키 범위와 실패 처리

- 컨테이너 하나에는 필요한 프로젝트 하나의 read 또는 write 키만 전달합니다.
- 연결 실패 시 키를 이미지에 복사하거나 `StrictHostKeyChecking=no`를 추가하지 않습니다. `known_hosts`, DNS/SSH host alias, 서버 공개키 변경 여부를 먼저 확인합니다.
- 서버가 `conflict`를 반환하면 다시 읽어 현재 revision을 확인한 뒤 병합합니다. 재시도로 덮어쓰지 않습니다.
- 삭제는 즉시 영구 삭제가 아니라 서버 휴지통으로 이동합니다. `note restore`의 `TRASH_ID`는 삭제 응답에서 받은 값을 사용합니다.
