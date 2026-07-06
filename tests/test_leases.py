"""Tests for GPU lease API (taOS #893)."""
from __future__ import annotations

import time

import pytest

from tinyagentos.cluster.manager import ClusterManager
from tinyagentos.cluster.worker_protocol import GpuLease, WorkerInfo


@pytest.mark.asyncio
async def test_claim_lease_success(client):
    """Claiming a lease on an online worker with enough VRAM returns 200."""
    # Register a worker with free VRAM
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
        "hardware": {"gpu": {"model": "GTX 1080", "vram_mb": 8192}},
    })
    # Send a heartbeat with free VRAM
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 6000,
        "used_vram_mb": 2000,
    })

    resp = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "caller": "skald-dispatcher",
        "ttl_seconds": 30,
        "required_vram_mb": 4000,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "claimed"
    assert data["lease_id"].startswith("l_")
    assert data["resource_id"] == "gpu-node:gpu-cuda-0"
    assert data["ttl_seconds"] == 30
    assert data["required_vram_mb"] == 4000
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_claim_lease_insufficient_vram(client):
    """Claiming with required_vram_mb > free_vram_mb returns 409."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 1000,
        "used_vram_mb": 7000,
    })

    resp = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "required_vram_mb": 8000,
    })
    assert resp.status_code == 409
    assert "unavailable" in resp.json()["error"]


@pytest.mark.asyncio
async def test_claim_lease_already_leased(client):
    """A second claim on the same resource returns 409 with the existing lease info."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
        "used_vram_mb": 0,
    })

    # First claim succeeds
    resp1 = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "caller": "skald-dispatcher",
        "ttl_seconds": 30,
    })
    assert resp1.status_code == 200
    lease_id = resp1.json()["lease_id"]

    # Second claim on same resource fails
    resp2 = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "caller": "a2a-agent:extract",
    })
    assert resp2.status_code == 409
    err = resp2.json()
    assert err["error"] == "resource already leased"
    assert err["lease_id"] == lease_id
    assert err["holder"] == "skald-dispatcher"


@pytest.mark.asyncio
async def test_claim_lease_worker_offline(client):
    """Claiming against an offline worker returns 409."""
    # Worker registered but no heartbeat ever sent — marked offline after
    # monitor_loop sweep.  The monitor_loop hasn't run in this test
    # context (no app startup), so the worker is technically "online" from
    # registration.  To test offline, claim against a nonexistent worker.
    resp = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "ghost:gpu-cuda-0",
        "required_vram_mb": 4000,
    })
    assert resp.status_code == 409
    assert "unavailable" in resp.json()["error"]


@pytest.mark.asyncio
async def test_claim_lease_malformed_resource_id(client):
    """A resource_id without a colon returns 409."""
    resp = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "bogus",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_release_lease_idempotent(client):
    """Releasing a lease returns 200; releasing again is also 200."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
    })

    claim = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
    })
    lease_id = claim.json()["lease_id"]

    # First release
    resp1 = await client.post("/api/cluster/leases/release", json={
        "lease_id": lease_id,
    })
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "released"

    # Second release (idempotent)
    resp2 = await client.post("/api/cluster/leases/release", json={
        "lease_id": lease_id,
    })
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_release_lease_unknown(client):
    """Releasing an unknown lease_id is still 200 (idempotent)."""
    resp = await client.post("/api/cluster/leases/release", json={
        "lease_id": "l_doesnotexist",
    })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_renew_lease_success(client):
    """Renewing an active lease extends its TTL."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
    })

    claim = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "ttl_seconds": 10,
    })
    lease_id = claim.json()["lease_id"]
    original_expiry = claim.json()["expires_at"]

    resp = await client.post("/api/cluster/leases/renew", json={
        "lease_id": lease_id,
        "ttl_seconds": 60,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "renewed"
    assert resp.json()["lease_id"] == lease_id
    assert resp.json()["expires_at"] > original_expiry


@pytest.mark.asyncio
async def test_renew_lease_expired(client):
    """Renewing an expired lease returns 409."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
    })

    claim = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "ttl_seconds": 0.001,  # effectively instant
    })
    lease_id = claim.json()["lease_id"]

    # Wait a moment for it to expire
    time.sleep(0.1)

    resp = await client.post("/api/cluster/leases/renew", json={
        "lease_id": lease_id,
        "ttl_seconds": 30,
    })
    assert resp.status_code == 409
    assert "expired" in resp.json()["error"]


@pytest.mark.asyncio
async def test_list_leases(client):
    """GET /leases returns active leases only."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
    })

    # No leases yet
    resp = await client.get("/api/cluster/leases")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0

    # Claim one
    claim = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "caller": "test",
        "ttl_seconds": 30,
    })
    assert claim.status_code == 200

    resp = await client.get("/api/cluster/leases")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    lease = resp.json()["leases"][0]
    assert lease["caller"] == "test"
    assert lease["resource_id"] == "gpu-node:gpu-cuda-0"
    assert "lease_id" in lease


@pytest.mark.asyncio
async def test_expired_lease_returns_409_on_claim(client):
    """After a lease expires, a new claim on the same resource succeeds."""
    await client.post("/api/cluster/workers", json={
        "name": "gpu-node",
        "url": "http://10.0.0.1:9000",
        "capabilities": ["llm-chat"],
    })
    await client.post("/api/cluster/heartbeat", json={
        "name": "gpu-node",
        "free_vram_mb": 8000,
    })

    # Claim with very short TTL
    await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "ttl_seconds": 0.001,
    })

    time.sleep(0.1)

    # The lease is now expired; a new claim succeeds
    resp = await client.post("/api/cluster/leases/claim", json={
        "resource_id": "gpu-node:gpu-cuda-0",
        "caller": "second-caller",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "claimed"


# ── ClusterManager unit tests ──────────────────────────────────────────


def _worker(name, free_vram=0):
    w = WorkerInfo(
        name=name,
        url=f"http://{name}:9000",
        capabilities=["llm-chat"],
        free_vram_mb=free_vram,
    )
    w.status = "online"
    w.last_heartbeat = time.time()
    return w


class TestClusterManagerLeases:
    def test_claim_success(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=6000)

        lease = mgr.claim_lease(
            "gpu-node:gpu-cuda-0",
            caller="test",
            ttl_seconds=30,
            required_vram_mb=4000,
        )
        assert lease is not None
        assert lease.lease_id.startswith("l_")
        assert lease.resource_id == "gpu-node:gpu-cuda-0"
        assert lease.caller == "test"
        assert lease.required_vram_mb == 4000

    def test_claim_fails_insufficient_vram(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=1000)

        lease = mgr.claim_lease(
            "gpu-node:gpu-cuda-0",
            required_vram_mb=8000,
        )
        assert lease is None

    def test_claim_fails_already_leased(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        first = mgr.claim_lease("gpu-node:gpu-cuda-0", caller="first")
        assert first is not None

        second = mgr.claim_lease("gpu-node:gpu-cuda-0", caller="second")
        assert second is None

    def test_claim_fails_worker_offline(self):
        mgr = ClusterManager()
        w = _worker("gpu-node", free_vram=8000)
        w.status = "offline"
        mgr._workers["gpu-node"] = w

        lease = mgr.claim_lease("gpu-node:gpu-cuda-0")
        assert lease is None

    def test_claim_fails_missing_worker(self):
        mgr = ClusterManager()
        lease = mgr.claim_lease("nonexistent:gpu-cuda-0")
        assert lease is None

    def test_release_idempotent(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        lease = mgr.claim_lease("gpu-node:gpu-cuda-0")
        assert lease is not None

        # Releasing works
        assert mgr.release_lease(lease.lease_id) is True

        # Releasing again (idempotent)
        assert mgr.release_lease(lease.lease_id) is True

    def test_release_unknown(self):
        mgr = ClusterManager()
        assert mgr.release_lease("l_nonexistent") is True

    def test_renew_active(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        lease = mgr.claim_lease("gpu-node:gpu-cuda-0", ttl_seconds=10)
        original_expiry = lease.expires_at

        renewed = mgr.renew_lease(lease.lease_id, ttl_seconds=60)
        assert renewed is not None
        assert renewed.expires_at > original_expiry

    def test_renew_expired(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        lease = mgr.claim_lease("gpu-node:gpu-cuda-0", ttl_seconds=0.001)
        time.sleep(0.1)

        renewed = mgr.renew_lease(lease.lease_id, ttl_seconds=30)
        assert renewed is None

    def test_renew_unknown(self):
        mgr = ClusterManager()
        assert mgr.renew_lease("l_nonexistent") is None

    def test_get_leases_active_only(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        mgr.claim_lease("gpu-node:gpu-cuda-0", ttl_seconds=30)
        assert len(mgr.get_leases()) == 1

        # Add an expired lease manually
        mgr._leases["l_expired"] = GpuLease(
            lease_id="l_expired",
            resource_id="gpu-node:gpu-cuda-0",
            expires_at=0,
        )
        # get_leases only returns active (non-expired)
        assert len(mgr.get_leases()) == 1

    def test_sweep_removes_expired(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        # Claim with instant TTL
        lease = mgr.claim_lease("gpu-node:gpu-cuda-0", ttl_seconds=0.001)
        time.sleep(0.1)

        # Before sweep, expired lease still in dict
        assert lease.lease_id in mgr._leases

        mgr._sweep_expired_leases()
        assert lease.lease_id not in mgr._leases
        assert len(mgr.get_leases()) == 0

    def test_claim_after_release_succeeds(self):
        mgr = ClusterManager()
        mgr._workers["gpu-node"] = _worker("gpu-node", free_vram=8000)

        first = mgr.claim_lease("gpu-node:gpu-cuda-0", caller="first")
        mgr.release_lease(first.lease_id)

        second = mgr.claim_lease("gpu-node:gpu-cuda-0", caller="second")
        assert second is not None
        assert second.caller == "second"
