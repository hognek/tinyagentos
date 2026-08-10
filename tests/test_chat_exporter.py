from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import pytest_asyncio

from tinyagentos.chat.chat_exporter import ChatExportError, ChatExporter, flatten_body
from tinyagentos.chat.message_store import ChatMessageStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def store(tmp_path):
    s = ChatMessageStore(tmp_path / "chat.db")
    await s.init()
    yield s
    await s.close()


def _make_file_writer(root: Path):
    async def writer(source_id: str, content: bytes) -> str:
        dest = root / "chat-export" / f"{source_id}.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return f"chat-export/{source_id}.txt"

    return writer


def _identity_map(user_ids: list[str], agent_ids: list[str] | None = None) -> dict[str, str]:
    m: dict[str, str] = {}
    for uid in user_ids:
        m[uid] = f"@{uid}"
    for aid in (agent_ids or []):
        m[aid] = f"@{aid}"
    return m


# ---------------------------------------------------------------------------
# flatten_body unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flatten_empty_blocks():
    assert flatten_body([]) == ""
    assert flatten_body(None) == ""


@pytest.mark.asyncio
async def test_flatten_text_blocks():
    blocks = [
        {"type": "paragraph", "text": "Hello"},
        {"type": "code", "lang": "py", "text": "print(1)"},
    ]
    assert flatten_body(blocks) == "Hello\nprint(1)"


@pytest.mark.asyncio
async def test_flatten_skips_empty_text():
    blocks = [
        {"type": "paragraph", "text": "Hello"},
        {"type": "image", "url": "http://x/img.png"},
        {"type": "paragraph", "text": ""},
    ]
    assert flatten_body(blocks) == "Hello"


# ---------------------------------------------------------------------------
# Exporter integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_channel_produces_valid_batch(store, tmp_path):
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="hello",
        content_blocks=[{"type": "paragraph", "text": "hello"}],
    )
    await store.send_message(
        channel_id="ch1",
        author_id="agent-1",
        author_type="agent",
        content="hi",
        content_blocks=[{"type": "paragraph", "text": "hi"}],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"], ["agent-1"]),
    )
    batch = await exporter.export_channel("ch1")

    assert len(batch) == 2
    for env in batch:
        assert env["from"]
        assert env["thread"] == "ch1"
        assert env["ts"] > 0
        assert env["source"] == "taos-chat"
        assert env["source_id"]
        assert isinstance(env["blocks"], list)


@pytest.mark.asyncio
async def test_every_message_has_non_empty_body(store):
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="",
        content_blocks=[{"type": "paragraph", "text": "blocks present"}],
    )
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="plain text",
        content_blocks=[],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_channel("ch1")
    assert len(batch) == 2
    for env in batch:
        assert env["body"] != ""


@pytest.mark.asyncio
async def test_unmapped_author_fails_whole_batch(store):
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="first",
    )
    await store.send_message(
        channel_id="ch1",
        author_id="unknown-user",
        author_type="user",
        content="second",
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    with pytest.raises(ChatExportError, match="unmapped author_id 'unknown-user'"):
        await exporter.export_channel("ch1")


@pytest.mark.asyncio
async def test_reexport_produces_byte_identical_output(store, tmp_path):
    for i in range(3):
        await store.send_message(
            channel_id="ch1",
            author_id="user1",
            author_type="user",
            content=f"msg{i}",
            content_blocks=[{"type": "paragraph", "text": f"msg{i}"}],
        )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch1 = await exporter.export_channel("ch1")
    batch2 = await exporter.export_channel("ch1")

    assert json.dumps(batch1, sort_keys=True, ensure_ascii=False) == json.dumps(
        batch2, sort_keys=True, ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_oversized_content_becomes_ref(store, tmp_path):
    big_text = "x" * 100_000
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content=big_text,
        content_blocks=[{"type": "paragraph", "text": big_text}],
    )

    writer = _make_file_writer(tmp_path)
    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
        file_writer=writer,
    )
    batch = await exporter.export_channel("ch1")
    assert len(batch) == 1
    env = batch[0]
    assert env["blocks"] == []
    assert "chat-export/" in env["body"]
    assert env["body"].endswith(".txt")
    written = (tmp_path / env["body"]).read_bytes()
    assert written.decode("utf-8") == big_text


@pytest.mark.asyncio
async def test_thread_ordering_preserved(store):
    ts = time.time()
    for i in range(3):
        await store.send_message(
            channel_id="ch1",
            author_id="user1",
            author_type="user",
            content=f"msg{i}",
            content_blocks=[{"type": "paragraph", "text": f"msg{i}"}],
        )
        await store._db.execute(
            "UPDATE chat_messages SET created_at = ? WHERE id = (SELECT id FROM chat_messages ORDER BY created_at DESC LIMIT 1)",
            (ts,),
        )
        await store._db.commit()

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch1 = await exporter.export_channel("ch1")
    batch2 = await exporter.export_channel("ch1")
    ids1 = [e["source_id"] for e in batch1]
    ids2 = [e["source_id"] for e in batch2]
    assert ids1 == ids2
    assert len(ids1) == 3


@pytest.mark.asyncio
async def test_reply_to_relationships_preserved(store):
    parent = await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="parent",
        content_blocks=[{"type": "paragraph", "text": "parent"}],
    )
    reply = await store.send_message(
        channel_id="ch1",
        author_id="user2",
        author_type="user",
        content="reply",
        content_blocks=[{"type": "paragraph", "text": "reply"}],
        thread_id=parent["id"],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1", "user2"]),
    )
    batch = await exporter.export_channel("ch1")
    reply_env = next(e for e in batch if e["source_id"] == reply["id"])
    assert reply_env.get("reply_to") == parent["id"]
    parent_env = next(e for e in batch if e["source_id"] == parent["id"])
    assert "reply_to" not in parent_env


@pytest.mark.asyncio
async def test_deleted_parent_omits_reply_to(store):
    parent = await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="parent",
        content_blocks=[{"type": "paragraph", "text": "parent"}],
    )
    await store.soft_delete_message(parent["id"])
    reply = await store.send_message(
        channel_id="ch1",
        author_id="user2",
        author_type="user",
        content="reply",
        content_blocks=[{"type": "paragraph", "text": "reply"}],
        thread_id=parent["id"],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1", "user2"]),
    )
    batch = await exporter.export_channel("ch1")
    reply_env = next(e for e in batch if e["source_id"] == reply["id"])
    assert "reply_to" not in reply_env


@pytest.mark.asyncio
async def test_export_all_channels(store):
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="ch1-msg",
        content_blocks=[{"type": "paragraph", "text": "ch1-msg"}],
    )
    await store.send_message(
        channel_id="ch2",
        author_id="user1",
        author_type="user",
        content="ch2-msg",
        content_blocks=[{"type": "paragraph", "text": "ch2-msg"}],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_all_channels(["ch1", "ch2"])
    assert len(batch) == 2
    threads = {e["thread"] for e in batch}
    assert threads == {"ch1", "ch2"}


@pytest.mark.asyncio
async def test_blocks_preserved_in_envelope(store):
    blocks = [
        {"type": "paragraph", "text": "line1"},
        {"type": "code", "lang": "python", "text": "print(1)"},
    ]
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="line1\nprint(1)",
        content_blocks=blocks,
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_channel("ch1")
    assert batch[0]["blocks"] == blocks


@pytest.mark.asyncio
async def test_ts_preserved(store):
    msg = await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="hello",
        content_blocks=[{"type": "paragraph", "text": "hello"}],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_channel("ch1")
    assert batch[0]["ts"] == msg["created_at"]


@pytest.mark.asyncio
async def test_source_id_is_original_message_id(store):
    msg = await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="hello",
        content_blocks=[{"type": "paragraph", "text": "hello"}],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_channel("ch1")
    assert batch[0]["source_id"] == msg["id"]


@pytest.mark.asyncio
async def test_custom_source_identifier(store):
    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
        source="my-custom-source",
    )
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="hello",
        content_blocks=[{"type": "paragraph", "text": "hello"}],
    )
    batch = await exporter.export_channel("ch1")
    assert batch[0]["source"] == "my-custom-source"


@pytest.mark.asyncio
async def test_empty_body_when_no_content(store):
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content="",
        content_blocks=[],
    )

    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
    )
    batch = await exporter.export_channel("ch1")
    assert batch[0]["body"] == ""


@pytest.mark.asyncio
async def test_file_writer_receives_utf8_body(store, tmp_path):
    text = "héllo wörld " * 10_000
    await store.send_message(
        channel_id="ch1",
        author_id="user1",
        author_type="user",
        content=text,
        content_blocks=[{"type": "paragraph", "text": text}],
    )

    writer = _make_file_writer(tmp_path)
    exporter = ChatExporter(
        message_store=store,
        identity_map=_identity_map(["user1"]),
        file_writer=writer,
    )
    batch = await exporter.export_channel("ch1")
    ref = batch[0]["body"]
    assert ref.startswith("chat-export/")
    assert ref.endswith(".txt")
    written = (tmp_path / ref).read_bytes()
    assert written.decode("utf-8") == text
