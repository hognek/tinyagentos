### Fixed

- Repaired five existing `changelog.d/` fragments that violated the new shape invariant (fenced code block, standalone prose paragraphs, and trailing `S2-23:` lines), so the `Doc drift gate` job passes again.
- Documented the fragment shape rule in `docs/changelog-fragments.md` and aligned `scripts/collate_changelog.py` to refuse leading `title:` frontmatter the same way the gate does.
