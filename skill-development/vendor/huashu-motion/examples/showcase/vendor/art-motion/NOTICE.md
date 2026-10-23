# art-motion engine (vendored)

Source: https://github.com/alchaincyf/huashu-art-motion — `scripts/engine/`, commit `57d6760` (2026-10-08).
License: MIT, see `LICENSE` in this folder. Fonts in `../../assets/fonts/` are SIL OFL 1.1, see `../../assets/fonts/LICENSES.md` and `OFL.txt`.

Only what this film draws with is copied: `engine.js`, `transitions.js`, `eras.js`, `scenes/index.js`, the 15 scenes listed in `eras.js`, `lib/util.js paint.js brush.js render.js post.js rig.js kit.js`, and 22 of the font files (the upstream `LICENSES.md` still lists the full set).

Changes from upstream:

- `scenes/01_cave.js`: the opening title reads `window.FILM_TITLE` (falls back to the original text), so it can be a composition variable. This is the only edited line.

Everything else is wired from `index.html` without touching these files: the scene scripts are loaded with `<script>` tags instead of the engine's synchronous XHR, `window.FONT_FACES` points at `assets/fonts/`, the finale is drawn with a 3-eighth time offset (its performance is keyed to absolute frame numbers authored for an earlier cut that had one more era), and `OM.clock` drives `renderFrame(t)` from the film's GSAP timeline.
