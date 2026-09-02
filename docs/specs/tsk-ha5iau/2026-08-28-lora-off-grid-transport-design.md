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
```text
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

## 3. Degradation Policy

### The Problem
`OutgoingMessage` carries buttons, images and cards, and `message.py:parse_inline_hints` parses `[button:Label:action]` and `[image:path]` out of agent replies. NONE of that survives a text-only ~237 byte link. The connector needs an explicit policy for rich elements, long replies, and a hard per-message size budget enforced BEFORE transmit. An agent that answers in 2KB of prose must not silently become a 12-packet flood.

### Rich Element Policy

| Element | Policy |
|---------|--------|
| Buttons | Drop. Emit one notice per response: `"[button dropped: Meshtastic is text-only]"` |
| Images | Drop. Emit one notice per response: `"[image dropped: Meshtastic is text-only]"` |
| Cards | Drop. Emit one notice per response: `"[card dropped: Meshtastic is text-only]"` |

Notices are per RESPONSE, not per conversation: `_degrade` builds a fresh notice list for
each `OutgoingMessage` and the connector transmits each notice as its own frame. There is
no conversation-scoped suppression; if repeats prove noisy in the field, suppression is a
follow-up, not part of this contract.

### Long Reply Policy

| Length | Policy |
|--------|--------|
| Fits one frame | Transmit as a single `[part 1/1] `-prefixed frame (prefix bytes count against the budget, so the content cutover sits at 237 minus the prefix length, not at 237) |
| Larger | Chunk into `[part N/M] `-prefixed frames, each <= 237 payload bytes |

Every emitted CONTENT frame carries the `[part N/M] ` prefix, including single-part
replies; notice frames (dropped buttons/images/cards) are transmitted before the content
parts and carry no prefix.
Receive-side reassembly is NOT implemented: `handle_incoming` routes each packet as its
own message. Parts arrive as separate messages; reassembly is a hardware-phase follow-up
(see section 5), not a promise of this connector.

### Hard Size Budget
Before transmit, every frame's text payload is verified to be <= 237 bytes — 237 is the Meshtastic application `Data.payload` limit, not the full on-wire frame (the 16-byte packet header rides outside it; the total LoRa frame caps at 255 bytes). The connector validates the UTF-8 text bytes only; the injected transport owns the serialized-frame limit at its own boundary. Long replies are chunked with a `[part N/M]` prefix whose denominator always equals the emitted part count; the connector guard raises (rather than shipping an over-budget frame) if any part still exceeds the limit after degradation.

### Example Degradation
```python
# In channel_hub/message.py
MAX_PAYLOAD = 237

def _degrade(response: OutgoingMessage) -> tuple[list[str], list[str]]:
    """Degrade rich elements and chunk long replies for the text-only link.

    - Reads response.buttons, response.images, response.cards; drops them
      and emits a notice per element kind (a fresh notice list per response).
    - Chunks on encoded bytes, never splitting a multibyte character: the
      chunk boundary is walked back to the last codepoint boundary before
      decoding, and the '[part N/M] ' prefix bytes always count against
      the 237-byte budget.
    - Derives total from the same chunking the parts use, so the label
      denominator always equals the number of emitted parts.
    """
    notices: list[str] = []

    # Drop buttons -- emit a notice per response
    if response.buttons:
        notices.append("[button dropped: Meshtastic is text-only]")
        response.buttons = []

    # Drop images -- emit a notice per response
    if response.images:
        notices.append("[image dropped: Meshtastic is text-only]")
        response.images = []

    # Drop cards -- emit a notice per response
    if response.cards:
        notices.append("[card dropped: Meshtastic is text-only]")
        response.cards = []

    # The text is already clean (parse_inline_hints stripped markup),
    # but we work with whatever content remains.
    encoded = response.content.encode("utf-8")
    if not encoded:
        return [], notices

    # Provisional total ignores the prefix length; refine until the label
    # denominator equals the actual number of emitted parts.
    total = max(1, (len(encoded) + MAX_PAYLOAD - 1) // MAX_PAYLOAD)
    while True:
        parts: list[str] = []
        idx = 1
        start = 0
        while start < len(encoded):
            prefix = f"[part {idx}/{total}] ".encode("utf-8")
            content_bytes = MAX_PAYLOAD - len(prefix)
            end = min(start + content_bytes, len(encoded))
            # Walk back to a codepoint boundary so we never slice a
            # multibyte character (which would corrupt it and inflate the
            # re-encoded size past the budget).
            while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
                end -= 1
            chunk_text = encoded[start:end].decode("utf-8")
            parts.append(f"[part {idx}/{total}] {chunk_text}")
            start = end
            idx += 1
        if len(parts) == total:
            return parts, notices
        total = len(parts)
```

## 4. Sovereignty

### Real, With One Caveat
Every other connector except webchat/webhook puts a company in the path. The sharper claim is not merely self-hosted but INFRASTRUCTURE INDEPENDENT: it keeps working with no ISP, no internet and no LAN. Caveat to design around rather than a blocker: encryption protects CONTENT, not PRESENCE. Broadcast RF means anyone in range observes that a transmission happened, roughly from where, how often and how large, and RF is direction-findable. Sovereignty over custody and content, not invisibility. Do not let the pitch drift into the latter.

## 5. Concrete First Milestone (Hardware Phase)

### Version 0.1.0 - "Point-to-Point Prototype"
**Target**: Q3 2026 (after hardware arrival)

#### Primary Objectives
1. **Hardware Setup**: Deploy two Heltec V4 modules in point-to-point configuration
2. **Connector Development**: Implement `meshtastic_connector.py` emitting `platform="meshtastic"`
3. **Authentication**: Complete per-device key registration and validation system
4. **Degradation Testing**: Verify rich elements are dropped, long replies are chunked, and the 237-byte budget is enforced

#### Technical Deliverables
- [ ] `meshtastic_connector.py` alongside the seven existing connectors
- [ ] Device key management system with secure storage
- [ ] `MessageRouter.assign_channel("meshtastic", <node_id>, <agent_name>)` wiring
- [ ] Configuration management for radio parameters (freq, SF, channel)
- [ ] Logging and monitoring for security events and degradation decisions
- [ ] Test suite for connector functionality, security properties, and degradation policy

Both modules run ONE shared operating configuration -- same region/frequency slot, same
modem preset (spreading factor/bandwidth), same channel name and PSK -- pinned in the radio
parameter configuration above. Two radios on different frequency slots cannot hear each
other; the prototype defines exactly one config and both modules load it. The pinned
configuration for milestone 1 is:

- Region: `EU_868` -- 869.4-869.65 MHz, sub-band P, centre 869.525 MHz, 10% duty cycle
  (360 s/hour on-air), +27 dBm ERP. This is the only EU/UK slot that allows 10% duty; the
  868.0-868.6 MHz 1% band (36 s/hour) cannot carry the 30-second beacon cadence (see
  Duty-Cycle Budget below).
- Modem preset: `LongFast` -- SF11, BW 250 kHz, coding rate 4/5 (~1.07 kbps link rate).
  Frequency slot 1 (centre 869.525 MHz) is the Meshtastic default after a factory reset, so
  both radios land on the same slot with no manual override.
- Channel name: `LongFast` (the Meshtastic default primary channel).
- PSK: provisioned out of band -- loaded onto each module via the non-radio configuration
  path as a custom 256-bit AES key (never the well-known `AQ==` default), and never
  transmitted over the link.

Modem-preset trade-off (Meshtastic preset table, see References): `LongFast` (SF11,
~1.07 kbps) buys range, `ShortFast` (SF7, ~10.94 kbps) buys throughput -- roughly a 10x
peak-rate swap, with each SF step adding ~2.5 dB of link budget at the long end. Milestone 1
uses LongFast because the off-grid point-to-point pair is range-bound (two fixed sites with
no infrastructure) and LongFast is the Meshtastic EU_868 default, so the two modules agree on
a frequency slot automatically and avoid the exact failure mode (radios on different slots)
called out above.

#### Deployment Architecture
```text
┌─────────────────────────────────────────────────────────┐
│  TAOS Controller                                        │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  channel_hub                                    │   │
│  │  • MessageRouter.get_agent_for_channel("meshtastic", node_id) │
│  │  • Archive and routing pipeline                  │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  meshtastic_connector.py                         │   │
│  │  • Ingest Meshtastic packets                     │   │
│  │  • Verify signature & decrypt                    │   │
│  │  • Degrade rich elements, chunk long replies     │   │
│  │  • Emit IncomingMessage(platform="meshtastic")   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Radio Links (2 Heltec V4 modules)                 │   │
│  │                                                 │   │
│  │  +----------------------+                    │   │
│  │  │  Module 1 (Radio 1) │                    │   │
│  │  │  - shared config    │                    │   │
│  │  │  - 28 dBm TX        │                    │   │
│  │  +----------------------+                    │   │
│  │  │  Module 2 (Radio 2) │                    │   │
│  │  │  - shared config    │                    │   │
│  │  │  - 28 dBm TX        │                    │   │
│  │  +----------------------+                    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

#### MVP Testing Requirements
- [ ] Message round-trip testing: Radio -> connector -> router -> agent -> connector -> Radio
- [ ] Security validation: Verify unsigned frames are rejected
- [ ] Degradation validation: Verify buttons and images are dropped with logged notices
- [ ] Size budget validation: Verify long replies are chunked into <=237-byte parts. Truncation is NEVER a success path — the guard raises rather than shipping or silently trimming an over-budget frame
- [ ] Performance testing: LongFast (1.07 kbps) link rate; latency scoped per payload, a full 237-byte part air-times to ~2.0 s at the pinned preset (~166 ms preamble plus ~1.87 s payload, SF11/250 kHz/CR 4/5), so the target is <1 s connector overhead (ingest -> route -> transmit handoff) on top of airtime, not <1 s end-to-end for maximum-size messages

#### Duty-Cycle Budget (EU_868, LongFast)

On-air time of one frame at the pinned preset (SF11, 250 kHz, coding rate 4/5, Meshtastic
16-symbol preamble). Symbol time `T_sym = 2^SF / BW` = 8.192 ms; DE = 0 because T_sym
= 8.192 ms < 16 ms so low-data-rate optimisation is not mandatory. Total on-air time:
`ToA = (n_preamble + 4.25) * T_sym + n_payload * T_sym` (Semtech AN1200.13 form, see
References).

For the payload-symbol count, with header IH = 0 (explicit header), CRC on (CRC = 1),
coding rate CR = 1 (4/5), DE = 0, SF = 11:

    n_payload = 8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH) /
                  (4*(SF - 2*DE))) * (CR + 4), 0)

PL = 237 bytes: n_payload = 8 + ceil(1896 / 44) * 5 = 8 + 43 * 5 = 228 symbols.
PL = 24 bytes:  n_payload = 8 + ceil(192  / 44) * 5 = 8 + 5  * 5 = 33  symbols.

- One full 237-byte part: ~2.03 s (20.25 preamble symbols = 165.9 ms + 228 payload
  symbols = 1.87 s). At the ~1.07 kbps link rate the pure payload serialization is ~1.77 s;
  the duty-cycle cap makes the full ~2.03 s of air time what counts.
- One status beacon: ~0.44 s, assuming a 24-byte payload (node id, uptime, battery,
  link-health). The spec does not define a beacon size, so 24 bytes is a pinned prototype
  assumption.

**Payload definition:** the 237-byte and 24-byte figures above are the Meshtastic application
`Data.payload` budget (see the size-budget bullet in MVP Testing Requirements and the Hard
Size Budget section). The actual on-air PHY frame adds the 16-byte Meshtastic packet header
and protobuf framing overhead that rides outside `Data.payload`, so a firmware engineer
building the LoRA frame must add those bytes to arrive at the full PHY payload size when
evaluating `n_payload`. Both readings reach the same conclusion — the 10% slot is sufficient,
the 1% slot is not — but the margin tightens slightly under PHY overhead: beacons consume
roughly 67 s (120 × ~0.56 s for a ~44-byte PHY frame), leaving approximately 293 s for
roughly 135 full application parts per hour, for a total of roughly 359 s against the 360 s
cap.

Hourly on-air budget under the EU_868 cap:

- 10% duty = 360 s/hour. 120 beacons/hour (~53 s) leaves ~307 s for application traffic,
   i.e. ~150 full 237-byte parts (~305 s). Beacons (~53 s) plus target rate (~305 s) total
   ~358 s, fitting the 360 s cap.
- 1% duty = 36 s/hour. The 120 beacons alone (~53 s) already exceed 36 s, so beacons plus
  any target rate do NOT fit 1%. No application traffic is available on a 1% band, which is
  why the prototype is pinned to the sub-band P 10% slot.

The ~1.07 kbps figure is the per-transmission link rate from the LongFast preset; the 10%
duty cycle caps sustained hourly-average throughput at ~0.07 kbps (~135 parts/hour at
~2.16 s on-air per application part under PHY overhead), so "sustained" in the 1% sense
is incoherent here -- the link is beacon-bound, not throughput-bound.

#### Success Criteria
1. **Functional**: Both radio modules connect and exchange messages
2. **Security**: All unsigned/replayed messages are rejected
3. **Degradation**: Rich elements are dropped and long replies are chunked
4. **Performance**: Status beacons sent every 30 seconds (120/hour) and 120 beacons plus the target message rate fit inside the 10% duty-cycle budget but not 1% (see Duty-Cycle Budget)
5. **Reliability**: Connector survives controller reboot without reconnection

### Notes
- This design focuses on the security model first as required
- Firmware implementation will follow after this design is approved
- The connector is a CONTROL channel, not a data tunnel
- All security decisions must be made before hardware deployment
- The EU/UK sub-band P / 10% duty-cycle figures above are EU-specific; other regions pin their own region code (e.g. US, CN, JP) and the duty-cycle budget must be re-run for that band plan

## References
- [Heltec WiFi LoRa 32 (V4)](https://heltec.org/project/wifi-lora-32-v4/)
- [Meshtastic Documentation](https://meshtastic.org/)
- [Meshtastic LoRa config (region and preset tables)](https://meshtastic.org/docs/configuration/radio/lora/)
- [Meshtastic radio settings (EU_868, 869.525 MHz centre, 10% duty)](https://meshtastic.org/docs/overview/radio-settings/)
- [LoRa time-on-air formula (Semtech AN1200.13)](https://www.semtech.com/products/wireless-rf/lora-software/sx1301sip)
- [taOS channel_hub Architecture](/tinyagentos/channel_hub/)
- [channel_hub/message.py](/tinyagentos/channel_hub/message.py)
- [channel_hub/router.py](/tinyagentos/channel_hub/router.py)
- [Jay's Note 2026-08-28](note-260828-f0fa88.md) — reference implementation

---
*Document created: 2026-08-28*
*Status: Draft design note*
*Author: taOS Lead*
*Tags: lora, meshtastic, channel_hub, security, radio*
