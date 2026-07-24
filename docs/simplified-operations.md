# 간단한 일상 운영 흐름

이 문서는 기존 보안 경계를 유지하면서 연구 메모리를 매일 짧은 명령으로 쓰는 방법을 정리합니다. 프로필은 **로컬 편의 설정**일 뿐이고, 실제 프로젝트 범위와 읽기/쓰기 권한은 계속 서버의 SSH forced-command 키가 결정합니다.

## 지금 권장하는 구성

현재 서버에서 Compose UI가 정상 동작한다면 그것을 그대로 유지합니다. SSH RPC는 호스트의 `/opt/research-memory` 런타임으로 실행하고, 노트북·연구실 서버·새 컨테이너는 프로젝트별 키로 접근합니다.

UI를 Compose와 systemd로 동시에 실행하면 같은 데이터 경로를 두 서비스가 동시에 다루게 됩니다. 따라서 지금은 두 방식을 섞지 않습니다. 장기적으로는 정기 점검 시간에 systemd 단일 런타임으로 전환할 수 있지만, 이는 별도의 중단·백업·검증 절차가 필요한 운영 변경입니다.

## 1회: 장비에 프로필 만들기

각 장비에서 프로젝트별 키를 만든 뒤, 키의 **경로만** 프로필에 저장합니다. 기본 프로필을 지정하면 이후의 일상 명령에서는 서버 주소, 사용자, 키 경로, `known_hosts`, 프로젝트 ID를 다시 쓰지 않아도 됩니다.

```bash
client/memctl.py profile add fab-gym-rw \
  --project fab-gym \
  --host memory-server-alias \
  --user memory-rpc \
  --identity "$HOME/.ssh/research-memory-fab-gym-rw" \
  --known-hosts "$HOME/.ssh/known_hosts" \
  --set-default
```

프로필 파일은 기본적으로 `~/.config/research-memory/client.json`에 만들어집니다. 파일에는 개인키 본문·비밀번호·토큰을 넣지 않습니다. 직접 JSON을 관리해야 하는 자동화에는 [profile 예시](../examples/memory-profiles.json.example)를 참고합니다. 여러 프로젝트를 보려면 다음처럼 관리합니다.

```bash
client/memctl.py profile list
client/memctl.py profile show fab-gym-rw
client/memctl.py profile use fab-gym-rw
```

프로필 이름은 사람이 읽기 쉬운 별칭일 뿐입니다. 같은 이름을 바꾸거나 복사해도 서버 권한이 늘어나지 않습니다.

## 매일: 짧은 메모리 명령

기본 프로필이 선택되어 있다면 다음처럼 호출합니다.

```bash
client/memctl.py note list
client/memctl.py note read setup/connection.md
client/memctl.py note search "SSH RPC"
client/memctl.py note write notes/today.md --file ./today.md
```

다른 프로젝트를 잠시 쓸 때는 연결 정보 전체가 아니라 프로필만 지정합니다.

```bash
client/memctl.py --profile another-project-rw note search "baseline"
```

기존의 명시형 명령도 계속 지원합니다. 자동화 스크립트에서 더 분명한 호출이 필요하면 `note read PROJECT PATH` 또는 `note write PROJECT PATH ...` 형태를 그대로 사용해도 됩니다.

## 새 컨테이너에서 사용하기

프로필을 지정하면 컨테이너 실행 시 필요한 프로젝트, SSH 연결 정보, 키 경로를 채웁니다. 컨테이너에는 선택된 개인키 하나만 읽기 전용으로 마운트됩니다.

```bash
client/memory-run \
  --profile fab-gym-rw \
  --docker-arg -v --docker-arg "$PWD:/workspace" \
  --docker-arg -w --docker-arg /workspace \
  --tty -- your-image:tag bash
```

컨테이너 안에서는 프로젝트 ID를 다시 쓰지 않아도 됩니다.

```bash
python "$RESEARCH_MEMORY_MEMCTL" note list
python "$RESEARCH_MEMORY_MEMCTL" note search "ablation"
```

컨테이너 이미지나 Dockerfile에 SSH 키를 복사하지 마세요. 프로필 파일도 키 경로만 담고, 컨테이너에는 host의 프로필 파일과 선택 키가 읽기 전용으로 전달됩니다.

## 서버: 공개키 등록·조회·폐기

서버에서 `authorized_keys`를 직접 조립하거나 편집할 필요가 없습니다. 배포된 런타임에서 공개키 파일을 대상으로 아래 관리 명령을 사용합니다.

```bash
sudo /opt/research-memory/.venv/bin/python \
  /opt/research-memory/server/admin.py key grant \
  --project fab-gym \
  --permission write \
  --actor laptop-fab-gym-rw \
  --public-key /safe/path/to/research-memory-fab-gym-rw.pub
```

`actor`는 감사 로그와 키 폐기에 쓰이는 서버 측 식별자입니다. 장비·프로젝트·권한을 알아볼 수 있게 고정하고, 개인키 파일명이나 비밀값을 넣지 않습니다.

```bash
# 이 도구가 관리하는 RPC 키만 JSON으로 조회
sudo /opt/research-memory/.venv/bin/python \
  /opt/research-memory/server/admin.py key list

# actor 기준으로 해당 키 접근을 폐기
sudo /opt/research-memory/.venv/bin/python \
  /opt/research-memory/server/admin.py key revoke \
  --actor laptop-fab-gym-rw
```

이 도구는 다른 `authorized_keys` 항목은 보존하고, 자신이 만든 marker가 붙은 RPC 항목만 다룹니다. 새 키를 먼저 등록하고 읽기·쓰기 검증을 마친 뒤에 이전 `actor`를 폐기하는 것이 안전합니다. 접근 유출이 의심되면 해당 `actor`를 즉시 폐기합니다.

## 왜 SSH RPC를 Docker 안으로 옮기지 않는가

SSH forced command를 Docker 컨테이너로 넘기기 위해 `memory-rpc` 계정에 Docker socket 또는 `docker` 그룹 권한을 주면, 그 계정은 사실상 호스트 root 수준의 권한을 얻게 됩니다. 보안 경계와 운영 복잡성이 모두 나빠지므로 권장하지 않습니다.

현재처럼 전용 서비스 계정은 호스트에서 제한된 RPC만 실행하고, Compose는 loopback UI만 담당하게 두는 편이 안전합니다. 추후 systemd 단일화 시에도 이 서비스 계정과 프로젝트별 키 분리는 유지합니다.
