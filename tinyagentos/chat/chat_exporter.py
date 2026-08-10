from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

_MAX_MESSAGE_BYTES = 64 * 1024
_DEFAULT_SOURCE = "taos-chat"


class ChatExportError(Exception):
    """Raised when a batch cannot be exported."""


def flatten_body(blocks: list[dict] | None) -> str:
    """Flatten content blocks to plain text."""
    if not blocks:
        return ""
    parts = []
    for block in blocks:
        if isinstance(block, dict):
            text = block.get("text") or block.get("content") or ""
            if text:
                parts.append(str(text))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts)


def _serialized_size(envelope: dict) -> int:
    return len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))


class ChatExporter:
    """Export chat messages to A2A bus import batches.

    Reads messages from a ChatMessageStore and transforms them into the
    envelope format expected by the taOSmd bus import endpoint.

    Identity mapping is explicit: every author_id in the batch must have a
    corresponding handle in identity_map, or the whole batch fails.
    """

    def __init__(
        self,
        message_store: Any,
        identity_map: dict[str, str],
        source: str = _DEFAULT_SOURCE,
        max_message_bytes: int = _MAX_MESSAGE_BYTES,
        file_writer: Callable[[str, bytes], Awaitable[str]] | None = None,
    ) -> None:
        self._msg_store = message_store
        self._identity_map = dict(identity_map)
        self._source = source
        self._max_message_bytes = max_message_bytes
        self._file_writer = file_writer

    async def export_channel(self, channel_id: str) -> list[dict]:
        """Export all non-deleted messages from a channel.

        Returns envelopes ordered by (created_at ASC, id ASC) for
        deterministic, reproducible output.  Raises ChatExportError if any
        author_id is unmapped.
        """
        messages = await self._msg_store.get_all_messages_for_channel(channel_id)
        messages = [m for m in messages if m.get("deleted_at") is None]
        messages.sort(
            key=lambda m: (m.get("created_at") or 0.0, m.get("id") or "")
        )

        batch: list[dict] = []
        exported_ids: set[str] = set()

        for msg in messages:
            envelope = await self._transform_message(msg)
            batch.append(envelope)
            exported_ids.add(envelope["source_id"])

        for envelope in batch:
            reply_to = envelope.get("reply_to")
            if reply_to is not None and reply_to not in exported_ids:
                del envelope["reply_to"]

        return batch

    async def _transform_message(self, msg: dict) -> dict:
        """Transform a single chat message to a bus envelope.

        Raises ChatExportError if author_id is not in identity_map.
        """
        author_id = msg.get("author_id", "")
        handle = self._identity_map.get(author_id)
        if handle is None:
            raise ChatExportError(
                f"unmapped author_id {author_id!r} for message {msg.get('id')!r}"
            )

        content_blocks = msg.get("content_blocks") or []
        body = flatten_body(content_blocks)

        if not body and msg.get("content"):
            body = str(msg["content"])

        if content_blocks and not body.strip():
            raise ChatExportError(
                f"message {msg.get('id')!r} has content_blocks but empty body"
            )

        source_id = msg.get("id", "")

        envelope: dict[str, Any] = {
            "from": handle,
            "thread": msg.get("channel_id", ""),
            "body": body,
            "blocks": content_blocks,
            "ts": msg.get("created_at", 0.0),
            "source": self._source,
            "source_id": source_id,
        }

        thread_id = msg.get("thread_id")
        if thread_id:
            envelope["reply_to"] = thread_id

        if _serialized_size(envelope) > self._max_message_bytes:
            if self._file_writer is None:
                raise ChatExportError(
                    f"message {source_id!r} exceeds {self._max_message_bytes} bytes "
                    f"and no file_writer configured"
                )
            ref = await self._file_writer(source_id, body.encode("utf-8"))
            envelope["body"] = ref
            envelope["blocks"] = []

        return envelope

    async def export_all_channels(self, channel_ids: list[str]) -> list[dict]:
        """Export multiple channels and concatenate the batches."""
        batch: list[dict] = []
        for ch_id in channel_ids:
            batch.extend(await self.export_channel(ch_id))
        return batch
