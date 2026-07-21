"""Library ingest pipeline — processors for cheap-tier file/text/pdf/image ingestion.

Processors are registered per detected kind and run asynchronously after ingest.
Each processor produces artifacts (e.g. metadata, extracted text, thumbnails)
that are stored on the item and optionally handed off to taosmd collections.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
from pathlib import Path

from tinyagentos.library_store import LibraryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------

_MIME_KIND_MAP: dict[str, str] = {
    "text/plain": "text",
    "text/markdown": "text",
    "text/csv": "text",
    "text/html": "text",
    "application/json": "text",
    "application/xml": "text",
    "text/xml": "text",
    "application/pdf": "pdf",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "image/svg+xml": "image",
    "application/zip": "archive",
    "application/gzip": "archive",
    "application/x-tar": "archive",
}


def detect_kind(source_url: str = "", content_type: str = "",
                file_path: str = "") -> str:
    """Detect the library item kind from URL, MIME, or file path."""
    # URL-based detection
    if source_url:
        lower = source_url.lower()
        if any(lower.startswith(p) for p in ("https://www.youtube.com/",
                                              "https://youtube.com/",
                                              "https://youtu.be/",
                                              "https://m.youtube.com/")):
            return "url:youtube"
        if any(lower.startswith(p) for p in ("https://", "http://")):
            return "url:web"

    # MIME-based detection
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _MIME_KIND_MAP:
            return _MIME_KIND_MAP[ct]

    # File extension fallback
    if file_path:
        ext = Path(file_path).suffix.lower()
        ext_map = {
            ".txt": "text", ".md": "text", ".csv": "text",
            ".json": "text", ".xml": "text", ".html": "text",
            ".pdf": "pdf",
            ".png": "image", ".jpg": "image", ".jpeg": "image",
            ".gif": "image", ".webp": "image", ".svg": "image",
            ".zip": "archive", ".gz": "archive", ".tar": "archive",
        }
        if ext in ext_map:
            return ext_map[ext]

    return "file"


# ---------------------------------------------------------------------------
# Processor registry
# ---------------------------------------------------------------------------

class Processor:
    """Base processor. Subclasses handle one kind of library item."""

    def __init__(self, store: LibraryStore, storage_dir: Path):
        self.store = store
        self.storage_dir = storage_dir

    async def process(self, item: dict) -> list[dict]:
        """Run processing on an item, return list of artifact dicts produced."""
        raise NotImplementedError


class FileProcessor(Processor):
    """Generic file processor — records basic metadata only."""

    async def process(self, item: dict) -> list[dict]:
        item_id = item["id"]
        artifacts: list[dict] = []

        storage_path = item.get("storage_path", "")
        source_url = item.get("source_url", "")
        if storage_path:
            p = Path(storage_path)
            if p.exists():
                stat = p.stat()
                file_meta = {
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                    "source_url": source_url,
                    "processed_at": time.time(),
                    "processor": "FileProcessor/v1",
                }
                # Try mimetype detection
                mime_type, _ = mimetypes.guess_type(p.name)
                if mime_type:
                    file_meta["mime_type"] = mime_type

                # path="" because storage_path is the user's original uploaded
                # file — the reprocess unlink loop must never delete it.
                await self.store.add_artifact(
                    item_id, kind="metadata", path="", meta=file_meta
                )
                artifacts.append({"kind": "metadata", "path": "", "meta": file_meta})

                # Update item bytes
                await self.store.update_item(item_id, bytes=stat.st_size)

        return artifacts


class TextProcessor(Processor):
    """Text file processor — extracts content as text artifact."""

    async def process(self, item: dict) -> list[dict]:
        item_id = item["id"]
        artifacts: list[dict] = []

        storage_path = item.get("storage_path", "")
        if not storage_path:
            return artifacts

        p = Path(storage_path)
        if not p.exists():
            logger.warning("Text processor: file not found %s", storage_path)
            return artifacts

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.warning("Text processor: could not read %s", storage_path,
                           exc_info=True)
            return artifacts

        # Write extracted text as an artifact
        text_dir = self.storage_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        text_path = text_dir / f"{item_id}.txt"
        text_path.write_text(text, encoding="utf-8")

        text_meta = {
            "char_count": len(text),
            "line_count": text.count("\n") + 1,
            "source_url": item.get("source_url", ""),
            "processed_at": time.time(),
            "processor": "TextProcessor/v1",
        }
        await self.store.add_artifact(
            item_id, kind="text", path=str(text_path), meta=text_meta
        )
        artifacts.append({"kind": "text", "path": str(text_path), "meta": text_meta})

        # Store a preview (first 200 chars)
        preview = text[:200]
        meta = json.loads(item.get("meta_json", "{}"))
        meta["preview"] = preview
        await self.store.update_item(item_id, meta_json=meta)

        # Auto-title from content if no title
        if not item.get("title"):
            title = text.strip().split("\n", 1)[0][:100]
            if title:
                await self.store.update_item(item_id, title=title)

        return artifacts


class PdfProcessor(Processor):
    """PDF processor — extracts page count and OCR-ready text (when available)."""

    async def process(self, item: dict) -> list[dict]:
        item_id = item["id"]
        artifacts: list[dict] = []

        storage_path = item.get("storage_path", "")
        if not storage_path:
            return artifacts

        p = Path(storage_path)
        if not p.exists():
            return artifacts

        pdf_meta = {"page_count": 0, "has_text": False}

        # Try extracting text with PyPDF2 / pypdf if available
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(p))
            pdf_meta["page_count"] = len(reader.pages)

            # Extract text from all pages
            pages_text: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)

            if pages_text:
                text_content = "\n\n".join(pages_text)
                pdf_meta["has_text"] = True
                pdf_meta["char_count"] = len(text_content)

                text_dir = self.storage_dir / "text"
                text_dir.mkdir(parents=True, exist_ok=True)
                text_path = text_dir / f"{item_id}_pdf.txt"
                text_path.write_text(text_content, encoding="utf-8")

                await self.store.add_artifact(
                    item_id, kind="text", path=str(text_path),
                    meta={"char_count": len(text_content), "pages": len(reader.pages)},
                )
                artifacts.append({
                    "kind": "text", "path": str(text_path),
                    "meta": {"char_count": len(text_content), "pages": len(reader.pages)},
                })

                # Update item with preview
                preview = text_content[:200]
                meta = json.loads(item.get("meta_json", "{}"))
                meta["preview"] = preview
                await self.store.update_item(item_id, meta_json=meta)
        except ImportError:
            logger.debug("pypdf not installed — PDF text extraction skipped")
        except Exception:
            logger.warning("PDF text extraction failed for %s", storage_path,
                           exc_info=True)

        await self.store.add_artifact(
            item_id, kind="metadata", path="", meta=pdf_meta
        )
        artifacts.append({"kind": "metadata", "path": "", "meta": pdf_meta})

        return artifacts


class ImageProcessor(Processor):
    """Image processor — records dimensions, creates thumbnail.

    Thumbnail generation requires Pillow (PIL), which is always available in
    the taOS dev dependencies.
    """

    async def process(self, item: dict) -> list[dict]:
        item_id = item["id"]
        artifacts: list[dict] = []

        storage_path = item.get("storage_path", "")
        if not storage_path:
            return artifacts

        p = Path(storage_path)
        if not p.exists():
            return artifacts

        img_meta: dict = {"width": 0, "height": 0, "format": ""}

        try:
            from PIL import Image
            with Image.open(p) as img:
                img_meta["width"] = img.width
                img_meta["height"] = img.height
                img_meta["format"] = img.format or ""

                # Create thumbnail (max 320px on longest side)
                thumb_dir = self.storage_dir / "thumbs"
                thumb_dir.mkdir(parents=True, exist_ok=True)
                thumb_path = thumb_dir / f"{item_id}_thumb.jpg"

                img.thumbnail((320, 320))
                # Convert to RGB if needed (e.g. RGBA/PNG → JPEG)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=75)

                img_meta["thumbnail"] = str(thumb_path)
                await self.store.add_artifact(
                    item_id, kind="thumbnail", path=str(thumb_path),
                    meta={"width": img.width, "height": img.height},
                )
                artifacts.append({
                    "kind": "thumbnail", "path": str(thumb_path),
                    "meta": {"width": img.width, "height": img.height},
                })
        except ImportError:
            logger.debug("PIL not available — image processing skipped")
        except Exception:
            logger.warning("Image processing failed for %s", storage_path,
                           exc_info=True)

        await self.store.add_artifact(
            item_id, kind="metadata", path="", meta=img_meta
        )
        artifacts.append({"kind": "metadata", "path": "", "meta": img_meta})

        return artifacts


# ---------------------------------------------------------------------------
# Processor registry
# ---------------------------------------------------------------------------

_PROCESSORS: dict[str, type[Processor]] = {
    "file": FileProcessor,
    "text": TextProcessor,
    "pdf": PdfProcessor,
    "image": ImageProcessor,
}


def get_processor(kind: str, store: LibraryStore,
                  storage_dir: Path) -> Processor:
    """Return a processor for the given kind, falling back to FileProcessor."""
    cls = _PROCESSORS.get(kind, FileProcessor)
    return cls(store, storage_dir)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


async def run_pipeline(
    store: LibraryStore,
    item_id: str,
    storage_dir: Path,
) -> None:
    """Run the ingest pipeline for one item.

    Steps:
    1. Mark item as 'processing'
    2. Determine processor from item kind
    3. Run file + kind-specific processors
    4. Collect artifacts
    5. Mark item as 'ready' (or 'error')
    """
    item = await store.get_item(item_id)
    if not item:
        return

    kind = item["kind"]

    # URL-only items (no storage_path) are stored as references — the pipeline
    # records a reference metadata artifact but does not fetch remote content
    # (future: WebFetcherProcessor).  The item gets a "reference" artifact so it
    # is not silently empty.
    if not item.get("storage_path") and item.get("source_url"):
        logger.info(
            "Library pipeline: URL-only item %s (%s) — stored as reference, not fetched",
            item_id, kind,
        )
        ref_meta = {
            "source_url": item["source_url"],
            "kind": kind,
            "note": "Reference-only item — content not fetched (TODO: WebFetcherProcessor)",
        }
        await store.add_artifact(
            item_id, kind="reference", path="", meta=ref_meta,
        )

    # If item has a storage_path that points to a missing file, fail early
    # (dropped/moved/corrupt source must not silently look successful).
    storage_path = item.get("storage_path", "")
    source_url = item.get("source_url", "")
    if storage_path and not source_url:
        sp = Path(storage_path)
        if not sp.exists():
            logger.warning(
                "Library pipeline: source file missing for item %s: %s",
                item_id, storage_path,
            )
            await store.update_item_status(item_id, "error")
            await store.update_item(
                item_id,
                meta_json={
                    **json.loads(item.get("meta_json", "{}")),
                    "error": f"Source file not found: {storage_path}",
                },
            )
            return

    try:
        await store.update_item_status(item_id, "processing")

        # Stage 1: basic file metadata (always)
        file_proc = FileProcessor(store, storage_dir)
        await file_proc.process(item)

        # Stage 2: kind-specific processor
        proc = get_processor(kind, store, storage_dir)
        if not isinstance(proc, FileProcessor):
            await proc.process(item)

        await store.update_item_status(item_id, "ready")
    except Exception:
        logger.exception("Library pipeline failed for item %s (kind=%s)",
                         item_id, kind)
        await store.update_item_status(item_id, "error")
        await store.update_item(
            item_id,
            meta_json={
                **json.loads(item.get("meta_json", "{}")),
                "error": f"Pipeline failed for kind={kind}",
            },
        )
