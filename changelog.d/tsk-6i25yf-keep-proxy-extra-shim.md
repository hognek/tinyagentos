### Fixed

- Updating an existing install past the LiteLLM removal no longer fails with "Dependency install failed". The updater already on the box still asks for the old `proxy` extra, so `proxy` stays defined as an empty extra that installs nothing.
