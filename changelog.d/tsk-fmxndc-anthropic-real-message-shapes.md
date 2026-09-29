### Fixed

- Anthropic through the LLM gateway now reads tool calls in the shape Anthropic actually sends: a flat `tool_use` block with `id`, `name` and an object `input`, turned into an OpenAI `tool_calls` entry whose `arguments` is a JSON string. Text written before a tool call is kept.
- Anthropic `stop_reason` is mapped to OpenAI `finish_reason` (`end_turn` and `stop_sequence` to `stop`, `max_tokens` to `length`, `tool_use` to `tool_calls`); any other value becomes `stop` and is logged. Clients that decide whether to run tools from `finish_reason` now see `tool_calls`.
- Streamed Anthropic responses are parsed from their real `event:`/`data:` frames and re-emitted as OpenAI `chat.completion.chunk` frames, with streamed tool arguments assembled from `input_json_delta` pieces, usage taken from `message_start` and `message_delta`, and a closing `data: [DONE]`.
- The Anthropic translator no longer carries an MIT licence header; it is AGPL-3.0 like the rest of taOS core, with a note that its design follows aisuite.
