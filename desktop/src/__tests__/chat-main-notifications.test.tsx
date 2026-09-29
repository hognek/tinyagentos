import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useNotificationStore } from "../stores/notification-store";

vi.mock("../apps/MessagesApp", () => ({
  MessagesApp: ({ windowId }: { windowId: string }) => (
    <div data-testid="messages-app-stub" data-window-id={windowId} />
  ),
}));

vi.mock("../shell/InstallPromptBanner", () => ({
  InstallPromptBanner: () => null,
}));

vi.mock("../hooks/use-is-mobile", () => ({
  useIsMobile: vi.fn(),
}));

import { useIsMobile } from "../hooks/use-is-mobile";
import { AppShell } from "../components/AppShell";
import { ChatStandalone } from "../ChatStandalone";
import { NotificationToasts } from "../components/NotificationToast";

describe("chat-main notification rendering", () => {
  beforeEach(() => {
    (useIsMobile as ReturnType<typeof vi.fn>).mockReturnValue(false);
    useNotificationStore.setState({ notifications: [] });
  });

  it("renders a pushed notification inside the chat-main tree", async () => {
    render(
      <AppShell>
        <NotificationToasts />
        <ChatStandalone />
      </AppShell>,
    );
    await act(async () => {
      useNotificationStore.getState().addNotification({
        source: "system",
        title: "New taOS version available",
        body: "Reload to upgrade.",
        level: "info",
      });
    });
    expect(screen.getByText("New taOS version available")).toBeInTheDocument();
  });
});
