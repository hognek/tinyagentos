### Fixed

- Auth requests now display the requested grant duration in consent cards and notifications. The human-readable duration is shown (e.g., "expires in 1 hour") when `duration_secs` is set, and "no expiry" when it is not.

- Backend routes now include `duration_secs` and `human_duration` in response payloads for both auth-request status and approval responses.

- Frontend consent actions now display the duration information with proper accessibility labels for screen readers.