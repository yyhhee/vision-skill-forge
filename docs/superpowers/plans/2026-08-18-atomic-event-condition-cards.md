# Atomic Event Condition Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two fixed event-condition fields with editable, atomic condition cards that compile to and run from the existing V2 workflow DAG.

**Architecture:** A card is an explicit comparison atom: measurement source, optional named-region key, selected target labels, comparison operator, and numeric threshold. The event holds an ordered `logic.all` or `logic.any` list of those atoms; temporal persistence and alert delivery remain one event-level policy so mixed conditions have unambiguous timing. Adding a card clones only the comparison and its measurement/filter branch, retaining the current workflow's typed inputs and scene bindings.

**Tech Stack:** Python 3.11, Gradio 5, Pydantic, pytest, browser acceptance.

**Spec:** User-provided condition-card reference image in this task.

## Global Constraints

- Conditions must be reusable registered DAG atoms, not a congestion-only rule format.
- A card's target label and named-region selection must affect runtime execution.
- Existing presets and saved packages remain readable and editable.
- Write and run failing real-behavior tests before production changes.

---

### Task 1: Make Cross-Region Condition Composition Executable

**Files:**
- Modify: `operators/logic.py`, `core/registry.py`
- Test: `tests/test_operator_semantics.py`

**Interfaces:**
- `logic.all@1.0` and `logic.any@1.0` accept `combine_scope: "by_key" | "frame_any"`.
- `frame_any` reduces each child condition at a timestamp, then emits one `global` condition.

- [ ] **Step 1: Write a failing test**

```python
combined = logic_all({"conditions": [north, south]}, {"combine_scope": "frame_any"}, None, "both")
assert [(item.key, item.value) for item in combined.items] == [("global", True)]
```

- [ ] **Step 2: Run `pytest tests/test_operator_semantics.py -k frame_any -v`; verify it fails because `frame_any` is unsupported.**
- [ ] **Step 3: Implement timestamp aggregation and register the typed parameter.**
- [ ] **Step 4: Re-run the focused test; verify it passes.**

### Task 2: Persist Variable Event Comparison Atoms

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- `V2AppController.apply_event_rule_cards(effective_json, media_type, event_id, cards, logic_mode, seconds, gap, trigger_mode, alert_label) -> str`.
- Each card has `template_id`, `region_id`, `categories`, `operator`, and `value`.

- [ ] **Step 1: Write a failing controller test for three cards: north-region vehicle `>2`, north-region vehicle `<5`, and south-region vehicle `>2`.**
- [ ] **Step 2: Run the focused test; verify the method is absent.**
- [ ] **Step 3: Clone only comparison measurement/filter atoms, rewire the event combiner, and use `frame_any` for independently selected regional keys.**
- [ ] **Step 4: Re-run the focused controller test and verify package validation succeeds.**

### Task 3: Render and Apply Condition Cards

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Audit UI renders six bounded cards with region/statistic, target labels, operator, threshold, enable, delete, and add controls.
- The event policy editor remains one explicit timing/trigger/alert section for the combined conditions.

- [ ] **Step 1: Write a failing UI contract test for `条件 1` card controls and `添加条件` action.**
- [ ] **Step 2: Run the focused test; verify it fails against the fixed two-row UI.**
- [ ] **Step 3: Replace fixed rows and the override table with bounded dynamic card groups and card-state callbacks.**
- [ ] **Step 4: Run UI tests and browser acceptance after loading a regional preset.**

### Task 4: Regression Verification

**Files:**
- Modify: `graphify-out/` (generated)

- [ ] **Step 1: Run the full pytest suite.**
- [ ] **Step 2: Restart localhost port 6130, load a regional event, add a second comparison, apply, and inspect the refreshed visible card state.**
- [ ] **Step 3: Run `graphify update .`.**
