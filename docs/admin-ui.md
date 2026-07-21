# SSH 터널로 관리 UI 사용하기

관리 UI는 프로젝트와 메모리를 생성·수정·휴지통 이동·복구하는 사람용 화면입니다. 앱 자체 로그인 기능은 없으므로 **반드시 서버 loopback에만 바인딩**하고 SSH 터널을 통해서만 엽니다.

## 서버 쪽 확인

UI 서비스의 기본값은 다음과 같습니다.

```text
MEMORY_DATA_DIR=/srv/research-memory
MEMORY_BIND_HOST=127.0.0.1
MEMORY_BIND_PORT=8787
```

서버에서 다음을 확인합니다.

```bash
sudo systemctl status research-memory-ui.service
ss -ltn | grep 8787
```

`127.0.0.1:8787`만 보여야 합니다. 공개 IP, `0.0.0.0`, Docker의 외부 publish가 보이면 서비스와 포트 노출을 먼저 수정합니다.

## 로컬 컴퓨터에서 터널 열기

일반 SSH 접근이 가능한 **관리자 전용 계정**으로 접속합니다. 컨테이너에 주는 `memory-rpc` 키는 `restrict`되어 있으므로 UI 터널에 사용할 수 없습니다.

```bash
ssh -N -L 8787:127.0.0.1:8787 research-admin@research-memory.example.edu
```

이 터미널을 열어 둔 상태에서 로컬 브라우저로 [http://127.0.0.1:8787](http://127.0.0.1:8787)을 엽니다. 로컬 8787 포트가 이미 사용 중이면 앞의 숫자만 바꿉니다.

```bash
ssh -N -L 18787:127.0.0.1:8787 research-admin@research-memory.example.edu
# 브라우저: http://127.0.0.1:18787
```

배경 실행이 필요하면 SSH 설정의 `ControlMaster`를 쓰거나, 먼저 foreground에서 연결과 host key를 검증한 뒤 운영 절차에 맞게 관리합니다. 인증 실패를 해결하려고 `-o StrictHostKeyChecking=no`를 쓰지 않습니다.

## UI에서 하는 작업

- Projects 화면에서 안정적인 프로젝트 ID와 표시 이름을 만듭니다.
- 프로젝트 안에서 Markdown 노트를 생성하고 수정합니다.
- 노트 삭제는 **Move to trash**를 사용합니다. 복구 전에 대상과 시점을 확인합니다.
- 프로젝트 삭제는 별도 확인 화면에서 프로젝트 ID 재입력을 요구하도록 운영합니다. 예상치 못한 삭제는 먼저 휴지통에서 복구하고 감사 기록을 확인합니다.

브라우저 자동완성, 공유 PC의 브라우저 기록, 스크린샷에도 연구 내용이 남을 수 있습니다. 공용 컴퓨터에서는 private browsing을 사용하고 작업 후 터널을 종료합니다.

## 문제 해결

| 증상 | 확인 순서 |
| --- | --- |
| 브라우저가 연결되지 않음 | 터널 프로세스가 살아 있는지, 서버 UI가 `127.0.0.1:8787`에서 듣는지 확인 |
| SSH는 연결되지만 터널이 거부됨 | 관리자 계정의 `AllowTcpForwarding` 정책과 대상 포트를 확인 |
| UI가 외부에서 바로 열림 | 즉시 서비스를 중지하고 bind/publish를 `127.0.0.1`로 수정 |
| 저장 충돌 | 페이지를 다시 열어 최신 revision을 확인한 뒤 내용을 병합 |

관리 UI를 reverse proxy, 공인 도메인, 포트 포워딩으로 공개하려면 이 기본 설계를 벗어납니다. 그 경우 별도 인증·TLS·접근 제어·감사 요구사항을 설계한 뒤에만 진행합니다.
