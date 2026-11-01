// A small film for the engine tests: no GSAP, a fake paused timeline, a video clip WITHOUT an id (the case that
// used to render black), variables, a non-JS script, an audio track. Built in a temp folder so nothing depends on outputs/.
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const HAS_FFMPEG = spawnSync('ffmpeg', ['-version']).status === 0;

export function makeFilm({ script = '', body = '', duration = 2, video = true, sound = true, clear = false } = {}) {
  const dir = join(mkdtempSync(join(tmpdir(), 'om-film-')), '片 子');
  mkdirSync(join(dir, 'assets'), { recursive: true });
  if (video) spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=30:duration=1.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', join(dir, 'assets', 'clip.mp4')]);
  if (sound) spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `sine=frequency=330:duration=${duration}`, '-af', 'volume=0.2', '-ar', '48000', '-ac', '2', join(dir, 'assets', 'sound.wav')]);
  writeFileSync(join(dir, 'index.html'), `<!doctype html>
<html data-composition-variables='[{"id":"title","type":"string","default":"Hello"},{"id":"n","type":"number","default":3},{"id":"on","type":"boolean","default":false}]'>
<head><meta charset="utf-8"><style>
html,body{margin:0;background:${clear ? 'transparent' : '#000'}}#film{position:relative;width:320px;height:180px;overflow:hidden;background:${clear ? 'transparent' : '#123'};color:#fff;font:20px sans-serif}
#box{position:absolute;left:0;top:100px;width:40px;height:40px;background:#fff}
video{position:absolute;left:160px;top:0;width:160px;height:90px;background:#000}
</style></head>
<body>
<div id="film" data-composition-id="film" data-width="320" data-height="180">
  ${sound ? `<audio id="om-sound" src="assets/sound.wav" data-start="0" data-duration="${duration}" data-track-index="8" data-volume="1"></audio>` : ''}
  <div id="box"></div>
  <div id="t" data-var-text="title">placeholder</div>
  ${video ? '<video src="assets/clip.mp4" data-start="0.5" data-duration="1" data-media-start="0" muted playsinline></video>' : ''}
  ${body}
</div>
<script type="text/vnd.abc" id="om-score">X:1 this is { not javascript</script>
<script>
window.__timelines = window.__timelines || {};
window.__timelines.film = { seek(t) { document.getElementById('box').style.transform = 'translateX(' + (t * 100) + 'px)'; window.__lastSeek = t; }, pause() {}, duration() { return ${duration}; }, labels: { 'scene:a': 0 } };
${script}
</script>
</body></html>`);
  return { dir, index: join(dir, 'index.html'), project: { root: dir, index: join(dir, 'index.html'), om: join(dir, '.om') } };
}

// Mean luma (0-255) of a w×h crop at x,y of the frame at time t in a video file.
export function luma(file, t, x, y, w, h) {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-ss', String(t), '-i', file, '-vf', `crop=${w}:${h}:${x}:${y},scale=1:1,format=gray`, '-frames:v', '1', '-f', 'rawvideo', '-'], { encoding: 'buffer' });
  return r.stdout[0];
}
