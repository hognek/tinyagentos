"""Library app routes — ingest, list, and manage library items.

POST /api/library/ingest  — accept file uploads or URL references
GET  /api/library/items   — list library items
GET  /api/library/items/{item_id} — item detail with artifacts
DELETE /api/library/items/{item_id} — remove item and its files
POST /api/library/items/{item_id}/reprocess — re-run the pipeline
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

from tinyagentos.library_pipeline import run_pipeline
from tinyagentos.library_collections import handoff_to_collections
from tinyagentos.task_utils import _create_supervised_task

logger = logging.getLogger(__name__)

router = APIRouter()

LIBRARY_DIR_NAME = "library"

# Module-level background task tracking so unreferenced tasks are not
# garbage-collected when request.app.state._background_tasks is absent.
_background_tasks: set[asyncio.Task] = set()


def _track_background_task(coro) -> asyncio.Task:
    """Create a task, store it in ``_background_tasks``, and auto-discard on done."""
    task = asyncio.create_task(coro)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)

    task.add_done_callback(_on_done)
    _background_tasks.add(task)
    return task


# ---------------------------------------------------------------------------
# App page
# ---------------------------------------------------------------------------


@router.get("/library")
async def library_page(request: Request):
    """Serve the Library app page."""
    return _templates.TemplateResponse(request=request, name="library.html")


# ---------------------------------------------------------------------------

def _library_dir_from_app(app) -> Path:
    """Return the library storage directory, creating it if needed."""
    data_dir = getattr(app.state, "data_dir", None)
    if data_dir:
        d = Path(data_dir) / LIBRARY_DIR_NAME
    else:
        d = Path(__file__).parent.parent.parent / "data" / LIBRARY_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _library_dir(request: Request) -> Path:
    return _library_dir_from_app(request.app)


async def _get_library_store(request: Request):
    """Get the LibraryStore from app.state (lazily initialised)."""
    store = getattr(request.app.state, "library_store", None)
    if store is None:
        from tinyagentos.library_store import LibraryStore

        data_dir = getattr(request.app.state, "data_dir", None)
        base = Path(data_dir) if data_dir else Path(__file__).parent.parent.parent / "data"
        store = LibraryStore(base / "library.db")
        await store.init()
        request.app.state.library_store = store
    return store


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


@router.post("/api/library/ingest")
async def ingest(
    request: Request,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    title: str | None = Form(None),
):
    """Ingest a file or URL into the library.

    Accepts a file upload (multipart) or a URL string form field. At least one
    of ``file`` or ``url`` must be provided.

    Returns ``{item_id, status: \"pending\"}`` immediately — pipeline processing
    happens asynchronously in a background task.
    """
    store = await _get_library_store(request)
    storage_dir = _library_dir(request)

    if file and file.filename:
        # File upload
        kind = _detect_kind_from_filename(file.filename, file.content_type)
        file_dir = storage_dir / "files"
        file_dir.mkdir(parents=True, exist_ok=True)

        # Sanitise filename
        safe_name = _sanitise_filename(file.filename)
        dest = file_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"

        # Stream file in bounded chunks to avoid loading it entirely into
        # memory.  Reject uploads exceeding 100 MB with HTTP 413.
        MAX_SIZE = 100 * 1024 * 1024  # 100 MB
        if file.size and file.size > MAX_SIZE:
            return JSONResponse(
                {"error": "Payload Too Large"}, status_code=413,
            )

        size = 0
        with dest.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SIZE:
                    dest.unlink(missing_ok=True)
                    return JSONResponse(
                        {"error": "Payload Too Large"}, status_code=413,
                    )
                f.write(chunk)

        item_id = await store.create_item(
            kind=kind,
            title=title or file.filename,
            storage_path=str(dest),
            size_bytes=size,
            source_url="",
        )
    elif url:
        # URL reference
        kind = _detect_kind_from_url(url)
        item_id = await store.create_item(
            kind=kind,
            source_url=url,
            title=title or url,
        )
    else:
        return JSONResponse(
            {"error": "Provide either 'file' (multipart upload) or 'url' (form field)."},
            status_code=400,
        )

    # Run pipeline in background
    task_set = getattr(request.app.state, "_background_tasks", None)
    coro = _ingest_task(request.app, item_id, store, storage_dir)
    if task_set is None:
        _track_background_task(coro)
    else:
        _create_supervised_task(coro, task_set)

    if _is_htmx(request):
        item = await store.get_item(item_id) or {}
        return HTMLResponse(_render_item_card(item), status_code=202)

    return JSONResponse({"item_id": item_id, "status": "pending"}, status_code=202)


async def _ingest_task(app, item_id: str, store, storage_dir: Path) -> None:
    """Background task: run pipeline + collections handoff for an item.

    Never raises — always leaves the item in a terminal status.
    """
    try:
        await run_pipeline(store, item_id, storage_dir)
    except Exception:
        logger.exception("Library ingest pipeline crashed for item %s", item_id)
        await store.update_item_status(item_id, "error")
        return

    # Auto-download: check matching rules with auto_download=True
    try:
        item = await store.get_item(item_id)
        if item and item.get("source_url"):
            rules = await store.match_rules(item["source_url"])
            for rule in rules:
                if rule.get("auto_download"):
                    from tinyagentos.library_pipeline import run_heavy_pipeline

                    quality = rule.get("quality", "") or "720"
                    logger.info(
                        "Auto-download triggered for item %s by rule %s (quality=%s)",
                        item_id, rule["id"], quality,
                    )
                    await run_heavy_pipeline(
                        store, item_id, storage_dir, quality=quality,
                    )
                    break  # First matching auto-download rule wins
    except Exception:
        logger.exception("Auto-download check failed for item %s", item_id)

    # Collections handoff after successful pipeline
    try:
        collections_dir = storage_dir.parent / "collections"
        await handoff_to_collections(store, item_id, collections_dir)
    except Exception:
        logger.exception("Collections handoff failed for item %s", item_id)


def _sanitise_filename(name: str) -> str:
    """Strip path separators and null bytes from a filename."""
    name = name.replace("/", "_").replace("\\", "_").replace("\x00", "")
    # Also prevent double-dots for path traversal
    name = name.replace("..", "_")
    return name or "unnamed"


def _detect_kind_from_filename(filename: str, content_type: str | None = None) -> str:
    """Detect kind from filename and optional MIME type."""
    from tinyagentos.library_pipeline import detect_kind
    return detect_kind(file_path=filename, content_type=content_type or "")


def _detect_kind_from_url(url: str) -> str:
    """Detect kind from URL pattern."""
    from tinyagentos.library_pipeline import detect_kind
    return detect_kind(source_url=url)


# ---------------------------------------------------------------------------
# HTMX helpers -- return HTML fragments when the HX-Request header is present
# ---------------------------------------------------------------------------


def _is_htmx(request: Request) -> bool:
    """Return True when the request is from an HTMX component."""
    return request.headers.get("HX-Request", "").lower() == "true"


def _format_bytes(size: int) -> str:
    """Format a byte count as a human-readable string."""
    if size < 1024:
        return f"{size} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024.0
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


_STATUS_CSS: dict[str, str] = {
    "pending": "status-pending",
    "processing": "status-processing",
    "ready": "status-ready",
    "error": "status-error",
}


def _render_item_card(item: dict) -> str:
    """Return an HTML .item-card <div> for *item*."""
    import html

    status = item.get("status", "pending")
    css = _STATUS_CSS.get(status, "status-pending")
    title = html.escape(item.get("title", "Untitled"))
    kind = html.escape(item.get("kind", "file"))
    bytes_val = item.get("bytes") or 0
    size_str = _format_bytes(bytes_val) if bytes_val else ""
    item_id = html.escape(item.get("id", ""))
    source_url = html.escape(item.get("source_url", ""))
    downloaded = bool(item.get("download_path", ""))

    parts = [
        f'<div class="item-card" id="item-{item_id}">',
        f'<div class="info">',
        f'<h3>{title}</h3>',
        f'<div class="meta">',
        f'<span class="status-badge {css}">{html.escape(status)}</span>',
        f" {kind}",
    ]

    if size_str:
        parts.append(f' &middot; <span class="item-size">{size_str}</span>')

    parts.append("</div>")  # .meta

    # YouTube download actions (only for url:youtube items, only when ready)
    if kind == "url:youtube" and status == "ready" and not downloaded:
        parts.append(
            f'<div class="item-actions" style="margin-top:0.5rem">'
            f'<select class="quality-select" id="quality-{item_id}" '
            f'  style="font-size:0.8rem;padding:0.15rem 0.3rem">'
            f'<option value="360">360p</option>'
            f'<option value="480">480p</option>'
            f'<option value="720" selected>720p</option>'
            f'<option value="1080">1080p</option>'
            f'<option value="best">Best</option>'
            f'</select> '
            f'<button class="outline secondary" style="font-size:0.8rem;padding:0.15rem 0.5rem"'
            f'  hx-post="/api/library/items/{item_id}/download"'
            f'  hx-include="#quality-{item_id}"'
            f'  hx-target="#item-{item_id}"'
            f'  hx-swap="outerHTML"'
            f'  hx-indicator="#item-{item_id}">'
            f'⬇ Download'
            f'</button>'
            f'</div>'
        )
    elif kind == "url:youtube" and downloaded:
        download_bytes_val = item.get("download_bytes") or 0
        parts.append(
            f'<div class="item-actions" style="margin-top:0.5rem;font-size:0.8rem;color:var(--pico-muted-color)">'
            f'✅ Downloaded ({_format_bytes(download_bytes_val)})'
            f'</div>'
        )

    parts.append("</div>")  # .info
    parts.append("</div>")  # .item-card

    return "".join(parts)


def _render_item_list(items: list[dict]) -> str:
    """Return an HTML fragment wrapping .item-card elements or an empty state."""
    if not items:
        return (
            '<div class="empty-state">'
            "<p>No items yet. Drop a file or paste a URL above.</p>"
            "</div>"
        )
    return "".join(_render_item_card(item) for item in items)


def _render_rules_list(rules: list[dict]) -> str:
    """Return an HTML fragment listing source rules."""
    import html as _h

    if not rules:
        return '<small style="color:var(--pico-muted-color)">No rules. Add one above to auto-download from matching sources.</small>'

    parts: list[str] = ['<ul style="list-style:none;padding:0;margin:0;font-size:0.85rem">']
    for rule in rules:
        rid = _h.escape(rule["id"])
        pat = _h.escape(rule["source_pattern"])
        qual = _h.escape(rule.get("quality", "720"))
        auto = "auto" if rule.get("auto_download") else "manual"
        parts.append(
            f'<li style="padding:0.3rem 0;border-bottom:1px solid var(--pico-muted-border-color);display:flex;justify-content:space-between;align-items:center">'
            f'<span><code>{pat}</code> ({qual}p, {auto})</span>'
            f'<button class="outline secondary" style="font-size:0.7rem;padding:0.1rem 0.3rem"'
            f'  hx-delete="/api/library/rules/{rid}"'
            f'  hx-target="#rules-list"'
            f'  hx-swap="innerHTML">'
            f'✕</button>'
            f'</li>'
        )
    parts.append("</ul>")
    return "".join(parts)


def _render_storage_summary(summary: dict) -> str:
    """Return an HTML snippet for the storage summary bar."""
    total_bytes = summary.get("total_bytes", 0)
    total_count = summary.get("total_count", 0)
    if not total_count:
        return '<small>No items stored yet.</small>'

    return (
        f'<small>Library storage: {_format_bytes(total_bytes)} '
        f'across {total_count} item{"s" if total_count != 1 else ""}'
        f'</small>'
    )


# ---------------------------------------------------------------------------
# List / Get / Delete
# ---------------------------------------------------------------------------


@router.get("/api/library/items")
async def list_items(
    request: Request,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List library items, optionally filtered by kind or status."""
    store = await _get_library_store(request)
    items = await store.list_items(kind=kind, status=status, limit=limit, offset=offset)

    if _is_htmx(request):
        return HTMLResponse(_render_item_list(items))

    return {"items": items, "count": len(items)}


@router.get("/api/library/items/{item_id}")
async def get_item(request: Request, item_id: str):
    """Get a library item with its artifacts."""
    store = await _get_library_store(request)
    item = await store.get_item(item_id)
    if not item:
        return JSONResponse({"error": f"Item {item_id!r} not found"}, status_code=404)

    artifacts = await store.get_artifacts(item_id)
    jobs = await store.get_item_jobs(item_id)
    return {"item": item, "artifacts": artifacts, "jobs": jobs}


@router.delete("/api/library/items/{item_id}")
async def delete_item(request: Request, item_id: str):
    """Delete a library item and its associated files."""
    store = await _get_library_store(request)
    item = await store.get_item(item_id)
    if not item:
        return JSONResponse({"error": f"Item {item_id!r} not found"}, status_code=404)

    # Remove on-disk files
    storage_path = item.get("storage_path", "")
    if storage_path and (p := Path(storage_path)).exists():
        try:
            p.unlink()
        except OSError:
            pass

    # Remove artifacts from disk
    artifacts = await store.get_artifacts(item_id)
    for art in artifacts:
        art_path = art.get("path", "")
        if art_path and (ap := Path(art_path)).exists():
            try:
                ap.unlink()
            except OSError:
                pass

    # Remove collections folder
    storage_dir = _library_dir(request)
    item_collection_dir = storage_dir.parent / "collections" / item_id
    if item_collection_dir.exists():
        import shutil
        try:
            shutil.rmtree(item_collection_dir)
        except OSError:
            pass

    await store.delete_item(item_id)
    return {"status": "deleted", "item_id": item_id}


@router.post("/api/library/items/{item_id}/reprocess")
async def reprocess_item(request: Request, item_id: str):
    """Re-run the ingest pipeline for an existing item."""
    store = await _get_library_store(request)
    item = await store.get_item(item_id)
    if not item:
        return JSONResponse({"error": f"Item {item_id!r} not found"}, status_code=404)

    storage_dir = _library_dir(request)

    task_set = getattr(request.app.state, "_background_tasks", None)
    coro = _ingest_task(request.app, item_id, store, storage_dir)
    if task_set is None:
        _track_background_task(coro)
    else:
        _create_supervised_task(coro, task_set)

    return JSONResponse({"item_id": item_id, "status": "reprocessing"}, status_code=202)


# ---------------------------------------------------------------------------
# Heavy tier: download
# ---------------------------------------------------------------------------


@router.post("/api/library/items/{item_id}/download")
async def trigger_download(
    request: Request,
    item_id: str,
    quality: str | None = Form(None),
):
    """Trigger heavy-tier media download for an item.

    Accepts optional ``quality`` form field (360, 480, 720, 1080, best).
    Runs the download asynchronously in a background task.
    """
    store = await _get_library_store(request)
    item = await store.get_item(item_id)
    if not item:
        return JSONResponse({"error": f"Item {item_id!r} not found"}, status_code=404)

    if item["kind"] != "url:youtube":
        return JSONResponse(
            {"error": "Heavy download only supports url:youtube items"},
            status_code=400,
        )

    storage_dir = _library_dir(request)
    quality_val = quality or item.get("quality", "") or "720"

    task_set = getattr(request.app.state, "_background_tasks", None)
    coro = _heavy_download_task(request.app, item_id, store, storage_dir, quality_val)
    if task_set is None:
        _track_background_task(coro)
    else:
        _create_supervised_task(coro, task_set)

    return JSONResponse(
        {"item_id": item_id, "status": "downloading", "quality": quality_val},
        status_code=202,
    )


async def _heavy_download_task(
    app, item_id: str, store, storage_dir: Path, quality: str
) -> None:
    """Background task: run heavy download for an item."""
    from tinyagentos.library_pipeline import run_heavy_pipeline

    try:
        result = await run_heavy_pipeline(store, item_id, storage_dir, quality=quality)
        if result:
            logger.info("Heavy download complete for item %s: %s", item_id, result)
    except Exception:
        logger.exception("Heavy download crashed for item %s", item_id)
        await store.update_item_status(item_id, "error")


@router.get("/api/library/items/{item_id}/download/status")
async def download_status(request: Request, item_id: str):
    """Check heavy download status for an item."""
    store = await _get_library_store(request)
    item = await store.get_item(item_id)
    if not item:
        return JSONResponse({"error": f"Item {item_id!r} not found"}, status_code=404)

    jobs = await store.get_item_jobs(item_id)
    heavy_jobs = [j for j in jobs if j.get("stage") == "heavy_download"]
    download_path = item.get("download_path", "")
    download_bytes = item.get("download_bytes", 0)

    return {
        "item_id": item_id,
        "downloaded": bool(download_path),
        "download_path": download_path,
        "download_bytes": download_bytes,
        "jobs": heavy_jobs,
    }


# ---------------------------------------------------------------------------
# Source rules
# ---------------------------------------------------------------------------


@router.post("/api/library/rules")
async def create_rule(
    request: Request,
    source_pattern: str = Form(...),
    quality: str | None = Form("720"),
    auto_download: bool = Form(False),
):
    """Create a source rule for automatic heavy download triggers."""
    store = await _get_library_store(request)
    rule_id = await store.create_rule(
        source_pattern=source_pattern,
        quality=quality or "720",
        auto_download=auto_download,
    )
    return JSONResponse(
        {"rule_id": rule_id, "source_pattern": source_pattern, "status": "created"},
        status_code=201,
    )


@router.get("/api/library/rules")
async def list_rules(request: Request):
    """List all source rules."""
    store = await _get_library_store(request)
    rules = await store.list_rules()

    if _is_htmx(request):
        return HTMLResponse(_render_rules_list(rules))

    return {"rules": rules, "count": len(rules)}


@router.delete("/api/library/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: str):
    """Delete a source rule."""
    store = await _get_library_store(request)
    rule = await store.get_rule(rule_id)
    if not rule:
        return JSONResponse({"error": f"Rule {rule_id!r} not found"}, status_code=404)

    await store.delete_rule(rule_id)
    return {"status": "deleted", "rule_id": rule_id}


# ---------------------------------------------------------------------------
# Storage accounting
# ---------------------------------------------------------------------------


@router.get("/api/library/usage")
async def storage_usage(request: Request):
    """Return storage accounting summary for the library."""
    store = await _get_library_store(request)
    summary = await store.get_storage_summary()

    if _is_htmx(request):
        return HTMLResponse(_render_storage_summary(summary))

    return summary
