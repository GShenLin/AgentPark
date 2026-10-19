# 按任务取用的提示词

下列大括号是需要填入的变量。保持用户已有美术方向，不把烹饪示例的颜色、物体或数量推广到所有项目。每次记录实际填写后的完整提示词与参考图路径。

## 数据驱动界面原型

```text
Input image 1 is the visual and layout reference.
Create a clean {aspect_ratio} game UI prototype for {screen_purpose}.
Preserve {style, materials, palette, lighting, layout regions}.
Use this view model: {explicit JSON with test values identified}.
Render these labels verbatim: {labels}.
Keep {selected, disabled, hover or other requested states} recognizable.
Remove only {player/browser overlays identified in the input}.
Fit all controls comfortably within the frame. Do not add game features.
This is a static prototype, not an editor view, annotated diagram or asset atlas.
```

既有设计稿已经满足需要时跳过本步。视觉参考中的未知数值可能被模型沿用，要逐项检查，不宣称整个图严格由 JSON 控制。

## 可复用素材图集

```text
Input image 1 is the source UI design.
Decompose and reconstruct exactly {count} reusable art elements on genuine
transparent alpha, preserving {style invariants}.
Layout: {rows} rows by {columns} columns. Asset order:
{row-by-row explicit list with one complete object per cell}.
Leave at least {padding} transparent space around every asset, no overlap.
Keep panels blank for runtime text: no labels, numbers or stat bars.
Preserve complete contours and distinguish {normal/selected/disabled states}.
No scene background, captions, grid lines, watermark or fake checkerboard.
Match perspective and lighting to the source. Do not add small decorations.
This is a generated reconstruction; prioritize consistent reusable artwork.
```

长面板和小图标混排容易导致不规则网格。实际需要统一尺寸时，分组生成或逐张生成；不要仅依赖行列提示词保证资源规范。

## 单元素透明图标

```text
Input image 1 is the source/reference.
Reconstruct ONLY {asset identity and distinguishing details} as one standalone
game sprite. Preserve {shape, viewpoint, proportions, materials and lighting}.
The full object must be visible and centered, with at least {fraction}%
transparent margin on every side. Target size/aspect: {requirement}.
No labels, panel, rating stars, scene, extra props or external shadow.
Use genuine alpha transparency and a clean contour, not a painted background.
```

写入尺寸/边距要求后仍需实测。需要准确原图轮廓时不要用“提取”掩盖生成重绘；如结果改变了形状，明确交付为新图标候选。

## 动效部件

```text
Input image 1 is a style reference for {game/UI}.
Generate {one asset OR an explicit separated list} for {effect purpose}.
Match {palette and visual style}. Show complete isolated sprites with generous
transparent gutters; do not overlap glows or clip the canvas edges.
Use smooth partial alpha for {steam/glow} and crisp contours for {spark/ember}.
No animation strip, diagrams, arrows, text, scene or checkerboard.
Output real transparent alpha. These are static parts to animate later.
```

光晕图集容易相互污染，重要光效优先独立生成。蒸汽的外观可能偏火焰或飘带，应明确形态；单颗余烬要禁止碎片群。

## 单缺陷修正

```text
Input image 1 is the previous generated version.
Change only {specific observed defect}. Keep {accepted properties} unchanged.
The acceptance requirement is {measurable constraint or visual comparison}.
Preserve real alpha transparency. Do not add or redesign other elements.
```

修正后重新检查；这段提示词不能保证其他部分完全不变。
