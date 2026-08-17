### Fixed

- paligemma-2 manifest: switch from single-shard `download_url` to `hf_repo` + `multi_file: true` so the installer fetches all shards; added combined-hash verification to `HFMultiInstaller` and a sweep-test guard that flags any sharded `download_url` missing the multi-file marker.
