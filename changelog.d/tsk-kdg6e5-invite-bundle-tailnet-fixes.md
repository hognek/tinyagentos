### Fixed
- Invite bundle now correctly advertises Tailscale CGNAT IPs (100.64.0.0/10) and Tailscale ULA (fd7a:115c:a1e0::/48) as priority-1 LAN endpoints instead of omitting them with a false "public address" warning.
- Hostname overrides ending in `.local`, `.lan`, `.home.arpa`, `.ts.net`, or single-label LAN names are now advertised over HTTP (previously all hostnames were omitted).
- Full-URL override (e.g. `http://192.168.1.5:6969`) now deduplicates correctly against LAN IP enumeration by comparing parsed hostname.
- Relay endpoint (`TAOS_CONTROLLER_RELAY_URL`) now requires `https://` only; `http://` relay URLs are omitted even for private addresses.
- Bare IPv6 callback overrides (e.g. `fd7a:115c:a1e0::1`) are now bracketed in the advertised bundle URL so they parse correctly and do not produce malformed endpoints.