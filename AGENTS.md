# vision_skill project instructions

Before planning, coding, or testing this project, read these files in order:

1. `PROJECT_CONTEXT.md`
2. `IMPLEMENTATION_PLAN.md`
3. `TEST_PLAN.md`
4. `project_state.json`
5. `tests/preset_test_results.json`

Project rules:

- Keep the project independent from the Rex-Omni source tree. Use Rex through its OpenAI-compatible vLLM API.
- Never print, copy into source code, or commit `.env` or any API key. Load secrets through environment variables.
- The LLM is only a compiler. It may select registered operators and fill parameters, but it may not create operator semantics or executable Python.
- Operator definitions are the single source of truth for Planner prompts, validation, UI forms, execution, and explanations.
- All runtime behavior must be represented in the effective `VisualSkillSpec`; do not add hidden fallbacks.
- Manual regions and directions belong to skill nodes. Do not introduce a separate SceneConfig requirement.
- Preserve original-media normalized coordinates through resize and tiling.
- Do not report a preset as passed until a real end-to-end run has produced saved media, events, trace, and effective skill artifacts.
- After each implementation or test milestone, update `project_state.json` and `tests/preset_test_results.json`.

