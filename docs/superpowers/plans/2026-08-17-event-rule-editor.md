# Event Rule Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make event conditions editable from the audit page for presets, saved skills, and natural-language-generated skills.

**Architecture:** Read the event node's upstream typed DAG into an event-rule control model. Write only existing editable atoms back to the effective package: comparison operator/value, condition combiner, temporal parameters, and alert label. Region scope remains a visible workflow fact linked to the existing annotation slot, so editing it cannot silently add or remove scene geometry.

**Tech Stack:** Python 3.11, Gradio, Pydantic, pytest, Playwright CLI.

## Global Constraints

- Preserve all behavior in the effective `SkillPackage`; no hidden scenario configuration.
- Reuse registered `logic.compare`, `logic.all`, `logic.any`, `temporal.persist`, and `output.alert` atoms.
- Do not create a congestion-specific operator or mutate geometry while editing numeric event conditions.
- Write a failing real-behavior test before production code.

---

### Task 1: Read Generic Event Rule Controls

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Produces `V2AppController.read_event_rule_controls(effective_json, media_type) -> list[dict[str, Any]]`.
- Each row includes event node ID, alert label, scope, comparisons, logic mode, duration, and alert target.

- [ ] **Step 1: Write a failing P04 control-model test**

```python
controls = controller.read_event_rule_controls(P04_JSON, "video")
assert controls[0]["scope"] == "region"
assert controls[0]["logic"] == "all"
assert controls[0]["comparisons"] == [
    {"node_id": "many", "measure": "每个命名区域内目标数量", "operator": ">=", "value": 4.0},
    {"node_id": "slow", "measure": "每个命名区域内目标速度", "operator": "<", "value": 10.0},
]
```

- [ ] **Step 2: Run the focused test and verify it fails for the missing method.**

- [ ] **Step 3: Implement backward DAG traversal from temporal event conditions through `logic.*` and `logic.compare`.**

- [ ] **Step 4: Re-run the focused test and verify it passes.**

### Task 2: Apply Existing Event Atoms

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Consumes `apply_event_rule_control(effective_json, media_type, event_id, comparison_ids, comparison_operators, comparison_values, logic_mode, seconds, gap_tolerance_seconds, trigger_mode, alert_label)`.
- Produces a schema-validated, registry-validated effective package.

- [ ] **Step 1: Write a failing P04 mutation test for count/speed comparisons, OR logic, duration, and alert label.**
- [ ] **Step 2: Verify it fails because the writer does not exist.**
- [ ] **Step 3: Update only the selected comparison, combiner, temporal, and alert nodes; reject missing IDs, invalid operators, and negative durations.**
- [ ] **Step 4: Verify the mutation test passes and configuration slots remain unchanged.**

### Task 3: Bind Rule Cards To The Audit UI

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- The audit page reads rule controls after preset load, saved-skill load, generation, variant change, and Apply.
- The UI exposes two comparison rows, AND/OR selection, scope explanation and annotation link, duration, trigger mode, and alert label.

- [ ] **Step 1: Write a UI-contract test asserting event-rule controls and the Apply button are present.**
- [ ] **Step 2: Verify it fails before the components exist.**
- [ ] **Step 3: Add a single event-rule editor accordion with conditional second comparison visibility and an Apply action.**
- [ ] **Step 4: Verify the UI contract and P04 read/apply behavior pass.**

### Task 4: Regression And Browser Acceptance

**Files:**
- Modify: `project_state.json`, `tests/preset_test_results.json`

- [ ] **Step 1: Run the complete pytest suite.**
- [ ] **Step 2: In the browser load P04, open the event rule editor, change a threshold, apply it, and confirm the summary updates.**
- [ ] **Step 3: Confirm a non-event image workflow states that no event rule is available.**
- [ ] **Step 4: Update state records and run `graphify update .`.**
