import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { SettingsApp } from "../SettingsApp";

function mockAuthStatus(isAdmin: boolean) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    if (String(input).includes("/auth/status")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            configured: true,
            authenticated: true,
            user: { username: "jay", is_admin: isAdmin },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    // Every other endpoint (system info, cloud account, memory, etc.) is
    // irrelevant to this test, so just answer with "not available" and let
    // the mounted section's own fetches settle quietly.
    return Promise.resolve(new Response(null, { status: 404 }));
  });
}

describe("SettingsApp admin-only sections", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("hides admin-only sections from a non-admin user", async () => {
    mockAuthStatus(false);
    render(<SettingsApp windowId="w1" />);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });

    await waitFor(() => {
      expect(screen.queryByText("Updates")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Users")).not.toBeInTheDocument();
    expect(screen.queryByText("Advanced")).not.toBeInTheDocument();

    // Personal sections stay visible in the sidebar.
    expect(within(nav).getByText("Themes")).toBeInTheDocument();
    expect(within(nav).getByText("Account")).toBeInTheDocument();
  });

  it("shows admin-only sections to an admin user", async () => {
    mockAuthStatus(true);
    render(<SettingsApp windowId="w1" />);
    const nav = screen.getByRole("navigation", { name: "Settings sections" });

    await waitFor(() => {
      expect(within(nav).getByText("Updates")).toBeInTheDocument();
    });
    expect(within(nav).getByText("Users")).toBeInTheDocument();
    expect(within(nav).getByText("Advanced")).toBeInTheDocument();

    expect(within(nav).getByText("Themes")).toBeInTheDocument();
    expect(within(nav).getByText("Account")).toBeInTheDocument();
  });
});
