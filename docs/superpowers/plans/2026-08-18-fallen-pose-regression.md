# Fallen-or-Lying Pose Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a standing person from being emitted as a fall event when a natural-language instruction requests a one-second fallen-person condition, while preserving the generic, visible pose and temporal workflow.

**Architecture:** Normalize the LLM-facing `state=fallen` representation into the existing `pose=fallen_or_lying` atom. Compile that atom through the existing generic pose grounding/association path with the explicit visual phrase `person lying on the ground`; retain `track.iou` and `temporal.persist` unchanged. The P12 preset uses the same evidence phrase so natural-language and preset paths stay aligned.

**Tech Stack:** Python 3.11, Pydantic SkillPackage schema, pytest, OpenCV fixture video, Rex gateway fake, real Rex API acceptance.

**Spec:** `IMPLEMENTATION_PLAN.md` sections 5.2, 5.3, 6.2, 9.2; `PROJECT_CONTEXT.md` section 15.

## Global Constraints

- LLM output remains Semantic IR only; no task-specific Python or hidden runtime fallback.
- Effective SkillSpec remains the only execution contract.
- The fix must be generic to the visible fallen-or-lying pose, not keyed to P12 or a media filename.
- Test-first: every production behavior change is covered by a regression that first fails.
- Preserve original-media coordinate handling and the existing track/persist semantics.
- Update `project_state.json`, `tests/preset_test_results.json`, and `graphify-out/` after verified milestones.

---

### Task 1: Lock the natural-language false-positive regression

**Files:**
- Create: `tests/test_fallen_pose_regression.py`
- Modify: `core/semantic.py`

**Interfaces:**
- Consumes: `SemanticNormalizer.normalize_ledger()`, `WorkflowCompiler.compile()`, `SkillPackageRuntime.run()`.
- Produces: a canonical `pose=fallen_or_lying` constraint whose only Rex evidence is `person lying on the ground`.

- [x] **Step 1: Write the failing tests**

```python
def test_fallen_state_ledger_normalizes_to_visible_fallen_or_lying_pose():
    ir = SemanticNormalizer().normalize_ledger(FALLEN_LEDGER, INSTRUCTION)
    assert ir.constraints[0].kind == "pose"
    assert ir.constraints[0].value == "fallen_or_lying"
    assert ir.constraints[0].phrases == ["person lying on the ground"]


def test_standing_person_does_not_become_persistent_fall_event_when_old_phrase_would_false_positive(tmp_path):
    package = _compile_fallen_instruction()
    record = SkillPackageRuntime(..., rex=StandingFalsePositiveRex(), ...).run(
        package, package, _write_three_frame_video(tmp_path)
    )
    assert json.loads((record.run_dir / "events.json").read_text("utf-8")) == []
```

- [x] **Step 2: Run tests to verify they fail**

Run: `conda run -n vision-skill python -m pytest -q tests/test_fallen_pose_regression.py`

Expected: FAIL because `state=fallen` remains a generic state and compiles `person fallen`, enabling the fake legacy false positive.

- [x] **Step 3: Implement the minimal canonical retyping**

```python
if kind == "state" and str(value).strip().lower() in {"fallen", "fallen_or_lying"}:
    kind = "pose"
    value = "fallen_or_lying"
    phrases = ["person lying on the ground"]
```

The production version must derive the target subject generically from the normalized target phrases rather than hard-code a P12 branch.

- [x] **Step 4: Run the regression to verify it passes**

Run: `conda run -n vision-skill python -m pytest -q tests/test_fallen_pose_regression.py`

Expected: PASS; the fake still treats legacy `person fallen` as a standing false positive, but no such phrase is dispatched.

### Task 2: Keep the preset and generated JSON aligned

**Files:**
- Modify: `core/preset_temporal.py`
- Modify: `core/preset_definitions.py`
- Modify: `tests/test_v2_presets.py`
- Regenerate: `presets_v2/P12_person_fall.json`

**Interfaces:**
- Consumes: `person_fall_builder()`, `build_preset_definitions()`, `scripts/generate_v2_presets.py`.
- Produces: P12 workflow and semantic ledger that use the same visible fallen-or-lying evidence phrase as natural-language compilation.

- [x] **Step 1: Write the failing preset assertion**

```python
def test_person_fall_preset_uses_only_explicit_lying_pose_evidence():
    package = _load_p12()
    phrases = _fallen_grounding_phrases(package)
    assert phrases == ["person lying on the ground"]
```

- [x] **Step 2: Run it to verify failure**

Run: `conda run -n vision-skill python -m pytest -q tests/test_v2_presets.py -k person_fall_preset_uses_only_explicit_lying_pose_evidence`

Expected: FAIL because P12 still includes `fallen person` and `person who has fallen`.

- [x] **Step 3: Make the smallest aligned implementation change**

Replace the P12 builder and ledger evidence lists with only `person lying on the ground`, then run:

```powershell
conda run -n vision-skill python scripts/generate_v2_presets.py
```

- [x] **Step 4: Verify the preset contract**

Run: `conda run -n vision-skill python -m pytest -q tests/test_v2_presets.py -k "person_fall or every_preset_semantic_ledger"`

Expected: PASS.

### Task 3: Verify the semantic and real-Rex acceptance matrix

**Files:**
- Modify: `project_state.json`
- Modify: `tests/preset_test_results.json`
- Modify: `tests/preset_v2_acceptance_results.json`

**Interfaces:**
- Consumes: P12 positive, standing-negative, and no-persistence confusion videos in `data/acceptance_media/v2/`.
- Produces: updated evidence-backed regression status and run artifacts.

- [x] **Step 1: Run focused code and preset tests**

Run:

```powershell
conda run -n vision-skill python -m pytest -q tests/test_fallen_pose_regression.py tests/test_semantic_normalizer_compiler.py tests/test_v2_presets.py tests/test_v2_persistence_runtime.py
```

Expected: PASS.

- [x] **Step 2: Run real Rex P12 semantic acceptance**

Run: `conda run -n vision-skill python scripts/run_v2_semantic_acceptance.py --preset P12`

Expected: P12 positive has an event; standing and short-lived controls have zero events; saved run directories include effective skill, events, trace, and annotated media.

- [x] **Step 3: Re-run the user instruction and source video**

Run the same Gradio/API compile-and-execute flow for `识别视频中是否有人摔倒，持续时间1s` with `data/acceptance_media/v2/P12_negative_standing.mp4`.

Expected: no orange `event` overlay; the result trace lists `person lying on the ground` as the pose evidence.

- [x] **Step 4: Run the complete test suite**

Run: `conda run -n vision-skill python -m pytest -q`

Expected: zero failures.

- [x] **Step 5: Record evidence and refresh graph**

Update status JSON with exact run IDs/counts and execute:

```powershell
graphify update .
```
