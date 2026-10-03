/**
 * Tests for upstream release detection in the Store updates tab.
 *
 * Docker-image apps get a daily, cached upstream check
 * (upstream_versions.py). When the registry tag is newer than the
 * catalog pin (the stale-pin case: SearXNG pins 2024.12.0 while
 * upstream ships 2026.10.2), the app must appear in the "updates"
 * tab with the version delta, even though the catalog pin itself
 * never changed.
 *
 * This suite verifies:
 *   - The catalog endpoint's upstream fields are normalized on mount.
 *   - An installed docker app with upstream_update_available=true
 *     appears in the updates tab showing the version delta.
 *   - Unknown upstream state (null) never reads as an update.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { StoreApp } from "./index";

interface CatalogAppPayload {
  id: string;
  name: string;
  type: string;
  category: string;
  version: string;
  description: string;
  installed: boolean;
  update_available: boolean;
  upstream_version: string | null;
  upstream_update_available: boolean | null;
  upstream_checked_at: number | null;
}

// Minimal fetch stubs for all endpoints the StoreApp calls on mount.
function makeFetch(catalogApps: CatalogAppPayload[]) {
  return vi.fn(async (url: string) => {
    if (url === "/api/store/catalog") {
      return new Response(JSON.stringify(catalogApps), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/store/installed-v2") {
      return new Response(JSON.stringify({ installed: [] }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/agents") {
      return new Response("[]", { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/cluster/install-targets") {
      return new Response(JSON.stringify([{ name: "local", label: "Local", type: "local" }]), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/apps/optional/catalog") {
      return new Response(JSON.stringify({ apps: [] }), { status: 200, headers: { "content-type": "application/json" } });
    }
    // framework API + other endpoints: 404 is fine (caught silently)
    return new Response(null, { status: 404 });
  });
}

const SEARXNG_UPSTREAM_UPDATE: CatalogAppPayload = {
  id: "searxng",
  name: "SearXNG",
  type: "service",
  category: "infrastructure",
  version: "2024.12.0",
  description: "Privacy-respecting metasearch engine",
  installed: true,
  update_available: true,
  upstream_version: "2026.10.2",
  upstream_update_available: true,
  upstream_checked_at: 1760000000,
};

beforeEach(() => {
  // jsdom doesn't implement scrollTo
  if (!Element.prototype.scrollTo) {
    Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
  }
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((q: string) => ({
        matches: false, media: q, onchange: null,
        addListener: vi.fn(), removeListener: vi.fn(),
        addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      })),
    });
  }
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Store updates tab -- upstream release detection", () => {
  it("shows an upstream-only update in the updates tab with the version delta", async () => {
    global.fetch = makeFetch([SEARXNG_UPSTREAM_UPDATE]) as any;
    render(<StoreApp windowId="test" />);
    const updatesBtn = await screen.findByRole("button", { name: /updates/i });
    fireEvent.click(updatesBtn);
    // The app card renders in the updates tab...
    await waitFor(() => expect(screen.getByText("SearXNG")).toBeInTheDocument());
    // ...with the pinned version and the upstream version delta.
    await waitFor(() => expect(screen.getByText("v2024.12.0")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("→ v2026.10.2")).toBeInTheDocument());
  });

  it("keeps the all-up-to-date empty state when upstream state is unknown", async () => {
    global.fetch = makeFetch([
      { ...SEARXNG_UPSTREAM_UPDATE, update_available: false, upstream_version: null, upstream_update_available: null },
    ]) as any;
    render(<StoreApp windowId="test" />);
    const updatesBtn = await screen.findByRole("button", { name: /updates/i });
    fireEvent.click(updatesBtn);
    // Unknown upstream state (network failure) is not an update: the
    // tab stays empty rather than claiming one.
    await waitFor(() => expect(screen.getByText(/all up to date/i)).toBeInTheDocument());
  });
});
