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
- Completed: the zoom ceiling has been raised to `400%` as the first safe reader ergonomics step.
- Follow-up work should stay separate: do not bundle new zoom controls or keyboard behavior into the same iteration.
- Put `Actual Size` and `Fit Height` into their own later iteration.
- Put keyboard shortcuts, zoom anchoring, and scroll-position preservation into separate later iterations.
- Restore clickable PDF link annotations and internal citation/reference jumps; the current reader can show linked text styling but still cannot follow those links into the reference section or other in-paper destinations.
- Right-column layout polish should stay a separate task from reader controls: widen the chat-column ceiling and reduce full-panel horizontal scrolling without reopening the PDF reader state machine.
- Each step must be independently shippable and reversible.

Design notes:
- Keep the paper-first layout.
- Do not make the reader header tall again just to add more controls.
- Any reader improvement must preserve continuous reading, independent scrolling, and import stability first.
- For the right chat column, prefer local overflow on genuinely long formula blocks over horizontal scrolling for the entire chat panel.

### P3. Stage A + Stage B Formula Selection Pilot

Goal: prepare the first real implementation slice of the mixed-selection formula pipeline.

Current baseline:
- Selection rectangle capture and internal crop handoff are wired into the existing selection-action flow.
- Math-heavy selections can now route through Stage A (vision-capable LaTeX recovery) and Stage B (paper-aware final explanation or translation).
- Normal prose selections still stay on the lighter text-only path.
- Intermediate crop and draft artifacts are no longer part of the default user-facing UI.
- The last local-OCR experiment was rejected because the latency and local model-loading cost were not acceptable for the product direction.
- Complex display math in the right panel is improved but not fully converged yet; some long theorem/probability formulas still fall back to visibly raw `$$ ... $$` text instead of rendering cleanly.

Near-term tasks:
- Harden the Stage A -> Stage B output contract and fallback behavior.
- Make the image-capable bridge route more robust before adding more UI.
- Keep Stage B on a single model pass that returns Markdown with KaTeX-friendly delimiters.
- Prefer Stage A as the source of truth for long display equations: next try should let Stage B reference recovered display formulas by placeholder rather than rewriting them from scratch.
- Preserve the current selective routing: math-heavy selections may escalate, normal prose should not.
- Decide later whether internal debug output needs a developer-only toggle rather than a default surface.

Design notes:
- Treat mixed selections such as body text + theorem statement + complex formula as the target case.
- Stage A + Stage B is an enhanced path for complex math-heavy selections, not the default path for every selection.
- Normal prose selections should continue to use the lighter text-only path unless there is a clear reason to escalate.
- Stage A and Stage B should remain separable for debugging and caching.
- Stage B should return Markdown with KaTeX-friendly inline and display math delimiters.
- For long display equations, Stage B should preferably reference the recovered Stage A equation rather than re-authoring the full block.
- Symbol-level normalization should follow [docs/markdown-math-compat.md](./docs/markdown-math-compat.md).
- Keep any local formatting repair deterministic and minimal; do not add a second model repair pass by default.
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
- Formula-heavy selection is now an active high-value track rather than a purely future idea.
- The next iterations should keep Stage A as an internal handoff layer and keep Stage B as the user-visible result.
- Stage B should remain a paper-aware interpretation layer rather than a generic post-processing step.
- The current blocker is no longer basic crop correctness or Stage A recovery; it is reliable rendering of complex display equations inside the final Stage B answer.

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

