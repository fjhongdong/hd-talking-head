# A-roll transparent overlay adapter

This adapter is a thin, parameterized `custom_fallback` producer for the user-approved Standard09 A-roll annotation. It imports the locked TalkCraft `schematic.tsx` primitives directly; it does not claim membership in the 108 qualified cards and does not invent a new visual style.

Install this directory's pinned `@remotion/paths@4.0.520` with `npm ci --ignore-scripts --no-audit --no-fund`. Other Remotion/React dependencies resolve from the existing sibling production runtime, which must not be upgraded for this adapter.

`render.mjs` is intended for `ReferenceProcessAdapter` and reads its entrypoint through `node --input-type=module /dev/fd/0`. It accepts exactly:

```text
--brief /abs/brief.json --output /abs/out.mov --adapter-root /abs/aroll-overlay --ffmpeg /abs/ffmpeg --source-sha256 <64hex> --browser /abs/browser
```

The brief envelope is `{schema_version:1, renderer_input, source_binding}`. The renderer validates the canvas, labels, finite local timing, and basic source-binding shape. The outer Python adapter remains responsible for proving the A-roll SHA and segment interval correspond to the approved Job. Output is a silent QTRLE/ARGB MOV with real transparency; the intermediate VP9 WebM is temporary and removed.

Timing is component-local seconds. `canvas.frames` may cover the full A-roll segment; after `timing.exit` the component is fully transparent. The renderer does not perform the heavy render during static checks; callers should keep render concurrency at one.
