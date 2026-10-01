### Fixed

- BLE pairing for Orb boards no longer mints or seals a model key (`llm` block) into the provision bundle; `revoke_for_node` is still called on (re)pair to retire any legacy key minted under the same name.
