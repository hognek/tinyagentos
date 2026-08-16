"""Sweep test for model-catalog manifest integrity.

Ensures every variant in app-catalog/models/*/manifest.yaml satisfies the
resolver schema contract: non-empty backends with known targets, a 64-char
lowercase hex sha256, a non-empty https download_url, and a positive size_mb.

A per-manifest allowlist tracks pre-existing sha256 debt until the catalog
is filled in.  The intent is zero entries.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import yaml

# Known target enums -- the resolver only accepts values produced by
# hardware_to_targets in tinyagentos/cluster/capabilities.py. DERIVED from
# that source file rather than hardcoded: a literal copy silently drifts the
# moment a new backend target lands (adding "hailo" there would have made
# this sweep bounce the very PR that introduced it).
_CAPABILITIES_SRC = (
    Path(__file__).resolve().parent.parent
    / "tinyagentos" / "cluster" / "capabilities.py"
).read_text()
KNOWN_TARGETS = set(
    re.findall(r'targets\.append\(\s*"([a-z0-9-]+)"', _CAPABILITIES_SRC)
) | set(
    # conditional-expression appends: targets.append("a" if cond else "b")
    t
    for pair in re.findall(
        r'targets\.append\(\s*"([a-z0-9-]+)" if .+ else "([a-z0-9-]+)"',
        _CAPABILITIES_SRC,
    )
    for t in pair
)
assert len(KNOWN_TARGETS) >= 6, (
    f"target derivation collapsed ({sorted(KNOWN_TARGETS)}) - "
    "capabilities.py changed shape; fix the extraction, do not hardcode"
)

_SHA256_ALLOWLIST: set[str] = set()

# Known-fabricated sha256 placeholders that must never appear in a real
# manifest.  This class of error has recurred twice (#2425, #2451) because
# an LLM-generated placeholder digest looks hex-valid.  A denylist gate is
# the only reliable stop -- a prompt did not stop it, a gate will.
_FABRICATED_SHA256_DENYLIST: set[str] = {
    # llama-3.2-1b/a8w4 -- blocked in PR #2425
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
    # qwen3-1.7b/a8w4 -- blocked in PR #2425
    "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5",
}

# Variant-level keys that belong inside hardware_tiers, not as stray
# siblings.  If they appear at variant level, hardware_tiers parsed as null
# and the model is silently treated as unrestricted.
_TIER_KEY_RE = re.compile(r"^(arm|x86|cpu)-")


def test_model_manifests_are_resolvable_and_integrity_pinned():
    root = Path(__file__).resolve().parent.parent / "app-catalog"
    errors: list[str] = []
    for path in sorted(glob.glob(str(root / "models" / "*" / "manifest.yaml"))):
        with open(path) as f:
            manifest = yaml.safe_load(f)
        mid = manifest.get("id") or Path(path).parent.name
        allowed_sha256 = mid in _SHA256_ALLOWLIST
        for variant in manifest.get("variants") or []:
            vid = variant.get("id", "<missing>")
            # Rule 1: requires.backends non-empty; every entry has non-empty
            # targets whose values are drawn from the known enum set.
            backends = ((variant.get("requires") or {}).get("backends")) or []
            if not backends:
                errors.append(f"{mid}/{vid}: requires.backends is empty")
                continue
            for backend in backends:
                targets = backend.get("targets") or []
                if not targets:
                    errors.append(
                        f"{mid}/{vid}: backend {backend.get('id')!r} has empty targets"
                    )
                else:
                    unknown = [t for t in targets if t not in KNOWN_TARGETS]
                    if unknown:
                        errors.append(
                            f"{mid}/{vid}: backend {backend.get('id')!r} has unknown targets {unknown}"
                        )
            # Rule 2: sha256 must be a 64-char lowercase hex string.  It must
            # also not be a known-fabricated placeholder digest (denylist --
            # this class has recurred twice and a prompt did not stop it).
            sha256 = variant.get("sha256")
            if sha256 in _FABRICATED_SHA256_DENYLIST:
                errors.append(
                    f"{mid}/{vid}: sha256 {sha256[:16]}... is a known-fabricated "
                    f"placeholder (blocked in PR #2425)"
                )
            elif not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
                if not allowed_sha256:
                    errors.append(
                        f"{mid}/{vid}: sha256 must be a 64-char lowercase hex string (got {sha256!r})"
                    )
            # Rule 3: download_url must be a non-empty https URL.
            url = variant.get("download_url", "")
            if not url or not url.startswith("https://"):
                errors.append(
                    f"{mid}/{vid}: download_url must be a non-empty https URL (got {url!r})"
                )
            # Rule 4: size_mb must be a positive int.
            size_mb = variant.get("size_mb")
            if not isinstance(size_mb, int) or size_mb <= 0:
                errors.append(
                    f"{mid}/{vid}: size_mb must be a positive int (got {size_mb!r})"
                )
            # Rule 5: tier keys (^(arm|x86|cpu)-) must nest under
            # hardware_tiers, not sit as stray siblings.  If
            # hardware_tiers is present it must be a non-empty mapping.
            stray_tier_keys = [
                k for k in variant if _TIER_KEY_RE.match(k)
            ]
            if stray_tier_keys:
                errors.append(
                    f"{mid}/{vid}: tier key must nest under hardware_tiers; "
                    f"stray variant-level keys {stray_tier_keys}"
                )
            if "hardware_tiers" in variant:
                # hardware_tiers is read at MANIFEST scope only
                # (cluster/capabilities.py, config.py); a variant-level block
                # is dead data that looks live -- exactly how PR #2453's
                # regression slipped past a variant-shape check.
                errors.append(
                    f"{mid}/{vid}: hardware_tiers must sit at manifest scope, "
                    f"not inside a variant (nothing reads it here)"
                )
        # Rule 6: manifest-scope hardware_tiers, when present, must be a
        # non-empty mapping, and tier keys must not sit stray at manifest
        # level either.
        stray_manifest_tier_keys = [
            k for k in manifest if _TIER_KEY_RE.match(k)
        ]
        if stray_manifest_tier_keys:
            errors.append(
                f"{mid}: tier key must nest under hardware_tiers; "
                f"stray manifest-level keys {stray_manifest_tier_keys}"
            )
        if "hardware_tiers" in manifest:
            hw_tiers = manifest["hardware_tiers"]
            if not isinstance(hw_tiers, dict) or not hw_tiers:
                errors.append(
                    f"{mid}: hardware_tiers present but not a non-empty "
                    f"mapping (got {hw_tiers!r})"
                )
    assert errors == [], (
        "model manifest integrity failures:\n" + "\n".join(errors)
    )
