// Static host and public TPL.compare parameters; all motion remains in Adu.
import {readFile, writeFile, mkdtemp, cp, rm, copyFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';

const args = process.argv.slice(2);
function arg(name) {
  const i = args.indexOf(name);
  if (i < 0 || !args[i + 1]) throw new Error('Missing ' + name);
  return args[i + 1];
}
const briefBytes = await readFile(arg('--brief'));
const b = JSON.parse(briefBytes);
if (!b.typography || typeof b.typography !== 'object') throw new Error('Missing Adu typography');
const typography = b.typography;
const geometryBytes = await readFile(arg('--geometry-module'));
if (createHash('sha256').update(geometryBytes).digest('hex') !== arg('--geometry-sha256')) {
  throw new Error('Adu text geometry module identity changed');
}
// The executor runs a frozen copy of this entry outside the Skill directory.
const {validateAduTextGeometry} = await import('data:text/javascript;base64,' + geometryBytes.toString('base64'));

const stable = value => {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])]));
  return value;
};
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
async function reuseExisting() {
  const manifestArg = arg('--reuse-media-manifest');
  if (!/^\/dev\/fd\/\d+$/.test(manifestArg)) throw new Error('Invalid completed Adu media manifest FD');
  const manifestBytes = await readFile(manifestArg);
  const manifest = JSON.parse(manifestBytes);
  if (manifest.schema_version !== 'reference-process-media/v1' || manifest.brief_sha256 !== digest(briefBytes)) {
    throw new Error('Frozen Adu completed media manifest mismatch');
  }
  const records = Object.fromEntries((manifest.media || []).map(item => [item.media_ref, item]));
  const refs = ['completed-native-video', 'original-native-brief', 'native-generation-evidence'];
  if ((manifest.media || []).length !== refs.length || Object.keys(records).length !== refs.length || refs.some(ref => !records[ref])) throw new Error('Completed Adu media references are incomplete');
  const blobs = {};
  for (const ref of refs) {
    const record = records[ref];
    if (!Number.isInteger(record.fd) || record.fd < 0 || !Number.isInteger(record.byte_length) || typeof record.sha256 !== 'string') throw new Error('Invalid completed Adu media descriptor');
    const blob = await readFile(`/dev/fd/${record.fd}`);
    if (blob.length !== record.byte_length || digest(blob) !== record.sha256) throw new Error('Completed Adu media hash mismatch');
    blobs[ref] = blob;
  }
  const original = JSON.parse(blobs['original-native-brief']);
  const currentComparable = {...b}; const originalComparable = {...original};
  delete currentComparable.source_binding; delete originalComparable.source_binding;
  if (JSON.stringify(stable(currentComparable)) !== JSON.stringify(stable(originalComparable))) throw new Error('Completed Adu brief differs from current brief');
  const evidence = JSON.parse(blobs['native-generation-evidence']);
  if (evidence.status !== 'completed' || evidence.template !== 'TPL.compare' || !Array.isArray(evidence.commands) || !evidence.commands.length || evidence.commands.some(command => command.exit_code !== 0)) throw new Error('Native Adu generation evidence is incomplete');
  await writeFile(arg('--output'), blobs['completed-native-video']);
  console.log(JSON.stringify({status: 'reused', native_generation_count: 0, media_sha256: digest(blobs['completed-native-video'])}));
}
if (args.includes('--reuse-media-manifest')) await reuseExisting();
if (args.includes('--reuse-media-manifest')) process.exit(0);
const output = path.resolve(arg('--output'));
const source = path.resolve(arg('--source'));
const ffmpeg = path.resolve(arg('--ffmpeg'));
const ffprobe = path.resolve(arg('--ffprobe'));
const python = path.resolve(arg('--python'));
for (const file of [ffmpeg, ffprobe, python]) {
  if (!existsSync(file)) throw new Error('Project-local Adu tool unavailable: ' + file);
}
const temp = await mkdtemp(path.join(os.tmpdir(), 'adu-native-compare-'));
const board = path.join(temp, 'board');
const report = {source, template: 'TPL.compare', directory: temp, commands: [], status: 'prepared'};
const json = value => JSON.stringify(value).replace(/</g, '\\u003c');
const html = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

async function run(executable, argv, env = process.env) {
  const record = {executable, argv, stdout: '', stderr: '', exit_code: null};
  report.commands.push(record);
  await new Promise((resolve, reject) => {
    const p = spawn(executable, argv, {stdio: ['ignore', 'pipe', 'pipe'], env});
    p.stdout.on('data', chunk => {record.stdout += chunk; process.stdout.write(chunk);});
    p.stderr.on('data', chunk => {record.stderr += chunk; process.stderr.write(chunk);});
    p.once('error', reject);
    p.once('close', code => {record.exit_code = code; code === 0 ? resolve() : reject(new Error('Native process exited ' + code));});
  });
  return record.stdout;
}

try {
  if (b.composition.width !== 1080 || b.composition.height !== 1920 || b.composition.fps !== 24) throw new Error('Invalid Adu canvas');
  const duration = b.composition.frames / 24;
  // This is an embedded shot, not Adu's final film. Keep its public scene/end
  // beyond the captured range so the native whole-film black outro does not
  // overlap the parent's own return to A-roll. All action cue times stay fixed.
  const nativeEnd = duration + 0.5;
  report.capture_end = duration;
  report.native_scene_end = nativeEnd;
  await cp(path.join(source, 'template'), board, {recursive: true});
  // Native pipeline creates these optional input stubs; this scene does not use them.
  for (const [name, contents] of Object.entries({
    'talkmap.js': 'window.TALKF=[];window.TALKMAP=[];',
    'face.js': 'window.FACE={};',
    'subs.js': 'window.SUBS=[];',
    'wall.js': 'window.WALL=[];'
  })) await writeFile(path.join(board, name), contents);
  const config = await readFile(path.join(board, 'config.js'), 'utf8');
  await writeFile(path.join(board, 'config.js'), config + '\nObject.assign(window.CONFIG,' +
    json({brand: '', account: '', demo: false, subtitles: false, end: nativeEnd, talkFrames: 0, race: {labels: [], keys: [0, duration]}}) + ');\n');
  const scene = {
    t0: 0, t1: nativeEnd, left: b.left, right: b.right, stamp: b.stamp,
    leftAt: b.left_frame / 24, rightAt: b.right_frame / 24, strikeAt: b.strike_frame / 24,
    bg: 'paper', cam: 'none', race: false, tag: ' ', trans: null
  };
  await writeFile(path.join(board, 'scenes.js'), 'TPL.compare(' + json(scene) + ');\n');
  const entry = path.join(temp, 'ENTRY.html');
  // Public upstream opt-out: the parent owns final-film branding and captions.
  await writeFile(path.join(temp, 'output-signature.json'), json({schema: 'adu-output-signature/1', enabled: false}));
  await writeFile(entry, '<!doctype html><meta charset="utf-8"><style>' +
    'html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#F7F7F5;color:#0A0A0A;font-family:-apple-system,"PingFang SC",sans-serif}' +
    'h1{position:absolute;top:170px;left:70px;right:70px;margin:0;font-size:76px;line-height:1.15;letter-spacing:-2px}' +
    '.rule{position:absolute;top:350px;left:70px;width:96px;height:8px;background:#2462EA}' +
    'iframe{position:absolute;left:0;top:430px;width:1920px;height:1080px;border:0;transform:scale(.5625);transform-origin:top left}' +
    '</style><h1>' + html(b.title) + '</h1><div class="rule"></div>' +
    '<iframe id="board" src="board/index.html"></iframe><script>' +
    'const board=document.getElementById("board");window.END=' + duration + ';' +
    'const validateActualTextGeometry=' + validateAduTextGeometry.toString() + ';' +
    'window.READY=new Promise((resolve,reject)=>{board.addEventListener("load",async()=>{try{await board.contentWindow.READY;' +
    'const s=board.contentDocument.createElement("style");s.textContent=' + JSON.stringify(
      `.card > div:nth-child(2){font-size:${Number(typography.title_px) / 0.5625}px !important}` +
      `.card > div:nth-child(n+3){font-size:${Number(typography.body_px) / 0.5625}px !important}`
    ) + ';board.contentDocument.head.appendChild(s);await board.contentDocument.fonts.ready;' +
    'try{board.contentWindow.renderAt(' + (Math.max(b.left_frame,b.right_frame)/24+.8) + ');window.ADU_TEXT_GEOMETRY=validateActualTextGeometry(board)}finally{board.contentWindow.renderAt(0)}' +
    ';document.title="done";resolve()}catch(e){reject(e)}},{once:true})});' +
    'window.renderAt=t=>board.contentWindow.renderAt(t);</script>');
  const native = path.join(temp, 'native.mp4');
  const childEnv = {...process.env, PATH: `${path.dirname(ffmpeg)}:${process.env.PATH || ''}`, ADU_PYTHON: python};
  await run(process.execPath, [path.join(source, 'scripts/render_project.mjs'), entry,
    '--output', native, '--fps', '24', '--width', '1080', '--height', '1920', '--end', String(duration),
    '--playwright-module', arg('--playwright-module'), '--browser', arg('--browser')], childEnv);
  const probe = JSON.parse(await run(ffprobe, ['-v', 'error', '-show_streams', '-of', 'json', native], childEnv));
  const video = probe.streams.find(s => s.codec_type === 'video');
  if (probe.streams.some(s => s.codec_type === 'audio')) throw new Error('Adu B-roll must be silent');
  let delivered = native;
  if (video.color_range === 'pc' || video.pix_fmt.startsWith('yuvj')) {
    delivered = path.join(temp, 'normalized.mp4');
    await run(ffmpeg, ['-n', '-v', 'error', '-i', native, '-vf', 'scale=in_range=full:out_range=limited,setsar=1',
      '-an', '-c:v', 'libx264', '-crf', '15', '-pix_fmt', 'yuv420p', '-frames:v', String(b.composition.frames), delivered]);
  }
  if (!video.sample_aspect_ratio || video.sample_aspect_ratio === 'N/A') {
    const squarePixels = path.join(temp, 'square-pixels.mp4');
    await run(ffmpeg, ['-n', '-v', 'error', '-i', delivered, '-map', '0:v:0', '-an',
      '-c:v', 'copy', '-bsf:v', 'h264_metadata=sample_aspect_ratio=1/1', '-aspect', '9:16', squarePixels]);
    delivered = squarePixels;
  }
  await copyFile(delivered, output);
  report.status = 'completed';
  console.log(json(report));
  await rm(temp, {recursive: true});
} catch (error) {
  report.status = 'failed';
  report.error = error.message;
  await writeFile(path.join(temp, 'failure-log.json'), JSON.stringify(report, null, 2));
  console.error('Adu stopped without retry. Inspect ' + path.join(temp, 'failure-log.json'));
  throw error;
}
