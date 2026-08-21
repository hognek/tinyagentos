### Fixed

- An unclean shutdown could leave `data/.auth_user.json` intact in size but
  full of NUL bytes, which taOS read as "no accounts exist" and answered with
  the first-run onboarding screen — and completing that form overwrote the
  real accounts. The account store, the session store, the legacy password
  file and the local auth token are now written atomically (temp file, fsync,
  rename, directory fsync), and an account store that exists but cannot be
  parsed now fails closed: the install still reports itself as configured,
  onboarding is refused, and `/auth/status` returns `store_error: "unreadable"`.
