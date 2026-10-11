### Fixed
- A2A GPU lease: a holder's claim and release on the same resource are now serialized, so a release that reaches the bus after a concurrent new claim can no longer clear that newer `[GPU CLAIM]` while the local lease stays held.
