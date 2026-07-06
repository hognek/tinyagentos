"""Tests for WorkerInfo KV cache quant plumbing."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from tinyagentos.cluster.worker_protocol import WorkerInfo
from tinyagentos.cluster.manager import ClusterManager


# ---------------------------------------------------------------------------
# WorkerInfo field defaults
# ---------------------------------------------------------------------------

class TestWorkerInfoKvQuantDefault:
    def test_default_is_fp16_only(self):
        w = WorkerInfo(name="w", url="http://localhost:9000")
        assert w.kv_cache_quant_support == ["fp16"]

    def test_custom_value_stored(self):
        w = WorkerInfo(
            name="w",
            url="http://localhost:9000",
            kv_cache_quant_support=["fp16", "turboquant-k3v2"],
        )
        assert w.kv_cache_quant_support == ["fp16", "turboquant-k3v2"]

    def test_serialises_via_asdict(self):
        w = WorkerInfo(
            name="w",
            url="http://localhost:9000",
            kv_cache_quant_support=["fp16", "int4-kv"],
        )
        d = asdict(w)
        assert "kv_cache_quant_support" in d
        assert d["kv_cache_quant_support"] == ["fp16", "int4-kv"]

    def test_roundtrip_default(self):
        w = WorkerInfo(name="w", url="http://localhost:9000")
        d = asdict(w)
        # Reconstruct from the serialised form; kv_cache_quant_support must
        # survive the round-trip.
        w2 = WorkerInfo(**{k: v for k, v in d.items()})
        assert w2.kv_cache_quant_support == ["fp16"]

    def test_roundtrip_custom(self):
        original = ["fp16", "turboquant-k3v2"]
        w = WorkerInfo(
            name="w",
            url="http://localhost:9000",
            kv_cache_quant_support=original,
        )
        d = asdict(w)
        w2 = WorkerInfo(**{k: v for k, v in d.items()})
        assert w2.kv_cache_quant_support == original


# ---------------------------------------------------------------------------
# ClusterManager.kv_quant_union
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestKvQuantUnion:
    async def _register(self, mgr: ClusterManager, name: str, quant: list[str]) -> None:
        w = WorkerInfo(
            name=name,
            url=f"http://localhost:900{name[-1]}",
            kv_cache_quant_support=quant,
        )
        await mgr.register_worker(w)

    async def test_empty_cluster_returns_fp16(self):
        mgr = ClusterManager()
        assert mgr.kv_quant_union() == ["fp16"]

    async def test_all_fp16_cluster_returns_fp16(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1", ["fp16"])
        await self._register(mgr, "w2", ["fp16"])
        assert mgr.kv_quant_union() == ["fp16"]

    async def test_mixed_cluster_returns_union(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1", ["fp16"])
        await self._register(mgr, "w2", ["fp16", "turboquant-k3v2"])
        result = mgr.kv_quant_union()
        assert "fp16" in result
        assert "turboquant-k3v2" in result
        assert len(result) == 2

    async def test_offline_worker_excluded(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1", ["fp16", "turboquant-k3v2"])
        # Mark it offline
        mgr._workers["w1"].status = "offline"
        # Without an online worker only the baseline fp16 is returned.
        assert mgr.kv_quant_union() == ["fp16"]

    async def test_result_is_sorted(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1", ["turboquant-k3v2", "fp16"])
        result = mgr.kv_quant_union()
        assert result == sorted(result)

    async def test_fp16_always_present(self):
        """fp16 is the baseline — always in the union even if no worker lists it."""
        mgr = ClusterManager()
        # Simulate a hypothetical backend that only lists a new type.
        await self._register(mgr, "w1", ["turboquant-k3v2"])
        result = mgr.kv_quant_union()
        assert "fp16" in result

    async def test_heartbeat_updates_kv_quant(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1", ["fp16"])
        assert mgr.kv_quant_union() == ["fp16"]

        # Worker sends an updated heartbeat (e.g. after a backend upgrade).
        mgr.heartbeat("w1", kv_cache_quant_support=["fp16", "turboquant-k3v2"])
        result = mgr.kv_quant_union()
        assert "turboquant-k3v2" in result


# ---------------------------------------------------------------------------
# WorkerInfo VRAM fields (taOS #894 slice)
# ---------------------------------------------------------------------------

class TestWorkerInfoVramDefaults:
    def test_default_vram_is_none(self):
        """Default is None (unknown), not 0 -- a worker with no VRAM probe
        (e.g. RK3588, Apple Silicon, CPU-only) must not read as 0 free."""
        w = WorkerInfo(name="w", url="http://localhost:9000")
        assert w.free_vram_mb is None
        assert w.used_vram_mb is None

    def test_vram_stored_and_serialised(self):
        w = WorkerInfo(
            name="w",
            url="http://localhost:9000",
            free_vram_mb=8192,
            used_vram_mb=4096,
        )
        assert w.free_vram_mb == 8192
        assert w.used_vram_mb == 4096
        d = asdict(w)
        assert d["free_vram_mb"] == 8192
        assert d["used_vram_mb"] == 4096

    def test_vram_roundtrip(self):
        w = WorkerInfo(
            name="w",
            url="http://localhost:9000",
            free_vram_mb=12288,
            used_vram_mb=2048,
        )
        d = asdict(w)
        w2 = WorkerInfo(**{k: v for k, v in d.items() if not isinstance(v, bytes)})
        assert w2.free_vram_mb == 12288
        assert w2.used_vram_mb == 2048


# ---------------------------------------------------------------------------
# ClusterManager heartbeat VRAM storage (taOS #894 slice)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHeartbeatVram:
    async def _register(self, mgr: ClusterManager, name: str) -> WorkerInfo:
        w = WorkerInfo(name=name, url=f"http://localhost:900{name[-1]}")
        await mgr.register_worker(w)
        return w

    async def test_heartbeat_stores_vram(self):
        mgr = ClusterManager()
        await self._register(mgr, "w1")
        mgr.heartbeat("w1", free_vram_mb=8192, used_vram_mb=4096)
        w = mgr.get_worker("w1")
        assert w.free_vram_mb == 8192
        assert w.used_vram_mb == 4096

    async def test_heartbeat_omitting_vram_preserves_prior(self):
        """Legacy heartbeat without VRAM fields leaves stored values unchanged."""
        mgr = ClusterManager()
        await self._register(mgr, "w1")
        mgr.heartbeat("w1", free_vram_mb=12288, used_vram_mb=4096)
        # Sparse heartbeat — only load + models, no VRAM fields
        mgr.heartbeat("w1", load=0.5, models=["phi3"])
        w = mgr.get_worker("w1")
        assert w.free_vram_mb == 12288
        assert w.used_vram_mb == 4096
        assert w.load == 0.5
        assert w.models == ["phi3"]

    async def test_vram_zero_is_stored(self):
        """Explicit zero is stored (distinct from 'not sent' which preserves prior)."""
        mgr = ClusterManager()
        await self._register(mgr, "w1")
        mgr.heartbeat("w1", free_vram_mb=8192, used_vram_mb=4096)
        mgr.heartbeat("w1", free_vram_mb=0, used_vram_mb=0)
        w = mgr.get_worker("w1")
        assert w.free_vram_mb == 0
        assert w.used_vram_mb == 0
