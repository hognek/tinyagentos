### Fixed
- A2A bus stream proxy now emits `: ping` heartbeats on a timer independent of upstream activity, so idle streams are kept alive and not reaped by intermediaries.
