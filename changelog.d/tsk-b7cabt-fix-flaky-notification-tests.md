### Fixed

- Fixed flaky notification tests that assumed `list()` return order. Tests in `test_notifications.py` and `test_notifications_agent_grant.py` now select notifications by content (title) instead of by list position (`items[0]` or `items[-1]`), since `ORDER BY timestamp DESC` makes `items[-1]` the oldest row and ties on whole-second timestamps are non-deterministic.