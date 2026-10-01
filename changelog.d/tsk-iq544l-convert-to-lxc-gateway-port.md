### Fixed

- **convert-to-lxc gateway port (C1+C2+C3)**: `_convert_to_lxc` now resolves the verified LLM gateway port from the local controller via `taosctl` (authenticated, `http://127.0.0.1:6969`) as a preflight step before any agents are drained or deleted. On failure (unreachable, 401, gateway not running) it prints a clear error pointing to `TAOS_TOKEN` or `~/.config/taosctl/config.json` and exits non-zero, preventing destructive deletion of flat-mode agents before the port is confirmed valid.
