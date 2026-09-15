### Fixed
- The SPA now correctly rejects the coarsened sentinel "taOS" version header from unauthenticated responses, preventing it from overwriting valid backend versions and falsely triggering update notifications. The shared `isValidVersion()` predicate now guards both health polling and version reporting to ensure a version must start with a digit to be accepted.
