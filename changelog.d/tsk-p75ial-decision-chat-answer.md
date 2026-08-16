### Added

- Decision blocks in chat now support clickable option buttons for answering decisions directly. Users can select options or enter text answers in the chat interface, which uses the same API endpoint as the Decisions app.

- Agents can no longer answer their own decisions. The answer endpoint now validates that decisions are answered by the human user assigned to them, not by the agent who created them.

- First-answer-wins logic ensures that when the same decision is answered concurrently from both the chat and Decisions app surfaces, exactly one answer is recorded. The second answer attempt receives a clean rejection error.

- Both chat and Decisions app surfaces update live in real-time through the existing broker/SSE machinery. Answering in chat resolves the card in an open Decisions app without requiring a page refresh, and vice versa.