### Fixed

- project_create decisions that fail during approval now route a specific failure reply to the asking agent instead of falling through to the generic 'approve' message. Every failure path in `_apply_project_create_grant` returns True after refusing the auth request, so the agent is never told it was approved when the project creation, grant write, or acceptance actually failed.