### Added

- **macOS worker install registers Apple Silicon as a `gpu-metal` resource**
  (#37). `scripts/install-worker.sh` now runs a macOS accelerator probe in its
  Darwin branch: arm64 with Metal present selects the `gpu-metal` resource
  class (MLX / llama.cpp Metal / Core ML on unified memory, 1 concurrent task),
  and probes the python for the MLX runtime only to advise on GPU inference.
  Intel Macs, and arm64 hosts whose Metal probe answers nothing (a VM), fall
  back to `cpu-inference`. `TAOS_FORCE_METAL=1` forces the Apple Silicon branch
  on a bench box whose probe is silent; `TAOS_WORKER_RESOURCES` overrides the
  detected set.

### Changed

- The macOS launchd agent (`~/Library/LaunchAgents/com.tinyagentos.worker.plist`)
  now carries `EnvironmentVariables` — `PYTHONUNBUFFERED`,
  `TAOS_WORKER_STATE_DIR`, and the detected `TAOS_WORKER_RESOURCES` — so the
  resource class survives a re-login instead of depending on the installer's
  process environment.
- `tinyagentos.worker.agent` advertises Apple Silicon as `gpu-metal` rather
  than `gpu-cuda-0` (an MLX/ollama backend on a Mac is the Metal GPU, not a
  CUDA device), and unions the installer-detected classes from
  `TAOS_WORKER_RESOURCES` into the `resources` array it reports at
  registration and on every heartbeat.
