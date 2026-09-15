### Fixed

- Migrated `poolOptions` to top-level `maxWorkers`, `minWorkers`, and `execArgv` in `desktop/vite.config.ts` for Vitest 4 compatibility, restoring the 2-fork bound and 4 GB heap guard that was silently inert under the removed key.
