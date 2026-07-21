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
only forced-command keys based on
`ssh/authorized_keys.example`. Validate SSH configuration before reload:

```bash
sudo sshd -t
sudo systemctl reload sshd
```

The forced command is `server/rpc.py`, which ignores arbitrary remote command
text and never starts a shell or subprocess. Scope is fixed by the key's
`--allow-project` and `--permission` arguments. The RPC account cannot make
port forwards; use a separate administrator SSH account for the UI tunnel.
