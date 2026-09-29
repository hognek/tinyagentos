### Fixed

- The agent container listing no longer crashes when an agent's container is stopped: Incus reports a stopped instance's network as null, which made `GET /api/agents/containers` return 500 for every agent (and the Agents app fell back to the stored status instead of the live one). Fixed in both the Incus listing and the LXC backend.
