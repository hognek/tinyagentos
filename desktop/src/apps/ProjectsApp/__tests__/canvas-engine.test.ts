import { describe, it, expect, vi, beforeEach } from "vitest";

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  global.localStorage = {
    ...global.localStorage,
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  };
  Object.defineProperty(window, "location", {
    value: { search: "" },
    writable: true,
    configurable: true,
  });
});

describe("canvas engine flag", () => {
  it("defaults to tldraw", async () => {
    window.location.search = "";
    (localStorage.getItem as any).mockReturnValue(null);
    const { getCanvasEngine, DEFAULT_ENGINE } = await import("../canvas/canvas-engine");
    expect(getCanvasEngine()).toBe(DEFAULT_ENGINE);
    expect(DEFAULT_ENGINE).toBe("tldraw");
  });

  it("query param wins over localStorage", async () => {
    window.location.search = "?canvas=excalidraw";
    (localStorage.getItem as any).mockReturnValue("tldraw");
    const { getCanvasEngine } = await import("../canvas/canvas-engine");
    expect(getCanvasEngine()).toBe("excalidraw");
  });

  it("localStorage selects excalidraw", async () => {
    window.location.search = "";
    (localStorage.getItem as any).mockReturnValue("excalidraw");
    const { getCanvasEngine } = await import("../canvas/canvas-engine");
    expect(getCanvasEngine()).toBe("excalidraw");
  });

  it("unknown values fall back to the default", async () => {
    window.location.search = "?canvas=unknown";
    (localStorage.getItem as any).mockReturnValue("also-unknown");
    const { getCanvasEngine, DEFAULT_ENGINE } = await import("../canvas/canvas-engine");
    expect(getCanvasEngine()).toBe(DEFAULT_ENGINE);
  });

  it("a throwing localStorage falls back to the default", async () => {
    window.location.search = "";
    (localStorage.getItem as any).mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    const { getCanvasEngine, DEFAULT_ENGINE } = await import("../canvas/canvas-engine");
    expect(getCanvasEngine()).toBe(DEFAULT_ENGINE);
  });
});
