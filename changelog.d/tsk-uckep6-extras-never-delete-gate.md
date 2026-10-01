### Fixed

- Moved the extras never-delete rule (a) from pytest into `scripts/check_extras_never_deleted.py` and wired it into the deleted-symbols gate workflow, fixing the `no merge base with origin/dev` failure on every CI shard
