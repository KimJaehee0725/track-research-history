# 개인 Linux 메모리 서버 설치

이 구성에서 개인 Linux 데스크탑은 연구 메모리의 **유일한 실시간 원본**입니다. 노트북, 연구실 서버, 임시 컨테이너는 SSH RPC로 이 서버를 읽고 씁니다. GitHub는 백업 또는 이력 복제에만 사용하며, 실제 메모리·SSH 키·백업 자격 증명은 이 코드 저장소에 넣지 않습니다.

## 서버 데이터 구조

`MEMORY_DATA_DIR`의 기본값은 `/srv/research-memory`입니다. 서비스 계정만 이 디렉터리에 쓸 수 있어야 합니다.

```text
/srv/research-memory/
  projects/
    alienlm/
      vault/                 # 사람이 읽을 수 있는 프로젝트별 Markdown
      project.yaml
    time-cot/
      vault/
      project.yaml
  registry.sqlite3           # 메타데이터·검색 인덱스·revision
  audit/                     # 변경 및 삭제 감사 기록
  trash/                     # 복구 가능한 삭제 항목
  backups/                   # 서버 로컬 백업 스테이징 영역
```

프로젝트 ID는 URL/경로에 안전한 영문자·숫자·`-`·`_`·`.`만 사용합니다. 이 ID가 SSH 키 권한 경계이므로 생성 후 이름을 바꾸지 않는 편이 안전합니다.

## 1. 서비스 계정과 저장소 만들기

Ubuntu/Debian 계열의 예시는 다음과 같습니다. `memory-rpc`는 UI와 SSH forced command가 **함께** 쓰는 전용 서비스 계정입니다. Compose 이미지와 systemd가 같은 데이터에 접근하도록 UID/GID `10001`을 맞춥니다. 해당 ID가 이미 사용 중이면 임의로 계속 진행하지 말고, Compose의 `user:`와 이 문서의 소유자를 같은 새 UID/GID로 함께 바꾸세요. forced command가 작동해야 하므로 셸은 `/bin/sh`로 두고, SSH 키 설정에서 일반 셸 접근을 차단합니다.

```bash
sudo groupadd --gid 10001 memory-rpc
sudo useradd --uid 10001 --gid 10001 --create-home --shell /bin/sh memory-rpc
sudo passwd --lock memory-rpc
sudo install -d -o memory-rpc -g memory-rpc -m 0700 /srv/research-memory
sudo install -d -o memory-rpc -g memory-rpc -m 0700 /srv/research-memory/{projects,audit,trash,backups}
sudo install -d -o memory-rpc -g memory-rpc -m 0700 /home/memory-rpc/.ssh
sudo touch /home/memory-rpc/.ssh/authorized_keys
sudo chown memory-rpc:memory-rpc /home/memory-rpc/.ssh/authorized_keys
sudo chmod 0600 /home/memory-rpc/.ssh/authorized_keys
```

소스는 예를 들어 `/opt/research-memory`에 배치하고, 배포 의존성은 [deploy/requirements-server.txt](../deploy/requirements-server.txt)를 사용합니다. Docker Compose와 systemd 예시는 [deploy/README.md](../deploy/README.md)에 있습니다. 둘 중 하나만 선택해 UI를 띄우고, 두 방식이 같은 `/srv/research-memory`를 동시에 쓰게 하지 마세요.

```bash
git clone https://github.com/KimJaehee0725/track-research-history.git /opt/research-memory
python3 -m venv /opt/research-memory/.venv
/opt/research-memory/.venv/bin/pip install -r /opt/research-memory/deploy/requirements-server.txt
```

공개 레포를 그대로 clone해도 되지만, 실제 데이터 경로와 개인 키는 절대 그 작업 트리에 만들지 않습니다.

## 2. localhost 전용 관리 UI 시작

UI는 반드시 `127.0.0.1:8787`에만 바인딩합니다. Compose를 사용한다면 `deploy/docker-compose.yml`의 기본 publish 설정도 loopback 전용입니다. systemd를 사용한다면 `deploy/systemd/research-memory-ui.service`를 설치한 뒤 다음처럼 확인합니다.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now research-memory-ui.service
sudo systemctl status research-memory-ui.service
ss -ltn | grep 8787
```

마지막 명령의 리스너가 `127.0.0.1:8787` 또는 `[::1]:8787`인지 확인합니다. `0.0.0.0:8787`이나 공인 IP에 열려 있으면 중지하고 `MEMORY_BIND_HOST=127.0.0.1`으로 고칩니다.

## 3. 컨테이너/에이전트용 SSH 키 등록

각 장비·프로젝트·권한별로 별도 키를 만듭니다. 예를 들어 AlienLM을 쓸 수 있는 노트북 키는 다음처럼 만듭니다.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/research-memory-alienlm -C "laptop-alienlm-write"
chmod 600 ~/.ssh/research-memory-alienlm
```

배포된 서버에서는 `authorized_keys` 줄을 수동으로 조립하지 말고 키 관리 도구로 등록합니다. 다음 명령은 `alienlm`만 읽고 쓸 수 있는 공개키를 추가합니다.

```bash
sudo /opt/research-memory/.venv/bin/python \
  /opt/research-memory/server/admin.py key grant \
  --project alienlm \
  --permission write \
  --actor laptop-alienlm-rw \
  --public-key ~/.ssh/research-memory-alienlm.pub
```

도구는 해당 프로젝트·권한을 고정한 `restrict,command=...` SSH entry를 만들고, 나중에 `actor`로 조회·폐기할 수 있는 marker를 함께 기록합니다. 기존의 다른 `authorized_keys` 항목은 보존합니다. 생성되는 형식은 [deploy/ssh/authorized_keys.example](../deploy/ssh/authorized_keys.example)에서 확인할 수 있습니다.

`restrict`는 PTY, 포트 포워딩, agent forwarding, X11 forwarding, 일반 셸을 차단합니다. 읽기 전용 키는 `--permission read`를 사용합니다. `--actor`는 감사 로그와 키 폐기에 쓰이는 서버 소유 식별자이므로 장비·프로젝트·권한을 알아볼 수 있게 고정합니다. 일반적인 컨테이너에는 단일 프로젝트 키를 권장합니다.

이 키는 UI 터널용 관리자 키와 분리해야 합니다. UI를 여는 계정에는 이 forced command를 쓰지 말고, 별도의 사람용 SSH 계정·키와 일반 SSH 접근 정책을 사용합니다.

## 4. SSH 설정과 동작 확인

서버에는 [deploy/ssh/sshd_config.d/research-memory.conf](../deploy/ssh/sshd_config.d/research-memory.conf)를 설치하고, 반영 전 설정을 검사합니다.

```bash
sudo sshd -t
sudo systemctl reload ssh
```

클라이언트에서는 연결·프로젝트·키 경로를 로컬 프로필에 한 번만 저장합니다.

```bash
client/memctl.py profile add alienlm-rw \
  --project alienlm \
  --host memory-server-alias \
  --user memory-rpc \
  --identity "$HOME/.ssh/research-memory-alienlm" \
  --known-hosts "$HOME/.ssh/known_hosts" \
  --set-default
client/memctl.py project list
client/memctl.py project init alienlm --title "AlienLM" --enable-git
```

첫 명령이 JSON 응답을 반환하면 SSH forced command, 키 권한, 서버 저장소가 모두 연결된 것입니다. `memory-rpc`라는 원격 명령은 식별용이며, 서버는 `SSH_ORIGINAL_COMMAND`를 신뢰하지 않습니다.

`--enable-git`은 해당 프로젝트 Vault와 `project.yaml`에 대해 서버 로컬 Git 스냅샷을 만듭니다. 원격 Git push나 자격 증명을 설정하지는 않으므로, 실제 재해 복구는 별도 private remote/NAS 백업 정책으로 계속 운영해야 합니다.

## 5. 운영 원칙

- 서버를 재설치하거나 저장소를 삭제하기 전에 [보안 및 백업 안내](security-and-backup.md)의 복구 테스트를 완료합니다.
- 프로젝트/노트 삭제는 UI 또는 `memctl`을 사용합니다. 서버 파일을 직접 지우면 휴지통·revision·감사 기록을 우회합니다.
- 서버 내 실제 메모리를 GitHub 공개 원격에 push하지 않습니다. 백업 remote는 별도의 private 저장소여야 합니다.
- OS 보안 업데이트와 디스크 SMART/여유 공간 확인은 서버 운영자의 정기 작업으로 둡니다.
- Compose UI가 정상 동작하는 서버는 그대로 유지합니다. systemd UI로 바꾸려면 먼저 Compose를 중지하고, 백업·loopback bind·SSH RPC smoke를 확인하는 별도 점검 시간에만 전환합니다. 두 UI 방식을 동시에 실행하지 않습니다.
