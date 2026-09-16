### Added

- Phone lock screen: a row of seven icons above the feed chooses what it shows
  — agents, phone, mailbox, apps, alerts, system and settings — with agents the
  default and the resting state. It is a real tablist: one tab stop, traversed
  with the arrow keys, so it does not put six dead ends between the clock and
  the unlock button.
- Phone lock screen: long-pressing an agent island's avatar opens that agent's
  menu. Nothing in it acts on the agent — the screen renders before sign-in, so
  the menu records what was asked for and then requires the passcode, the way
  the decision sheet already does. A short tap and a long press on the rest of
  the island keep opening the conversation as before.
- Phone lock screen: a system view reporting CPU, memory and GPU clock, plus the
  remote processors as running/offline chips, from a new console-only
  `/auth/lock-stats`. It reports only what the hardware exposes: there is no NPU
  utilisation counter on this SoC, so none is shown, the GPU is labelled as a
  clock rather than as usage, and anything unmeasured renders `--` rather than
  zero.
