"""Build a self-contained warm-clay fragment for the native Barty transparent renderer."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = PACKAGE_ROOT / 'references/production-defaults.json'
THREE = PACKAGE_ROOT / 'assets/motion-native-runtime/cinecode/three/build'
KIT = PACKAGE_ROOT / 'assets/warm-clay-overlay.js'
GUIDE = PACKAGE_ROOT / 'references/warm-clay-overlay.md'


def overlay_style(treatment=None):
    if (treatment or {}).get('overlay_style') == 'native':
        return None
    return json.loads(DEFAULTS.read_text(encoding='utf-8'))['aroll_overlay']['style']


def authoring_input(style, *, frames=None, timing=None):
    argv = [sys.executable, str(Path(__file__).resolve())]
    if timing is not None:
        argv += ['--frames', str(frames), '--action-start-frame', str(timing.get('action_start_frame', 0)),
                 '--settled-frame', str(timing['settled_frame']),
                 '--visible-until-frame', str(timing['visible_until_frame'])]
    return {**style, 'guide': str(GUIDE), 'build_argv': argv}


def _js(value):
    return json.dumps(value, ensure_ascii=True).replace('</', '<\\/')


def build_fragment(source, *, frames, center_x, center_y, action_start_frame, settled_frame, visible_until_frame):
    defaults = json.loads(DEFAULTS.read_text(encoding='utf-8'))
    canvas = defaults['canvas']
    options = {**canvas, 'frames': frames, 'centerX': center_x, 'centerY': center_y,
               'cues': {'action_start_frame': action_start_frame, 'settled_frame': settled_frame,
                        'visible_until_frame': visible_until_frame}, 'style': defaults['aroll_overlay']['style']}
    core = _js((THREE / 'three.core.js').read_text(encoding='utf-8'))
    module = _js((THREE / 'three.module.js').read_text(encoding='utf-8'))
    return f'''<title>Warm clay overlay</title>
<style>
#clay-scene {{ position: absolute; inset: 0; width: {canvas['width']}px; height: {canvas['height']}px; }}
#clay-scene canvas {{ display: block; }}
</style>
<div data-slot="over"><div id="clay-scene"></div></div><!--/over-->
<script>
{KIT.read_text(encoding='utf-8')}
{source}
const clayOptions = {_js(options)};
let drawClay;
const seekClay = M.scene({{
  W: clayOptions.width, H: clayOptions.height, T: clayOptions.frames / clayOptions.fps,
  center: [0, 0], bg: null, intro: null, SH: {{ clay: {{ w: 0, h: 0, r: 0, bg: '#000000', cam: 1 }} }},
  start: 'clay', SEQ: [], extra: t => drawClay?.(t),
}});
const clayCoreURL = URL.createObjectURL(new Blob([{core}], {{type: 'text/javascript'}}));
const claySource = {module};
const clayModuleURL = URL.createObjectURL(new Blob([claySource.replaceAll('./three.core.js', clayCoreURL)],
                                                   {{type: 'text/javascript'}}));
const clayReady = import(clayModuleURL).then(async THREE => {{
  URL.revokeObjectURL(clayModuleURL);
  URL.revokeObjectURL(clayCoreURL);
  drawClay = await createWarmClay(THREE, document.getElementById('clay-scene'), clayOptions, designOverlay);
  drawClay(0);
}});
window.seek = async t => {{
  await clayReady;
  seekClay(t);
}};
</script>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path, help='Job-local JavaScript that defines designOverlay')
    parser.add_argument('fragment', type=Path, help='Job-local input to native engine/build.py')
    parser.add_argument('--frames', type=int, required=True)
    parser.add_argument('--center-x', type=int, default=540)
    parser.add_argument('--center-y', type=int, required=True)
    parser.add_argument('--action-start-frame', type=int, required=True)
    parser.add_argument('--settled-frame', type=int, required=True)
    parser.add_argument('--visible-until-frame', type=int, required=True)
    args = parser.parse_args()
    fragment = build_fragment(args.scene.read_text(encoding='utf-8'), frames=args.frames,
        center_x=args.center_x, center_y=args.center_y, action_start_frame=args.action_start_frame,
        settled_frame=args.settled_frame, visible_until_frame=args.visible_until_frame)
    args.fragment.write_text(fragment, encoding='utf-8')


if __name__ == '__main__':
    main()
