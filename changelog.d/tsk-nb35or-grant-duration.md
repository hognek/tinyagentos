### Fixed

- Agent consent cards and notifications now display human-readable grant duration bounds (e.g., "expires in 1 hour", "no expiry") when duration_secs is set on auth requests, making it clear to approvers how long the grant will last. This addresses the issue where unbounded grants and bounded grants were indistinguishable in the UI.

- Updated backend notification messages and auth-request status responses to include human-readable duration information
- Updated frontend ConsentActions component to display the human-readable duration in the consent UI
- Updated frontend AuthRequestCard component in the Decisions app to display grant duration information
