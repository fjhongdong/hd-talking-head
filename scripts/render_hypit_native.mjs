// Native chat + public static layout. Never author or replace native animation.
import {readFile, writeFile, mkdtemp, cp, copyFile, mkdir, symlink} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';

const args = process.argv.slice(2);
function arg(name) {
  const i = args.indexOf(name);
  if (i < 0 || !args[i + 1]) throw new Error('Missing ' + name);
  return args[i + 1];
}
const rawBrief = await readFile(arg('--brief'));
const b = JSON.parse(rawBrief);
function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function comparableBrief(value) {
  const copy = JSON.parse(JSON.stringify(value));
  delete copy.source_binding;
  return copy;
}
async function reuseMedia() {
  const manifestFd = arg('--reuse-media-manifest');
  if (!/^\/dev\/fd\/\d+$/.test(manifestFd)) throw new Error('Invalid Hypit reuse manifest FD');
  const manifest = JSON.parse(await readFile(manifestFd, 'utf8'));
  if (manifest.schema_version !== 'reference-process-media/v1'
      || manifest.brief_sha256 !== createHash('sha256').update(rawBrief).digest('hex')
      || !Array.isArray(manifest.media)
      || manifest.media.length !== 3
      || stable(manifest.media.map(x => x.media_ref).sort()) !== stable(['completed-native-video', 'original-native-brief', 'native-generation-evidence'].sort())) {
    throw new Error('Invalid Hypit reuse media manifest');
  }
  const refs = Object.fromEntries(manifest.media.map(x => [x.media_ref, x]));
  async function snapshot(ref) {
    if (!ref || !Number.isInteger(ref.fd) || ref.fd < 0 || !Number.isInteger(ref.byte_length) || ref.byte_length < 0
        || typeof ref.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(ref.sha256)) throw new Error('Invalid Hypit media reference');
    const data = await readFile(`/dev/fd/${ref.fd}`);
    if (data.byteLength !== ref.byte_length || createHash('sha256').update(data).digest('hex') !== ref.sha256) throw new Error('Hypit media reference changed');
    return data;
  }
  const originalBrief = JSON.parse(await snapshot(refs['original-native-brief']));
  if (stable(comparableBrief(originalBrief)) !== stable(comparableBrief(b))) throw new Error('Hypit brief changed outside source binding');
  const evidence = JSON.parse(await snapshot(refs['native-generation-evidence']));
  if (!Array.isArray(evidence.commands) || !evidence.commands.some(c => c.exit_code === 0 && c.argv?.[1] === 'build'
      && c.stdout && JSON.parse(c.stdout).format === 'hypit.cli-build@1'
      && typeof JSON.parse(c.stdout).build?.id === 'string'
      && JSON.parse(c.stdout).build?.work?.outcome === 'complete'
      && JSON.parse(c.stdout).build?.result?.state === 'complete')) throw new Error('Invalid Hypit generation evidence');
  const media = await snapshot(refs['completed-native-video']);
  await writeFile(arg('--output'), media);
  const build = evidence.commands.find(c => c.exit_code === 0 && c.argv?.[1] === 'build');
  const buildResult = JSON.parse(build.stdout);
  console.log(JSON.stringify({status: 'reused', native_generation_count: 0, media_sha256: refs['completed-native-video'].sha256, build_id: buildResult.build.id}));
}
if (args.includes('--reuse-media-manifest')) {
  await reuseMedia();
  process.exit(0);
}
const source = path.resolve(arg('--source'));
const layout = path.resolve(arg('--layout-root'));
const output = path.resolve(arg('--output'));
const project = await mkdtemp(path.join(os.tmpdir(), 'hypit-native-chat-'));
const report = {source, project, native_scene: '@example/chat-scene', commands: [], build_id: null, status: 'prepared'};
const {writeNativeChatBundle, copyCompiledNativeChatPackage} = await import(pathToFileURL(path.join(layout, 'src/author.mjs')));
async function run(argv, executable = process.execPath) {
  const record = {executable, argv, stdout: '', stderr: '', exit_code: null};
  report.commands.push(record);
  await new Promise((resolve, reject) => {
    const child = spawn(executable, argv, {stdio: ['ignore', 'pipe', 'pipe']});
    child.stdout.on('data', data => {record.stdout += data; process.stdout.write(data);});
    child.stderr.on('data', data => {record.stderr += data; process.stderr.write(data);});
    child.once('error', reject);
    child.once('close', code => {record.exit_code = code; code === 0 ? resolve() : reject(new Error('Hypit exited ' + code));});
  });
  return record.stdout;
}
try {
  if (b.template_request.semantic_family !== 'plan_change_dialogue') throw new Error('Invalid Hypit semantic family');
  await copyCompiledNativeChatPackage(path.join(source, 'examples/semantic-composition/packages/chat-scene'), path.join(project, 'packages/chat-scene'));
  await cp(layout, path.join(project, 'packages/hypit-native-layout'), {recursive: true});
  // Our private project resolves unchanged distribution packages through the
  // existing installation. The source checkout and its lockfile are not edited.
  await mkdir(path.join(project, 'node_modules/@hypit'), {recursive: true});
  for (const name of ['composition', 'html-program', 'media', 'spatial', 'temporal', 'timeline']) {
    await symlink(path.join(source, 'packages', name), path.join(project, 'node_modules/@hypit', name), 'dir');
  }
  await symlink(source, path.join(project, 'node_modules/@hypit/hypit'), 'dir');
  await symlink(path.join(source, 'node_modules/@fontsource-variable'), path.join(project, 'node_modules/@fontsource-variable'), 'dir');
  await writeNativeChatBundle(project, {
    title: b.title, messages: b.messages, frames: b.messages.map(m => m.frame),
    durationFrames: b.composition.frames,
    chromePath: arg('--browser'), ffmpegPath: arg('--ffmpeg'), ffprobePath: arg('--ffprobe')
  });
  const cli = path.join(source, 'bin/hypit.mjs');
  const profile = path.join(project, 'hypit.runtime.json');
  if (args.includes('--check-only')) {
    await run([cli, 'check', path.join(project, 'chat.svml'), '--project', project]);
    report.status = 'source_valid';
  } else {
    // Exactly one Build. If its outcome is unknown, retain its ID; do not resubmit.
    const result = JSON.parse(await run([cli, 'build', path.join(project, 'chat.svrun'), '--project', project,
      '--runtime', profile, '--follow', '--json', '--max-wait-ms', '240000']));
    if (result.format !== 'hypit.cli-build@1') throw new Error('Unexpected Hypit build protocol');
    report.build_id = result.build?.id;
    if (typeof report.build_id !== 'string' || !report.build_id) throw new Error('Hypit build did not return its canonical id');
    await writeFile(path.join(project, 'invocation-log.json'), JSON.stringify(report, null, 2));
    if (result.build.work?.outcome !== 'complete' || result.build.result?.state !== 'complete') {
      throw new Error('Hypit build has no complete result; inspect the retained build id without resubmitting');
    }
    const staged = path.join(project, 'native.mp4');
    await run([cli, 'get', report.build_id, '--project', project, '--output', 'final.video', '--to', staged]);
    // Native HTML-video muxes a silent AAC track even with no AudioTrack.
    // Stream-copy keeps every video frame; the parent owns the only voice track.
    const delivered = path.join(project, 'broll.mp4');
    await run(['-n', '-v', 'error', '-i', staged, '-map', '0:v:0', '-c:v', 'copy', '-an',
      '-bsf:v', 'h264_metadata=sample_aspect_ratio=1/1', delivered], arg('--ffmpeg'));
    await copyFile(delivered, output);
    report.status = 'completed';
    // Only our private Runtime; no shared worker or other Build is stopped.
    await run([cli, 'runtime', 'down', '--project', project, '--runtime', profile]);
    await run([cli, 'programs', 'down', '--project', project, '--runtime', profile]);
  }
  await writeFile(output + '.native-log.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify({status: report.status, project, build_id: report.build_id}));
} catch (error) {
  report.status = 'failed';
  report.error = error.message;
  await writeFile(path.join(project, 'failure-log.json'), JSON.stringify(report, null, 2));
  console.error('Hypit stopped without retry. Inspect ' + path.join(project, 'failure-log.json'));
  throw error;
}
