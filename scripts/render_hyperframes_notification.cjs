'use strict';
// Executed from reviewed stdin by ReferenceProcessAdapter, never from cwd.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {pipeline} = require('node:stream/promises');

const TEMPLATE_ID = 'hyperframes/notification-cascade';
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const defaults = {
  notifTitle: 'New render',
  message1: 'Launch video is ready.',
  message2: 'All checks passed.',
  message3: '4K render done in 92s.',
  message4: 'Published to the catalog.',
  appName: 'HyperFrames',
  headlineTop: 'SHIP VIDEO',
  headlineAccent: 'FROM HTML',
  footerText: 'hyperframes.heygen.com',
};

function validateBrief(b) {
  const check = (ok, message) => { if (!ok) throw new Error(`Notification Cascade brief: ${message}`); };
  const exact = (value, keys, label) => check(value && typeof value === 'object' &&
    !Array.isArray(value) && Object.keys(value).sort().join('|') === [...keys].sort().join('|'), label);
  exact(b, ['schema_version', 'canvas', 'template_request', 'props'], 'unknown/missing fields');
  check(b.schema_version === 1, 'schema_version must be 1');
  exact(b.canvas, ['width', 'height', 'fps', 'duration_in_frames'], 'canvas fields');
  check(b.canvas.width === 1080 && b.canvas.height === 1920 && b.canvas.fps === 24,
    'requires native 1080x1920/24fps');
  check(b.canvas.duration_in_frames === 336, 'native template duration must be exactly 336 frames');
  exact(b.template_request, ['semantic_family', 'information_units', 'numeric_values', 'numeric_scale'],
    'template_request fields');
  const request = b.template_request;
  check(['milestone_notifications', 'progress_sequence', 'delivery_checkpoints'].includes(request.semantic_family),
    'semantic_family mismatch');
  check(request.information_units === 4, 'requires exactly four information units');
  check(Array.isArray(request.numeric_values) && request.numeric_values.length === 0 &&
    request.numeric_scale === 'not_applicable', 'numeric fields must be empty/not_applicable');
  exact(b.props, ['data'], 'props fields');
  const keys = ['notifTitle', 'messages', 'appName', 'headlineTop', 'headlineAccent', 'footerText', 'brandLogo'];
  exact(b.props.data, keys, 'data fields must be explicit (no sample defaults)');
  const data = b.props.data;
  const clean = value => typeof value === 'string' && value.trim() && !/[\x00-\x1f\x7f]/u.test(value);
  check(Array.isArray(data.messages) && data.messages.length === 4, 'messages must contain exactly four strings');
  const values = {
    notifTitle: data.notifTitle,
    message1: data.messages[0], message2: data.messages[1],
    message3: data.messages[2], message4: data.messages[3],
    appName: data.appName, headlineTop: data.headlineTop,
    headlineAccent: data.headlineAccent, footerText: data.footerText,
  };
  for (const [id, value] of Object.entries(values)) {
    check(clean(value), `${id} must be a nonempty single line`);
    const original = [...defaults[id]].length;
    const length = [...value].length;
    check(length >= Math.ceil(original * .8) && length <= Math.floor(original * 1.2),
      `${id} must stay within the upstream 20% length window`);
  }
  check(typeof data.brandLogo === 'string' &&
    /^data:image\/(?:svg\+xml|png);base64,[A-Za-z0-9+/]+={0,2}$/u.test(data.brandLogo),
    'brandLogo must be an inline base64 SVG or PNG, not a remote URL');
  return b;
}

function safeRegistry(root, relative) {
  if (typeof relative !== 'string' || path.isAbsolute(relative) || relative.split('/').includes('..')) {
    throw new Error('Registry path must stay inside the Skill');
  }
  const resolvedRoot = fs.realpathSync(root);
  const resolved = fs.realpathSync(path.join(root, relative));
  if (resolved !== resolvedRoot && !resolved.startsWith(resolvedRoot + path.sep)) {
    throw new Error('Registry path escapes the Skill');
  }
  return resolved;
}

async function main(args) {
  if (args.length === 1 && args[0] === '--validate') {
    process.stdout.write(JSON.stringify(validateBrief(JSON.parse(fs.readFileSync(0, 'utf8')))));
    return;
  }
  const names = ['--brief', '--output', '--skill-root', '--runtime-root', '--browser',
    '--registry-path', '--registry-sha256', '--renderer-version'];
  if (args.length !== names.length * 2 || names.some((name, index) => args[index * 2] !== name)) {
    throw new Error('Use the approved hyperframes_notification_adapter factory');
  }
  const opt = Object.fromEntries(names.map((name, index) => [name.slice(2), args[index * 2 + 1]]));
  const briefBytes = fs.readFileSync(opt.brief);
  const b = validateBrief(JSON.parse(briefBytes));
  const registryPath = safeRegistry(opt['skill-root'], opt['registry-path']);
  const registryBytes = fs.readFileSync(registryPath);
  if (sha(registryBytes) !== opt['registry-sha256']) throw new Error('Template registry changed; rebind');
  const template = JSON.parse(registryBytes).templates.find(item => item.template_id === TEMPLATE_ID);
  if (!template || String(template.render_contract.engine).toLowerCase() !== 'hyperframes') {
    throw new Error('Template is not registered for HyperFrames');
  }
  const packageJson = JSON.parse(fs.readFileSync(path.join(opt['runtime-root'], 'packages/cli/package.json')));
  if (packageJson.version !== opt['renderer-version']) throw new Error('HyperFrames version drift');
  fs.accessSync(opt.browser, fs.constants.X_OK);

  const sourceDir = path.posix.dirname(template.source_entrypoint);
  const files = template.source_files.map(record => {
    if (!record.path.startsWith(sourceDir + '/') || record.path.split('/').includes('..')) {
      throw new Error('Unexpected template source path');
    }
    const absolute = path.join(opt['skill-root'], record.path);
    const bytes = fs.readFileSync(absolute);
    if (sha(bytes) !== record.sha256) throw new Error(`Template source changed: ${record.path}`);
    return {relative: path.posix.relative(sourceDir, record.path), bytes};
  });
  if (!files.some(file => file.relative === path.posix.basename(template.source_entrypoint))) {
    throw new Error('Template entrypoint is missing from source files');
  }

  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hd-hyperframes-notification-'));
  try {
    for (const file of files) {
      const destination = path.join(temp, ...file.relative.split('/'));
      fs.mkdirSync(path.dirname(destination), {recursive: true});
      fs.writeFileSync(destination, file.bytes, {flag: 'wx'});
    }
    const variables = {
      notifTitle: b.props.data.notifTitle,
      message1: b.props.data.messages[0], message2: b.props.data.messages[1],
      message3: b.props.data.messages[2], message4: b.props.data.messages[3],
      appName: b.props.data.appName, headlineTop: b.props.data.headlineTop,
      headlineAccent: b.props.data.headlineAccent, footerText: b.props.data.footerText,
      brandLogo: b.props.data.brandLogo,
    };
    const variablesPath = path.join(temp, 'variables.json');
    fs.writeFileSync(variablesPath, JSON.stringify(variables), {flag: 'wx'});
    const rendered = path.join(temp, 'render.mp4');
    const tsxCli = path.join(opt['runtime-root'], 'node_modules/tsx/dist/cli.mjs');
    const hyperframesCli = path.join(opt['runtime-root'], 'packages/cli/src/cli.ts');
    fs.accessSync(tsxCli, fs.constants.R_OK);
    fs.accessSync(hyperframesCli, fs.constants.R_OK);
    const cliArgs = [tsxCli, hyperframesCli, 'render', temp,
      '--composition', path.posix.basename(template.source_entrypoint), '--output', rendered,
      '--fps', '24', '--quality', 'high', '--workers', '1', '--variables-file', variablesPath,
      '--strict-variables', '--strict', '--low-memory-mode', '--no-browser-gpu', '--no-best-effort', '--quiet'];
    const result = spawnSync(process.execPath, cliArgs, {
      cwd: '/', encoding: 'utf8', maxBuffer: 1024 * 1024,
      env: {...process.env, HYPERFRAMES_BROWSER_PATH: opt.browser,
        HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1'},
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      throw new Error(`HyperFrames render failed (${result.status}): ${(result.stderr || result.stdout).slice(-4000)}`);
    }
    if (!fs.existsSync(rendered) || fs.statSync(rendered).size === 0) throw new Error('HyperFrames produced no MP4');
    await pipeline(fs.createReadStream(rendered), fs.createWriteStream(opt.output));
    process.stdout.write(JSON.stringify({template_id: TEMPLATE_ID, brief_sha256: sha(briefBytes),
      variables_sha256: sha(JSON.stringify(variables)), frames: 336, fps: 24, workers: 1, muted: true}));
  } finally {
    fs.rmSync(temp, {recursive: true, force: true});
  }
}

module.exports = {validateBrief};
if (require.main === module || process.argv[1] === '-') main(process.argv.slice(2)).catch(error => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
