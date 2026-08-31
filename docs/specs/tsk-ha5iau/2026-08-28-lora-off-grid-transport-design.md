# tsk-ha5iau: LoRa Off-Grid Transport for taOS - Design Note

## Executive Summary
This design note addresses the requirement to add Meshtastic as a first-class platform in the taOS channel hub, routing messages to the correct agent via the existing `MessageRouter`. The solution adds a `meshtastic_connector.py` alongside the seven existing connectors and a Talk app surface, inheriting routing, archive and the existing app for free. The hard work is degradation policy for the 237-byte text-only link, not transport plumbing.

## 1. Enforced Security Model for the Connector

### Core Principles
- **Zero Trust Extension**: The connector does NOT inherit channel hub trust. Messages must be authenticated at the connector ingress before reaching the router.
- **Per-Device Authentication**: Each Heltec module is registered with unique cryptographic keys.
- **Message Replay Protection**: All frames include a timestamp and sequence number to prevent replay attacks.
- **Payload Integrity**: AES-256-GCM encryption with per-frame nonces for message integrity.

### Security Architecture
```
┌─────────────────────────────────────────────────────────────┐
│  Source (LoRa)                                              │
│  • Signed payload (device key)                              │
│  • Sequence number + timestamp                             │
│  • AES-256-GCM encrypted                                        │
└─────────────────┬-------------------------------------------┘
                    │ Verify signature & decrypt
┌─────────────────▼-------------------------------------------─┐
│  meshtastic_connector.py                                    │
│  • Device key registry                                       │
│  • Sequence number validation                                 │
│  • Timestamp freshness check                                  │
│  • If verification fails: drop & log                        │
└─────────────────┬-------------------------------------------┘
                    │ Emits IncomingMessage with platform="meshtastic"
                    │ Routes via MessageRouter.get_agent_for_channel
┌─────────────────▼-------------------------------------------─┐
│  channel_hub/router.py MessageRouter                        │
│  • assign_channel(platform="meshtastic", bot_id, agent_name) │
│  • get_agent_for_channel resolves the target agent           │
│  • Standard routing and archive pipeline                     │
└─────────────────────────────────────────────────────────────┘
```

### Security Handling Policies

**Unsigned Frames:**
- Dropped immediately at connector ingress
- Logged with device identifier and geolocation (if available)
- Alert generation: `"LoRa security breach: unsigned frame from <MAC>"`

**Replayed Frames:**
- Detected via sequence number gap analysis
- Old frames (timestamp > 5 minutes or sequence number < last_seen) rejected
- Connector maintains sliding window per device
- Alert generation: `"LoRa replay detected from <MAC> (seq <n>)"`

**Corrupted Frames:**
- MAC validation failure (AES-GCM tag mismatch)
- Decryption failure
- Dropped, logged, and alert generated

**Allowed Security Violations:**
- Connector may accept unencrypted messages during testing mode (configurable)
- Connector logs and forwards with testing flag for debugging
- All production deployments require encryption

## 2. Integration via channel_hub

### Existing Seam
`tinyagentos/channel_hub/` holds seven working connectors on a common envelope: discord, telegram, slack, matrix, email, webchat, webhook (4-5K each). `channel_hub/message.py` defines `IncomingMessage` with a `platform` field and `OutgoingMessage` for replies. `channel_hub/router.py` `MessageRouter` already provides `assign_channel(platform, bot_id, agent_name)` and `get_agent_for_channel(platform, bot_id)`.

### meshtastic_connector.py
The new connector sits alongside the existing seven. It emits `IncomingMessage(platform="meshtastic", ...)` and calls `self.router.route_message(self.agent_name, incoming)`, exactly like `telegram_connector.py` or `webchat_connector.py`. A Meshtastic channel (or node) maps to one agent via `assign_channel`. Addressing lives on the channel the message arrived on, not in the payload.

### Routing Keys on the Channel, Not the Payload
Map one Meshtastic channel (or node) to one agent and addressing costs ZERO bytes of the ~237 byte packet. The naive alternative is bad: real agent identities on this fleet are 25-30 chars (kilo-taos-20260711-000740, laguna-s-ora-20260721-191750, stepflash-taos-20260713-103907). Carrying sender + recipient in-payload would burn ~60 of 237 bytes, a quarter of the packet, before a single character of content. Meshtastic supports 8 channels, so channel-per-agent caps there and node-per-agent needs a board per agent; past that use a SHORT-CODE REGISTRY (2-4 bytes) mapped to canonical identity. Never put canonical ids on the radio.
