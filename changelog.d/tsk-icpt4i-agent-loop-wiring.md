### Changed

- **Agent loop wiring**: `AgentLoop` is now the single per-agent serialization
  owner. `AgentChatRouter` drives OpenClaw ACP turns through a per-agent
  `AgentLoop` (replacing the per-agent lock) and the turn-holder drives
  messages queued mid-turn at its safe point. The desktop taOS agent chat
  endpoint serializes on one `AgentLoop` too — fixing a race where two
  concurrent POSTs shared the opencode session with no serialization —
  queueing concurrent messages and surfacing them in the turn-holder's stream
  tail. New `GET /api/taos-agent/status` endpoint returns the desktop loop's
  status scoped to state / current turn / queue depth / subagent descriptors
  (subagent result/error payloads stay server-side) (#tsk-icpt4i).
