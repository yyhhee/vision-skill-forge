# Grounding Prompt Debug Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users inspect, edit, apply, and reset the text sent to each Rex Grounding node, while retaining the fixed bounding-box protocol; use it to compare fall-related open-reference prompts on the one-FPS video.

**Architecture:** Add an optional `query_prompt` parameter to generic `rex.ground` nodes. An absent prompt retains the current phrase-derived input. A present prompt replaces only the visual query, while the gateway still appends its fixed coordinate-return contract. The V2 review page updates the selected node in Effective SkillPackage only.

**Tech Stack:** Python 3.11, Pydantic SkillPackage schema, Gradio, pytest, Rex gateway.

**Spec:** User request of August 19, 2026: test `Someone fell down` and `fall-down event`, then expose editable model input prompts for debugging.

## Global Constraints

- Existing calls remain behaviorally identical with no `query_prompt`.
- The fixed bounding-box output contract is always appended.
- The editor affects the selected Effective SkillPackage variant only.
- Every `rex.ground@*` node is exposed; do not special-case P12.
- Blank prompt text is rejected; reset removes the override.

---

### Task 1: Gateway and generic operator forwarding

**Files:**
- Modify: `clients/rex_client.py`
- Modify: `operators/perception.py`
- Modify: `core/registry.py`
- Test: `tests/test_clients.py`

**Interfaces:**
- Produces: `RexGateway.detect(image, phrases, query_prompt=None)` and optional Grounding `query_prompt` params.

- [x] **Step 1: Write a failing gateway test**

```python
def test_rex_gateway_uses_query_prompt_but_keeps_fixed_box_contract():
    fake = FakeClient([RAW_PERSON_BOX])
    RexGateway(client=fake).detect(
        Image.new("RGB", (20, 10), "white"), ["person"],
        query_prompt="Someone fell down",
    )
    prompt = fake.chat.completions.calls[0]["messages"][1]["content"][1]["text"]
    assert prompt.startswith("Someone fell down.")
    assert "Return every visible instance" in prompt
    assert "bounding box coordinates" in prompt
```

- [x] **Step 2: Run to verify RED**

Run: `conda run -n vision-skill python -m pytest -q tests/test_clients.py -k query_prompt`

Expected: `RexGateway.detect` does not accept `query_prompt`.

- [x] **Step 3: Implement the minimal forwarding**

```python
query = (query_prompt or f"Detect {', '.join(phrases)}").strip()
prompt = f"{query}. " + FIXED_BOX_RETURN_CONTRACT
```

Forward the new keyword from Grounding operators only when non-empty, preserving existing test doubles.

- [x] **Step 4: Verify GREEN**

Run: `conda run -n vision-skill python -m pytest -q tests/test_clients.py -k "rex_gateway or query_prompt"`

Expected: PASS.

### Task 2: Persisted controller and review controls

**Files:**
- Modify: `app_v2.py`
- Test: `tests/test_v2_ui.py`

**Interfaces:**
- Produces: `grounding_prompt_controls()`, `apply_grounding_prompt_control()`, `reset_grounding_prompt_control()` and a review-page prompt editor.

- [x] **Step 1: Write failing controller/UI tests**

```python
def test_grounding_prompt_controls_expose_all_generic_grounding_nodes(tmp_path):
    controls = _controller(tmp_path).grounding_prompt_controls(P12_JSON, "video")
    assert [item["node_id"] for item in controls] == ["people_raw", "fallen_people_raw"]
    assert controls[1]["prompt"] == "Detect person lying on the ground"

def test_apply_grounding_prompt_updates_only_the_selected_node(tmp_path):
    updated = _controller(tmp_path).apply_grounding_prompt_control(
        P12_JSON, "video", "fallen_people_raw", "Someone fell down"
    )
    nodes = {node["id"]: node for node in json.loads(updated)["variants"]["video"]["nodes"]}
    assert nodes["fallen_people_raw"]["params"]["query_prompt"] == "Someone fell down"
    assert "query_prompt" not in nodes["people_raw"]["params"]
```

- [x] **Step 2: Run to verify RED**

Run: `conda run -n vision-skill python -m pytest -q tests/test_v2_ui.py -k grounding_prompt`

Expected: missing controller methods.

- [x] **Step 3: Implement minimal review editor**

Show all Grounding nodes with a readable node/target selector. Read the default as `Detect <joined target phrases>`; apply a non-empty override to one selected node and validate the package; reset removes it. Place the compact accordion before advanced JSON and explain that the coordinate-return protocol is always appended.

- [x] **Step 4: Verify GREEN**

Run: `conda run -n vision-skill python -m pytest -q tests/test_v2_ui.py -k grounding_prompt`

Expected: PASS.

### Task 3: Prompt comparison and complete verification

**Files:**
- Modify: `project_state.json`
- Modify: `tests/preset_test_results.json`

**Interfaces:**
- Consumes: `data/acceptance_media/v2/摔倒.mp4` at one FPS.
- Produces: evidence-backed comparison counts for default pose, `Someone fell down`, and `fall-down event`.

- [ ] **Step 1: Run three real-Rex prompts on identical sampled frames** (blocked: local Rex vLLM endpoint was unavailable on August 19, 2026)

Record per-prompt detections and raw outputs. Do not infer a temporal event solely from a frame-level prompt.

- [x] **Step 2: Verify fall regression and full suite**

Run: `conda run -n vision-skill python -m pytest -q tests/test_fallen_pose_regression.py` followed by `conda run -n vision-skill python -m pytest -q`.

- [ ] **Step 3: Refresh graph**

Run: `graphify update .`

Expected: all tests pass and graph artifacts are current.
