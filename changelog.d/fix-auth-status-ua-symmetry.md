### Fixed

- **PWA refresh loop after a browser auto-update**: `/auth/status`, `/auth/me`
  and the chat/canvas/terminal/web-chat WebSocket handlers now apply the same
  session User-Agent binding check as the API middleware. Previously a session
  created before a browser update kept reading as authenticated on
  `/auth/status` while every `/api/*` call was rejected, so the desktop shell
  remounted in a loop; the WebSocket endpoints conversely accepted a cookie
  the APIs refused.
