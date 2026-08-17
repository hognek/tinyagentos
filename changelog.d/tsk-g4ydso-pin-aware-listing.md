### Fixed
- pin-aware HF listing now uses the revision-path `blobs=true` endpoint so nonexistent revisions 404 and real file sizes are returned
- per-file `lfs.sha256` verification after download catches corrupted or mismatched shards
- paligemma-2 `file_set_hash` recomputed with real sizes from the pinned-revision blobs listing
