# Gemini Omni motion draft and localized edit pass

Use this optional stage only when the ChatCut plugin is installed and the user has video-generation entitlement. In ChatCut, the user-facing model is **Gemini Omni**, the tool value is `model: "omni"`, and the backend model is `gemini-omni-flash-preview`.

Gemini Omni belongs between approved keyframes and final animation. It is an editing and drafting layer, not the default finishing model.

## Decision table

| Need | Route |
| --- | --- |
| Quickly test motion from one approved keyframe | Gemini Omni + `firstFrame` |
| Generate a new scene using up to three subject/style images | Gemini Omni + `refImages` |
| Change one local property in an existing clip and preserve the rest | Gemini Omni + `continueFrom` |
| 1080p final, source longer than 10 seconds, extension or bridge | Seedance 2 or Kling |
| Exact Logo part motion, UI, URL, Chinese text or pixel-precise timing | HyperFrames or deterministic overlay |
| No ChatCut access or credits | Skip this stage; use another Phase 4 route |

## Required limits

- Duration target: 3–10 seconds. An edit inherits the source clip duration.
- Output: always 720p at 24fps. Do not pass `resolution`; `1080p` is rejected.
- Ratios: `16:9` or `9:16` only.
- Choose exactly one input mode: `firstFrame`, `refImages` or `continueFrom`.
- `refImages` accepts at most three images.
- There is no `lastFrame`, interpolation, extension, bridge, `refVideos` or `refAudios` mode.
- Generated clips can contain native audio, but Omni cannot accept audio references or replace spoken audio.
- Output contains an invisible SynthID watermark.

## Prompt rules for paper collage

Write prompts in English. Describe what should happen positively; do not use a negative-prompt block. Replace “no camera shake” with “locked-off static camera.” Use bracketed timing when a beat must land at a specific moment.

Track no more than three important subjects. Preserve the approved paper system explicitly: fibrous off-white stock, halftone dots, cut edges, narrow warm-white keyline and consistent lower-right shadows. Keep the camera simple so the result tests the paper action rather than inventing a new visual language.

Example motion prompt:

```text
[0-2s] Locked-off static camera. Three cut-paper file cards slide in from the left one at a time, each landing with a small stop-motion bounce and a soft paper tap. [2-4s] The green paper lever flips down and the cards line up neatly. [4-5s] Hold the finished composition. Preserve the fibrous off-white stock, halftone dots, cut edges and lower-right paper shadows.
```

Do not ask Omni to render Chinese or other CJK text. Latin text is also weaker than a deterministic overlay. Generate the physical action first, then add exact labels, URL, UI and wordmark in HyperFrames or another motion-graphics layer.

## ChatCut call patterns

The IDs below are project asset references returned by ChatCut. Do not use local file paths directly in these fields; import the media into the ChatCut project first.

First-frame motion draft:

```js
submit_video({
  model: "omni",
  prompt: "[0-3s] Locked-off static camera. The cut-paper cards slide into place one by one with restrained stop-motion bounce. [3-5s] Hold the final composition. Preserve the paper texture, halftone dots and shadows.",
  firstFrame: "<image-asset-id>",
  durationSeconds: 5,
  ratio: "16:9",
  name: "Scene 01 - Omni motion draft"
})
```

Localized repair of an existing clip:

```js
submit_video({
  model: "omni",
  prompt: "Make only the top paper card forest green. Keep everything else exactly the same.",
  continueFrom: "<video-asset-id>",
  name: "Scene 01 - green card repair"
})
```

Reference-image draft:

```js
submit_video({
  model: "omni",
  prompt: "Create a new locked-off cut-paper scene using Image 1 as the character and Image 2 as the material and color reference. The character pushes one file card into a paper machine, then pauses proudly.",
  refImages: ["<character-image-id>", "<style-image-id>"],
  durationSeconds: 6,
  ratio: "16:9",
  name: "Scene 02 - Omni reference draft"
})
```

Do not combine the three input forms and do not add `resolution`.

## Review gate and handoff

After each generation, inspect the whole clip and compare first, middle and final frames against the approved keyframe. Check paper texture, silhouette, shadows, brand colors, unexpected objects, text artifacts and the readability of the comic action.

- If the motion idea fails, change the beat or regenerate from the clean keyframe.
- If one localized visual detail fails, use one concise `continueFrom` edit.
- If the change affects motion, camera, duration or the whole visual style, regenerate with Seedance/Kling rather than forcing a local edit.
- If an edit chain reaches round four, stop and refresh from a clean source; degradation and full-generation charges compound.
- If the approved 720p result is acceptable for delivery, keep it as a scene source.
- If the final requires 1080p, treat the Omni clip as motion reference and finish in Seedance/Kling, or reproduce the approved timing precisely in HyperFrames.

The cost is charged for each complete generated clip, including edits. Ask for approval of the draft before starting another paid round.
