# 01 技能库独立缩略图

2026-10-19，使用内置 imagegen 生成，非CLI/API fallback。都是演示用照片，不是检测结果。每张独立生成与检查，没有从拼图裁切，不含UI/标注/文字/水印。生成后从默认输出复制到项目，无旧文件被覆盖。消费位置：SkillLibrary，原生列表80×80px；同一图片可作为示例详情预览。

| 文件（本目录） | 源像素 | SHA256 |
|---|---|---|
| furniture.png | 1254×1254 | de6666fc1d317cd86b6cf14f3e7a838ff23ae65719f01089ba4801e28dcff767 |
| traffic.png | 1254×1254 | 600002135b8e96cfcf1f0d796b6b757b1fa02ee4c258d43e5b3d9d08425e7455f |
| debris.png | 1254×1254 | 23e59f557145301d4ade4ac2c1787e776960e9815b9efc5b598bb88ad15d1572 |
| bridge.png | 1254×1254 | 459f14b96d86156f52b3b229bc5a3aadccba49e4043e29fcedb57f101581c105 |

参考：`C:/Users/83915/Vision Skill Forge UI Concepts/2026-10-19-frontend-spec/references/01-skill-library.png` 的对应小图方向。不是原图像素完全相同的复原，不宣称来自真实业务媒体。主施工图与品牌/字体继续使用原已确认文件，不重新生成。

## Exact prompt · furniture.png

```text
Use case: photorealistic-natural
Asset type: square raster photograph for an 80×80 furniture thumbnail in a visual skill library
Primary request: a mustard-yellow fabric armchair on the left, a white upholstered chair on the right, and a small light-wood round table between them, in a bright contemporary neutral living room
Scene/backdrop: simple white walls and pale natural wood flooring
Style/medium: photorealistic interior photography with real woven upholstery and wood grain
Composition/framing: native square image, minimum 288×288 pixels; furniture grouped centrally and fully recognizable in a square cover crop; eye-level view, similar visual direction to a small clean furniture catalog thumbnail
Lighting/mood: soft daylight, calm neutral room
Constraints: only the furniture photograph; no interface elements, no text, no borders, no boxes, no logos, no watermark
```

## Exact prompt · traffic.png

```text
Use case: photorealistic-natural
Asset type: square photograph thumbnail for a vision skill library, readable at 80x80 pixels, source at least 288x288.
Primary request: elevated oblique viewpoint of a congested divided multilane highway curving gently away between green trees in daylight.
Scene/backdrop: realistic gray asphalt, white lane markings, concrete median and roadside barriers, dense green trees edging both sides.
Subject: many closely spaced cars filling the near carriageway, with visibly lighter traffic on the opposite carriageway; varied everyday white, gray, black and blue cars.
Composition/framing: square crop, highway fills almost the entire image; foreground near lanes broad across lower frame, road narrowing and bending gently toward upper middle; no dominant sky area.
Style/medium: photorealistic documentary transportation photograph, naturally detailed cars and road textures.
Lighting/mood: ordinary soft daytime light.
Color palette: neutral natural gray road and green trees.
Constraints: image only; no labels, no UI, no detection boxes, no overlays, no logos, no watermark, no artificial dramatic color grading.
```

## Exact prompt · debris.png

```text
Use case: photorealistic-natural
Asset type: square website library thumbnail, displayed at 80x80 pixels
Primary request: one photorealistic view along a grey asphalt road with orange-and-white traffic cones tipped over and small orange cargo pieces scattered in the foreground, with a few distant cars near the upper edge.
Style/medium: realistic daytime documentary road photograph, natural neutral colors and visible asphalt grain.
Composition/framing: native square image at least 288x288 pixels; road and clearly recognizable orange debris fill the foreground; perspective recedes toward the upper edge; clear subject readable at a tiny thumbnail scale.
Lighting/mood: ordinary soft daytime light, neutral palette.
Constraints: a single cohesive photograph; no UI, labels, bounding boxes, text, watermark, collage, or graphic overlays.
```

## Exact prompt · bridge.png

```text
Use case: photorealistic-natural
Asset type: square raster bridge inspection photograph for an 80×80 visual skill library thumbnail
Primary request: the underside of a concrete road bridge with a large weathered gray concrete pier and beam, a small surface crack and water stain, dark horizontal metal railing at the upper edge, pale blue-gray daylight sky
Style/medium: photorealistic civil infrastructure photograph, natural neutral colors and concrete texture
Composition/framing: native square image, at least 288×288 pixels; close view looking slightly upward with the large bridge pier and underside centrally framed and recognizable at tiny thumbnail scale; bridge deck runs across the upper part of the image
Lighting/mood: soft neutral daylight
Constraints: subtle ordinary surface weathering only; no major structural collapse; no people; no interface elements, no text, no bounding boxes, no border, no logos, no watermark
```
