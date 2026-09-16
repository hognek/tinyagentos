- Phone kiosk: replaced the `cage` compositor with `sway`, which implements
  `wlr-output-power-management-v1`. The screen now really powers down after 30s
  idle (cage could only dim the backlight, leaving the output powered and touch
  live) and the hardware power key toggles the display.
- Added a phone lock screen: console PIN requests render a clock, device and
  battery chips, a native round PIN keypad, and Dynamic-Island style agent pills
  fed by a new console-only `GET /auth/lock-widgets`. LAN browsers still get the
  plain login card.
- Lock screen: the keypad is no longer always on screen. The resting screen is
  the clock, the widgets and the agents; a home-indicator bar at the bottom
  raises the passcode, by swipe or by tapping it.
- Agent islands are pressable. Press-and-hold opens the agent's conversation in
  a bottom sheet with the background blurred; an island that is waiting on a
  decision pulses and opens an Approve/Deny sheet instead. Answering a real
  decision still requires unlocking -- the lock screen holds no session.
- Pinned the OS's own agent to the top of the island list, with the product mark
  and its OMP harness badge.
- Fixed: waking the screen with the POWER KEY left the phone lit indefinitely.
  Powering the output on over the compositor IPC produces no input event, so
  swayidle never saw its resume, stayed latched idle and never reached its
  timeout again. The key handler now re-arms the idle watcher through the
  compositor.
- Fixed: the conversation sheet opened empty. `/auth/lock-thread/` was never
  added to the auth middleware's exempt prefixes, so the lock screen — which
  renders before sign-in — got a 401 with nothing shown and nothing logged.
- Lock screen chrome: product name and battery moved to a top status bar as
  plain text; the device hostname is gone. Dictation button on every island
  opens a voice sheet whose waveform is driven by the real microphone.
- Fixed: "Use my password instead" dropped the lock-screen class, which threw
  away `overflow:hidden` (a chromium scrollbar appeared) and un-hid the
  keyboard's floating toggle. The password form now stays on the lock screen
  and raises the keyboard itself.
- Fixed: the conversation sheet was dismissed by any downward drag, so the
  thread could not be scrolled. Dismissal is now the header/grabber only.
