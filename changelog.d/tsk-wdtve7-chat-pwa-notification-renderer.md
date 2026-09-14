### Fixed

- **chat PWA notifications missing renderer**: `chat-main.tsx` and `app-standalone-main.tsx` both mounted `<AppShell>` without `<NotificationToasts />`, so notifications pushed by `UpdateAvailableToast` and `SpaUpdateToast` were recorded in the store but never displayed on the chat PWA or standalone app PWA paths. Added the renderer to both entry points. Removed the `test.fixme` quarantine on the `/chat-pwa` update-toast e2e assertion so it runs again.
