# Brand mark provenance

- Date: 2026-10-19 (Asia/Shanghai).
- Mode: built-in `image_gen`, `transparent_background: true`; one generation and one targeted cleanup edit. No CLI fallback or external model API key used.
- Reference: `C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/04-linked-workbench.png`, header mark near x23, y20, displayed at approximately 30 × 30 CSS pixels.
- Final selected generated source: `C:/Users/83915/.codex/generated_images/01a151d1-20d1-70b2-8f1a-e72e51ace362/exec-107e3ea3-a46f-4554-b7e9-934ba3238d22.png`.
- Project asset: `C:/Users/83915/Vision Skill Forge Frontend/public/assets/brand/vision-forge-mark.png`.
- Dimensions: 1254 × 1254 PNG, 32-bit ARGB. Outside corner alpha = 0; center sampled alpha = 254. This is genuine alpha, not an opaque checkerboard.
- Consumption: AppShell header at 30 × 30 CSS pixels; preserve aspect ratio. The generated rounded square has approximately 7–9% transparent outer margin and can appear smaller than a 30 px CSS box. Prefer a 30 px overflow-hidden image viewport with a centered approximately 116% image rather than changing the source bytes. This is an approximate consumption adjustment to verify in the header screenshot, not an assertion of exact pixel equivalence.
- Visual review: white capital V and vivid indigo rounded square match the reference identity. The final asset is cleaner than the initial generation, but is not an exact vector duplicate: its V is slightly rounder/heavier, color has slight raster variation, outer alpha includes a few faint stray edge pixels. At 30 px these need checking in the implementation capture; do not call this asset pixel-identical or mark the full page accepted.
- No Python editing, resampling, or background replacement was used; selected output was copied intact. Original generated variants retained.

## Final cleanup prompt

```text
Edit target: the standalone V mark in image 1. Input image 2 is the original app header reference.
Use case: logo-brand
Change ONLY the asset finish and crop. Keep the same indigo rounded square and centered white capital V with its original layout.
Remove every texture, smudge, blotch, stray pixel, shadow, lighting gradient and irregular edge. Make the square uniformly opaque flat indigo #4F46FF and the V uniformly opaque flat pure white, with clean antialiased boundaries.
Tight square framing: the rounded square spans 98% of both image width and height. Transparent background outside the rounded square and nowhere inside it. The output is a clean app icon PNG on genuine alpha, no extra design, no letters except V, no watermark, no border. Match the original small reference mark's simple neat V.
```

## Prior generation prompt

```text
Use case: logo-brand
Asset type: standalone transparent PNG brand mark for a desktop web app header, displayed at 30 x 30 CSS pixels.
Input image 1 is a visual reference ONLY. Reproduce ONLY the tiny brand mark in its top-left corner at approximately x23 y20: a compact indigo/purple rounded square with a simple white uppercase V centered inside.
Primary request: create a clean high-resolution standalone raster of exactly that mark, closely matching the reference shape, color, corner radius and centered white V. The square should almost fill the square image canvas, with only a very small transparent margin.
Text (verbatim): "V"
Color palette: vivid indigo approximately #4F46FF; pure white letter.
Style: crisp flat UI brand mark, smooth antialiased edge; no new symbol.
Constraints: transparent outside the rounded square; square composition; at least 120 x 120 pixels; no product name, no slogan, no shadow, no decorative effects, no added background, no watermark. Preserve the reference's plain simple V rather than turning it into a complicated chevron or emblem.
```
