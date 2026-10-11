// Native chat + public static layout. Never author or replace native animation.
import {readFile, writeFile, mkdtemp, cp, copyFile, mkdir, symlink} from 'node:fs/promises';
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
const b = JSON.parse(await readFile(arg('--brief'), 'utf8'));
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
