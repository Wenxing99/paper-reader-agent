# Multi-Agent Workflow

This document describes the preferred multi-agent workflow for `paper-reader-agent`.

It complements [AGENTS.md](../AGENTS.md): `AGENTS.md` holds the hard rules, while this document explains the recommended operating pattern.

## Why This Repo Needs A Workflow

This repository has a few traits that make unstructured parallel editing risky:

- some files are boot-critical and can break the whole app if changed carelessly;
- some changes are tightly coupled across prompt design, rendering, and UI state;
- the project relies on calm, reversible iterations rather than large bundled rewrites;
- user-facing Chinese text can be damaged by careless editing workflows.

Because of that, multi-agent work should be deliberate rather than default.

Practical default:
- for non-trivial work, first decompose the task as if it might use multiple agents;
- then decide whether to keep the work serial or actually run agents in parallel;
- in other words, default to multi-agent-style planning, not to automatic parallel execution.

## Preferred Agent Roles

### 1. Main Agent

Responsibilities:
- restate the goal in repo terms;
- choose whether parallel work is worth it;
- define task boundaries and write scopes;
- integrate changes;
- run the final checks;
- decide whether to keep, refine, or revert.

The main agent should stay responsible for the critical path.

### 2. Explorer Agents

Use explorers for read-only tasks such as:
- tracing where a bug likely originates;
- comparing current behavior against docs or constraints;
- auditing a dependency or license question;
- finding all code paths that touch a user-visible behavior;
- collecting evidence before a risky edit.

Explorers should usually not edit files.

### 3. Worker Agents

Use workers for bounded implementation tasks with clear ownership.

Good worker tasks:
- update one backend service file plus its tests;
- adjust a CSS-only change in one visual area;
- add or update documentation for a finished feature;
- add one new test file for an already-decided implementation.

Bad worker tasks:
- "fix the whole formula pipeline";
- "improve the app startup flow";
- any task whose write set is still ambiguous.

### 4. Verification Agent

Use a verification-oriented agent when it can stay mostly read-only and answer questions like:
- do the changed files still match `AGENTS.md` and `ROADMAP.md`?
- what regressions are most likely from this patch?
- which tests should be run before keeping the change?

The verification role is especially useful after parallel workers finish.

## Write-Scope Rules

Before spawning workers, define file ownership.

Recommended default write zones:
- backend worker: `src/paper_reader_agent/services/...`
- frontend worker: `src/paper_reader_agent/static/...`
- docs/tests worker: `docs/...`, `ROADMAP.md`, `README.md`, `tests/...`

High-risk files should usually have only one writer in a round:
- `src/paper_reader_agent/static/app.js`
- `src/paper_reader_agent/services/formula_stage.py`
- `src/paper_reader_agent/app.py`

If one of those files is already in motion, prefer serial work over parallel work.

## When Multi-Agent Work Is Worth It

Good fits:
- one agent inspects a bug while another updates docs or tests in a disjoint write area;
- one agent audits license compatibility while the main agent continues local implementation;
- one agent explores rendering behavior while another explores backend prompt/output behavior.

Poor fits:
- fragile startup or boot regressions;
- intertwined UI state bugs;
- text-encoding cleanup on user-visible strings;
- any task where the next action depends immediately on one unresolved result.

## Recommended Workflow

### Step 1: Scope First

The main agent should write down:
- the exact user-visible goal;
- the files most likely involved;
- which part of the task is on the critical path;
- which subtasks, if any, are safe to parallelize.

This step is now the default for non-trivial work in this repo, even when the final implementation stays with one agent.

### Step 2: Spawn Only Sidecar Work

Parallel agents should help with sidecar tasks, not block the immediate next move.

Examples:
- an explorer maps the render path while the main agent inspects current failing output;
- a docs worker updates design notes after the implementation direction is already decided.

### Step 3: Keep Ownership Narrow

Each worker should own:
- one module or subsystem;
- one test surface;
- one documentation surface.

Avoid overlapping edits unless the main agent explicitly expects to reconcile them.

### Step 4: Integrate Centrally

After parallel work returns, the main agent should:
- review changed files;
- verify they still match repo constraints;
- run the minimum meaningful checks;
- update docs if the product behavior changed.

### Step 5: Revert Narrowly

If something regresses:
- revert the smallest recent slice;
- keep proven-good adjacent work when possible;
- document the lesson if the failure pattern is likely to repeat.

## Repo-Specific Recommendations

For `paper-reader-agent`, the most effective parallel pattern is usually:

1. Main agent owns the critical implementation thread.
2. Explorer A investigates the backend path.
3. Explorer B investigates the frontend/rendering path.
4. Worker C updates tests or docs only after the implementation direction is settled.

This repo is usually **not** well served by:
- multiple concurrent writers on `app.js`;
- multiple concurrent writers on `formula_stage.py`;
- one worker changing prompts while another changes rendering and a third changes app state.

## Example Playbooks

### Formula Rendering Bug

Safe split:
- main agent: inspect the failing output and decide the likely layer;
- explorer: trace whether the corruption starts in Stage A, Stage B, or final rendering;
- worker: update tests and docs once the fix direction is settled.

Usually unsafe split:
- one worker changes prompt wording;
- another changes local normalization;
- another changes the front-end renderer.

That combination should usually stay serial.

### Reading Guide Progress Polish

Safe split:
- main agent: adjust the actual state flow;
- explorer: inspect race conditions or late writes;
- docs/tests worker: update roadmap and regression tests after the fix lands.

## Decision Heuristic

Before using multiple agents, ask:

1. Is the write scope already clear?
2. Can I keep writers disjoint?
3. Is the parallel task sidecar work rather than critical-path work?
4. If something breaks, can I revert one slice cleanly?

If the answer to any of these is "no", prefer serial work.

## Short Version

Default behavior for this repo:
- first decompose the task in a multi-agent-friendly way;
- then parallelize only the low-coupling parts;
- keep high-regression or tightly coupled core changes serial;
- let the main agent own integration and final judgment.
