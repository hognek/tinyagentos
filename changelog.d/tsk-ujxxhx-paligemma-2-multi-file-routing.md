### Fixed
- paligemma-2: pin hf_revision to immutable commit, replace metadata sha256 with file_set_hash for multi-file install verification
- POST /api/models/download: route multi_file variants through HFMultiInstaller instead of the single-file download path
