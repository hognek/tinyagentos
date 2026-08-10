import { render, screen, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  stripAt,
  registryEntriesEqual,
  RegistryPanel,
  type RegistryEntry,
} from "./RegistryPanel";

/* ------------------------------------------------------------------ */
/*  stripAt — pure unit tests (no timers needed)                       */
/* ------------------------------------------------------------------ */

describe("stripAt", () => {
  it("strips a leading @ from a name", () => {
    expect(stripAt("@taOSmd-dev")).toBe("taOSmd-dev");
  });

  it("leaves a name without @ untouched", () => {
    expect(stripAt("taOSmd-dev")).toBe("taOSmd-dev");
  });

  it("only strips the first @", () => {
    expect(stripAt("@foo@bar")).toBe("foo@bar");
  });

  it("handles empty string", () => {
    expect(stripAt("")).toBe("");
  });

  it("handles string that is just @", () => {
    expect(stripAt("@")).toBe("");
  });
});

/* ------------------------------------------------------------------ */
/*  registryEntriesEqual — poll no-op comparison                       */
/* ------------------------------------------------------------------ */

describe("registryEntriesEqual", () => {
  const base: RegistryEntry = {
    canonical_id: "id-1",
    framework: "openclaw",
    display_name: "Agent",
    user_id: "user-1",
    origin: "external-selfjoin",
    handle: "",
    role: null,
    capabilities: ["a2a_send"],
    status: "active",
    registered_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    revoked_at: null,
  };

  it("returns true for identical snapshots", () => {
    expect(registryEntriesEqual([base], [{ ...base, capabilities: ["a2a_send"] }])).toBe(true);
  });

  it("returns false when status changes", () => {
    expect(
      registryEntriesEqual([base], [{ ...base, status: "suspended" }]),
    ).toBe(false);
  });

  it("returns false when length differs", () => {
    expect(registryEntriesEqual([base], [])).toBe(false);
  });

  it("returns false when capabilities differ", () => {
    expect(
      registryEntriesEqual([base], [{ ...base, capabilities: ["a2a_send", "memory_read"] }]),
    ).toBe(false);
  });
});

/* ------------------------------------------------------------------ */
/*  Shared fixture                                                      */
/* ------------------------------------------------------------------ */

const fakeEntry: RegistryEntry = {
  canonical_id: "taosmd-dev-20260101-000000",
  framework: "openclaw",
  display_name: "@taOSmd-dev",
  user_id: "user-1",
  origin: "external-selfjoin",
  handle: "",
  role: null,
  capabilities: [],
  status: "active",
  registered_at: new Date().toISOString(),
  updated_at: null,
  revoked_at: null,
};

function makeFetch(entries: RegistryEntry[] = [fakeEntry]) {
  return vi.fn().mockImplementation((url: string) => {
    if (url === "/auth/status") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
      });
    }
    if (url === "/api/agents/registry") {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(entries),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

/* ------------------------------------------------------------------ */
/*  Display name rendering (real timers — no fake timer conflict)      */
/* ------------------------------------------------------------------ */

describe("RegistryPanel display name", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("strips leading @ from display_name in the rendered row", async () => {
    vi.stubGlobal("fetch", makeFetch());

    render(<RegistryPanel />);

    // Click the toggle to expand
    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        // Should show "taOSmd-dev" not "@taOSmd-dev"
        expect(screen.getByText("taOSmd-dev")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
    expect(screen.queryByText("@taOSmd-dev")).not.toBeInTheDocument();
  }, 10_000);
});

/* ------------------------------------------------------------------ */
/*  Polling behaviour (fake timers)                                     */
/* ------------------------------------------------------------------ */

describe("RegistryPanel polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls the registry every 5s while expanded", async () => {
    const mockFetch = makeFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    // Expand — use real microtask queue for state update
    await act(async () => { toggle.click(); });

    // Drain any pending microtasks from initial load
    await act(async () => { await Promise.resolve(); });

    const callsBefore = mockFetch.mock.calls.length;
    expect(callsBefore).toBeGreaterThan(0);

    // Advance 5s → should trigger one more poll cycle
    await act(async () => {
      vi.advanceTimersByTime(5_000);
      await Promise.resolve();
    });

    expect(mockFetch.mock.calls.length).toBeGreaterThan(callsBefore);
  });

  it("stops polling after collapse (cleanup runs)", async () => {
    const mockFetch = makeFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });

    // Expand
    await act(async () => { toggle.click(); });
    await act(async () => { await Promise.resolve(); });

    // Collapse — triggers useEffect cleanup which stops the timer
    await act(async () => { toggle.click(); });
    await act(async () => { await Promise.resolve(); });

    const callsAtCollapse = mockFetch.mock.calls.length;

    // No new calls should fire after 15s while collapsed
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    expect(mockFetch.mock.calls.length).toBe(callsAtCollapse);
  });

  it("refetches immediately after an action", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([fakeEntry]),
        });
      }
      // Action endpoints (suspend, approve, etc.)
      if (typeof url === "string" && /\/(suspend|approve|reject|reactivate)$/.test(url)) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(fakeEntry) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });
    await act(async () => { await Promise.resolve(); });

    const callsBeforeAction = mockFetch.mock.calls.length;

    // Entry is "active" so Suspend must be present — assert rather than guard.
    const suspendBtn = screen.getByTitle("Suspend");
    await act(async () => {
      suspendBtn.click();
      await Promise.resolve();
    });
    // Should have triggered an additional registry fetch (post-action reload)
    expect(mockFetch.mock.calls.length).toBeGreaterThan(callsBeforeAction);
  });

  it("unchanged poll does not show loading spinner (scroll stays mounted)", async () => {
    const mockFetch = makeFetch();
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });
    await act(async () => { await Promise.resolve(); });

    // Initial load finished; row is visible
    expect(screen.getByText("taOSmd-dev")).toBeInTheDocument();
    expect(screen.queryByText(/Loading registry/i)).not.toBeInTheDocument();

    const callsBefore = mockFetch.mock.calls.length;

    // Quiet poll with identical payload must not flash the loading UI
    await act(async () => {
      vi.advanceTimersByTime(5_000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockFetch.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(screen.queryByText(/Loading registry/i)).not.toBeInTheDocument();
    expect(screen.getByText("taOSmd-dev")).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  Collapse behaviour — retired agents                                */
/* ------------------------------------------------------------------ */

describe("RegistryPanel collapsed retired", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders retired section collapsed by default, expands on click, active agents always visible", async () => {
    const entries: RegistryEntry[] = [
      { ...fakeEntry, canonical_id: "active-1", display_name: "ActiveAgent", status: "active" },
      { ...fakeEntry, canonical_id: "active-2", display_name: "ActiveTwo", status: "active" },
      {
        ...fakeEntry,
        canonical_id: "revoked-1",
        display_name: "RevokedAgent",
        status: "revoked",
      },
      {
        ...fakeEntry,
        canonical_id: "suspended-1",
        display_name: "SuspendedAgent",
        status: "suspended",
      },
    ];
    vi.stubGlobal("fetch", makeFetch(entries));

    render(<RegistryPanel />);

    // Expand the registry panel
    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => {
      toggle.click();
    });

    await waitFor(
      () => {
        // Active agents always visible
        expect(screen.getByText("ActiveAgent")).toBeInTheDocument();
        expect(screen.getByText("ActiveTwo")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    // Retired section is present
    const retiredSection = screen.getByRole("region", {
      name: "Retired registry entries",
    });
    expect(retiredSection).toBeInTheDocument();

    // Retired toggle shows count and is collapsed
    const retiredToggle = screen.getByRole("button", {
      name: /retired \(2\)/i,
    });
    expect(retiredToggle).toBeInTheDocument();
    expect(retiredToggle).toHaveAttribute("aria-expanded", "false");

    // Retired panel is hidden (collapsed by default — jsdom does not compute
    // Tailwind CSS visibility, so we assert on the class rather than element
    // visibility)
    const retiredPanel = document.getElementById("retired-registry-panel");
    expect(retiredPanel).toBeInTheDocument();
    expect(retiredPanel!).toHaveClass("hidden");

    // Revoked + suspended agents are IN the DOM but inside a hidden container
    expect(screen.getByText("RevokedAgent")).toBeInTheDocument();
    expect(screen.getByText("SuspendedAgent")).toBeInTheDocument();

    // Click to expand retired section
    await act(async () => {
      retiredToggle.click();
    });

    // Retired toggle is now expanded, panel class loses "hidden"
    expect(retiredToggle).toHaveAttribute("aria-expanded", "true");
    expect(retiredPanel!).not.toHaveClass("hidden");
  }, 10_000);
});

/* ------------------------------------------------------------------ */
/*  Handle (alias) editing UI                                           */
/* ------------------------------------------------------------------ */

describe("RegistryPanel handle editing", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the handle text and edit button for owner/admin", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "my-alias",
    };
    vi.stubGlobal("fetch", makeFetch([entryWithHandle]));

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@my-alias")).toBeInTheDocument();
        expect(screen.getByTitle("Edit handle")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("hides edit button for non-owner non-admin", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "my-alias",
      user_id: "other-user",
    };
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: false, id: "viewer-user" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([entryWithHandle]),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@my-alias")).toBeInTheDocument();
        expect(screen.queryByTitle("Edit handle")).not.toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("enters edit mode and saves handle via PATCH", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "old-alias",
    };
    const mockFetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([entryWithHandle]),
        });
      }
      if (typeof url === "string" && url.includes("/api/agents/registry/") && opts?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ...entryWithHandle, handle: "new-alias" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@old-alias")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    const editBtn = screen.getByTitle("Edit handle");
    await act(async () => { editBtn.click(); });

    const input = screen.getByRole("textbox");
    expect(input).toHaveValue("old-alias");

    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )!.set!;
      nativeInputValueSetter.call(input, "new-alias");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const saveBtn = screen.getByTitle("Save handle");
    await act(async () => { saveBtn.click(); });
    await act(async () => { await Promise.resolve(); });

    const patchCalls = mockFetch.mock.calls.filter(
      ([url, opts]) => typeof url === "string" && url.includes("/api/agents/registry/") && (opts as RequestInit)?.method === "PATCH",
    );
    expect(patchCalls.length).toBeGreaterThanOrEqual(1);
    const body = JSON.parse((patchCalls[0][1] as RequestInit).body as string);
    expect(body.handle).toBe("new-alias");
  });

  it("shows error message when PATCH fails", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "old-alias",
    };
    const mockFetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([entryWithHandle]),
        });
      }
      if (typeof url === "string" && url.includes("/api/agents/registry/") && opts?.method === "PATCH") {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({ error: "handle is already owned by another active agent" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@old-alias")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    const editBtn = screen.getByTitle("Edit handle");
    await act(async () => { editBtn.click(); });

    const input = screen.getByRole("textbox");
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )!.set!;
      nativeInputValueSetter.call(input, "taken-alias");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const saveBtn = screen.getByTitle("Save handle");
    await act(async () => { saveBtn.click(); });
    await act(async () => { await Promise.resolve(); });

    expect(screen.getByText("handle is already owned by another active agent")).toBeInTheDocument();
  });

  it("cancel restores original handle and exits edit mode", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "original",
    };
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([entryWithHandle]),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@original")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    const editBtn = screen.getByTitle("Edit handle");
    await act(async () => { editBtn.click(); });

    const input = screen.getByRole("textbox");
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )!.set!;
      nativeInputValueSetter.call(input, "modified");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const cancelBtn = screen.getByTitle("Cancel");
    await act(async () => { cancelBtn.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@original")).toBeInTheDocument();
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
        expect(screen.getByTitle("Edit handle")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("displays a stored @-prefixed handle with a single @ (internal seeds)", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "@taOS-dev",
    };
    vi.stubGlobal("fetch", makeFetch([entryWithHandle]));

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@taOS-dev")).toBeInTheDocument();
        expect(screen.queryByText("@@taOS-dev")).not.toBeInTheDocument();
      },
      { timeout: 3000 },
    );
  });

  it("strips a typed leading @ before PATCH (@ is bus syntax, not part of the name)", async () => {
    const entryWithHandle: RegistryEntry = {
      ...fakeEntry,
      handle: "old-alias",
    };
    const mockFetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url === "/auth/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ user: { is_admin: true, id: "user-1" } }),
        });
      }
      if (url === "/api/agents/registry") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([entryWithHandle]),
        });
      }
      if (typeof url === "string" && url.includes("/api/agents/registry/") && opts?.method === "PATCH") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ...entryWithHandle, handle: "new-alias" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    vi.stubGlobal("fetch", mockFetch);

    render(<RegistryPanel />);

    const toggle = screen.getByRole("button", { name: /agent registry/i });
    await act(async () => { toggle.click(); });

    await waitFor(
      () => {
        expect(screen.getByText("@old-alias")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );

    const editBtn = screen.getByTitle("Edit handle");
    await act(async () => { editBtn.click(); });

    const input = screen.getByRole("textbox");
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      )!.set!;
      nativeInputValueSetter.call(input, "@new-alias");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const saveBtn = screen.getByTitle("Save handle");
    await act(async () => { saveBtn.click(); });
    await act(async () => { await Promise.resolve(); });

    const patchCalls = mockFetch.mock.calls.filter(
      ([url, opts]) => typeof url === "string" && url.includes("/api/agents/registry/") && (opts as RequestInit)?.method === "PATCH",
    );
    expect(patchCalls.length).toBe(1);
    const body = JSON.parse((patchCalls[0][1] as RequestInit).body as string);
    expect(body.handle).toBe("new-alias");
  });
});
