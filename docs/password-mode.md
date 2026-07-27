# 개인 비밀번호 전체 접근 모드

이 모드는 한 명만 쓰는 Research Memory 서버에서 모든 프로젝트를 하나의
`memory-rpc` 비밀번호로 조회·수정할 때 사용한다. SSH 키와 `known_hosts` 검증을
사용하지 않는다. 서버의 RPC 강제 명령, PTY 차단, 포트 포워딩 차단은 유지한다.

## 서버에서 한 번만 설정

`/opt/research-memory`가 최신 checkout인지 확인한 뒤 다음 도우미를 실행한다.
기존 SSH 설정은 `.before-personal-password` 백업으로 보존되고, 비밀번호는
대화형으로만 입력한다.

```bash
cd /opt/research-memory
bash deploy/enable-personal-password-mode.sh
```

이 구성은 `memory-rpc` 로그인에 항상 `server/rpc.py --allow-all-projects
--permission write`를 강제한다. 일반 셸, PTY, 포트 포워딩은 허용하지 않는다.

## 컨테이너 또는 일반 클라이언트

실제 값은 Git에 넣지 말고 무시되는 환경 파일에만 둔다. 형식은
[`examples/memory-password.env.example`](../examples/memory-password.env.example)을
참고한다. `MEMORY_PROJECT`가 비어 있으면 먼저 프로젝트 목록을 읽고 사용자에게
선택을 물어본다.

비밀번호 모드는 `sshpass`를 사용한다. Dolphin 이미지는 이를 포함하지만, 다른
클라이언트에서는 운영체제 패키지 관리자로 `sshpass`를 설치해야 한다.

```bash
set -a
source /safe/ignored/memory-password.env
set +a
client/memctl.py project list
client/memctl.py note list fab-gym
```

`MEMORY_PROJECT=fab-gym`을 설정하면 `client/memctl.py note list`처럼 프로젝트
인자를 생략할 수 있다. 비밀번호가 설정된 상태에서 client는 자동으로
`sshpass -e`를 사용하고 SSH host-key 확인을 끈다. 비밀번호 자체는 client 출력,
dry-run 출력, Git에 기록되지 않는다.
