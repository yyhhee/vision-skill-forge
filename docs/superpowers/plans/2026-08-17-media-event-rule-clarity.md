# Media Recovery And Event Rule Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore media replacement after clearing a preset and expose each duration threshold as the explicit event condition it governs.

**Architecture:** Guard annotation callbacks against an empty Effective SkillPackage so clearing a media file cannot poison the Gradio queue. Derive a human-readable event rule from the existing typed DAG: `measure.* -> logic.compare -> logic.all/any -> temporal.persist|event.from_condition`. Keep region scope, target filtering, numeric comparisons, duration, and alert labels as separate registered atoms; the UI renders their dataflow rather than adding congestion-specific logic.

**Tech Stack:** Python 3.11, Gradio, Pydantic, pytest, Playwright CLI.

## Global Constraints

- Preserve all runtime semantics in the Effective SkillPackage; do not add hidden event defaults.
- Reuse `measure.count@1.0`, `measure.region_count@1.0`, `objects.filter_by_label@1.0`, `logic.compare@1.0`, `logic.all@1.0`, `temporal.persist@1.0`, and `event.from_condition@1.0`.
- Use original-media normalized coordinates for manual regions.
- Write a failing real-behavior test before production code.

---

### Task 1: Make Empty Media Reset Queue-Safe

**Files:**
- Modify: `app_v2.py:1400-1410, 3578-3610`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Consumes: `V2AppController.annotation_selection_defaults(effective_json, media_type, slot_id, state)`.
- Produces: an empty draft `("rectangle", "", "", {"tool": "rectangle", "points": []})` when no skill JSON exists.

- [ ] **Step 1: Write the failing test**

```python
def test_empty_skill_has_a_safe_annotation_draft_after_media_is_cleared(tmp_path):
    controller = _controller(tmp_path)
    assert controller.annotation_selection_defaults("", "image", None) == (
        "rectangle", "", "", {"tool": "rectangle", "points": []}
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v2_ui.py::test_empty_skill_has_a_safe_annotation_draft_after_media_is_cleared -q`

Expected: `ValidationError` because the old method parses an empty string as `SkillPackage`.

- [ ] **Step 3: Write minimal implementation**

```python
if not effective_json:
    return "rectangle", "", "", {"tool": "rectangle", "points": []}
```

Return harmless empty updates from `_select_annotation_slot` before it renders an annotation preview when `effective_json` is empty.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v2_ui.py::test_empty_skill_has_a_safe_annotation_draft_after_media_is_cleared -q`

Expected: PASS.

### Task 2: Explain The Event Condition Bound To Each Duration

**Files:**
- Modify: `app_v2.py:455-478, 2515-2542, 3268-3308`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Consumes: `SkillPackage` variant DAG and `atom_bindings`.
- Produces: each `read_temporal_controls()` row with `event_label` and `condition_summary` in addition to duration fields.

- [ ] **Step 1: Write failing tests**

```python
def test_temporal_controls_explain_congestion_count_speed_and_region_scope(tmp_path):
    controls = _controller(tmp_path).read_temporal_controls(P04_JSON, "video")
    assert controls[0]["event_label"] == "高速车辆拥堵"
    assert "每个命名区域内目标数量 >= 4" in controls[0]["condition_summary"]
    assert "每个命名区域内目标速度 < 10" in controls[0]["condition_summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_v2_ui.py::test_temporal_controls_explain_congestion_count_speed_and_region_scope -q`

Expected: `KeyError: 'event_label'`.

- [ ] **Step 3: Write minimal implementation**

```python
def temporal_control_description(self, package, variant, event_node):
    # Walk event.inputs["condition"] backward through logic operators.
    # Render measure.region_count and measure.region_speed with scope and compare params.
    # Use output.alert label when it consumes this event node.
```

Render the selected rule below the temporal dropdown and state that no duration setting exists for image-only and non-event workflows.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_v2_ui.py -q`

Expected: PASS.

### Task 3: Preserve Generic Count-Event Composition

**Files:**
- Test: `tests/test_operator_semantics.py`, `tests/test_workflow_atom_compilation.py`
- Verify only unless a missing composition is found: `core/registry.py`, `operators/measure.py`, `core/semantic.py`

**Interfaces:**
- `objects.filter_by_label@1.0`: one or more explicit labels -> ObjectSet.
- `measure.count@1.0`: full-frame target count or per-label count -> ScalarSet.
- `measure.region_count@1.0`: selected-target count per named region -> ScalarSet.
- `logic.compare@1.0` and `logic.all@1.0`: threshold and conjunction -> ConditionSet.
- `temporal.persist@1.0` / `event.from_condition@1.0`: duration and alert label -> EventSet.

- [ ] **Step 1: Add a real DAG test**

```python
def test_named_region_count_threshold_can_persist_as_a_region_event():
    # selected vehicle classes -> region count -> >= 4 -> persist(1s, region)
    # assert event key remains the named region id.
```

- [ ] **Step 2: Run it against the existing registry and operators**

Run: `python -m pytest tests/test_operator_semantics.py::test_named_region_count_threshold_can_persist_as_a_region_event -q`

Expected: PASS if the existing generic atoms already provide this path; otherwise the failure identifies the missing atomic boundary.

- [ ] **Step 3: Implement only an identified missing atomic capability**

Do not add `congestion` operators. If filtering a set of labels before region counting is missing, compile `objects.filter_by_label@1.0` before the existing `measure.region_count@1.0` node.

- [ ] **Step 4: Verify end-to-end DAG and browser flow**

Run: `python -m pytest tests/test_v2_ui.py tests/test_operator_semantics.py tests/test_workflow_atom_compilation.py tests/test_v2_presets.py -q`

Use Playwright to clear P04 preset media, upload a local video, load the P04 event rule, and verify no queue or console error.
