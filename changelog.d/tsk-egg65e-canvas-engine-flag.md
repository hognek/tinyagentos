### Added
- Dev-only canvas engine flag (`?canvas=excalidraw` or localStorage `taos.canvas.engine`) to switch between tldraw and Excalidraw engines in CanvasView
- New `ExcalidrawCanvas` component that renders the Excalidraw board using `useCanvasElements`
- Lazy-loading for both `CanvasBoard` and `ExcalidrawCanvas` via `React.lazy` with `Suspense`
