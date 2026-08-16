### Fixed
- project_notes scope now requires project_id binding when granting via auth request approve, rejecting the unbound approvals that previously minted inert grants (approval looked successful while the agent silently had no notes access)
