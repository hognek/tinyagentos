### Fixed

- The delegation and skill-exec governance gates now deny (403) when `app.state.execution_policies` is absent instead of silently allowing every request. An absent store indicates a misconfigured app because the startup wiring in `app.py` sets `app.state.execution_policies` unconditionally.
