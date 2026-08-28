# tsk-ha5iau: LoRa Off-Grid Transport for taOS - Design Note

## Executive Summary
This design note addresses the requirement to bridge Meshtastic onto the A2A bus as a CONTROL channel, not a data tunnel, for LoRa off-grid transport. The solution implements a taOS <-> Meshtastic bridge that operates within the existing A2A bus architecture while addressing LoRa's broadcast nature and limited throughput constraints.

## 1. Enforced Security Model for the Bridge

### Core Principles
- **Zero Trust Extension**: The bridge does NOT inherit A2A bus trust. Messages must be authenticated at the bridge layer before reaching the bus.
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
└─────────────────┬-------------------------------------------─┘
                  │ Verify signature & decrypt
┌─────────────────▼-------------------------------------------─┐
│  Bridge Server                                               │
│  • Device key registry                                       │
│  • Sequence number validation                                 │
│  • Timestamp freshness check                                  │
│  • If verification fails: drop & log                        │
└─────────────────┬-------------------------------------------─┘
                  │ Message passes security validation
┌─────────────────▼-------------------------------------------─┐
│  A2A Bus (Controlled Trust)                                  │
│  • Messages injected with bridge handle (@bridge-<id>)       │
│  • No inheritance of sender field from LoRa                 │
│  • Bridge is the verified source of all radio messages       │
└─────────────────────────────────────────────────────────────┘
```

### Security Handling Policies

**Unsigned Frames:**
- Dropped immediately at bridge ingress
- Logged with device identifier and geolocation (if available)
- Alert generation: `"LoRa security breach: unsigned frame from <MAC>"

**Replayed Frames:**
- Detected via sequence number gap analysis
- Old frames (timestamp > 5 minutes or sequence number < last_seen) rejected
- Bridge maintains sliding window per device
- Alert generation: `"LoRa replay detected from <MAC> (seq <n>)"

**Corrupted Frames:**
- MAC validation failure (AES-GCM tag mismatch)
- Decryption failure
- Dropped, logged, and alert generated

**Allowed Security Violations:**
- Bridge may accept unencrypted messages during testing mode (configurable)
- Bridge logs and forwards with bridge handle for debugging
- All production deployments require encryption

## 2. Message Schema and Size Budget

### Meshtastic Payload Constraints
- Maximum payload: 237 bytes per packet
- Physical layer: LoRa SF7-BW500 @ 10kbps theoretical
- Effective throughput: ~1kbps with Meshtastic defaults
- Half-duplex with ~2-5 second latency

### Bridge Message Schema
```json
{
  "from": "@bridge-<module-id>",
  "thread": "<a2a-thread-name>",
  "body": "<meshtastic-payload>",
  "metadata": {
    "device_id": "<hex-mac-or-uuid>",
    "sequence": <uint32>,
    "timestamp": <unix-timestamp>,
    "hop_limit": <uint8>,
    "channel": "<meshtastic-channel-name>"
  }
}
```

### Size Analysis
| Component | Size (bytes) | Notes |
|-----------|--------------|-------|
| AES-256-GCM overhead | 16 | Tag + IV |
| JSON serialization | 20-80 | Depends on content |
| Bridge message wrapper | 30-50 | Static headers |
| Actual Meshtastic data | ~130-180 | Remaining budget |
| **Total** | **<=237** | **Fits exactly** |

### Payload Allocation
- **Control Messages** (Status beacons): 50 bytes
- **Command Messages**: 80 bytes  
- **Data Messages** (short telemetry): 107 bytes
- **Keep-Alive Messages**: 20 bytes

### Compression Strategies
- Use CBOR instead of JSON for control messages (saves ~40%)
- Delta encoding for timestamps and sequence numbers
- Binary framing for critical messages

## 3. Allowed A2A Kinds Over Radio

### Permitted A2A Message Types
The bridge allows only these A2A kinds to prevent security issues:

**✓ Allowed (Read-Only):**
- `status`: System status beacons from nodes
- `alert`: Critical alerts and warnings
- `command`: Short administrative commands
- `heartbeat`: Connection health monitoring

**✗ Refused (Security Risk):**
- `chat`: User-to-user messaging (cannot be trusted)
- `decision`: Decision records (require authentication)
- `task`: Project task updates (must be authenticated)
- `action`: State-changing operations
- `file`: File transfers

### A2A Kind Filtering Implementation
```python
# In bridge service
ALLOWED_RADIO_KINDS = frozenset({
    "status", "alert", "command", "heartbeat"
})

# Example bridge filtering logic
if message["kind"] not in ALLOWED_RADIO_KINDS:
    logger.warning("A2A kind %s rejected over radio", message["kind"])
    return None  # Drop message
```

### Thread Channel Mapping
| Radio Channel | A2A Thread | Purpose |
|---------------|------------|---------|
| `status` | `taos-status` | Node health + metrics |
| `alerts` | `taos-alerts` | Critical system alerts |
| `commands` | `taos-commands` | Administrative commands |
| `heartbeats` | `taos-heartbeats` | Connection monitoring |

## 4. Concrete First Milestone (Hardware Phase)

### Version 0.1.0 - "Point-to-Point Prototype"
**Target**: Q3 2026 (after hardware arrival)

#### Primary Objectives
1. **Hardware Setup**: Deploy two Heltec V4 modules in point-to-point configuration
2. **Bridge Development**: Implement basic message forwarding from Meshtastic to A2A bus
3. **Authentication**: Complete per-device key registration and validation system
4. **Security Testing**: Verify replay protection and message authenticity

#### Technical Deliverables
- [ ] Bridge service daemon (`taos-lora-bridge`) with command-line interface
- [ ] Device key management system with secure storage
- [ ] Integration with existing A2A bus proxy (`/api/a2a/bus/send`)
- [ ] Configuration management for radio parameters (freq, SF, channel)
- [ ] Logging and monitoring for security events
- [ ] Test suite for bridge functionality and security properties

#### Deployment Architecture
```
┌─────────────────────────────────────────────────────────┐
│  TAOS Controller (Bridge Host)                          │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │                                                 │   │
│  │  +----------------------+    +----------------+ │   │
│  │  │   taos-lora-bridge   │───▶│  A2A Bus       │ │   │
│  │  │  (REST API)          │    │  @bridge-node1 │ │   │
│  │  +----------------------+    +----------------+ │   │
│  │                                                 │   │
│  │  +----------------------+    +----------------+ │   │
│  │  │  taos-lora-bridge   │───▶│  A2A Bus       │ │   │
│  │  │  (REST API)          │    │  @bridge-node2 │ │   │
│  │  +----------------------+    +----------------+ │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Radio Links (2 Heltec V4 modules)                 │   │
│  │                                                 │   │
│  │  +----------------------+                    │   │
│  │  │  Module 1 (Radio 1) │                    │   │
│  │  │  - 919-923 MHz      │                    │   │
│  │  │  - 28 dBm TX        │                    │   │
│  │  +----------------------+                    │   │
│  │  │  Module 2 (Radio 2) │                    │   │
│  │  │  - 923-924 MHz      │                    │   │
│  │  │  - 28 dBm TX        │                    │   │
│  │  +----------------------+                    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

#### MVP Testing Requirements
- [ ] Message round-trip testing: Radio → Bridge → A2A → Bridge → Radio
- [ ] Security validation: Verify unsigned frames are rejected
- [ ] Performance testing: 1kbps sustained throughput with <1s latency
- [ ] Integration testing: Verify A2A bus messages appear correctly

#### Success Criteria
1. **Functional**: Both radio modules connect and exchange messages
2. **Security**: All unsigned/replayed messages are rejected
3. **Performance**: Status beacons sent every 30 seconds
4. **Reliability**: Bridge survives controller reboot without reconnection

### Notes
- This design focuses on the security model first as required
- Firmware implementation will follow after this design is approved
- The bridge operates as a CONTROL channel, not a data tunnel
- All security decisions must be made before hardware deployment

## References
- [Heltec WiFi LoRa 32 V4 Datasheet](https://docs.heltec.org/en/latest/wifi_lora_32/tty/v4.html)
- [Meshtastic Documentation](https://meshtastic.org/)
- [taOS A2A Bus Architecture](/tinyagentos/routes/a2a_bus.py)
- [Jay's Note 2026-08-28](note-260828-f0fa88.md - reference implementation)

---
*Document created: 2026-08-28*
*Status: Draft design note*
*Author: taOS Lead*
*Tags: lora, meshtastic, bridge, security, radio*