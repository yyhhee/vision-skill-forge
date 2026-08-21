# Independent Regions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every manually required region and evaluate independent regional conditions together at the same sampled time.

**Architecture:** Add a typed `regions.merge@1.0` operator that combines multiple `RegionSet` values without changing their IDs. The workflow compiler uses this operator only when several distinct region sources need presentation, and sets boolean aggregation to `frame_any` only when conditions refer to distinct region sources; conditions sharing a source retain `by_key`.

**Tech Stack:** Python 3.11, Pydantic SkillPackage schema, typed operator registry, pytest.

**Spec:** User report from `C:\Users\83915\AppData\Local\Temp\codex-clipboard-500af0e5-68ac-4559-bb80-5fd36f66b26d.png` and run `data/runs/20260818_111143_a37ff4e7`.

## Global Constraints

- Regions remain manual scene configuration; the compiler must not create automatic regions.
- `by_key` preserves same-region AND/OR semantics; `frame_any` means independent regional conditions must be true in the same sampled frame.
- Operator inputs and outputs remain typed and validated through the existing registry.

---

### Task 1: Failing Compiler Contracts

**Files:**
- Modify: `tests/test_workflow_atom_compilation.py`

**Interfaces:**
- Consumes: `WorkflowCompiler.compile(CanonicalSemanticIR, ...)`
- Produces: a video variant containing `regions.merge@1.0` and an event combiner with an explicit `combine_scope`.

- [ ] **Step 1: Write failing tests**

```python
assert draw.inputs["regions"] == "$draw_regions"
assert merged.op == "regions.merge@1.0"
assert combined.params["combine_scope"] == "frame_any"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_workflow_atom_compilation.py -q`

Expected: a missing `draw_regions` merge node and default `by_key` combination.

### Task 2: Region Aggregation Atom

**Files:**
- Modify: `operators/region.py`
- Modify: `operators/__init__.py`
- Modify: `core/registry.py`
- Modify: `tests/test_operator_semantics.py`

**Interfaces:**
- Produces: `regions_merge(inputs, params, services, node_id) -> RegionSet` registered as `regions.merge@1.0`.

- [ ] **Step 1: Write the failing operator test**

```python
result = regions_merge({"regions": [first, second]}, {}, None, "draw_regions")
assert [region.id for region in result.items] == ["area_1", "area_2"]
```

- [ ] **Step 2: Implement and register the minimal typed operator**

```python
return RegionSet([region for region_set in inputs["regions"] for region in region_set.items])
```

- [ ] **Step 3: Run focused operator tests**

Run: `python -m pytest tests/test_operator_semantics.py -q`

### Task 3: Compile and Review Semantics

**Files:**
- Modify: `core/semantic.py`
- Modify: `app_v2.py`
- Modify: `tests/test_v2_ui.py`

**Interfaces:**
- `WorkflowCompiler._compile_variant` tracks the source region node per condition and merges unique display region nodes.
- `V2AppController.apply_event_rule_cards` determines the boolean scope from selected fixed or named region sources.

- [ ] **Step 1: Keep tests red until source-aware selection is implemented**
- [ ] **Step 2: Compile distinct sources as `frame_any`; retain `by_key` for one shared source**
- [ ] **Step 3: Rebuild event cards without discarding fixed-region source identity**
- [ ] **Step 4: Run focused compiler/UI tests**

### Task 4: Verification

**Files:**
- Modify: `graphify-out/` via `graphify update .`

- [ ] **Step 1: Run the full suite**

Run: `python -m pytest -q`

- [ ] **Step 2: Restart the 6130 service and inspect the local page**
- [ ] **Step 3: Run `graphify update .` after code changes**
