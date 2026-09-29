### Added

- Agents app rows now have Start, Stop, Restart and Pause/Resume controls that follow the agent's live container state: Start when stopped, Stop, Restart and Pause when running, Resume when paused or frozen. Stop and Restart ask for confirmation, controls are disabled while a request is in flight, and failures are shown as notifications.
- The Agents app reads live container state (running, stopped, frozen) from `/api/agents/containers` instead of relying only on the stored agent status.

### Fixed

- Pause now really pauses an agent: after a best-effort graceful prepare it freezes the agent's container with `incus pause`, and Resume unfreezes it before clearing the paused flag. Previously Pause only set a flag that nothing enforced.
- Agent start, stop and restart now target the container's own Incus project (for example `user-999`) instead of relying on the ambient project, matching delete.
- `/api/agents/containers` lists agent containers across all Incus projects, so agents in a restricted project show their real state.
- Start and Restart return an error status with a message when Incus fails, instead of a 200 response with `success: false`. A successful Start clears a stale paused flag left by Stop.
