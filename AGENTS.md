# vision_skill project instructions

## Independent next-branch workspace

- This checkout starts at original checkpoint `8b86c7e`. The original Gradio backend remains at the repository root; the independently running frontend prototype is in `frontend/`.
- For frontend work, read `frontend/AGENTS.md`, `frontend/README.md`, and `docs/NEXT_FRONTEND_CHECKPOINT.md`. Do not treat co-location as an implemented backend integration or an approved production release.
- The original context/state files listed below were local-only and may be absent after clone. When absent, use tracked implementation documents and checkpoint notes; do not invent their contents or copy secrets/runtime data to satisfy the list.
- Keep existing 6131 and 6174 services untouched. The user approved an independent, no-login Chromium context on local port 6175 for checking this copied frontend on 2026-10-20; never use a logged-in profile.
- Preserve `frontend/src/`, assets and locked dependencies at this checkpoint. Existing audited defects are recorded, not silently fixed during archival. Worktree-specific test output goes outside Git or under ignored local-check directories.
- Frontend-only milestones update `docs/NEXT_FRONTEND_CHECKPOINT.md` and frontend QA notes, not backend preset accuracy results. Do not rewrite historical backend acceptance status merely because frontend tests pass.
- After each authorized commit, update the user's Chinese local version ledger with the actual commit/date/verification/push state. Do not create recursive commits for that local ledger.

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
- Maintain human-readable Chinese checkpoint notes in `docs/VERSION_HISTORY.md`. After each user-authorized Git commit, also update the user's local version ledger when its location is known: Beijing date/time, project/branch, commit and optional tag, changes, actual verification/evidence, limitations, push status, and restoration notes. Preserve history; never equate committed with fully verified. Verify the remote before marking uploaded. Do not auto-commit/push or create recursive commits just to record the local ledger; never include secrets.

