### Added
- Remote DM channel rendering in Messages app (type=dm-remote, Globe icon, Remote sidebar section)
- Delivery-tick states for dm-remote messages (single Check for sent, double CheckCheck for delivered)
- Offline indicator in ChannelSidebar (Wifi/WifiOff icons with connection status)
- PeerOutboxStore exponential backoff retry (60s → 120s → 300s → 600s → 1800s cap)
- remote_msg_id dedupe via unique constraint on (channel_id, remote_msg_id)
- Offline-queue drain on peer last_seen refresh via mark_peer_seen peer_outbox integration
