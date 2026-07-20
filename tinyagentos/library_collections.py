"""Library collections handoff — index text artifacts into taosmd collections.

After the ingest pipeline produces text artifacts (extracted text, transcripts,
descriptions), this module hands them off to taosmd collections via the qmd
HTTP API so agents can query the content through collection grants.

The design doc (docs/design/library-app.md) says:
  "Collections handoff: write text artifacts into a per-target folder under an
  allowed root, then taosmd collections index; link to project; grants stay
  EXPLICIT"

Flow (Phase 1):
  1. Write text artifacts under collections_dir/{item_id}/
  2. Create a collection via POST /collections (qmd HTTP API)
  3. Index each text artifact via POST /collections/{id}/index
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Text artifact kinds that should be indexed into collections
_TEXT_ARTIFACT_KINDS = frozenset({"text", "transcript", "description", "ocr"})


async def handoff_to_collections(
    store,
    item_id: str,
    collections_dir: Path,
    qmd_base_url: str | None = None,
    project_id: str | None = None,
) -> int:
    """Hand off all text artifacts for an item to taosmd collections.

    Writes text artifacts under ``collections_dir/{item_id}/``, then calls
    the qmd HTTP API to create a collection and index the text content.

    Returns the number of artifacts successfully indexed into the collection.
    Returns 0 when qmd is unavailable (no collection created).

    Parameters
    ----------
    store:
        LibraryStore instance.
    item_id:
        Library item id.
    collections_dir:
        Allowed root for collection files (e.g. ``data/collections/``).
    qmd_base_url:
        Base URL of the running qmd serve instance (e.g. ``http://localhost:7832``).
        When omitted or None, file-copy still happens but no collection is
        created or indexed — the caller must have already created the collection
        separately (production paths always supply this; test paths may omit it).
    project_id:
        Optional project to link the collection to (Phase 2+).
    """
    from tinyagentos.library_store import LibraryStore

    artifacts = await store.get_artifacts(item_id)
    if not artifacts:
        return 0

    text_artifacts = [
        a for a in artifacts if a["kind"] in _TEXT_ARTIFACT_KINDS
    ]
    if not text_artifacts:
        return 0

    item = await store.get_item(item_id)
    if not item:
        return 0

    # Write text artifacts to a per-item folder under the collections root
    item_dir = collections_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)

    # Copy each text artifact and collect content for indexing
    indexed_paths: list[tuple[str, str]] = []  # (path, text_content)
    for art in text_artifacts:
        art_path = art.get("path", "")
        if not art_path:
            continue

        src = Path(art_path)
        if not src.exists():
            continue

        dst = item_dir / src.name
        try:
            raw_bytes = src.read_bytes()
            dst.write_bytes(raw_bytes)
        except OSError:
            logger.warning("Failed to copy artifact %s → %s", src, dst,
                           exc_info=True)
            continue

        try:
            text_content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            text_content = ""
        indexed_paths.append((str(dst), text_content))

    if not indexed_paths:
        return 0

    # Index into taosmd collections via the qmd HTTP API
    if not qmd_base_url:
        logger.debug("qmd base URL not provided — collection indexing skipped")
        return 0

    indexed = 0
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as http_client:
            # 1. Create a collection for this library item
            collection_name = f"library-{item_id[:12]}"
            db_path = str(collections_dir / "library-collections.db")
            title = item.get("title", "Untitled") or "Untitled"

            create_resp = await http_client.post(
                f"{qmd_base_url}/collections",
                json={
                    "dbPath": db_path,
                    "name": collection_name,
                    "metadata": {
                        "title": title,
                        "kind": item.get("kind", ""),
                        "source_url": item.get("source_url", ""),
                        "library_item_id": item_id,
                    },
                },
            )
            if create_resp.status_code >= 400:
                logger.warning(
                    "qmd POST /collections returned %d for item %s: %s",
                    create_resp.status_code, item_id, create_resp.text[:200],
                )
                return 0
            collection_id = create_resp.json().get("id", "")

            if not collection_id:
                logger.warning(
                    "qmd POST /collections returned no id for item %s", item_id,
                )
                return 0

            # 2. Index each text artifact into the collection
            for file_path, text_content in indexed_paths:
                if not text_content.strip():
                    continue
                try:
                    index_resp = await http_client.post(
                        f"{qmd_base_url}/collections/{collection_id}/index",
                        json={
                            "dbPath": db_path,
                            "text": text_content,
                            "metadata": {
                                "source_path": file_path,
                                "library_item_id": item_id,
                                "item_title": title,
                            },
                        },
                    )
                    if index_resp.status_code < 400:
                        indexed += 1
                        logger.debug(
                            "Indexed artifact %s into collection %s",
                            Path(file_path).name, collection_id,
                        )
                    else:
                        logger.warning(
                            "qmd POST /collections/%s/index returned %d",
                            collection_id, index_resp.status_code,
                        )
                except Exception:
                    logger.warning(
                        "qmd index failed for artifact %s in collection %s",
                        file_path, collection_id, exc_info=True,
                    )

            logger.info(
                "Collections handoff for item %s: %d/%d artifacts indexed into %s",
                item_id, indexed, len(indexed_paths), collection_id,
            )

    except ImportError:
        logger.debug("httpx not available — collection indexing skipped")
    except Exception:
        logger.exception(
            "qmd collections API unreachable for item %s", item_id,
        )

    return indexed
