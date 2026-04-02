# AGENTS.md

## Project Identity

Project name: `paper-reader-agent`

This repository is the canonical home for a personal paper-reading tool designed around agent workflows, not around Vibero compatibility.

The product is a standalone local web app that helps a researcher:
- open and read PDFs locally;
- generate a high-level reading guide for the whole paper;
- ask questions about the full paper in an AI chat panel;
- select text from the paper and explicitly choose `解释` or `翻译`;
- later integrate notes and outputs with Obsidian.

This repository should be treated as an original project. It is allowed to borrow ideas from previous prototypes, but it must not depend on Vibero, Zotero plugin APIs, or upstream closed product behavior.

## Product Vision

The goal is not to clone Vibero exactly.

The goal is to build a better tool for the owner's real workflow:
- a local-first reading environment;
- a cleaner, calmer UI than generic AI chat apps;
- full-paper context for AI interactions;
- deliberate user actions instead of surprise auto-translation;
- future Obsidian integration for note capture and knowledge management.

The intended public narrative for GitHub and resume use is:
- an agent-built tool for reading papers;
- product design driven by real user workflow;
- local bridge architecture that reuses Codex access;
- iterative development with explicit agent constraints.

## Core Principles

1. Paper-first, not chat-first.
The paper itself is the center of the interface. AI is an assistant layered around the reading flow, not the main surface.

2. Full-paper context matters.
Reading guide generation and AI chat should share the same paper context, rather than treating each page as a disconnected request.

3. User intent must be explicit.
Selecting text should reveal actions like `解释` and `翻译`. The system should not auto-fire translations merely because text was selected.

4. Local-first architecture.
Files, cached outputs, and user-owned artifacts should live locally. Cloud dependence should be minimized to the model call itself.

5. Obsidian-compatible future.
The project should be designed so that later it can export notes, summaries, highlights, and chat outputs into an Obsidian-friendly structure.

## Primary User

The primary user is the repository owner: a researcher who reads academic papers, wants high-signal reading assistance, values control over the workflow, and uses or plans to use Obsidian as part of the research knowledge system.

This is not a generic enterprise product. Design decisions should optimize for a serious individual researcher workflow.

## Current Product Scope

### In Scope

- Local web app interface.
- Open PDF files from a local folder-based library.
- Generate a whole-paper reading guide.
- Display the raw paper in the center reading area.
- Provide AI chat on the right side using full-paper context.
- Allow text selection followed by an explicit popover for `解释` or `翻译`.
- Cache parsed paper artifacts locally.
- Reuse the existing local Codex bridge architecture when appropriate.

### Out of Scope For Now

- Vibero plugin compatibility.
- Zotero plugin compatibility.
- Reproducing Vibero's exact UI.
- Auto-translation on selection.
- Heavy per-page precomputation as the default workflow.
- Multi-user auth, sync, collaboration, or team features.
- Production cloud hosting.

## Information Architecture

### Top-Level Layout

The app should use a three-column layout:

- Left column: reading guide only.
- Center column: original paper viewer only.
- Right column: AI chat only.

This layout is intentional and should not drift casually.

### Left Column Requirements

Must include:
- reading guide derived from the whole paper.

Should not include for now:
- always-visible paper library list;
- section navigation panel as a dedicated permanent block.

Paper library access should exist, but as an entry action near the top controls, tied to a local folder rather than a bulky persistent sidebar list.

The current reading guide behavior is a strong baseline and should be preserved conceptually.

### Center Column Requirements

Must include:
- the original PDF as the primary reading surface.

Must not include:
- a large persistent extracted-text panel under the PDF.

Selection-based actions are still required, but the visual experience should feel like a normal paper viewer rather than a tool dashboard.

### Right Column Requirements

Must include:
- AI chat only.

AI chat must be based on the full paper context, not just the current page.
Current page may still be used as extra context when helpful, but chat must fundamentally understand the whole paper and ongoing conversation.

## Interaction Design Rules

### Text Selection

When the user selects text from the paper reading surface, the app should:
- show a small action popover;
- offer `解释` and `翻译`;
- only run the action after the user clicks one of them.

The app must not auto-translate or auto-explain immediately upon selection.

### Reading Guide

The reading guide should summarize the whole paper in a structured format such as:
- one-sentence summary;
- background;
- core problem;
- innovations;
- method;
- results;
- limitations;
- suggested reading order.

The reading guide may later include clickable references to sections or pages when confidence is high enough.
That is a future enhancement, not the current priority.

### AI Chat

AI chat should feel like a paper companion, not a blank general chatbot.

The model should be able to answer questions such as:
- what is the core innovation of this paper;
- how this section relates to the rest of the paper;
- whether a paragraph is describing motivation, method, or result;
- translation or explanation requests grounded in already-known paper context.

## Context Model Requirements

The system should preserve paper context across operations.

Desired behavior:
- reading guide generation establishes the paper-level context;
- later chat uses that paper-level context;
- if the user pastes or selects a paragraph for follow-up explanation, the assistant should interpret it in the context of the already-loaded paper.

Important note:
The implementation does not literally need a single remote API conversation thread if another architecture can preserve equivalent context correctly.
But from the product perspective, the user experience should behave as if the assistant remains inside the same paper-aware thread.

In practice, acceptable approaches include:
- a persistent local conversation state with paper context injected into each request;
- a session object that includes reading-guide outputs plus extracted paper text;
- a future true threaded backend if needed.

The key constraint is behavioral continuity, not attachment to a single technical mechanism.

## Obsidian Direction

The project should be designed with future Obsidian integration in mind.

Near-term desired direction:
- connect the app to a local paper folder;
- cache outputs in local structured files;
- make it easy later to export or sync summaries, highlights, and chat takeaways into Markdown.

Future likely features:
- export reading guide to Markdown;
- save selected explanations as notes;
- create Obsidian-friendly frontmatter and link structure;
- optionally map PDFs to notes in a vault.

Do not hardcode Obsidian assumptions too early, but avoid designs that would block this path.

## Technical Strategy

### Recommended Initial Stack

Preferred baseline stack:
- backend: Python with Flask;
- frontend: simple server-rendered shell plus plain JavaScript and CSS, unless complexity justifies a framework later;
- PDF handling: prefer a permissive-license stack for local parsing/rendering, and move toward a controllable PDF rendering layer when selection UX requires it;
- model bridge: local OpenAI-compatible bridge backed by Codex;
- storage: local JSON or lightweight local database for cached paper artifacts.

### Environment Baseline

This repository must be treated as an independent Python project.

Environment requirements:
- create and use a repo-local virtual environment at `.venv`;
- do not rely on globally installed Python packages or packages that happen to exist in another repo;
- keep Python dependencies explicit and installable from repository-owned files;
- document the exact local setup flow in `README.md` and keep it updated when setup changes;
- add and maintain a repo-local `.gitignore` so `.venv`, caches, generated artifacts, and temporary data do not enter git;
- do not introduce Node.js as a default hard dependency unless a concrete frontend need justifies a build toolchain.

Practical workflow expectation:
- all Python commands should be run through the repo's `.venv`;
- new dependencies should be added deliberately rather than inferred from the machine state;
- if a future frontend toolchain is introduced, the reason should be explicit and should not weaken the local-first workflow.
- if the app uses a local Codex bridge, the bridge script and its startup entrypoints should live in this repo and must not depend on another repository being present.

### Open Source Hygiene

If this repository is prepared for public GitHub release:
- do not commit imported paper PDFs, rendered page images, extracted page text, reading-guide caches, or other user-owned paper artifacts;
- keep local paper caches under ignored paths only;
- prefer permissive-license dependencies for the standalone repo unless the user explicitly chooses a copyleft or commercial path;
- document third-party components and license-sensitive choices in `README.md` when they affect redistribution;
- before release, run a repository hygiene check to confirm paper content and temporary local files are not entering git.

### Architecture Baseline

The previous prototype established a useful baseline:
- local web app;
- local PDF ingestion;
- extracted text cache;
- local bridge to Codex;
- structured reading guide generation.

That baseline should be treated as a prototype reference, not a final architecture.

### Likely Technical Evolution

1. Start with the current local web app model.
2. Replace rough prototype layout with the constrained layout above.
3. Improve full-paper context management for chat.
4. Replace simplistic browser PDF embedding with a controllable PDF rendering solution when needed.
5. Add local library folder handling.
6. Add Obsidian export/integration.

## Performance Constraints

The product should not default to expensive whole-document page-by-page parsing for every paper.

Observed issue from prototype:
- using `gpt-5.4@high` to parse a 33-page paper took roughly 20 minutes.

Therefore:
- whole-paper reading guide generation should be preferred over whole-document per-page analysis as the default entry action;
- page-level analysis should be on-demand;
- chat should rely on cached paper context instead of repeatedly re-parsing everything;
- design should optimize for perceived responsiveness.

Where possible, the app should:
- cache outputs aggressively;
- separate cheap operations from expensive ones;
- avoid forcing the user through long blocking flows before reading can begin.

## Design Constraints

The interface should feel intentional and research-focused.

Desired qualities:
- clean;
- calm;
- paper-centric;
- high-signal;
- not cluttered with too many side tools;
- not visually similar to a generic AI dashboard.

Avoid:
- stuffing every capability into sidebars;
- surfacing prototype/debug concepts in user-facing UI;
- making the center area feel like anything other than a PDF reader.

## Codebase Rules

1. Keep modules focused.
2. Prefer explicit local data models over ad hoc dictionaries once structures stabilize.
3. Cache outputs in a way that can later be migrated to Markdown or Obsidian exports.
4. Avoid coupling core product logic to Vibero or Zotero code.
5. Preserve a clean boundary between:
- paper ingestion;
- paper context state;
- chat orchestration;
- UI rendering;
- export/integration layers.

## License Guardrails

This repository should remain publishable under the MIT license unless the user explicitly approves a different direction.

Therefore:
- prefer MIT, BSD, Apache-2.0, or similarly MIT-compatible dependencies and implementation paths;
- do not introduce AGPL, GPL, SSPL, commercial-only, or other strong-copyleft / restricted dependencies by default;
- when evaluating a new dependency or vendored asset, check license compatibility before implementation, not afterward;
- if a new dependency becomes part of the shipped app, update `THIRD_PARTY_NOTICES.md` in the same working session;
- if license compatibility is unclear, stop and surface the uncertainty before proceeding.

## Agent Workflow Rules

Agents working in this repo should follow this order:

1. Re-read this `AGENTS.md` before making major product changes.
2. Preserve the product direction described here unless explicitly updated by the user.
3. When a requested change conflicts with this file, surface the conflict clearly instead of silently drifting.
4. Prefer small, testable increments.
5. Keep architecture documents, `ROADMAP.md`, and this file aligned with real product changes.
6. When editing user-facing Chinese text, preserve UTF-8, avoid shell-based rewrites that may corrupt encoding, and re-scan for mojibake/placeholder strings before finishing.

## Definition Of Success For Near-Term Iterations

A near-term iteration is successful if:
- the app opens local papers cleanly;
- the center view is clearly the paper itself;
- the left side gives a useful reading guide;
- the right side supports meaningful whole-paper chat;
- text selection leads to explicit explain/translate actions;
- the workflow feels faster and more natural than the current prototype.

## First Implementation Priorities

Priority 1:
- create clean repo structure;
- migrate the local web app baseline;
- write this constraints file;
- keep the reading guide flow.

Priority 2:
- remove prototype-era layout elements that violate the intended UX;
- make AI chat full-paper-aware;
- add explicit selection popover flow.

Priority 3:
- implement local paper-folder library entry;
- improve PDF rendering and selection fidelity;
- prepare Obsidian export path.

Priority 4:
- add richer section anchoring from the reading guide;
- refine aesthetics and ergonomics;
- add project polish for public GitHub presentation.

## Change Management

This file is expected to evolve.

When product direction changes materially, update this file in the same working session or immediately afterward so the repository remains a reliable source of truth.
