### Fixed

- **Item 1 (LLM GATEWAY COST KEY)**: Fixed `cost_of` callers in `tinyagentos/llm_gateway/forward.py` and `tinyagentos/llm_gateway/embeddings.py` to pass `route.backend_type or route.backend_name` instead of `route.backend_name`. This ensures local backends with custom names (e.g. `llama-cpp` backend named `pi-npu`) are correctly billed as $0, and OpenRouter backends are not mistakenly priced from the direct-provider price table.
