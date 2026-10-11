// dev-only; deleted by the flip+removal card

export type CanvasEngine = "tldraw" | "excalidraw";

export const DEFAULT_ENGINE: CanvasEngine = "tldraw";

export function getCanvasEngine(): CanvasEngine {
  if (typeof window === "undefined") return DEFAULT_ENGINE;

  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("canvas");
  if (fromQuery === "tldraw" || fromQuery === "excalidraw") return fromQuery;

  try {
    const fromStorage = localStorage.getItem("taos.canvas.engine");
    if (fromStorage === "tldraw" || fromStorage === "excalidraw") return fromStorage;
  } catch {
    // ignore
  }

  return DEFAULT_ENGINE;
}
