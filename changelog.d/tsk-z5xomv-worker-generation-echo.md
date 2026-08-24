### Fixed: worker generation echo in register/heartbeat responses

- The controller now echoes the current generation in both POST /api/cluster/workers
  (register) and POST /api/cluster/heartbeat responses, enabling the split-brain
  layer-2 protection (manager.py:110-115, 294-299) that was previously unreachable
  because the responses carried no generation field.