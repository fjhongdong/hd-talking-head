# 3.14.1-rc.1 output signature verification

The common still/video renderer adds the official animated Circle and final-output clock. Frozen packs, catalog selections, published demos, narrative timing, subtitle runtime, presenter motion and audio recipes remain unchanged.

Verified on macOS, 2026-10-18:

- Current catalog: 11 styles, 21 supported landscape/portrait routes, all 101 scene groups.
- Original anim3 and anim4 routes plus all nine starter components: total 24 routes / 131 groups.
- Each group: native dimensions, one output layer, safe insets and final output time. Each route also checks animation changes, reversible seeks, unchanged SFX event data and no duplicate decorative `.tc` clock.
- Local mixed iframe composition: one parent signature, source HUD clock removed, user brand retained and moved outside the signature slot. A scene clock outside the HUD stays visible.
- Light/dark background selection, bounded short films, full long-film animation windows, explicit opt-out, old projects without new config, changed-asset rejection and cropped legacy viewports.
- Native 1080×1920 and 1920×1080 actual encoded 15-second QA videos, 12 fps, three separately rendered segments each: identical whole-film signature receipts, all 180 display timestamps verified, audio correlation 0.999998 with the explicit test-tone source, unchanged input project hashes.
- 245 Python regressions passed. Existing macro, presenter, subtitle, preview-player and authored-unit Node regressions passed, as did signature schedule tests. One stale quality-test expectation was corrected to the already-existing `classic-performance@1.1.1-candidate` catalog default; no selection was changed.

Reproduction:

```sh
npm ci
python -m pip install -r requirements-runtime.txt
python -m unittest discover -s tests
node --test tests/test_output_signature.mjs
node tests/test_signature_browser.mjs
```

Use `CHROME` for an existing Chromium executable; `ADU_TEST_PYTHON` can select the fixture Python. `ADU_SIGNATURE_REPORT` optionally saves route screenshots and a JSON report outside the repository. Test-owned temporary directories are removed.

These checks use explicitly synthetic images, system fonts and a test tone. They certify the new decoration and regressions; they do not certify new human narration, artistic acceptance, Windows hardware, or any historical candidate pack's independent production readiness.
