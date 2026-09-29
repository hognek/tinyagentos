### Fixed
- A lock-screen event stream that (re)opens, for example after a controller restart, now starts with the current screen state (`screen-off` or `screen-on`) as its first event, sent to that client only. The page pauses its widgets poll on `screen-off`, so a reopen while the panel is dark no longer resumes the poll until the next screen-off.
- The status-change highlight on a lock-screen agent island now stays for its full 700 ms. The attribute that drives it was removed after 380 ms, cutting the glow off partway; its lifetime is now a named constant tied to the keyframe duration.
