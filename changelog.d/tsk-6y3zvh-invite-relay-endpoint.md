### Added
- Invite bundle `relay` endpoint kind: when `TAOS_CONTROLLER_RELAY_URL` is set to an `https://` URL (or a private address), it is emitted at priority 1 ahead of LAN and mesh endpoints. Public `http://` relay or callback-host endpoints are omitted with a logged warning rather than downgraded to cleartext.
