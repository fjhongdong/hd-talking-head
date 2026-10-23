import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';
import { REPO_URL, exportHtml, injectRuntime, readMeta, shipped, sourceFiles } from '../cli/lib/export.js';
import { openProject } from '../cli/lib/project.js';

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const tmp = () => mkdtempSync(join(tmpdir(), 'om-export-'));

const HTML = `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>huashu-motion · Q3 &amp; more</title>
<script src="vendor/gsap.min.js"></script>
</head><body><header>not the head</header>
<div data-composition-id="root" data-width="1080" data-height="1920" data-duration="4"><h1>hi</h1></div>
</body></html>
`;

function fixture() {
  const root = join(tmp(), 'my-film');
  const put = (rel, data) => { mkdirSync(dirname(join(root, rel)), { recursive: true }); writeFileSync(join(root, rel), data); };
  put('index.html', HTML);
  put('vendor/gsap.min.js', '/* gsap */');
  put('assets/fonts/A.woff', Buffer.from([0, 1, 2, 3, 250, 251]));
  put('assets/字.txt', '中文文件名');
  put('out/my-film-v1.mp4', 'video');
  put('.om/history/000001.html', 'old');
  put('.om/inbox.jsonl', '{}');
  put('snapshots/a.png', 'png');
  put('node_modules/x/index.js', 'x');
  put('.DS_Store', 'junk');
  return openProject(root);
}

// Minimal reader for the archives we write: walk the central directory, inflate each entry, check its CRC.
function unzip(buf) {
  const end = buf.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = buf.readUInt16LE(end + 10);
  let p = buf.readUInt32LE(end + 16);
  const out = {};
  for (let i = 0; i < count; i++) {
    assert.equal(buf.readUInt32LE(p), 0x02014b50);
    const method = buf.readUInt16LE(p + 10), crc = buf.readUInt32LE(p + 16), size = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28), extra = buf.readUInt16LE(p + 30), comment = buf.readUInt16LE(p + 32), at = buf.readUInt32LE(p + 42);
    assert.ok(buf.readUInt16LE(p + 8) & 0x0800, 'names are flagged UTF-8');
    const name = buf.subarray(p + 46, p + 46 + nameLen).toString('utf8');
    const start = at + 30 + buf.readUInt16LE(at + 26) + buf.readUInt16LE(at + 28);
    const body = buf.subarray(start, start + size);
    const data = method === 8 ? zlib.inflateRawSync(body) : Buffer.from(body);
    assert.equal(zlib.crc32 ? zlib.crc32(data) : crc, crc, `crc of ${name}`);
    out[name] = data;
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));

test('exclusion rules: tool state, renders and junk never ship', () => {
  for (const rel of ['out', 'out/a.mp4', '.om/inbox.jsonl', 'snapshots/x.png', 'node_modules/a/b.js', '.DS_Store', 'assets/.DS_Store']) assert.equal(shipped(rel), false, rel);
  for (const rel of ['index.html', 'assets/out.png', 'vendor/om.js', 'outline/x.js', 'assets/fonts/A.woff']) assert.equal(shipped(rel), true, rel);
  const project = fixture();
  assert.deepEqual(sourceFiles(project.root), ['assets/fonts/A.woff', 'assets/字.txt', 'index.html', 'vendor/gsap.min.js']);
});

test('injectRuntime puts the engine first in <head>, never in <header>, and leaves the rest alone', () => {
  const CFG = '<script>window.__omConfig={video:"live",lenient:true}</script>';
  const out = injectRuntime(HTML);
  assert.equal(out, HTML.replace('<head>', `<head>${CFG}<script src="../player/om-engine.js"></script>`));
  assert.ok(!out.includes('<header><script'));
  assert.equal(injectRuntime('<head lang="x">a', 'r.js'), `<head lang="x">${CFG}<script src="r.js"></script>a`);
  assert.equal(injectRuntime('<body><header>x</header></body>', 'r.js'), `${CFG}<script src="r.js"></script><body><header>x</header></body>`);
});

test('readMeta prefers gallery.json, then template.json, then <title> without the brand prefix', () => {
  const project = fixture();
  assert.deepEqual(readMeta(project.root, HTML), { title: 'Q3 & more', description: '' });
  writeFileSync(join(project.root, 'template.json'), JSON.stringify({ title: 'T', summary: 'from template' }));
  assert.deepEqual(readMeta(project.root, HTML), { title: 'T', description: 'from template' });
  writeFileSync(join(project.root, 'gallery.json'), JSON.stringify({ title: { en: 'G', zh: '片' }, description: 'from gallery' }));
  assert.deepEqual(readMeta(project.root, HTML), { title: { en: 'G', zh: '片' }, description: 'from gallery' });
});

test('export writes every file, injects the runtime into the copy only, and zips the source', () => {
  const project = fixture();
  const dir = join(tmp(), 'share');
  const r = exportHtml(project, { out: dir, description: 'one line' });
  assert.equal(r.dir, dir);
  for (const f of ['index.html', 'source.zip', 'film/index.html', 'film/vendor/gsap.min.js', 'film/assets/fonts/A.woff', 'film/assets/字.txt',
    'player/om-player.js', 'player/om-engine.js', 'fonts/Inter-var.woff', 'fonts/OFL.txt']) {
    assert.ok(existsSync(join(dir, f)), `missing ${f}`);
  }
  for (const f of ['film/out', 'film/.om', 'film/snapshots', 'film/node_modules', 'film/.DS_Store']) assert.ok(!existsSync(join(dir, f)), `${f} should not ship`);

  const film = readFileSync(join(dir, 'film/index.html'), 'utf8');
  assert.equal(film, injectRuntime(HTML));
  assert.ok(existsSync(join(dir, 'film', '../player/om-engine.js')), 'the injected path resolves');
  assert.equal(readFileSync(project.index, 'utf8'), HTML, 'source untouched');
  assert.deepEqual(readFileSync(join(dir, 'player/om-engine.js')), readFileSync(join(PKG, 'runtime/om-engine.js')));
  assert.ok(film.includes('window.__omConfig={video:"live"'), 'the copy runs the engine in preview mode');

  const zip = unzip(readFileSync(join(dir, 'source.zip')));
  assert.deepEqual(Object.keys(zip).sort(), sourceFiles(project.root).map((f) => `my-film/${f}`).sort());
  assert.equal(zip['my-film/index.html'].toString('utf8'), HTML, 'the zip holds the original, not the injected copy');
  assert.deepEqual(zip['my-film/assets/fonts/A.woff'], Buffer.from([0, 1, 2, 3, 250, 251]));
  assert.equal(zip['my-film/assets/字.txt'].toString('utf8'), '中文文件名');

  const page = readFileSync(join(dir, 'index.html'), 'utf8');
  assert.ok(page.includes('src="film/index.html"') && page.includes('src="player/om-player.js"') && page.includes('<om-player id="player"'));
  assert.ok(page.includes('href="source.zip" download'));
  assert.ok(page.includes('--ar: 1080 / 1920'), 'aspect ratio comes from the composition');
  assert.ok(page.includes('Q3 &amp; more') && page.includes('one line'));
  assert.ok(page.includes('npx huashu-motion demo'));
  for (const [, code] of page.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(code); // the inline scripts parse
});

test('export never overwrites: default goes to out/<name>-share, then -v2; a non-empty --out is refused', () => {
  const project = fixture();
  const a = exportHtml(project), b = exportHtml(project);
  assert.equal(relative(project.root, a.dir), join('out', 'my-film-share'));
  assert.equal(relative(project.root, b.dir), join('out', 'my-film-share-v2'));
  assert.throws(() => exportHtml(project, { out: a.dir }), /already exists/);
  assert.throws(() => exportHtml(project, { out: join(project.root, 'assets', 'share') }), /out\/ folder or outside/);
  const again = unzip(readFileSync(join(b.dir, 'source.zip')));
  assert.ok(!Object.keys(again).some((n) => n.includes('/out/')), 'an earlier export is not zipped into the next one');
});

// Viewing a share page must not touch the network. Pages we generate may only link to REPO_URL; the
// bundled third-party files may only carry URLs that are never fetched (XML namespaces, license notes).
const NEVER_FETCHED = [
  /^http:\/\/www\.w3\.org\//, // XML namespaces inside SVG/MathML code
  /^https?:\/\/gsap\.com/, // GSAP's license banner and comments
  /^https?:\/\/$/, // protocol prefixes the runtime tests URLs against
  /^https:\/\/html\.spec\.whatwg\.org\//,
];
const urls = (text) => [...text.matchAll(/https?:\/\/[^\s"'`)<>\\]*/g)].map((m) => m[0]);

for (const example of ['showcase', 'voice-demo']) {
  test(`no outside requests in the export of examples/${example}`, { skip: !existsSync(join(PKG, 'examples', example, 'index.html')) }, () => {
    const dir = join(tmp(), 'share');
    exportHtml(openProject(join(PKG, 'examples', example)), { out: dir });
    const files = walk(dir).filter((f) => /\.(html?|js|css|svg)$/i.test(f));
    assert.ok(files.length > 3);
    for (const f of files) {
      const rel = relative(dir, f), text = readFileSync(f, 'utf8');
      if (/LICENSE/i.test(rel)) continue; // license documents are read by people, not loaded by the page
      if (rel === 'index.html' || rel === 'film/index.html') {
        for (const u of urls(text)) assert.ok(u === REPO_URL || NEVER_FETCHED.some((r) => r.test(u)), `${rel} links to ${u}`);
        continue;
      }
      for (const u of urls(text)) {
        assert.ok(NEVER_FETCHED.some((r) => r.test(u)), `${rel} references ${u}`);
      }
      // Loading contexts in markup and styles must stay local whatever the allowlist says.
      if (/\.(html?|css|svg)$/i.test(rel)) {
        assert.ok(!/<(script|link|img|iframe|audio|video|source)\b[^>]*\b(src|href)\s*=\s*["']?(https?:)?\/\//i.test(text), `${rel} loads a remote resource`);
        assert.ok(!/(url\(\s*["']?|@import\s+["'])(https?:)?\/\//i.test(text), `${rel} loads a remote style or font`);
      }
    }
    assert.ok(readFileSync(join(dir, 'film/index.html'), 'utf8').includes('<script src="../player/om-engine.js"></script>'), 'the engine is injected into the film copy');
  });
}
