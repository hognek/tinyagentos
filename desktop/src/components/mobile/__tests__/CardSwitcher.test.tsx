import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { useProcessStore } from "@/stores/process-store";

const { isShell, list, focus, close } = vi.hoisted(() => ({
  isShell: vi.fn(),
  list: vi.fn(),
  focus: vi.fn(),
  close: vi.fn(),
}));
vi.mock("@/lib/mobile-shell", () => ({
  isShellDevice: isShell,
  listShellWindows: list,
  focusShellWindow: focus,
  closeShellWindow: close,
}));

import { CardSwitcher } from "../CardSwitcher";

const WINDOWS = [
  { con_id: 11, app_id: "chrome-127.0.0.1__app.html-Default", title: "Files", label: "Files", workspace: "1", focused: false },
  { con_id: 12, app_id: "firefox", title: "Example Domain", label: "Firefox", workspace: "2", focused: true },
];

function setup(open = true) {
  const props = { open, onClose: vi.fn(), onSelectApp: vi.fn(), onLaunchpad: vi.fn() };
  render(<CardSwitcher {...props} />);
  return props;
}

async function flush() {
  await act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
  });
}

describe("CardSwitcher shell windows", () => {
  beforeEach(() => {
    useProcessStore.setState({ windows: [], nextZIndex: 1 });
    isShell.mockReturnValue(true);
    list.mockReset();
    list.mockResolvedValue(WINDOWS);
    focus.mockReset();
    focus.mockResolvedValue(true);
    close.mockReset();
    close.mockResolvedValue(true);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders compositor windows as cards named by label, Firefox as Browser", async () => {
    setup();
    await flush();
    expect(screen.getByRole("button", { name: "Switch to Files" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Switch to Browser" })).toBeTruthy();
    expect(screen.queryByText("No apps open")).toBeNull();
  });

  it("tap focuses the window and closes the switcher", async () => {
    const props = setup();
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Switch to Browser" }));
    expect(focus).toHaveBeenCalledWith(12);
    expect(props.onClose).toHaveBeenCalled();
    expect(props.onSelectApp).not.toHaveBeenCalled();
  });

  it.each(["Enter", " "])("keyboard %j on a card focuses the window", async (key) => {
    const props = setup();
    await flush();
    fireEvent.keyDown(screen.getByRole("button", { name: "Switch to Browser" }), { key });
    expect(focus).toHaveBeenCalledWith(12);
    expect(props.onClose).toHaveBeenCalled();
  });

  it("Enter on the X button does not also switch to the card", async () => {
    setup();
    await flush();
    fireEvent.keyDown(screen.getByRole("button", { name: "Close Browser" }), { key: "Enter" });
    expect(focus).not.toHaveBeenCalled();
  });

  it("the X button closes the window and refreshes the list", async () => {
    setup();
    await flush();
    list.mockResolvedValue([WINDOWS[1]]);
    const calls = list.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Close Files" }));
    await flush();
    expect(close).toHaveBeenCalledWith(11);
    expect(list.mock.calls.length).toBeGreaterThan(calls);
    expect(screen.queryByRole("button", { name: "Switch to Files" })).toBeNull();
  });

  it("polls every 2s while open", async () => {
    vi.useFakeTimers();
    setup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const first = list.mock.calls.length;
    expect(first).toBeGreaterThanOrEqual(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(list.mock.calls.length).toBe(first + 1);
  });

  it("empty state shows when both lists are empty", async () => {
    list.mockResolvedValue([]);
    setup();
    await flush();
    expect(screen.getByText("No apps open")).toBeTruthy();
  });

  it("non-shell device makes no shell calls and shows in-page windows only", async () => {
    isShell.mockReturnValue(false);
    setup();
    await flush();
    expect(list).not.toHaveBeenCalled();
    expect(screen.getByText("No apps open")).toBeTruthy();
  });
});
