# Construction clean photo — provenance

Created: 2026-10-19. Consumer: `SceneViewport`. Built-in `image_gen` edit mode; no API CLI or manually drawn replacement.

## Source and result

- Source reference: `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/04-linked-workbench.png` (1513×1040).
- Intended extraction area: x217, y275, width585, height440. Source is a generated UI composite, not an independent camera original.
- Selected raw output: `C:/Users/83915/.codex/generated_images/01a151d0-e3a7-73f3-b57d-76830aa728be/exec-15b046a6-d151-4f07-b0c5-0c3c19777c8a.png`.
- Project copy: `C:/Users/83915/Vision Skill Forge Frontend/public/assets/media/construction-clean.png`.
- Actual selected output dimensions: **1448×1086**, exact 4:3.
- First generation: `C:/Users/83915/.codex/generated_images/01a151d0-e3a7-73f3-b57d-76830aa728be/exec-4217f491-8c1b-4425-a964-884c36f0cda3.png`, also1448×1086; preserved unchanged.

## Inspection

Both generated candidates were viewed. Selected image contains only a clean photographic scene, no UI, text, labels, ROI tints, polygon outlines or handles. Four workers remain: left red top/gray trousers; upper middle navy worker; right pair orange and lime reflective vests. Elevated perspective, green mesh, crane structure and rebar arrangement broadly match the reference crop.

This is a **generative reconstruction**, not pixel-identical extraction. Material textures, small construction details and individual positioning differ from source. A second explicit high-resolution request still returned1448×1086: the requested long edge≥1600 is **not satisfied**. No code upscale was used to conceal this limit. Resolution is more than2× the585×440 native viewport, but do not mark the source-resolution requirement as passed. Exact raw-photo pixel matching remains unavailable without the independent original. Static still only; not video evidence or actual detection output.

## Initial prompt

```text
Use case: precise-object-edit.
Asset type: clean photographic construction-site background for the SceneViewport component of a frontend, NOT a UI screenshot.
Input image 1 is the edit target and composition reference. Extract and reconstruct ONLY the rectangular construction photograph inside it, whose bounds are x=217,y=275,width=585,height=440 in the 1513x1040 source. Output only that photo as a high-resolution 4:3 landscape raster, target 2048x1536 or at least 1600 pixels long edge. Do not include surrounding application UI.
Preserve the crop's elevated steep oblique camera looking down onto a concrete construction floor, exact subject placement and scale, building and daylight direction. Left foreground quarter: one worker yellow hardhat, red long-sleeve top, gray pants, facing away standing upright. Middle upper area: one worker yellow hardhat and dark blue/navy clothing walking away. Right half: two workers in yellow hardhats and reflective safety vests, one orange vest and one yellow-lime vest, close together facing away. Four workers total.
Keep concrete slab floor and construction materials, grid of vertical rebar cages, piles of horizontal reinforcing steel, green-mesh scaffolding across the top, orange/yellow tower crane structural beam at far right, sunlit surfaces and strong diagonal long shadows. Preserve the source photograph's realistic texture, perspective and construction-material layout as closely as possible, without inventing new major objects.
Remove ALL orange and teal ROI polygon tint fills, outlines, circular handles, region labels, markings, drawings, and text that were overlaid on the photograph. Reconstruct clean natural photographic pixels beneath them. No bounding boxes, no geometric overlays, no watermark, no captions, no UI chrome. Only the clean construction photograph.
```

## Targeted high-resolution follow-up

```text
Use case: precise-object-edit.
Asset type: clean photographic construction-site background for the SceneViewport component of a frontend, NOT a UI screenshot.
Input image 1 is the edit target and composition reference. Extract and reconstruct ONLY the rectangular construction photograph inside it, whose bounds are x=217,y=275,width=585,height=440 in the 1513x1040 source. Output only that photo as a high-resolution 4:3 landscape raster, target 2048x1536 or at least 1600 pixels long edge. Do not include surrounding application UI.
Preserve the crop's elevated steep oblique camera looking down onto a concrete construction floor, exact subject placement and scale, building and daylight direction. Left foreground quarter: one worker yellow hardhat, red long-sleeve top, gray pants, facing away standing upright. Middle upper area: one worker yellow hardhat and dark blue/navy clothing walking away. Right half: two workers in yellow hardhats and reflective safety vests, one orange vest and one yellow-lime vest, close together facing away. Four workers total.
Keep concrete slab floor and construction materials, grid of vertical rebar cages, piles of horizontal reinforcing steel, green-mesh scaffolding across the top, orange/yellow tower crane structural beam at far right, sunlit surfaces and strong diagonal long shadows. Preserve the source photograph's realistic texture, perspective and construction-material layout as closely as possible, without inventing new major objects.
Remove ALL orange and teal ROI polygon tint fills, outlines, circular handles, region labels, markings, drawings, and text that were overlaid on the photograph. Reconstruct clean natural photographic pixels beneath them. No bounding boxes, no geometric overlays, no watermark, no captions, no UI chrome. Only the clean construction photograph.
Targeted change: upscale the already reconstructed clean photograph to 2048x1536 or 2048x1536-equivalent high-resolution 4:3. Preserve every placement, crop, perspective, all four people and construction arrangement. Increase pixel dimensions, do not redesign. This asset needs a long edge at least 1600 pixels. No UI, markings or text.
```
