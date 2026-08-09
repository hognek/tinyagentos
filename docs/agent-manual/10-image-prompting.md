<!-- How to write good prompts for the generate_image tool. -->

# Generating good images

Prompt quality drives results. Spend a sentence getting it right rather than
regenerating five times.

## Structure a prompt

A reliable order:

1. **Subject** — what it is. "a small red sailboat", "a friendly cartoon fox".
2. **Descriptors** — appearance, colour, material, mood. "weathered wooden hull,
   bright red sail".
3. **Setting / background** — where it is. "on a calm blue lake at sunrise".
4. **Composition** — framing and viewpoint. "wide shot, centred, low angle".
5. **Style** — the look. "watercolour children's book illustration", "flat vector
   art", "photorealistic", "oil painting". Naming a concrete style matters more
   than any other single word.
6. **Lighting / quality** — "soft warm light, gentle shadows, highly detailed".

Example: `a friendly cartoon fox under a tree, autumn leaves, warm light, watercolour
illustration, centred, highly detailed`.

## Principles

- **Be specific, not long.** Concrete nouns and adjectives beat a wall of vague words.
- **Front-load what matters.** Earlier words carry more weight; put the subject and
  must-have details first.
- **One clear scene.** Don't pack unrelated ideas into one prompt; the model blends
  them into mush. Generate separate images instead.
- **Name the style explicitly.** For a storybook look, say "children's book
  illustration" or "storybook watercolour"; for a logo, say "flat minimalist vector logo".
- **Match the user's intent.** Describe what they pictured, not a generic version.

## Use negative_prompt to remove faults

`negative_prompt` lists what to avoid (comma-separated). It is the fix for common
defects:

- General cleanup: `blurry, low quality, jpeg artifacts, watermark, text, signature`.
- People/animals: add `deformed hands, extra fingers, extra limbs, mutated`.
- Keep a clean style: add `cluttered, busy background` for simplicity.

## Parameters (what the tool exposes)

- **size** — `256x256`, `384x384`, or `512x512`. Use 512x512 for final artwork;
  smaller only for a quick draft.
- **steps** — 1 to 8 (default 4). 4 is a good balance; 6 to 8 for more detail.
- **guidance_scale** — 1 to 20 (default 7.5). Raise when the model ignores a
  requested detail; lower if results look over-baked.
- **seed** — omit for a fresh image. To tweak a liked image, reuse its `seed` and
  keep the prompt close.
- **model** — call `describe_image_capabilities` first; a fast NPU model for
  drafting, a GPU model for the final cover. Omit to auto-pick.

## Picking a model by intent

Model families differ: FLUX-style models follow full natural-language sentences;
SDXL-style models like comma-separated phrases and strong style keywords. Text in
the image is unreliable on most models, so keep it short and quoted, e.g.
`a poster titled "Brave Little Fox"`.

## Iterate deliberately

If the first image is close but not right, change one thing at a time (a style
word, a missing detail, a negative term), keep the same seed, and tell the user
what changed.
