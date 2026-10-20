# Vision Skill Forge

Build inspectable, editable, and executable visual skills from one sentence.

[English](README.md) | [中文](README_zh.md)

---

## Overview

Vision Skill Forge is a visual-skill builder for images and videos. Describe targets, attributes, relationships, regions, counts, temporal behavior, or business events in natural language. The system turns that intent into a typed workflow that can be reviewed, edited, validated, and executed with visible evidence.

The project combines LLM planning with deterministic compilation. The LLM selects from registered business capabilities and execution atoms; fixed code validates the plan, creates the runtime graph, runs visual inference, binds evidence to entities, and produces explainable results.

## Why Vision Skill Forge?

| Conventional visual demo | Vision Skill Forge |
| --- | --- |
| Detection logic is hidden in code | The generated workflow is visible and editable |
| One prompt maps to one opaque result | Results retain boxes, evidence, decisions, and execution traces |
| Complex tasks require custom coding | Targets, attributes, regions, relations, counts, logic, and events can be composed |
| Similar model queries run repeatedly | Compatible categories for the same inference image/frame are grouped into one grounding request |
| Model output is treated as the business answer | Visual evidence and business decisions are separated |

## Core capabilities

- **One-sentence skill creation** — turn a natural-language request into a complete visual skill.
- **Typed visual workflows** — compile only registered, versioned operators with explicit inputs, outputs, and parameters.
- **Editable business logic** — review and adjust branches, AND / OR / NOT groups, thresholds, regions, relations, events, and trigger policies.
- **Shared multi-category inference** — detect compatible categories together, then perform evidence binding and instance deduplication downstream.
- **Image and video support** — reuse semantic intent while compiling media-specific execution graphs.
- **Explainable results** — inspect annotations, intermediate evidence, node traces, and final business outputs.
- **P01–P13 demonstrations** — ready-made examples for traffic, safety, facility, and infrastructure scenarios.

## How it works

```text
Natural-language request
        ↓
Canonical Semantic IR
        ↓
Business capabilities + execution atoms
        ↓
Deterministic typed compiler
        ↓
Editable SkillPackage
        ↓
Visual inference → evidence binding → logic/events
        ↓
Annotated and explainable result
```

The LLM performs constrained planning. It does not generate runtime code or invent unregistered operators.

## Example requests

```text
Detect people without safety helmets.
Detect yellow sofas and white chairs.
Detect whether multiple lane regions are congested; more than three vehicles in one lane is congestion.
Raise a regional alert when Region 1 contains a person in a red top and gray trousers,
and Region 2 contains at least two people.
Detect bridge defects: exposed reinforcement, cracks, corrosion, seepage, and concrete spalling.
```

## Quick start

### Prerequisites

- Python environment with the dependencies from `requirements.txt`
- Planner API settings configured in `.env`; see `.env.example`
- Rex-Omni OpenAI-compatible service available at `http://127.0.0.1:8000/v1`
- Original local media (`imgs/` and `data/acceptance_media/`) for the current preset defaults and media-dependent tests. These directories are not included in Git; the bundled `data/demo_media/` alone does not cover all current defaults.

Never commit real API keys. Keep them only in the local `.env` file.

### Install and run

```powershell
git clone https://github.com/yyhhee/vision-skill-forge.git
cd vision-skill-forge
conda env create -f environment.yml
conda activate vision-skill
pip install -r requirements.txt
$env:VISION_SKILL_PORT = "6131"
python app_v2.py
```

Open [http://127.0.0.1:6131](http://127.0.0.1:6131).
If the `vision-skill` environment already exists, skip its creation. The explicit port above selects 6131; without `VISION_SKILL_PORT`, `app_v2.py` defaults to 6122.
Restore the required local media before starting the preset catalog. A code-only clone can fail during default-media seeding (for example, the missing P01 image); this checkpoint is not a self-contained installer. See the checkpoint notes for the verified scope.

## Workflow in the UI

1. Describe the visual task in one sentence or select a preset skill.
2. Review the generated semantic intent and editable conditions.
3. Add only the scene resources the task needs, such as regions or direction references.
4. Validate and generate the current runnable version.
5. Run it on an image or video and inspect the evidence and result.

## Preset demonstrations

| ID | Skill |
| --- | --- |
| P01 | Fire and smoke detection |
| P02 | Traffic accident detection |
| P03 | Special vehicle detection |
| P04 | Highway congestion |
| P05 | Wrong-way driving |
| P06 | Person dwelling in a lane |
| P07 | Illegal parking |
| P08 | Road debris |
| P09 | Person without a safety helmet |
| P10 | Work at height without a safety rope |
| P11 | Service-area garbage |
| P12 | Person fall detection |
| P13 | Bridge damage |

Preset packages are stored in `presets_v2/`. They demonstrate the same registered capabilities and runtime used by naturally generated skills.

## Repository layout

```text
vision-skill-forge/
├── app_v2.py          # Gradio application
├── clients/           # Planner and Rex clients
├── core/              # Semantic IR, compiler, editor, validation, and runtime
├── operators/         # Registered typed execution operators
├── presets_v2/        # P01–P13 preset skill packages
├── scripts/           # Acceptance and maintenance scripts
├── tests/             # Automated tests and reproduction fixtures
├── data/              # Demo media and local runtime artifacts
└── .env.example       # Environment configuration template
```

## Testing and reproduction

```powershell
python -m pytest -q
python -m scripts.run_v2_semantic_acceptance
python -m scripts.run_historical_v2_acceptance
```

Execution results must come from actual runs. Expected outputs must never be presented as successful runtime results.
The acceptance commands call real model services and require their configured credentials and test media; they are separate from the deterministic test suite. Historical acceptance records do not certify changed presets or a new checkout automatically. Video sampling and optional tiling can create multiple inference requests; multi-category batching does not mean one request for an entire video.

## Checkpoints and restoration

See [Version history and restoration](docs/VERSION_HISTORY.md) for the human-readable checkpoint record and safe restoration instructions. The separately developed frontend prototype is not included in this original Gradio application checkpoint.

## Design principles

- Generated skills must remain inspectable and editable.
- Visual evidence must remain separate from business decisions.
- Operators must have explicit versions, parameters, and input/output types.
- Media preprocessing, grounding, tracking, logic, and temporal behavior must remain explicit in the effective workflow.
- Scene resources such as ROIs are required only when the task semantics require them.
- Existing skills remain compatible unless an explicit migration is performed.

## What this project does not do

- It does not let the LLM generate arbitrary executable code.
- It does not hide missing configuration behind fabricated defaults.
- It does not use expected answers as model outputs.
- It does not replace scenario-specific acceptance testing or human review for high-risk deployments.

## Project status

Vision Skill Forge is under active development. The repository currently provides the V2 application, typed workflow runtime, editable skill review, image and video execution, and P01–P13 demonstrations.
