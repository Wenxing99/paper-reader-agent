# Formula Selection Pipeline

## Purpose

This document captures the planned Stage A + Stage B pipeline for handling formula-heavy PDF selections.

It exists so the design does not get lost across future sessions, context compression, or roadmap reshuffles.

## Problem Statement

The current selection-action flow works reasonably well for normal prose, but it breaks down on math-heavy selections.

Typical failure case:
- the selected region contains body text, a theorem statement, and one or more dense formulas;
- the PDF text layer does not preserve the formula structure cleanly;
- extracted text becomes flattened, reordered, or corrupted;
- the model receives partial or broken symbols and can only guess.

This means the current text-only path is not the full solution for mathematical papers.

## Product Goal

The goal is not only formula OCR.

The real product goal is paper-aware understanding for mixed selections such as:
- body text + theorem statement + complex inequality;
- theorem + proof snippet + displayed formula;
- paragraph + equation + surrounding explanation.

For these cases, the complete solution is:
- Stage A: recover structured math-aware text from the selected region;
- Stage B: interpret that recovered output using the paper context.

Stage A alone is not enough.
Stage A + Stage B together are the intended complete path.

## Current System Limitation

Today the selection-action flow effectively sends a flattened text selection plus local paper context.

That is not reliable for math because:
- PDF stores formulas as layout, not semantic math structure;
- symbol fonts may not map cleanly to Unicode;
- the current text layer groups content by visual lines, which is acceptable for prose but lossy for formulas;
- superscripts, subscripts, matrices, aligned equations, and unusual operators may be damaged before the model ever sees them.

## Current Implementation Status

Shipped today:
- selection rectangle capture and internal crop generation are working;
- math-heavy selections can now route through Stage A and Stage B in the existing selection-action flow;
- the current Stage A prompt aims for a full-crop LaTeX transcription rather than a short "main math only" summary;
- the current Stage A route goes through the local bridge path with image input rather than a bundled local OCR backend;
- normal prose selections still use the lighter text-only path;
- the default UI now shows the final Stage B explanation or translation instead of exposing the intermediate Stage A draft;
- Stage B is now expected to emit Markdown with KaTeX-friendly math delimiters so formulas can render directly in the right panel.

This means the repository now has the first real end-to-end Stage A + Stage B slice, even though the output contract and fallback behavior still need refinement.

## Proposed Architecture

### Stage A

Responsibilities:
- take the selected PDF region;
- crop a high-resolution image of that region;
- run a formula-aware OCR / image-to-LaTeX backend;
- return structured recovery output.

Expected Stage A output:
- `latex`: best-effort LaTeX or math-like structured output;
- `plain_text`: readable fallback transcription;
- `confidence`: coarse confidence signal if available;
- `warnings`: any signs that recognition is uncertain or partial;
- `backend_name` and `backend_version` for traceability.

Stage A is a recovery step, not an explanation step.

### Stage B

Responsibilities:
- take the Stage A output;
- combine it with local paper context;
- explain or translate the selected content in a paper-aware way.

Expected Stage B inputs:
- original user action (`explain` or `translate`);
- raw selected text if available;
- Stage A OCR result;
- current-page local context;
- full-paper guide / full-paper context;
- optional page number and selection metadata.

Expected Stage B behavior:
- acknowledge when OCR is uncertain;
- explain the formula structure itself;
- explain how it relates to the theorem / paragraph / argument nearby;
- return Markdown whose formulas are wrapped in KaTeX-friendly delimiters;
- avoid leaving bare LaTeX commands floating in prose;
- avoid pretending damaged symbols were recovered perfectly when they were not.

Stage B should be implemented as a paper-aware interpretation layer, not as generic post-processing.
A tiny local normalization layer is acceptable for obvious delimiter cleanup, but the default path should not add a second model repair pass.

## Minimal Implementation Plan

### Step 1: Selection Rectangle Capture

Goal:
- capture the selected region as page coordinates, not only as text.

Deliverables:
- selection metadata includes page number and bounding rectangle;
- rectangle capture works for the current PDF.js-based viewer;
- no OCR yet.

Why first:
- if the crop is wrong, every later step is wrong.

### Step 2: Region Cropping

Goal:
- produce a high-resolution image for the selected region.

Deliverables:
- deterministic crop image from the selected rectangle;
- local debug output available during development;
- crop path or bytes can be handed to Stage A.

Notes:
- this should not require changing the visible selection UX;
- start with a debug-first implementation before optimizing.

### Step 3: Stage A OCR Prototype

Goal:
- send the crop to one OCR backend and recover best-effort LaTeX.

Deliverables:
- a replaceable OCR adapter interface;
- one working backend integration;
- stable internal handoff from Stage A output into Stage B.

Current backend direction:
- keep the shipped vision-capable model route that receives the cropped selection image and returns a best-effort full-crop LaTeX draft;
- keep the Stage A backend replaceable in case the bridge or model changes later.

Reason:
- the crop-debug foundation already works;
- the current image-capable bridge path is much lighter than bundling a local OCR stack;
- a local OCR backend was tested and rejected because the latency and local model-loading cost were not acceptable for the intended product experience.

### Step 4: Stage B Explanation Path

Goal:
- route Stage A output into a dedicated math-aware explanation flow.

Deliverables:
- separate prompt / orchestration path for formula-heavy explanation;
- final user-facing response comes from Stage B rather than the raw Stage A draft;
- uncertainty from Stage A is used internally and mentioned only when it materially affects interpretation.

### Step 5: Routing and Fallbacks

Goal:
- decide when to use the advanced path and when to stay with the current text-only path.

Deliverables:
- heuristic or explicit trigger for formula-heavy selections;
- text-only fallback remains available for normal prose;
- graceful degradation when OCR fails.

## Current Backend Direction

Current practical direction for Stage A:
- keep the working crop-debug path as the baseline;
- avoid shipping a local OCR backend by default for now;
- use the crop as the handoff artifact into a vision-capable model that can recover LaTeX quickly enough for interactive use.

Why this is the current direction:
- the crop path is already validated;
- the recent local-OCR prototype proved that correctness alone is not enough if latency is too high;
- the intended product experience is closer to "click and get a useful answer quickly" than "load and run a heavy local OCR stack".

Local OCR remains a research branch, not the current default product path.

## Interface Design Notes

The user-facing interaction should stay simple.

Preferred UX:
- keep the existing `解释 / 翻译` action entry;
- do not add noisy extra buttons too early;
- detect when the advanced path should run;
- show the recovered formula or OCR draft inside the answer when helpful.

Why:
- the user wants a paper-reading tool, not a debug dashboard;
- but for trust, the intermediate OCR result should still be visible somewhere when needed.

## Data and Caching Notes

Recommended cache key dimensions:
- `paper_id`
- `page_number`
- `selection_rect`
- `backend_name`
- `backend_version`

Recommended cached payload:
- crop metadata;
- OCR result;
- confidence / warnings;
- timestamps.

Why cache:
- repeated explain / translate requests on the same formula should not rerun OCR every time;
- debugging is much easier when intermediate results are inspectable.

## Failure Modes and Fallback Strategy

Expected failure modes:
- crop misses part of the formula;
- OCR backend cannot recover rare symbols;
- theorem text and formula get merged poorly;
- confidence is low or OCR result is obviously damaged.

Fallback behavior:
- preserve the current text-based selection path for non-math cases;
- if Stage A fails, say so clearly instead of pretending the formula was fully recovered;
- when possible, still explain the surrounding prose and state what part of the formula remains uncertain.

## License Notes

This pipeline must stay aligned with the repository's MIT-first direction.

Therefore:
- Stage A backend choices must be checked for license compatibility before integration;
- model weights and packaged assets matter, not just repository source licenses;
- any vendored or newly shipped assets must be added to `THIRD_PARTY_NOTICES.md` in the same working session.

## Definition Of Success

This design is successful when:
- formula-heavy selections no longer depend only on flattened PDF text;
- the system can recover useful structured math output for mixed theorem/formula regions;
- explanations are grounded in both OCR recovery and paper context;
- the OCR layer is replaceable;
- the user can tell when OCR is uncertain;
- the implementation remains compatible with the repository's license direction.

