"""Tests for the Library app — store, pipeline, routes, and collections handoff."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from tinyagentos.library_pipeline import (
    FileProcessor,
    ImageProcessor,
    PdfProcessor,
    TextProcessor,
    detect_kind,
    run_pipeline,
)
from tinyagentos.library_store import LibraryStore
from tinyagentos.library_collections import handoff_to_collections


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def lib_store():
    """Create a LibraryStore backed by a temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    store = LibraryStore(db_path)
    await store.init()

    yield store

    await store.close()
    try:
        db_path.unlink()
    except OSError:
        pass


@pytest.fixture
def storage_dir():
    """Create a temporary directory for file artifacts."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------


class TestKindDetection:
    def test_detect_youtube_url(self):
        assert detect_kind(source_url="https://www.youtube.com/watch?v=abc123") == "url:youtube"
        assert detect_kind(source_url="https://youtube.com/watch?v=abc123") == "url:youtube"
        assert detect_kind(source_url="https://youtu.be/abc123") == "url:youtube"
        assert detect_kind(source_url="https://m.youtube.com/watch?v=abc123") == "url:youtube"

    def test_detect_web_url(self):
        assert detect_kind(source_url="https://example.com") == "url:web"
        assert detect_kind(source_url="http://blog.example.com/post") == "url:web"

    def test_detect_by_mime(self):
        assert detect_kind(content_type="text/plain") == "text"
        assert detect_kind(content_type="application/pdf") == "pdf"
        assert detect_kind(content_type="image/png") == "image"
        assert detect_kind(content_type="image/jpeg") == "image"
        assert detect_kind(content_type="application/zip") == "archive"

    def test_detect_by_filename(self):
        assert detect_kind(file_path="doc.txt") == "text"
        assert detect_kind(file_path="report.pdf") == "pdf"
        assert detect_kind(file_path="photo.jpg") == "image"
        assert detect_kind(file_path="icon.png") == "image"

    def test_detect_fallback(self):
        assert detect_kind(file_path="unknown.xyz") == "file"
        assert detect_kind() == "file"


# ---------------------------------------------------------------------------
# LibraryStore
# ---------------------------------------------------------------------------


class TestLibraryStore:
    @pytest.mark.asyncio
    async def test_create_and_get_item(self, lib_store):
        item_id = await lib_store.create_item(
            kind="text",
            title="test.txt",
            source_url="",
            storage_path="/tmp/test.txt",
            size_bytes=42,
        )
        assert item_id

        item = await lib_store.get_item(item_id)
        assert item is not None
        assert item["kind"] == "text"
        assert item["title"] == "test.txt"
        assert item["status"] == "pending"
        assert item["bytes"] == 42

    @pytest.mark.asyncio
    async def test_get_nonexistent_item(self, lib_store):
        item = await lib_store.get_item("nonexistent")
        assert item is None

    @pytest.mark.asyncio
    async def test_list_items(self, lib_store):
        id1 = await lib_store.create_item(kind="text", title="a.txt")
        id2 = await lib_store.create_item(kind="pdf", title="b.pdf")
        id3 = await lib_store.create_item(kind="image", title="c.png")

        items = await lib_store.list_items()
        assert len(items) == 3

        text_items = await lib_store.list_items(kind="text")
        assert len(text_items) == 1
        assert text_items[0]["title"] == "a.txt"

        assert len(await lib_store.list_items(status="pending")) == 3
        assert len(await lib_store.list_items(status="ready")) == 0

    @pytest.mark.asyncio
    async def test_update_item(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="old")
        await lib_store.update_item(item_id, title="new", status="ready")

        item = await lib_store.get_item(item_id)
        assert item["title"] == "new"
        assert item["status"] == "ready"

    @pytest.mark.asyncio
    async def test_update_item_meta(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        await lib_store.update_item(item_id, meta_json={"preview": "hello"})

        item = await lib_store.get_item(item_id)
        meta = json.loads(item["meta_json"])
        assert meta["preview"] == "hello"

    @pytest.mark.asyncio
    async def test_update_invalid_status(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        with pytest.raises(ValueError):
            await lib_store.update_item_status(item_id, "invalid_status")

    @pytest.mark.asyncio
    async def test_delete_item(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        item = await lib_store.get_item(item_id)
        assert item is not None

        await lib_store.delete_item(item_id)
        item = await lib_store.get_item(item_id)
        assert item is None

    @pytest.mark.asyncio
    async def test_artifacts(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        art_id = await lib_store.add_artifact(item_id, kind="text", path="/tmp/test.txt")

        artifacts = await lib_store.get_artifacts(item_id)
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "text"

        await lib_store.delete_artifact(art_id)
        assert len(await lib_store.get_artifacts(item_id)) == 0

    @pytest.mark.asyncio
    async def test_cascade_delete_artifacts(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        await lib_store.add_artifact(item_id, kind="text", path="/tmp/a.txt")
        await lib_store.add_artifact(item_id, kind="thumbnail", path="/tmp/thumb.jpg")

        await lib_store.delete_item(item_id)
        assert len(await lib_store.get_artifacts(item_id)) == 0

    @pytest.mark.asyncio
    async def test_jobs(self, lib_store):
        item_id = await lib_store.create_item(kind="text", title="test")
        job_id = await lib_store.create_job(item_id, "ingest")

        job = await lib_store.get_job(job_id)
        assert job is not None
        assert job["stage"] == "ingest"
        assert job["state"] == "queued"

        await lib_store.update_job(job_id, state="done")
        job = await lib_store.get_job(job_id)
        assert job["state"] == "done"


# ---------------------------------------------------------------------------
# Pipeline processors
# ---------------------------------------------------------------------------


class TestFileProcessor:
    @pytest.mark.asyncio
    async def test_process_existing_file(self, lib_store, storage_dir):
        file_path = storage_dir / "test.txt"
        file_path.write_text("hello world")

        item_id = await lib_store.create_item(
            kind="file", title="test.txt", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = FileProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "metadata"

    @pytest.mark.asyncio
    async def test_process_missing_file(self, lib_store, storage_dir):
        item_id = await lib_store.create_item(
            kind="file", title="missing.txt", storage_path="/nonexistent/file.txt"
        )
        item = await lib_store.get_item(item_id)

        proc = FileProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)
        assert len(artifacts) == 0


class TestTextProcessor:
    @pytest.mark.asyncio
    async def test_extract_text(self, lib_store, storage_dir):
        file_path = storage_dir / "notes.txt"
        file_path.write_text("line one\nline two\nline three")

        item_id = await lib_store.create_item(
            kind="text", title="notes.txt", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = TextProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)
        assert len(artifacts) == 1
        assert artifacts[0]["kind"] == "text"
        assert artifacts[0]["meta"]["line_count"] == 3
        assert artifacts[0]["meta"]["char_count"] == 28

        text_path = Path(artifacts[0]["path"])
        assert text_path.exists()
        assert "line one" in text_path.read_text()

    @pytest.mark.asyncio
    async def test_text_auto_title(self, lib_store, storage_dir):
        file_path = storage_dir / "notes.txt"
        file_path.write_text("My Title\nmore content here")

        item_id = await lib_store.create_item(
            kind="text", title="", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = TextProcessor(lib_store, storage_dir)
        await proc.process(item)

        updated = await lib_store.get_item(item_id)
        assert updated["title"] == "My Title"

    @pytest.mark.asyncio
    async def test_text_preview(self, lib_store, storage_dir):
        file_path = storage_dir / "long.txt"
        file_path.write_text("A" * 500)

        item_id = await lib_store.create_item(
            kind="text", title="long.txt", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = TextProcessor(lib_store, storage_dir)
        await proc.process(item)

        updated = await lib_store.get_item(item_id)
        meta = json.loads(updated["meta_json"])
        assert "preview" in meta
        assert len(meta["preview"]) == 200


class TestPdfProcessor:
    @pytest.mark.asyncio
    async def test_process_pdf(self, lib_store, storage_dir):
        file_path = storage_dir / "test.pdf"
        _create_minimal_pdf(file_path)

        item_id = await lib_store.create_item(
            kind="pdf", title="test.pdf", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = PdfProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)

        meta_artifacts = [a for a in artifacts if a["kind"] == "metadata"]
        assert len(meta_artifacts) >= 1
        assert meta_artifacts[0]["meta"]["page_count"] >= 0

    @pytest.mark.asyncio
    async def test_process_missing_pdf(self, lib_store, storage_dir):
        item_id = await lib_store.create_item(
            kind="pdf", title="missing.pdf", storage_path="/nonexistent/file.pdf"
        )
        item = await lib_store.get_item(item_id)

        proc = PdfProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)
        assert len(artifacts) == 0


class TestImageProcessor:
    @pytest.mark.asyncio
    async def test_process_image(self, lib_store, storage_dir):
        file_path = storage_dir / "test.png"
        _create_test_image(file_path)

        item_id = await lib_store.create_item(
            kind="image", title="test.png", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = ImageProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)

        kinds = {a["kind"] for a in artifacts}
        assert "metadata" in kinds
        assert "thumbnail" in kinds

        thumb_art = [a for a in artifacts if a["kind"] == "thumbnail"][0]
        assert Path(thumb_art["path"]).exists()

    @pytest.mark.asyncio
    async def test_process_missing_image(self, lib_store, storage_dir):
        item_id = await lib_store.create_item(
            kind="image", title="missing.png", storage_path="/nonexistent/file.png"
        )
        item = await lib_store.get_item(item_id)

        proc = ImageProcessor(lib_store, storage_dir)
        artifacts = await proc.process(item)
        assert len(artifacts) == 0


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


class TestRunPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_text(self, lib_store, storage_dir):
        file_path = storage_dir / "notes.txt"
        file_path.write_text("sample content")

        item_id = await lib_store.create_item(
            kind="text", title="notes.txt", storage_path=str(file_path)
        )
        await run_pipeline(lib_store, item_id, storage_dir)

        item = await lib_store.get_item(item_id)
        assert item["status"] == "ready"

        artifacts = await lib_store.get_artifacts(item_id)
        artifact_kinds = {a["kind"] for a in artifacts}
        assert "metadata" in artifact_kinds
        assert "text" in artifact_kinds

    @pytest.mark.asyncio
    async def test_pipeline_file(self, lib_store, storage_dir):
        file_path = storage_dir / "unknown.xyz"
        file_path.write_text("raw data")

        item_id = await lib_store.create_item(
            kind="file", title="unknown.xyz", storage_path=str(file_path)
        )
        await run_pipeline(lib_store, item_id, storage_dir)

        item = await lib_store.get_item(item_id)
        assert item["status"] == "ready"

    @pytest.mark.asyncio
    async def test_pipeline_error_status(self, lib_store, storage_dir):
        item_id = await lib_store.create_item(
            kind="file", title="missing.txt", storage_path="/missing/file.txt"
        )
        await run_pipeline(lib_store, item_id, storage_dir)
        item = await lib_store.get_item(item_id)
        assert item["status"] == "error"


# ---------------------------------------------------------------------------
# Collections handoff
# ---------------------------------------------------------------------------


class TestCollectionsHandoff:
    @pytest.mark.asyncio
    async def test_handoff_files_copied(self, lib_store, storage_dir):
        """Text artifacts are copied to collections dir even without qmd;
        returns 0 when qmd is unreachable (no silent ImportError success)."""
        file_path = storage_dir / "notes.txt"
        file_path.write_text("content for collections")

        item_id = await lib_store.create_item(
            kind="text", title="notes.txt", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = TextProcessor(lib_store, storage_dir)
        await proc.process(item)

        collections_dir = storage_dir / "collections"
        count = await handoff_to_collections(lib_store, item_id, collections_dir)

        # Files copied but no qmd → 0 indexed
        assert count == 0

        # Verify files were still copied to collections dir
        item_dir = collections_dir / item_id
        assert item_dir.exists()
        text_files = list(item_dir.glob("*.txt"))
        assert len(text_files) >= 1
        assert "content for collections" in text_files[0].read_text()

    @pytest.mark.asyncio
    async def test_handoff_with_qmd(self, lib_store, storage_dir):
        """Handoff indexes into qmd when the API is reachable."""
        from unittest.mock import AsyncMock, patch

        file_path = storage_dir / "notes.txt"
        file_path.write_text("hello from library")

        item_id = await lib_store.create_item(
            kind="text", title="notes.txt", storage_path=str(file_path)
        )
        item = await lib_store.get_item(item_id)

        proc = TextProcessor(lib_store, storage_dir)
        await proc.process(item)

        collections_dir = storage_dir / "collections"
        qmd_url = "http://localhost:17832"

        # Mock httpx.AsyncClient to simulate a working qmd
        from unittest.mock import AsyncMock, MagicMock

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        # POST responses — MagicMock for sync .json(), AsyncMock for async .post()
        mock_create_resp = MagicMock()
        mock_create_resp.status_code = 200
        mock_create_resp.json.return_value = {"id": "coll-123"}
        mock_index_resp = MagicMock()
        mock_index_resp.status_code = 200
        mock_client.post = AsyncMock(side_effect=[mock_create_resp, mock_index_resp])

        with patch("httpx.AsyncClient", return_value=mock_client):
            count = await handoff_to_collections(
                lib_store, item_id, collections_dir,
                qmd_base_url=qmd_url,
            )

        assert count == 1  # One artifact indexed


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


class TestLibraryRoutes:
    @pytest.mark.asyncio
    async def test_library_page_gone(self, client):
        """The server-rendered /library page was dropped (fold 6) —
        the Library UI is the React desktop app."""
        resp = await client.get("/library")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ingest_no_input(self, client):
        resp = await client.post("/api/library/ingest")
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_ingest_url(self, client):
        resp = await client.post("/api/library/ingest", data={"url": "https://example.com/page"})
        assert resp.status_code == 202
        data = resp.json()
        assert "item_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_ingest_file(self, client, tmp_path):
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world")

        with open(test_file, "rb") as f:
            resp = await client.post(
                "/api/library/ingest",
                files={"file": ("hello.txt", f, "text/plain")},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert "item_id" in data

    @pytest.mark.asyncio
    async def test_list_items(self, client):
        resp = await client.get("/api/library/items")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_item(self, client):
        resp = await client.get("/api/library/items/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_item(self, client):
        resp = await client.delete("/api/library/items/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reprocess_nonexistent_item(self, client):
        resp = await client.post("/api/library/items/nonexistent/reprocess")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_ingest_and_get(self, client):
        resp = await client.post("/api/library/ingest", data={"url": "https://example.com"})
        assert resp.status_code == 202
        item_id = resp.json()["item_id"]

        resp = await client.get(f"/api/library/items/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["id"] == item_id
        assert "artifacts" in data

    @pytest.mark.asyncio
    async def test_filter_by_kind(self, client):
        await client.post("/api/library/ingest", data={"url": "https://example.com"})
        await client.post("/api/library/ingest", data={"url": "https://youtube.com/watch?v=abc"})

        resp = await client.get("/api/library/items", params={"kind": "url:youtube"})
        data = resp.json()
        for item in data["items"]:
            assert item["kind"] == "url:youtube"

    # -- Auth: all endpoints require a session (CSRF is bypassed in tests, but
    #    unauthenticated requests still hit the global auth middleware).  Test
    #    that the 6 new endpoints return 401 when no session cookie/header is
    #    present.

    @pytest.mark.asyncio
    async def test_unauth_library_endpoints(self, app):
        """All 6 library endpoints return 401 without authentication."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauth_client:
            endpoints: list[tuple[str, str]] = [
                ("post", "/api/library/ingest"),
                ("get", "/api/library/items"),
                ("get", "/api/library/items/abc123"),
                ("delete", "/api/library/items/abc123"),
                ("post", "/api/library/items/abc123/reprocess"),
            ]
            for method, url in endpoints:
                if method == "post":
                    resp = await unauth_client.post(url, data={"url": "https://example.com"})
                elif method == "delete":
                    resp = await unauth_client.delete(url)
                else:
                    resp = await unauth_client.get(url)
                assert resp.status_code == 401, f"{method.upper()} {url} returned {resp.status_code}, expected 401"

    # -- 413: oversized upload (tested at the HTTP level in integration;
    #    ASGI transport does not propagate Content-Length to file.size)

    @pytest.mark.asyncio
    async def test_reprocess_idempotent(self, client, tmp_path):
        """Reprocessing an item deletes old artifacts first — no duplicates."""
        test_file = tmp_path / "notes.txt"
        test_file.write_text("test content")

        with open(test_file, "rb") as f:
            resp = await client.post(
                "/api/library/ingest",
                files={"file": ("notes.txt", f, "text/plain")},
            )
        assert resp.status_code == 202
        item_id = resp.json()["item_id"]

        # Wait for pipeline to finish (background task)
        import asyncio
        await asyncio.sleep(0.5)

        # First reprocess
        resp = await client.post(f"/api/library/items/{item_id}/reprocess")
        assert resp.status_code == 202

        await asyncio.sleep(0.5)

        # Second reprocess — should still work, no duplicates
        resp = await client.post(f"/api/library/items/{item_id}/reprocess")
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_reprocess_while_processing_returns_409(self, client, app):
        """Reprocessing an item that is already pending/processing returns 409."""
        # Ingest normally and wait for pipeline to finish
        import asyncio

        resp = await client.post(
            "/api/library/ingest",
            data={"url": "https://example.com"},
        )
        assert resp.status_code == 202
        item_id = resp.json()["item_id"]
        await asyncio.sleep(0.5)

        # Force status to "processing" to simulate an in-flight pipeline
        store = app.state.library_store
        await store.update_item_status(item_id, "processing")

        # Reprocess should be rejected
        resp = await client.post(f"/api/library/items/{item_id}/reprocess")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_minimal_pdf(path: Path):
    """Create a minimal valid PDF file for testing."""
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF\n"
    )
    path.write_bytes(pdf_content)


def _create_test_image(path: Path):
    """Create a simple test image using PIL."""
    from PIL import Image
    img = Image.new("RGB", (100, 50), color="blue")
    img.save(path)
