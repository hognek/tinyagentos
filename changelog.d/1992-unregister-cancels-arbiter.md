### Fixed

- Unregistering a worker now cancels the GPU arbiter tasks still running on its leases, releasing their VRAM reservations and scheduler slots instead of leaking them into a later re-registration of the same GPU.
