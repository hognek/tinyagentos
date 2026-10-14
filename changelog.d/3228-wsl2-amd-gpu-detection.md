### Fixed

- Hardware: AMD GPUs under WSL2 are now detected via `/dev/dxg` + `rocminfo`. WSL2 exposes the GPU through DXG (no lspci, no `/opt/rocm`), so workers running there previously reported no leasable GPU resource. The marketing name is parsed from `rocminfo` and VRAM looked up from the existing AMD table (#3228).
