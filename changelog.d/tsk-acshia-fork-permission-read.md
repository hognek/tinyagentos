### Fixed

- A failed permission read for one reviewer no longer aborts fork-PR evaluation before later qualifying approvals are checked. The gate now records the first failing login and continues, returning EXIT_OK as soon as a valid admin/write approval is found, and only returning EXIT_ERROR naming that login if no approval qualified.
