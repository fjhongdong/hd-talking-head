# Punk Avatar Prompt Blueprint

This blueprint defines the complete avatar-prompt shape used by `punk-avatar`.

`styles/{style-id}/STYLE.md` is a reusable visual style atom. This blueprint is the avatar shape. The final `prompts/avatar.md` must compile the selected style atom into this avatar shape and read like one complete image-generation prompt.

Do not paste this blueprint verbatim with empty placeholders. Fill it with derived subject fields and selected style anchors.

## Required Final Prompt Structure

```text
# {style name} avatar prompt

You are a top-tier avatar art director, portrait designer, character designer, and image-generation prompt director.

Create one single avatar image with aspect ratio {ratio}.

The avatar must use the selected visual style: {style name} / {style id}.
This style is not a decorative filter. Every major avatar decision must be implemented through this style's visual language.

## Input

- Subject type: {subject_type}
- Generation mode: {image_based_or_description_based}
- Subject identity: {subject_identity}
- Recognizable traits: {recognizable_traits}
- Name or text to include: {name_or_text}
- Intended use: {use_case}
- Aspect ratio: {ratio}
- Background preference: {background_preference}
- Mood: {mood}
- Preserve: {preserve}
- Avoid: {avoid}

## Source Interpretation

If the input includes an image, use it as the primary source. Extract only the subject traits needed for an avatar: silhouette, face or head structure, hair or fur, eyes, expression, posture, signature colors, clothing, accessories, marks, and memorable details.

If the input is text-only, create a description-based fictional avatar. Do not claim that the result preserves photo likeness.

Do not preserve the original environment unless the user explicitly asks for a small meaningful clue and the selected style can support it.

## Avatar Objective

Generate a deliberate avatar or avatar-derived keepsake image, not a generic illustration, poster, cover, sticker sheet, advertisement, or multi-scene composition.

The avatar must work at profile-picture size:

- Clear subject identity.
- Strong silhouette.
- Readable face, head, body, or object shape.
- Simplified background.
- No important facial features, ears, paws, hair, accessories, or object edges cropped by accident.
- One primary subject unless the user explicitly asks otherwise.

## Likeness Policy

For image-based inputs, preserve the subject's most recognizable visual traits while translating them into the selected style. Preserve recognizability through selected features, not through photorealistic copying.

For description-based inputs, follow the described traits and mood. Do not promise real-person or real-pet likeness.

## Style Application

Apply the selected style's non-negotiable anchors:

- Style intent: {style_intent}
- Style anchors from the visual atom: {style_anchors}
- Subject and composition behavior: {subject_composition_behavior}
- Background behavior: {background_behavior}
- Color, material, and texture logic: {color_material_texture_rules}
- Must preserve: {must_preserve}
- Style-specific avoid list: {style_avoid}

These anchors must visibly affect:

1. Subject simplification and exaggeration.
2. Face, expression, posture, or object silhouette.
3. Crop and safe area.
4. Background or frame structure.
5. Color, line, material, and texture.
6. Optional name, signature, or tiny text behavior.

Do not mention a style trait unless it is actually visible in the final image.

## Composition

Design an avatar-specific composition using the selected style.

Define:

- Primary visual center: {primary_visual_center}
- Crop: {crop_strategy}
- Safe area: keep the subject's key identifying features away from the outer edge.
- Background or frame: {background_or_frame}
- Small-size readability: the subject must remain clear when reduced to a profile-picture thumbnail.
- Optional text: {optional_text_behavior}

For `polaroid-keepsake`, keep the polaroid frame recognizable even at `1:1` unless the user specified a vertical ratio. Preserve the wide bottom white margin and small handwritten name if a name is provided.

## Color, Material, and Texture

Use the selected style's color, material, and texture logic:

{color_material_texture_rules}

The result must feel like a finished avatar artwork in this style, not a style word applied superficially.

## Negative Constraints

Avoid:

- {avoid}
- Cover layout or poster layout.
- Article title hierarchy.
- Generic social media cover composition.
- Complex background that competes with the subject.
- Multiple unrelated subjects.
- Cropped-off identity features.
- Text that is too large for an avatar.
- Photorealistic copying unless explicitly required by user and compatible with the selected style.
- Style-specific failures: {style_avoid}

## Final Standard

Generate only one final image.

Do not output explanations, alternatives, grids, contact sheets, or multi-option compositions.

The final image must satisfy all of these:

1. It is clearly an avatar or avatar-derived keepsake image at {ratio}.
2. It preserves or invents the subject according to the generation mode.
3. It uses the selected style as the visible organizing language.
4. The subject remains readable at small profile-picture size.
5. Background, crop, color, and texture support the subject instead of competing with it.
6. The result has the completeness and specificity of a full avatar prompt, while keeping the selected style reusable as an independent atom.
```

## Compilation Notes

- Rewrite the blueprint into a natural final prompt. Do not leave meta-instructions like `{primary_visual_center}` unresolved.
- Use the selected `META.md` metadata when it provides structured fields.
- Use `STYLE.md` to recover style language that is not yet structured in metadata.
- The final prompt may add style-specific sections when needed, but must not add another style.
- The final prompt should be longer and more complete than the raw style atom, because it includes avatar shape, likeness policy, crop safety, and subject adaptation.
