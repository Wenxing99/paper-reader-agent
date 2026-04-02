# ROADMAP

`ROADMAP.md` tracks upcoming requirements, priorities, and staged implementation notes.

Guardrails:
- Product and development constraints still follow [AGENTS.md](./AGENTS.md).
- This file captures planning, not irreversible implementation promises.
- New capabilities should default to MIT-compatible implementation paths.

## Rollout Discipline

The most important recent lesson is that front-end interaction changes must ship in smaller steps, especially around the center PDF reader.

Execution rules:
- Do not change button layout, initialization state, keyboard shortcuts, scroll anchoring, and caching strategy in the same iteration.
- Prefer single-point, high-signal, low-regression improvements over bundled interaction rewrites.
- Any change that touches PDF reader boot, PDF import, or first-page rendering should be split into 2 to 4 small iterations.
- Left-column and right-column rendering upgrades can usually go before center-reader core changes because the regression surface is smaller.
- After each front-end change, verify at minimum: app boots, importing a PDF responds, the first page appears, and reading guide / chat / text selection still work.

## Current Priorities

### P1. Markdown + Formula Rendering

Goal: make the left reading guide and right AI chat suitable for math and statistics papers.

Near-term tasks:
- Render Markdown in the reading guide.
- Render Markdown in chat responses.
- Support inline math and block math.
- Support basic lists, code blocks, and tables.
- Keep a plain-text fallback so rendering failures do not make content unreadable.
- Preserve copy, selection, and scrolling behavior after rendering.

Implementation notes:
- Prefer MIT-compatible libraries by default.
- If a Markdown or LaTeX rendering library is added, check license compatibility first and update `THIRD_PARTY_NOTICES.md` in the same working session.
- If HTML sanitization is needed, use an MIT-compatible safety layer.

### P2. Reading Guide Progress Feedback

Goal: reduce uncertainty while a reading guide is being generated.

Stage 1:
- Show an explicit in-progress state inside the left column.
- Use stage-based progress instead of fake percentages.
- Example stages: read paper -> build context -> draft section summaries -> assemble reading guide.

Stage 2:
- Add true percentage progress only after backend work is split into measurable steps.
- If feasible, add estimated remaining time or a clearer current-stage description.

Design notes:
- Do not add misleading fake progress bars.
- Progress feedback should live in the left reading-guide area, not compete with the center PDF surface.

### P3. PDF Reader Ergonomics

Goal: keep improving the center PDF reader, but only through smaller independent releases.

Near-term tasks:
- First small step: raise the zoom ceiling to at least `300%`.
- If stable, consider a separate follow-up step for `400%`.
- Put `Actual Size` and `Fit Height` into their own later iteration.
- Put keyboard shortcuts, zoom anchoring, and scroll-position preservation into separate later iterations.
- Each step must be independently shippable and reversible.

Design notes:
- Keep the paper-first layout.
- Do not make the reader header tall again just to add more controls.
- Any reader improvement must preserve continuous reading, independent scrolling, and import stability first.

## Recommended Execution Order

1. Markdown + Formula Rendering.
2. Reading Guide Progress Feedback.
3. PDF Reader Ergonomics in smaller steps.

Why this order:
- Left and right rendering-layer work addresses a core user need and is less likely to break the PDF reader startup path.
- Reading guide progress feedback improves waiting experience without requiring another reader-core rewrite.
- PDF reader ergonomics still matter, but should now follow a much safer rollout rhythm.

## Stage A + Stage B Formula Understanding Path

Detailed implementation sketch: [docs/formula-selection-pipeline.md](./docs/formula-selection-pipeline.md)

Context: for complex formulas inside PDF selection actions, plain text extraction is often not enough. A future two-stage path is approved in principle:
- Stage A: crop the selected region and recover math-friendly structured text, ideally LaTeX.
- Stage B: explain or translate based on the Stage A output plus local paper context.

Important product note:
- Stage A alone is not the complete solution. It only solves the recovery problem: what symbols and structure are present in the selected region.
- Stage A + Stage B together are the full solution for mixed selections such as body text + theorem statement + complex formula, or similar math-heavy passages.
- For this product, the end goal is not just formula OCR. The end goal is paper-aware understanding grounded in both the recovered math and the surrounding argument.

Current recommendation ranking for Stage A candidates:
1. Pix2Text
2. TexTeller
3. LaTeX-OCR / pix2tex
4. Simple-LaTeX-OCR

Why this order:
- Pix2Text is the best fit for mixed regions that may contain theorem text plus formulas, and it appears to stay on the MIT-compatible path.
- TexTeller looks especially strong for dense or multi-line formulas and is a strong second option, especially if we later support a formula-only routing path.
- LaTeX-OCR / pix2tex is a mature pure-formula baseline and a good fallback if we want the simplest first OCR experiment.
- Simple-LaTeX-OCR is worth watching, but not preferred for the first integration pass.

Current exclusions:
- Texo is not a default option because AGPL-3.0 conflicts with the current MIT-first direction.
- Nougat is not a default option because the code and model-license story is not as clean for this repository's current path.

Roadmap implication:
- If formula selection continues to be a core pain point after the current Markdown/math rendering improvements, the Stage A + Stage B path should be treated as a future high-value track.
- The first implementation should keep the OCR backend replaceable and make the intermediate Stage A output visible for debugging and trust.
- Stage B should be designed as a paper-aware interpretation layer rather than a generic post-processing step.

## Open Questions

- Should tables and code highlighting ship with the first Markdown renderer, or should the first pass focus on text and formulas only?
- Is KaTeX the right first formula renderer, or is another MIT-compatible option preferable?
- Should reading-guide progress also appear as a small secondary status near the top action bar?

## Definition Of Done For This Roadmap Slice

This slice is done when:
- The left and right columns render common Markdown and math cleanly.
- Reading guide generation exposes credible progress feedback.
- Future PDF-reader upgrades can land in smaller steps without breaking import or startup.
- New implementation choices stay on the MIT-compatible path.

