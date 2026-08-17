### Fixed

- Distrust green gate: CI check now fails PRs where added or modified test files have all tests skipping via `pytest.importorskip` or `pytest.skip`, with an escape hatch for intentional landing tests (`Tests-Skipped-Intentionally` trailer in PR body).