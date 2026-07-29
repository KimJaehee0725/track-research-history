# Server deployment

The management UI is intentionally a **loopback-only** service. It has no
application account or login page. Access it with an SSH tunnel from an account
that is allowed to log into the host:

```bash
ssh -N -L 8787:127.0.0.1:8787 admin@memory-host
```

Then open `http://127.0.0.1:8787` locally. Do not add a public firewall rule,
reverse proxy, or `0.0.0.0` host publication for this UI.

## Persistent data

The only persistent store root is `/srv/research-memory`. Before a rootless
container deployment, create it once with ownership matching the container
account (`10001:10001`) and restrictive permissions:

```bash
sudo install -d -o 10001 -g 10001 -m 0750 /srv/research-memory
```

Docker Compose deliberately bind-mounts that exact path. It does not put
credentials, private keys, or passwords in the image, Compose file, or
environment. From the repository root, start the UI with:

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

Compose uses `0.0.0.0` only inside its isolated container so Docker can route
the published port. The host publication is still exactly
`127.0.0.1:8787:8787`; the non-containerized service defaults to
`127.0.0.1:8787` directly.

## Local smoke checks

After installing the runtime requirements in the server virtual environment,
verify that the UI imports the same core store used by the SSH endpoint:

```bash
cd /opt/research-memory
MEMORY_DATA_DIR=/srv/research-memory \
  PYTHONPATH=src:. .venv/bin/python -c 'from server.app import app; print(app.title)'
```

The forced-command wrapper can be tested without SSH by sending a single
protocol line. The project scope still has to be declared outside the JSON
request, exactly as it is in `authorized_keys`:

```bash
printf '%s\n' '{"version":1,"op":"project.list","params":{}}' | \
  MEMORY_DATA_DIR=/srv/research-memory \
  PYTHONPATH=src:. .venv/bin/python server/rpc.py \
  --allow-project alienlm --permission read
```

## systemd alternative

Compose와 systemd는 UI를 띄우는 **대안**입니다. 현재 Compose UI가 정상 동작한다면 그대로 유지합니다. systemd 단일 런타임으로 바꾸는 작업은 서비스 중단, 백업, loopback bind 검사, UI/RPC smoke를 포함한 별도 점검 시간에만 수행하고 두 방식을 동시에 실행하지 않습니다.

For a host virtual environment installation, copy
`systemd/research-memory-ui.service` to `/etc/systemd/system/`, verify that
`/opt/research-memory` contains this checkout and its virtual environment, then
run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now research-memory-ui
sudo systemctl status research-memory-ui
```

The supplied unit runs as the dedicated `memory-rpc` service user and only
grants write access to `/srv/research-memory`. The container image uses the
same numeric UID/GID (`10001`) under an internal name, so host ownership stays
consistent across the systemd and Compose options.

## SSH RPC keys

The JSON-lines RPC endpoint is for containers and non-UI clients. Create the
dedicated `memory-rpc` account, install the `sshd_config.d` fragment, and add
only forced-command keys. The server-side helper is safer than manually
assembling an `authorized_keys` line:

```bash
sudo /opt/research-memory/.venv/bin/python \
  /opt/research-memory/server/admin.py key grant \
  --project example-project \
  --permission write \
  --actor laptop-example-project-rw \
  --public-key /safe/path/to/key.pub
```

The helper preserves unrelated `authorized_keys` entries and manages only its
own marked RPC entries. `ssh/authorized_keys.example` remains the reference
format. Validate SSH configuration before reload:

```bash
sudo sshd -t
sudo systemctl reload sshd
```

The forced command is `server/rpc.py`, which ignores arbitrary remote command
text and never starts a shell or subprocess. Scope is fixed by the key's
`--allow-project` and `--permission` arguments. The RPC account cannot make
port forwards; use a separate administrator SSH account for the UI tunnel.

## Private vault backup

For a private offsite backup of all project Markdown in one `memory-vaults`
branch, use [the private vault backup guide](../docs/private-vault-backup.md).
The backup is intentionally separate from the source-code `main` branch and
does not upload SSH keys, passwords, SQLite state, audit logs, or trash.

Do not move this forced command into Docker by giving `memory-rpc` access to
the Docker socket or `docker` group: that access is effectively host-root
privilege. Keep the RPC account on the host with its limited forced command.
