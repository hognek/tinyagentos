### Fixed: worker generation echo in register/heartbeat responses

- WorkerAgent now echoes the controller's generation on every register and heartbeat request,
  enabling the split-brain layer 2 protection (manager.py:110-115, 294-299) that was previously
  unreachable because workers never sent a generation field.