'use strict';
// Adapts the pinned upstream Registry block; HyperFrames remains the renderer.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {pipeline} = require('node:stream/promises');

const SOURCE_SHA256 = '5f2d91c91d37dd6b57a015a02361c67c9a62ca33849b901b3bebad8157fb7dbb';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function check(ok, message) { if (!ok) throw new Error(`hw-pipeline: ${message}`); }
function replaceOnce(source, oldText, newText) {
  check(source.split(oldText).length === 2, `upstream pattern changed: ${oldText.slice(0, 40)}`);
  return source.replace(oldText, newText);
}
function validateBrief(b) {
  check(b && typeof b === 'object' && !Array.isArray(b), 'brief must be an object');
  check(Object.keys(b).sort().join('|') === 'canvas|label_frames|labels|schema_version|source_binding|template_request|word_anchors', 'brief fields');
  check(b.schema_version === 1, 'schema_version');
  check(b.canvas && b.canvas.width === 1080 && b.canvas.height === 1920 && b.canvas.fps === 24 &&
    Number.isInteger(b.canvas.frames) && b.canvas.frames >= 72 && b.canvas.frames <= 360, 'canvas must be 3–15 seconds at 24fps');
  const contrast = b.template_request?.semantic_family === 'dual_contrast';
  const units = contrast ? 2 : 3;
  check(Array.isArray(b.labels) && b.labels.length === units && b.labels.every(s =>
    typeof s === 'string' && [...s].length >= 1 && [...s].length <= 6 && !/[\x00-\x1f\x7f]/u.test(s)),
  'concise visible labels required');
  check(Array.isArray(b.label_frames) && b.label_frames.length === units &&
    b.label_frames.every(Number.isInteger) && b.label_frames[0] >= 0 &&
    b.label_frames[1] - b.label_frames[0] >= 20 &&
    (contrast || b.label_frames[2] - b.label_frames[1] >= 20) &&
    b.label_frames.at(-1) <= b.canvas.frames - 30, 'label_frames must fit the spoken sequence');
  check(Array.isArray(b.word_anchors) && b.word_anchors.length === units &&
    b.word_anchors.every(anchor => anchor && Object.keys(anchor).sort().join('|') === 'index|text' &&
      Number.isInteger(anchor.index) && anchor.index >= 0 &&
      typeof anchor.text === 'string' && anchor.text.length > 0),
  'word_anchors must identify source-transcript words');
  check(b.template_request && ['three_step_flow', 'dual_contrast'].includes(b.template_request.semantic_family) &&
    b.template_request.information_units === units && Array.isArray(b.template_request.numeric_values) &&
    b.template_request.numeric_values.length === 0 && b.template_request.numeric_scale === 'not_applicable', 'template_request');
  check(b.source_binding && typeof b.source_binding.aroll_sha256 === 'string' &&
    /^[a-f0-9]{64}$/u.test(b.source_binding.aroll_sha256) && typeof b.source_binding.segment_id === 'string' &&
    Number.isFinite(b.source_binding.start) && Number.isFinite(b.source_binding.end) &&
    b.source_binding.end > b.source_binding.start, 'source_binding');
  return b;
}
function run(executable, args, env) {
  const result = spawnSync(executable, args, {cwd: '/', encoding: 'utf8', maxBuffer: 1024 * 1024, env});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(executable)} failed (${result.status}): ${(result.stderr || result.stdout).slice(-3000)}`);
}
async function main(args) {
  if (args.length === 1 && args[0] === '--validate') {
    process.stdout.write(JSON.stringify(validateBrief(JSON.parse(fs.readFileSync(0, 'utf8')))));
    return;
  }
  const names = ['--brief', '--output', '--runtime-root', '--source', '--vendor-gsap', '--browser', '--ffmpeg'];
  check(args.length === names.length * 2 && names.every((name, i) => args[i * 2] === name), 'use approved adapter');
  const opt = Object.fromEntries(names.map((name, i) => [name.slice(2), args[i * 2 + 1]]));
  const briefBytes = fs.readFileSync(opt.brief);
  const b = validateBrief(JSON.parse(briefBytes));
  const sourceBytes = fs.readFileSync(opt.source);
  check(sha(sourceBytes) === SOURCE_SHA256, 'upstream Registry block changed; re-review required');
  const packageJson = JSON.parse(fs.readFileSync(path.join(opt['runtime-root'], 'packages/cli/package.json')));
  check(packageJson.name === '@hyperframes/cli' && packageJson.version === '0.8.19', 'HyperFrames runtime changed');
  fs.accessSync(opt.browser, fs.constants.X_OK);
  fs.accessSync(opt.ffmpeg, fs.constants.X_OK);
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hd-hw-pipeline-'));
  try {
    const compositions = path.join(temp, 'compositions');
    fs.mkdirSync(path.join(compositions, 'vendor'), {recursive: true});
    fs.copyFileSync(opt['vendor-gsap'], path.join(compositions, 'vendor', 'gsap.min.js'));
    fs.mkdirSync(path.join(temp, 'vendor'), {recursive: true});
    fs.copyFileSync(opt['vendor-gsap'], path.join(temp, 'vendor', 'gsap.min.js'));
    fs.writeFileSync(path.join(temp, 'hyperframes.json'), JSON.stringify({paths: {blocks: 'compositions', assets: 'assets'}}));
    let html = sourceBytes.toString('utf8');
    html = replaceOnce(html, '<!doctype html>', '<!-- hyperframes-registry-item: hw-pipeline -->\n<!doctype html>');
    html = replaceOnce(html, 'https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js', 'vendor/gsap.min.js');
    html = html.replaceAll('"Caveat", cursive', '"PingFang SC", "Heiti SC", sans-serif');
    html = replaceOnce(html, '      #hw-pl-svg path {', `      #hw-pl-root::before {\n        content: ""; position: absolute; left: 120px; top: 200px;\n        width: 1680px; height: 310px; border-radius: 34px;\n        background: rgba(13, 19, 31, 0.84);\n        box-shadow: 0 16px 60px rgba(0, 0, 0, 0.25);\n      }\n      #hw-pl-svg path {`);
    const duration = (b.canvas.frames / 24).toFixed(4).replace(/0+$/u, '').replace(/\.$/u, '');
    html = html.replaceAll('data-duration="7"', `data-duration="${duration}"`);
    html = replaceOnce(html, 'nodes: [{ label: "Idea" }, { label: "Record" }, { label: "Shine!" }]',
      `nodes: ${JSON.stringify(b.labels.map(label => ({label})))}`);
    if (b.template_request.semantic_family === 'dual_contrast') {
      // The native boxes draw unchanged; comparison must not imply a causal arrow.
      html = replaceOnce(html, 'if (i < n - 1) {', 'if (false) {');
    }
    html = replaceOnce(html, 'y: 455, // top of the row; x centers automatically', 'y: 260, // portrait safe area');
    // Use the native editable box/font parameters; Chinese labels need glyph width,
    // not the upstream short Latin demo's fixed 320px box.
    const glyphs = Math.max(...b.labels.map(label => [...label].length));
    const maxBoxWidth = Math.floor((1680 - (b.labels.length - 1) * 190) / b.labels.length);
    const fontSize = Math.min(70, Math.floor((maxBoxWidth - 64) / glyphs));
    const boxWidth = Math.max(320, glyphs * fontSize + 64);
    html = replaceOnce(html, 'boxW: 320,', `boxW: ${boxWidth},`);
    html = replaceOnce(html, 'fontSize: 56,', `fontSize: ${fontSize},`);
    html = replaceOnce(html, 'var DUR = 7;', `var DUR = ${duration};`);
    html = replaceOnce(html, 'var t = 0.3;', `var starts = ${JSON.stringify(b.label_frames.map(frame => frame / 24))};`);
    html = replaceOnce(html, 'CONFIG.nodes.forEach(function (_, i) {\n          var p = boxes[i];',
      'CONFIG.nodes.forEach(function (_, i) {\n          var t = starts[i];\n          var p = boxes[i];');
    html = replaceOnce(html, '          t += 0.7;\n', '');
    html = replaceOnce(html, '            tl.to(c, { strokeDashoffset: 0, duration: 0.45, ease: "power2.inOut" }, t);',
      '            tl.to(c, { strokeDashoffset: 0, duration: 0.45, ease: "power2.inOut" }, t + 0.55);');
    html = replaceOnce(html, '            t += 0.5;\n', '');
    fs.writeFileSync(path.join(compositions, 'hw-pipeline.html'), html, {flag: 'wx'});
    const rendered = path.join(temp, 'native.mov');
    const cliArgs = [path.join(opt['runtime-root'], 'node_modules/tsx/dist/cli.mjs'),
      path.join(opt['runtime-root'], 'packages/cli/src/cli.ts'), 'render', temp,
      '--composition', 'compositions/hw-pipeline.html', '--output', rendered, '--format', 'mov',
      '--fps', '24', '--quality', 'high', '--workers', '1', '--low-memory-mode',
      '--no-browser-gpu', '--no-best-effort', '--quiet'];
    run(process.execPath, cliArgs, {...process.env, HYPERFRAMES_BROWSER_PATH: opt.browser,
      HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1'});
    check(fs.existsSync(rendered) && fs.statSync(rendered).size > 0, 'HyperFrames produced no MOV');
    const converted = path.join(temp, 'portrait.mov');
    run(opt.ffmpeg, ['-v', 'error', '-y', '-i', rendered, '-an', '-vf',
      'scale=1080:608:flags=lanczos,pad=1080:1920:0:0:color=black@0,format=argb',
      '-frames:v', String(b.canvas.frames), '-r', '24', '-c:v', 'qtrle', '-pix_fmt', 'argb', converted], process.env);
    await pipeline(fs.createReadStream(converted), fs.createWriteStream(opt.output));
    process.stdout.write(JSON.stringify({upstream: 'hyperframes-registry/hw-pipeline',
      upstream_sha256: SOURCE_SHA256, brief_sha256: sha(briefBytes), frames: b.canvas.frames,
      fps: 24, source_binding: b.source_binding}));
  } finally {
    fs.rmSync(temp, {recursive: true, force: true});
  }
}
module.exports = {validateBrief};
if (require.main === module || process.argv[1] === '-') main(process.argv.slice(2)).catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
