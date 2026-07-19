"""Tests for Community View endpoints (Milestone F)."""

import pytest


# ---------------------------------------------------------------------------
# community/snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_community_snapshot_empty_project(client):
    """Snapshot returns metadata + empty lists for a project with no tasks."""
    resp = await client.post(
        "/api/projects",
        json={"name": "Test Project", "slug": "test-community", "description": "a test"},
    )
    assert resp.status_code == 200
    pid = resp.json()["id"]

    resp = await client.get(f"/api/projects/{pid}/community/snapshot")
    assert resp.status_code == 200
    body = resp.json()

    assert body["project"]["id"] == pid
    assert body["project"]["name"] == "Test Project"
    assert body["project"]["slug"] == "test-community"
    assert body["project"]["description"] == "a test"
    assert body["project"]["status"] == "active"
    assert isinstance(body["tasks"], list)
    assert len(body["tasks"]) == 0
    assert isinstance(body["status_counts"], dict)
    assert isinstance(body["contributors"], list)
    assert len(body["contributors"]) == 0
    assert isinstance(body["recent_activity"], list)
    assert len(body["recent_activity"]) == 0


@pytest.mark.asyncio
async def test_community_snapshot_with_tasks(client):
    """Snapshot includes allowlisted task fields and status breakdown."""
    resp = await client.post(
        "/api/projects",
        json={"name": "P", "slug": "p-with-tasks"},
    )
    pid = resp.json()["id"]

    # Create tasks in different statuses.
    for i in range(3):
        await client.post(
            f"/api/projects/{pid}/tasks",
            json={"title": f"Task {i}", "priority": i},
        )
    # Claim one task.
    tasks = (await client.get(f"/api/projects/{pid}/tasks")).json()["items"]
    await client.post(
        f"/api/projects/{pid}/tasks/{tasks[0]['id']}/claim",
        json={"claimer_id": "agent-1"},
    )
    # Close another.
    await client.post(
        f"/api/projects/{pid}/tasks/{tasks[1]['id']}/close",
        json={"closed_by": "agent-1"},
    )

    resp = await client.get(f"/api/projects/{pid}/community/snapshot")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["tasks"]) == 3

    # Status breakdown.
    sc = body["status_counts"]
    assert sc.get("open", 0) == 1
    assert sc.get("claimed", 0) == 1
    assert sc.get("closed", 0) == 1

    # Sanitised task fields — only allowlisted keys.
    for t in body["tasks"]:
        assert "body" not in t  # body is NOT allowlisted
        assert "claimed_by" in t
        assert "id" in t
        assert "title" in t
        assert "status" in t

    # Leaderboard — contributors should have claim + close events.
    assert len(body["contributors"]) > 0
    contributor = body["contributors"][0]
    assert "actor" in contributor
    assert "claims" in contributor
    assert "closes" in contributor
    assert "total" in contributor


@pytest.mark.asyncio
async def test_community_snapshot_not_found(client):
    """404 for a nonexistent project."""
    resp = await client.get("/api/projects/nonexistent/community/snapshot")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# community/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_community_stats(client):
    """Stats endpoint returns status counts + leaderboard without full task list."""
    resp = await client.post(
        "/api/projects",
        json={"name": "Stats Project", "slug": "stats-proj"},
    )
    pid = resp.json()["id"]

    # Create + claim + close tasks to generate audit events.
    for i in range(2):
        await client.post(
            f"/api/projects/{pid}/tasks",
            json={"title": f"S{i}"},
        )
    tasks = (await client.get(f"/api/projects/{pid}/tasks")).json()["items"]
    await client.post(
        f"/api/projects/{pid}/tasks/{tasks[0]['id']}/claim",
        json={"claimer_id": "claimer-a"},
    )
    await client.post(
        f"/api/projects/{pid}/tasks/{tasks[0]['id']}/close",
        json={"closed_by": "claimer-a"},
    )

    resp = await client.get(f"/api/projects/{pid}/community/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["project_id"] == pid
    assert body["project_name"] == "Stats Project"
    assert isinstance(body["status_counts"], dict)
    assert isinstance(body["leaderboard"], list)

    # Stats should NOT include the full task list.
    assert "tasks" not in body

    # Leaderboard should have at least one contributor.
    if len(body["leaderboard"]) > 0:
        lb = body["leaderboard"][0]
        assert "actor" in lb
        assert "claims" in lb
        assert "closes" in lb
        assert "total" in lb


@pytest.mark.asyncio
async def test_community_stats_not_found(client):
    """404 for a nonexistent project."""
    resp = await client.get("/api/projects/nonexistent/community/stats")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Leaderboard rollup unit test (no HTTP — pure function)
# ---------------------------------------------------------------------------


def test_build_leaderboard():
    """Unit test for the leaderboard aggregation function."""
    from tinyagentos.routes.community import _build_leaderboard

    events = [
        {"actor": "agent-1", "event": "task.claimed", "task_id": "t1"},
        {"actor": "agent-1", "event": "task.closed", "task_id": "t1"},
        {"actor": "agent-2", "event": "task.claimed", "task_id": "t2"},
        {"actor": "agent-1", "event": "task.claimed", "task_id": "t3"},
        {"actor": "agent-3", "event": "claimed", "task_id": "t4"},
    ]

    lb = _build_leaderboard(events)

    # Sorted by total descending.
    assert len(lb) == 3
    assert lb[0]["actor"] == "agent-1"
    assert lb[0]["claims"] == 2
    assert lb[0]["closes"] == 1
    assert lb[0]["total"] == 3

    # agent-2 and agent-3 are tied at total=1 — order within ties is
    # insertion-order stable, so both orderings are valid.
    tied = {lb[1]["actor"], lb[2]["actor"]}
    assert tied == {"agent-2", "agent-3"}
    for entry in (lb[1], lb[2]):
        assert entry["claims"] == 1
        assert entry["closes"] == 0
        assert entry["total"] == 1


def test_build_leaderboard_empty():
    """Empty events give empty leaderboard."""
    from tinyagentos.routes.community import _build_leaderboard

    assert _build_leaderboard([]) == []


def test_build_leaderboard_ignores_unknown_events():
    """Events other than claim/close are ignored."""
    from tinyagentos.routes.community import _build_leaderboard

    events = [
        {"actor": "agent-1", "event": "task.created", "task_id": "t1"},
        {"actor": "agent-2", "event": "task.assigned", "task_id": "t1"},
        {"actor": "agent-1", "event": "task.claimed", "task_id": "t2"},
    ]
    lb = _build_leaderboard(events)
    assert len(lb) == 1
    assert lb[0]["actor"] == "agent-1"
    assert lb[0]["claims"] == 1
    assert lb[0]["closes"] == 0
    assert lb[0]["total"] == 1
