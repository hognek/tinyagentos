### Fixed

- The changelog collator now refuses fragments that start with a YAML frontmatter `---` delimiter instead of silently pasting the frontmatter into CHANGELOG.md. The doc-gate invariants step now also validates that every `changelog.d/*.md` fragment contains only markdown bullets, section headings, or indented continuation lines, rejecting any fragment that carries `---` delimiters or `title:` keys.
