# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    MEMORY_DATA_DIR=/srv/research-memory \
    MEMORY_BIND_HOST=127.0.0.1 \
    MEMORY_BIND_PORT=8787

WORKDIR /app

RUN groupadd --gid 10001 research-memory \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin research-memory

COPY deploy/requirements-server.txt /tmp/requirements-server.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements-server.txt \
    && rm -f /tmp/requirements-server.txt

COPY src /app/src
COPY server /app/server

RUN mkdir -p /srv/research-memory \
    && chown research-memory:research-memory /srv/research-memory

USER research-memory:research-memory
VOLUME ["/srv/research-memory"]
EXPOSE 8787

# The image itself defaults to loopback.  docker-compose publishes only a
# loopback host port while binding inside the container to permit Docker NAT.
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8787"]
