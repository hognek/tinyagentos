### Fixed
- dm-remote channels no longer render duplicate contradictory receipt ticks; the legacy dm-remote tick branch remains as the single source for that channel type.
- EventSource `onerror` handler no longer calls `close()`, allowing the browser to reconnect after transient errors and keeping live receipt updates flowing.
- ThreadPanel now marks live thread replies as seen when the thread opens, including replies arriving over the WebSocket stream that are not in the initially fetched message set.
