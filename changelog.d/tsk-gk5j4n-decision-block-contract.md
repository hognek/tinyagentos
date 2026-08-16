### Added
- DecisionBlock tests updated to assert new interactive contract: `disabled={!isOpen}` — open decisions render enabled controls that submit answers, and non-open decisions render disabled controls
- Added first-answer-wins test verifying that submitting a second answer is rejected when decision status is no longer "pending"