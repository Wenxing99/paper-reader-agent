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

### P1. Reading Guide Progress Feedback Follow-Up

Goal: keep the new stage-based guide feedback honest, calm, and informative.

Current baseline:
- The left column already shows stage-based progress while a reading-guide job is running.
- The current implementation intentionally avoids fake numeric percentages.

Observed issue to revisit later:
- If the user imports a new paper and immediately starts guide generation, the visible progress can feel non-intuitive: stage 1 is visible, stage 3 often becomes visible, while stages 2 and 4 may appear to be skipped entirely.

Next tasks:
- Refine current-stage wording and failure recovery hints.
- Consider whether a very small secondary status near the top action bar adds value without stealing space from the paper.
- Add true percentage only after backend work is split into measurable chunks.

### P2. PDF Reader Ergonomics

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

### P3. Stage A + Stage B Formula Selection Pilot

Goal: prepare the first real implementation slice of the mixed-selection formula pipeline.

Current baseline:
- Selection rectangle capture and crop-debug preview are now wired into the existing selection-action flow.
- The current slice is still debug-first: it validates region capture and crop fidelity before OCR is introduced.
- The last local-OCR experiment was rejected because the latency and local model-loading cost were not acceptable for the product direction.

Near-term tasks:
- Start with selection-rectangle capture and cropped-image debugging output.
- Keep the OCR backend replaceable from day one.
- Avoid committing to a heavyweight OCR dependency before the crop/debug path is proven.
- Feed Stage A output into Stage B only after the crop and OCR draft are inspectable.

Design notes:
- Treat mixed selections such as body text + theorem statement + complex formula as the target case.
- Stage A + Stage B is an enhanced path for complex math-heavy selections, not the default path for every selection.
- Normal prose selections should continue to use the lighter text-only path unless there is a clear reason to escalate.
- Stage A and Stage B should remain separable for debugging and caching.
- Keep the path MIT-compatible by default.

## Recommended Execution Order

1. Reading Guide Progress Feedback Follow-Up.
2. PDF Reader Ergonomics in smaller steps.
3. Stage A + Stage B Formula Selection Pilot.

Why this order:
- Guide progress has already landed and can now be polished without reopening the old synchronous blocking flow.
- PDF reader ergonomics still matter, but should continue to ship in smaller and safer steps.
- Formula selection is strategically important, but should begin with a narrow debug-first slice once the smaller interaction surfaces remain stable.

## Stage A + Stage B Formula Understanding Path

Detailed implementation sketch: [docs/formula-selection-pipeline.md](./docs/formula-selection-pipeline.md)

Context: for complex formulas inside PDF selection actions, plain text extraction is often not enough. A future two-stage path is approved in principle:
- Stage A: crop the selected region and recover math-friendly structured text, ideally LaTeX.
- Stage B: explain or translate based on the Stage A output plus local paper context.

Important product note:
- Stage A alone is not the complete solution. It only solves the recovery problem: what symbols and structure are present in the selected region.
- Stage A + Stage B together are the full solution for mixed selections such as body text + theorem statement + complex formula, or similar math-heavy passages.
- For this product, the end goal is not just formula OCR. The end goal is paper-aware understanding grounded in both the recovered math and the surrounding argument.

Current direction for Stage A:
- keep the already-working crop-debug path;
- do not ship a local OCR backend by default;
- next try should send the cropped image to a vision-capable model that can recover LaTeX quickly;
- Stage B should then interpret that recovered LaTeX in paper context.

Current cautions:
- Local OCR backends remain interesting for research, but they are not the default product path after the recent latency test.
- Any future vision-model route must still stay aligned with the repo's MIT-first shipped surface and local-first architecture.

Roadmap implication:
- If formula selection continues to be a core pain point after the current Markdown/math rendering improvements, the Stage A + Stage B path should be treated as a future high-value track.
- The next implementation should keep the crop/debug output visible for trust and use it as the handoff into a vision-capable Stage A.
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

