"""A deliberately small, loopback-only web UI for Research Memory.

This module owns presentation and request handling only.  All persisted state is
read or changed through :class:`research_memory.store.MemoryStore`; it never
opens vault files, SQLite databases, or trash directories itself.

The UI is intended to be reached over an SSH local-forward, for example::

    ssh -N -L 8787:127.0.0.1:8787 researcher@memory-host

It has no application-level login.  Keep the process bound to loopback and use
the host's SSH policy to control who can create the tunnel.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from html import escape
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from research_memory.store import MemoryStore
from research_memory.web_security import (
    mutation_source_is_same_origin,
    request_host_is_loopback,
)


DEFAULT_DATA_DIR = "/srv/research-memory"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8787


def _data_dir() -> Path:
    """Return the store root without creating or inspecting it directly."""

    return Path(os.environ.get("MEMORY_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()


def _new_store() -> MemoryStore:
    """Construct the only persistence dependency used by the server."""

    return MemoryStore(data_dir=_data_dir(), actor="admin-ui")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.memory_store = _new_store()
    yield


app = FastAPI(
    title="Research Memory",
    docs_url=None,
    redoc_url=None,
    lifespan=_lifespan,
)


def _store(request: Request) -> MemoryStore:
    """Use the lifespan store, with a lazy fallback for direct unit calls."""

    store = getattr(request.app.state, "memory_store", None)
    if store is None:
        store = _new_store()
        request.app.state.memory_store = store
    return store


def _value(record: Any, *names: str, default: Any = "") -> Any:
    """Read a field from either the store's dataclass records or mappings."""

    for name in names:
        if isinstance(record, Mapping) and name in record:
            return record[name]
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _view_record(record: Any) -> Any:
    """Use the store's stable serialization boundary for HTML rendering."""

    to_dict = getattr(record, "to_dict", None)
    return to_dict() if callable(to_dict) else record


def _project_id(project: Any) -> str:
    return str(_value(project, "project_id", "id", "slug", default=""))


def _note_id(note: Any) -> str:
    return str(_value(note, "note_id", "id", default=""))


def _project_title(project: Any) -> str:
    return str(_value(project, "title", "name", "project_id", "id", default=""))


def _note_title(note: Any) -> str:
    return str(_value(note, "title", "name", "note_id", "id", default="Untitled note"))


def _note_body(note: Any) -> str:
    return str(_value(note, "body", "content", "markdown", default=""))


def _record_time(record: Any, *names: str) -> str:
    value = _value(record, *names, default="")
    return "" if value is None else str(value)


def _route(value: str) -> str:
    return quote(str(value), safe="")


def _project_path(project_id: str) -> str:
    return f"/projects/{_route(project_id)}"


def _note_path(project_id: str, note_id: str) -> str:
    return f"{_project_path(project_id)}/notes/{_route(note_id)}"


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


async def _form(request: Request) -> dict[str, str]:
    """Parse a standard URL-encoded HTML form without a multipart dependency."""

    raw = (await request.body()).decode("utf-8", errors="replace")
    values: dict[str, str] = {}
    for segment in raw.split("&"):
        if not segment:
            continue
        key, separator, value = segment.partition("=")
        if not separator:
            continue
        # ``unquote_plus`` is intentionally imported locally to keep route
        # encoding and form encoding visibly distinct.
        from urllib.parse import unquote_plus

        values[unquote_plus(key)] = unquote_plus(value)
    return values


def _require_text(values: Mapping[str, str], name: str, label: str | None = None) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{label or name} is required.")
    return value


def _render_page(
    title: str,
    body: str,
    *,
    current_project: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    project_link = (
        f'<a href="{_project_path(current_project)}">{escape(current_project)}</a>'
        if current_project
        else ""
    )
    navigation = f"""
      <nav>
        <a href="/">Projects</a>
        <a href="/trash">Project trash</a>
        {project_link}
      </nav>
    """
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Research Memory</title>
  <style>
    :root {{ color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0 auto; max-width: 1040px; padding: 1.8rem; line-height: 1.45; }}
    header {{ border-bottom: 1px solid #8a8a8a; margin-bottom: 1.5rem; }}
    nav {{ display: flex; flex-wrap: wrap; gap: .9rem; margin: .65rem 0 1rem; }}
    a {{ color: #1167b1; }}
    .notice {{ background: #fff7d6; border-left: 4px solid #b98a00; color: #322800; padding: .75rem .9rem; margin: 1rem 0; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); }}
    .card {{ border: 1px solid #999; border-radius: .45rem; padding: 1rem; }}
    .muted {{ color: #666; font-size: .9rem; }}
    label {{ display: block; font-weight: 600; margin-top: .8rem; }}
    input, textarea {{ box-sizing: border-box; display: block; font: inherit; margin-top: .25rem; max-width: 100%; padding: .5rem; width: 100%; }}
    textarea {{ min-height: 15rem; resize: vertical; }}
    button, .button {{ background: #1167b1; border: 0; border-radius: .3rem; color: white; cursor: pointer; display: inline-block; font: inherit; margin-top: .8rem; padding: .5rem .8rem; text-decoration: none; }}
    .danger {{ background: #a32424; }}
    .secondary {{ background: #555; }}
    .inline {{ display: inline-block; margin-right: .5rem; }}
    .inline button {{ margin-top: 0; }}
    code {{ background: #eee; color: #222; padding: .1rem .25rem; }}
    @media (prefers-color-scheme: dark) {{
      .notice {{ background: #4a3b00; color: #fff4cf; }}
      code {{ background: #303030; color: #fff; }}
      a {{ color: #7fc5ff; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Research Memory</h1>
    {navigation}
  </header>
  <p class="notice"><strong>Loopback-only UI.</strong> This service is meant to bind to <code>127.0.0.1:8787</code> and be opened through an SSH tunnel. It has no application login; do not expose it on a public interface.</p>
  <main>{body}</main>
</body>
</html>"""
    return HTMLResponse(document, status_code=status_code)


@app.middleware("http")
async def _same_origin_mutation_guard(request: Request, call_next: Any) -> Any:
    """Block cross-site form posts to an SSH-forwarded loopback service."""

    if not request_host_is_loopback(request.headers.get("host")):
        return _render_page(
            "Invalid host",
            "<h2>Invalid host</h2>"
            "<p>Open this service through a localhost or loopback SSH forward.</p>",
            status_code=400,
        )
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not mutation_source_is_same_origin(
            str(request.base_url),
            origin=request.headers.get("origin"),
            referer=request.headers.get("referer"),
            fetch_site=request.headers.get("sec-fetch-site"),
        ):
            return _render_page(
                "Cross-site request blocked",
                "<h2>Cross-site request blocked</h2>"
                "<p>Reload this page from the loopback Research Memory UI and retry.</p>",
                status_code=403,
            )
    return await call_next(request)


def _storage_problem(exc: Exception) -> HTTPException:
    """Map the core store's normal domain errors to safe HTTP responses."""

    name = exc.__class__.__name__.lower()
    if isinstance(exc, KeyError) or "notfound" in name or "not_found" in name:
        return HTTPException(status_code=404, detail="The requested memory record was not found.")
    if "conflict" in name or "revision" in name or "alreadyexists" in name or "already_exists" in name:
        return HTTPException(
            status_code=409,
            detail="This note changed elsewhere. Reload it before saving your edit.",
        )
    if isinstance(exc, ValueError) or "validation" in name:
        return HTTPException(status_code=400, detail=str(exc) or "Invalid memory request.")
    return HTTPException(status_code=500, detail="The memory store could not complete this request.")


def _store_call(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return callable_(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # The store owns its detailed exception taxonomy.
        raise _storage_problem(exc) from exc


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> HTMLResponse:
    detail = escape(str(exc.detail))
    return _render_page(
        "Request problem",
        f"<h2>Request problem</h2><p>{detail}</p><p><a href=\"/\">Return to projects</a></p>",
        status_code=exc.status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def project_list(request: Request) -> HTMLResponse:
    projects = [_view_record(project) for project in _store_call(_store(request).list_projects)]
    cards: list[str] = []
    for project in projects:
        project_id = _project_id(project)
        title = _project_title(project)
        updated = _record_time(project, "updated_at", "created_at")
        cards.append(
            f"""<article class=\"card\">
  <h3><a href=\"{_project_path(project_id)}\">{escape(title)}</a></h3>
  <p class=\"muted\">ID: <code>{escape(project_id)}</code>{' · ' + escape(updated) if updated else ''}</p>
</article>"""
        )
    project_cards = "\n".join(cards) or "<p>No active projects yet.</p>"
    body = f"""
<div class=\"grid\">
  <section>
    <h2>Projects</h2>
    {project_cards}
  </section>
  <section class=\"card\">
    <h2>Create project</h2>
    <form method=\"post\" action=\"/projects\">
      <label for=\"project-id\">Project ID</label>
      <input id=\"project-id\" name=\"project_id\" required pattern=\"[A-Za-z0-9][A-Za-z0-9._-]*\" autocomplete=\"off\" placeholder=\"alienlm\">
      <p class=\"muted\">Use a stable, URL-safe ID. It cannot be changed later.</p>
      <label for=\"project-title\">Display title (optional)</label>
      <input id=\"project-title\" name=\"title\" placeholder=\"AlienLM research\">
      <button type=\"submit\">Create project</button>
    </form>
  </section>
</div>"""
    return _render_page("Projects", body)


@app.post("/projects")
async def create_project(request: Request) -> RedirectResponse:
    form = await _form(request)
    project_id = _require_text(form, "project_id", "Project ID")
    title = form.get("title", "").strip() or None
    _store_call(_store(request).create_project, project_id, title=title)
    return _redirect(_project_path(project_id))


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str) -> HTMLResponse:
    store = _store(request)
    project = _view_record(_store_call(store.get_project, project_id))
    notes = [_view_record(note) for note in _store_call(store.list_notes, project_id)]
    cards: list[str] = []
    for note in notes:
        note_id = _note_id(note)
        note_title = _note_title(note)
        updated = _record_time(note, "updated_at", "created_at")
        cards.append(
            f"""<article class=\"card\">
  <h3><a href=\"{_note_path(project_id, note_id)}\">{escape(note_title)}</a></h3>
  <p class=\"muted\">ID: <code>{escape(note_id)}</code>{' · ' + escape(updated) if updated else ''}</p>
  <form class=\"inline\" method=\"post\" action=\"{_note_path(project_id, note_id)}/delete\">
    <button class=\"danger\" type=\"submit\">Move to trash</button>
  </form>
</article>"""
        )
    note_cards = "\n".join(cards) or "<p>No active notes yet.</p>"
    title = _project_title(project)
    body = f"""
<h2>{escape(title)}</h2>
<p class=\"muted\">Project ID: <code>{escape(project_id)}</code></p>
<p><a href=\"{_project_path(project_id)}/trash\">View note trash</a> · <a href=\"{_project_path(project_id)}/delete\">Delete this project</a></p>
<div class=\"grid\">
  <section>
    <h2>Notes</h2>
    {note_cards}
  </section>
  <section class=\"card\">
    <h2>Create note</h2>
    <form method=\"post\" action=\"{_project_path(project_id)}/notes\">
      <label for=\"note-id\">Markdown path</label>
      <input id=\"note-id\" name=\"note_id\" required pattern=\"[A-Za-z0-9][A-Za-z0-9._/-]*\\.md\" autocomplete=\"off\" placeholder=\"notes/experiment-baseline.md\">
      <p class=\"muted\">Use a stable, project-relative Markdown path. It cannot be changed later.</p>
      <label for=\"note-title\">Title</label>
      <input id=\"note-title\" name=\"title\" required placeholder=\"Experiment baseline\">
      <label for=\"note-body\">Markdown</label>
      <textarea id=\"note-body\" name=\"body\" placeholder=\"# Notes&#10;&#10;Write project memory here.\"></textarea>
      <button type=\"submit\">Create note</button>
    </form>
  </section>
</div>"""
    return _render_page(title, body, current_project=project_id)


@app.post("/projects/{project_id}/notes")
async def create_note(request: Request, project_id: str) -> RedirectResponse:
    form = await _form(request)
    note_id = _require_text(form, "note_id", "Note ID")
    title = _require_text(form, "title", "Title")
    body = form.get("body", "")
    note = _view_record(
        _store_call(_store(request).create_note, project_id, note_id, title, body)
    )
    return _redirect(_note_path(project_id, _note_id(note)))


@app.get("/projects/{project_id}/notes/{note_id:path}", response_class=HTMLResponse)
async def note_detail(request: Request, project_id: str, note_id: str) -> HTMLResponse:
    note = _view_record(_store_call(_store(request).get_note, project_id, note_id))
    title = _note_title(note)
    body = _note_body(note)
    revision = _value(note, "revision", "version", default="")
    created = _record_time(note, "created_at")
    updated = _record_time(note, "updated_at")
    meta = " · ".join(part for part in (f"Created {created}" if created else "", f"Updated {updated}" if updated else "") if part)
    page_body = f"""
<p><a href=\"{_project_path(project_id)}\">← Back to project</a></p>
<h2>{escape(title)}</h2>
<p class=\"muted\">ID: <code>{escape(note_id)}</code>{' · ' + escape(meta) if meta else ''}</p>
<form method=\"post\" action=\"{_note_path(project_id, note_id)}/save\">
  <input type=\"hidden\" name=\"expected_revision\" value=\"{escape(str(revision), quote=True)}\">
  <label for=\"note-title\">Title</label>
  <input id=\"note-title\" name=\"title\" required value=\"{escape(title, quote=True)}\">
  <label for=\"note-body\">Markdown</label>
  <textarea id=\"note-body\" name=\"body\">{escape(body)}</textarea>
  <button type=\"submit\">Save changes</button>
</form>
<form method=\"post\" action=\"{_note_path(project_id, note_id)}/delete\">
  <button class=\"danger\" type=\"submit\">Move note to trash</button>
</form>"""
    return _render_page(title, page_body, current_project=project_id)


@app.post("/projects/{project_id}/notes/{note_id:path}/save")
async def update_note(request: Request, project_id: str, note_id: str) -> RedirectResponse:
    form = await _form(request)
    title = _require_text(form, "title", "Title")
    expected_revision = form.get("expected_revision", "").strip() or None
    _store_call(
        _store(request).update_note,
        project_id,
        note_id,
        title=title,
        body=form.get("body", ""),
        expected_revision=expected_revision,
    )
    return _redirect(_note_path(project_id, note_id))


@app.post("/projects/{project_id}/notes/{note_id:path}/delete")
async def delete_note(request: Request, project_id: str, note_id: str) -> RedirectResponse:
    _store_call(_store(request).delete_note, project_id, note_id)
    return _redirect(_project_path(project_id))


@app.get("/projects/{project_id}/trash", response_class=HTMLResponse)
async def note_trash(request: Request, project_id: str) -> HTMLResponse:
    store = _store(request)
    _store_call(store.get_project, project_id)
    notes = [
        _view_record(note)
        for note in _store_call(store.list_notes, project_id, include_deleted=True)
    ]
    deleted_notes = [note for note in notes if _value(note, "deleted_at", "is_deleted", default=None)]
    cards: list[str] = []
    for note in deleted_notes:
        note_id = _note_id(note)
        title = _note_title(note)
        deleted_at = _record_time(note, "deleted_at")
        cards.append(
            f"""<article class=\"card\">
  <h3>{escape(title)}</h3>
  <p class=\"muted\">ID: <code>{escape(note_id)}</code>{' · Deleted ' + escape(deleted_at) if deleted_at else ''}</p>
  <form method=\"post\" action=\"{_note_path(project_id, note_id)}/restore\">
    <button type=\"submit\">Restore note</button>
  </form>
</article>"""
        )
    cards_html = "\n".join(cards) or "<p>No deleted notes in this project.</p>"
    body = f"""
<p><a href=\"{_project_path(project_id)}\">← Back to project</a></p>
<h2>Note trash</h2>
{cards_html}"""
    return _render_page("Note trash", body, current_project=project_id)


@app.post("/projects/{project_id}/notes/{note_id:path}/restore")
async def restore_note(request: Request, project_id: str, note_id: str) -> RedirectResponse:
    _store_call(_store(request).restore_note, project_id, note_id)
    return _redirect(_note_path(project_id, note_id))


@app.get("/projects/{project_id}/delete", response_class=HTMLResponse)
async def project_delete_confirmation(request: Request, project_id: str) -> HTMLResponse:
    project = _view_record(_store_call(_store(request).get_project, project_id))
    title = _project_title(project)
    body = f"""
<p><a href=\"{_project_path(project_id)}\">← Cancel</a></p>
<h2>Delete project: {escape(title)}</h2>
<p>This moves the project and its notes to trash. Restore is available from Project trash until the server retention policy permanently removes it.</p>
<form method=\"post\" action=\"{_project_path(project_id)}/delete\">
  <label for=\"confirm-project\">Type the exact project ID <code>{escape(project_id)}</code> to continue</label>
  <input id=\"confirm-project\" name=\"confirmation\" required autocomplete=\"off\">
  <button class=\"danger\" type=\"submit\">Move project to trash</button>
</form>"""
    return _render_page("Confirm project deletion", body, current_project=project_id)


@app.post("/projects/{project_id}/delete")
async def delete_project(request: Request, project_id: str) -> RedirectResponse:
    form = await _form(request)
    if form.get("confirmation", "").strip() != project_id:
        raise HTTPException(status_code=400, detail="Project ID confirmation did not match.")
    _store_call(_store(request).delete_project, project_id)
    return _redirect("/trash")


@app.get("/trash", response_class=HTMLResponse)
async def project_trash(request: Request) -> HTMLResponse:
    projects = [
        _view_record(project)
        for project in _store_call(_store(request).list_projects, include_deleted=True)
    ]
    deleted_projects = [project for project in projects if _value(project, "deleted_at", "is_deleted", default=None)]
    cards: list[str] = []
    for project in deleted_projects:
        project_id = _project_id(project)
        title = _project_title(project)
        deleted_at = _record_time(project, "deleted_at")
        cards.append(
            f"""<article class=\"card\">
  <h3>{escape(title)}</h3>
  <p class=\"muted\">ID: <code>{escape(project_id)}</code>{' · Deleted ' + escape(deleted_at) if deleted_at else ''}</p>
  <form method=\"post\" action=\"/projects/{_route(project_id)}/restore\">
    <button type=\"submit\">Restore project</button>
  </form>
</article>"""
        )
    cards_html = "\n".join(cards) or "<p>No deleted projects.</p>"
    return _render_page("Project trash", f"<h2>Project trash</h2>{cards_html}")


@app.post("/projects/{project_id}/restore")
async def restore_project(request: Request, project_id: str) -> RedirectResponse:
    _store_call(_store(request).restore_project, project_id)
    return _redirect(_project_path(project_id))


def uvicorn_options() -> dict[str, str | int]:
    """Expose safe defaults for a simple ``python -m uvicorn`` launch."""

    return {
        "host": os.environ.get("MEMORY_BIND_HOST", DEFAULT_BIND_HOST),
        "port": int(os.environ.get("MEMORY_BIND_PORT", str(DEFAULT_BIND_PORT))),
    }


if __name__ == "__main__":  # pragma: no cover - convenience only
    import uvicorn

    uvicorn.run("server.app:app", **uvicorn_options())
