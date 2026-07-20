"""Library collections handoff — writes processed text artifacts to taosmd.

After the ingest pipeline produces text artifacts (extracted text, transcripts,
descriptions), this module hands them off to taosmd collections so agents can
query the content through collection grants.

The design doc (docs/design/library-app.md) says:
  "Collections handoff: write text artifacts into a per-target folder under an
  allowed root, then taosmd collections index; link to project; grants stay
  EXPLICIT"
"""

from __future__ import annotations

import logging
import json
from pathlib import Path

from tinyagentos.library_store import LibraryStore

logger = logging.getLogger(__name__)

# Text artifact kinds that should be indexed into collections
_TEXT_ARTIFACT_KINDS = frozenset({"text", "transcript", "description", "ocr"})


async def handoff_to_collections(
    store: LibraryStore,
    item_id: str,
    collections_dir: Path,
    project_id: str | None = None,
) -> int:
    """Hand off all text artifacts for an item to the taosmd collection index.

    Reads text artifacts from the library store and ingests them into taosmd.
    Returns the number of artifacts successfully handed off.

    The collections_dir is the allowed root (e.g. ``data/collections/``).
    Each library item gets a subfolder named by its id, so a future
    re-index or deletion can target it cleanly.
    """
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

    handed_off = 0
    for art in text_artifacts:
        art_path = art.get("path", "")
        if not art_path:
            continue

        src = Path(art_path)
        if not src.exists():
            continue

        # Copy to collections folder
        dst = item_dir / src.name
        try:
            dst.write_bytes(src.read_bytes())
        except OSError:
            logger.warning("Failed to copy artifact %s → %s", src, dst,
                           exc_info=True)
            continue

        # Ingest into taosmd
        try:
            import taosmd

            text_content = src.read_text(encoding="utf-8", errors="replace")
            await taosmd.ingest(
                text_content,
                agent=f"library-{item_id[:12]}",
                project=project_id,
            )
            handed_off += 1
            logger.debug("Library item %s artifact %s ingested into taosmd",
                         item_id, art["kind"])
        except ImportError:
            logger.debug("taosmd not available — collection indexing skipped")
            # Still count as handed off since file is in place
            handed_off += 1
        except Exception:
            logger.warning(
                "taosmd ingest failed for item %s artifact %s",
                item_id, art["kind"], exc_info=True,
            )

    # Write a manifest so downstream knows what's here
    manifest = {
        "item_id": item_id,
        "title": item.get("title", ""),
        "kind": item.get("kind", ""),
        "source_url": item.get("source_url", ""),
        "created_at": item.get("created_at", 0),
        "artifacts": [
            {"kind": a["kind"], "file": Path(a["path"]).name}
            for a in text_artifacts if a.get("path")
        ],
    }
    manifest_path = item_dir / "manifest.json"
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2))
    except OSError:
        pass

    return handed_off
