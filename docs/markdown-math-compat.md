# Markdown and Math Compatibility Notes

This document records the repo-level rules for rendering math through the current right-panel pipeline:

1. model output -> Markdown string
2. markdown-it renders HTML
3. KaTeX auto-render scans the rendered HTML for math delimiters

Because Markdown runs before KaTeX, some characters are high-risk even when the final intent is valid LaTeX.

## Source Notes

- CommonMark treats `*` and `_` as emphasis delimiters and allows backslash escaping for ASCII punctuation.
- KaTeX supports normal TeX subscripts with `_`, literal underscore with `\_`, and math symbols such as `\ast`.

Useful references:
- https://spec.commonmark.org/0.31.2/
- https://katex.org/docs/supported

## Repo Rules

### 1. Always wrap math explicitly

- Inline math must use `$...$`.
- Display math must use `$$...$$`.
- Do not use plain parentheses like `(x)` or square brackets like `[ ... ]` as math delimiters.

### 2. Keep `_` for subscripts

- Use `$P_a$` for a normal subscript.
- Do **not** rewrite that as `$P\_a$`.
- Use `\_` only when the underscore itself is literal text, not a subscript.

### 3. Avoid raw `*` inside math when it means a star symbol

- In this pipeline, raw `*` is risky because Markdown also uses it for emphasis.
- When the symbol is a wildcard or star index, prefer `\ast`.
- Example: write `P_{\ell,\ast}` instead of `P_{\ell,*}`.

### 4. Prefer braced style commands

- Prefer `\hat{K}` over `\hat K`.
- Prefer `\mathbb{P}` over `\mathbb P`.
- Prefer `\mathcal{Q}` over `\mathcal Q`.

These forms are easier to normalize and less likely to degrade when the model rewrites formulas.

### 5. Keep prose outside math mode when possible

- If a word must appear inside math, use `\text{...}`.
- Do not leave free prose mixed into a display-math block unless it is wrapped as text.

### 6. Be conservative in local normalization

The shipped normalization layer should:
- fix obvious delimiter mistakes;
- normalize high-risk tokens like wildcard `*`;
- add braces to a small set of common style commands when they are obviously missing.

It should not try to repair arbitrary broken LaTeX by guesswork.

## Current Shipped Normalization Targets

The current local pass is intentionally narrow. It may normalize:
- `P_{\ell,*}` -> `P_{\ell,\ast}`
- `\hat K` -> `\hat{K}`
- `\mathbb P` -> `\mathbb{P}`

Anything more ambiguous should stay in the model-facing prompt or be handled by Stage A / Stage B rather than a wide local rewrite.
