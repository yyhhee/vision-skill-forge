# Region Event Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow event rules to combine named regions explicitly and override comparison thresholds per region, while making event execution and empty-event reasons visible in results.

**Architecture:** Keep region geometry in the existing `region.manual_set@1.0` configuration slot. Add a deterministic keyed comparison atom that consumes the existing per-region measurement stream and applies a default plus per-region overrides; add an explicit region aggregation atom for any/all/N matching regions. Preserve region IDs as event entity IDs. Expose the configuration and execution explanation through the existing event-rule editor and result contract.

**Tech Stack:** Python, Pydantic SkillPackage schemas, existing operator registry, Gradio UI, pytest.

## Global Constraints

- Existing single-region and same-threshold multi-region skills must remain executable without migration.
- Region IDs are the stable keys; labels are display-only.
- An empty EventSet is a valid execution result and must be distinguishable from a missing event output.
- Production code is added only after a failing test demonstrates the requested behavior.

### Task 1: Keyed Region Comparisons

**Files:**
- Modify: `operators/logic.py`
- Modify: `core/registry.py`
- Test: `tests/test_operator_semantics.py`

**Interfaces:**
- Add `logic.compare_by_key@1.0`, consuming `ScalarSet`/`VectorSet` as `left` and optional keyed overrides in params.
- Params: `operator`, `value`, `overrides` mapping stable region key to numeric value.
- Output preserves each input item's key, timestamp, and frame index.

- [ ] Write a failing test for two region keys with different thresholds.
- [ ] Run the focused test and verify it fails because the operator is absent.
- [ ] Register and implement the minimal operator by reusing comparison predicates.
- [ ] Run the focused test and verify it passes.

### Task 2: Region-Set Aggregation

**Files:**
- Modify: `operators/logic.py`
- Modify: `core/registry.py`
- Test: `tests/test_operator_semantics.py`

**Interfaces:**
- Add `logic.region_aggregate@1.0`, consuming a `ConditionSet` keyed by region.
- Params: `mode` (`any`, `all`, `at_least`), `minimum` for `at_least`.
- Output is a global condition stream per frame; metadata identifies matching region IDs.

- [ ] Write failing tests for any, all, and at-least-N region semantics.
- [ ] Run tests to verify the missing operator failure.
- [ ] Implement aggregation with deterministic frame grouping.
- [ ] Run focused and existing operator tests.

### Task 3: Event Rule Editing and Persistence

**Files:**
- Modify: `app_v2.py`
- Modify: `core/semantic.py` only where compiler output needs the new atom.
- Test: `tests/test_v2_ui.py`
- Test: `tests/test_workflow_atom_compilation.py`

**Interfaces:**
- Extend the event-rule control model with region aggregation mode and per-region overrides.
- Read region IDs from the bound `region.manual_set@1.0` node.
- Save overrides into keyed comparison params and preserve them when regions are added, renamed, or deleted; removed IDs are pruned, new IDs use the default.
- Keep existing `02` controls valid for skills without keyed overrides.

- [ ] Write failing controller/UI tests for reading and applying per-region values and aggregation mode.
- [ ] Run focused tests to verify the current editor cannot represent the configuration.
- [ ] Implement model extraction, validation, and persistence.
- [ ] Add concise UI controls: region aggregation selector and a compact per-region override editor.
- [ ] Run focused UI and compiler tests.

### Task 4: Event Result Diagnostics

**Files:**
- Modify: `core/runtime.py`
- Modify: `app_v2.py`
- Test: `tests/test_video_pipeline.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Persist event-producing node trace summaries and a reason when an EventSet is empty (condition never true, duration not reached, or input has no region samples).
- Result contract must report `适用 · 本次 0 条` with the diagnostic instead of appearing blank.
- The run status must state whether event output was declared and whether any event triggered.

- [ ] Write failing test for a declared event output with zero events and an explanatory diagnostic.
- [ ] Run focused test to verify the current result lacks the explanation.
- [ ] Implement diagnostic derivation from trace and condition/temporal inputs.
- [ ] Run focused tests and the full suite.

### Task 5: Verification

**Files:**
- Modify: `docs/` only if user-facing rule semantics need a short reference.

- [ ] Run `pytest -q`.
- [ ] Run `graphify update .`.
- [ ] Exercise the live Gradio flow with two named regions: different thresholds, any/all/at-least-N, and inspect the Event Results tab.

