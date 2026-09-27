### Added

- An MLX (Apple Silicon) backend installer. Installing a model on the `mlx`
  backend now goes through `MLXInstaller` instead of the generic download
  fallback: it verifies the host is Apple Silicon, installs the `mlx-lm`
  runtime in the serving interpreter on demand, and pulls the model
  (`mlx_repo`, falling back to `hf_repo`, or a single `download_url`) into the
  shared layout at `~/models/mlx/<family>/<manifest_id>/`. On any other
  platform it fails with a clear message rather than dropping a file the
  runtime can never load.
- Apple Silicon hosts register their GPU as the `gpu-metal` scheduler resource
  (`docs/design/resource-scheduler.md`) instead of the CUDA-indexed
  `gpu-cuda-0`, in controller discovery and in the worker's advertised
  inventory alike, so lease ids and resource names match the hardware. The A2A
  GPU lease default follows the host too — a claim that names no resource no
  longer names one a Mac worker cannot have. Port 7837 is reserved for the MLX
  server alongside 7833-7836.
