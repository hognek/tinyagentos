import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { Suspense } from "react";
import type { ReactElement } from "react";

vi.mock("../canvas/CanvasBoard", () => ({
  CanvasBoard: () => <div data-testid="canvas-board-stub" />,
}));

vi.mock("../canvas/ExcalidrawCanvas", () => ({
  ExcalidrawCanvas: () => <div data-testid="excalidraw-canvas-stub" />,
  default: () => <div data-testid="excalidraw-canvas-stub" />,
}));

import { CanvasView } from "../canvas/CanvasView";

afterEach(cleanup);

function renderWithSuspense(ui: ReactElement) {
  return render(<Suspense fallback={null}>{ui}</Suspense>);
}

describe("CanvasView engine switching", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    Object.defineProperty(window, "location", {
      value: { search: "" },
      writable: true,
      configurable: true,
    });
  });

  it("renders CanvasBoard by default", async () => {
    window.location.search = "";
    renderWithSuspense(<CanvasView projectId="p1" projectSlug="s1" />);
    await screen.findByTestId("canvas-board-stub");
    expect(screen.queryByTestId("excalidraw-canvas-stub")).not.toBeInTheDocument();
  });

  it("renders ExcalidrawCanvas when ?canvas=excalidraw", async () => {
    window.location.search = "?canvas=excalidraw";
    renderWithSuspense(<CanvasView projectId="p1" projectSlug="s1" />);
    await screen.findByTestId("excalidraw-canvas-stub");
    expect(screen.queryByTestId("canvas-board-stub")).not.toBeInTheDocument();
  });
});
