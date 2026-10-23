// node --test runtime/clip/test/
// The timing that clip.js computes before anything is drawn (cues.js), and the wiring of the eight grammar templates.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PKG = join(HERE, '..', '..', '..');
await import('../cues.js');
const { findWord, prepare } = globalThis.ClipCues;

// What `om voice` writes into om-cues: ICU splits 缓存命中 into 缓|存命|中.
const WORDS = [
  { word: '先', start: 0.2, end: 0.4 }, { word: '看', start: 0.4, end: 0.6 }, { word: '缓', start: 0.6, end: 0.8 },
  { word: '存命', start: 0.8, end: 1.2 }, { word: '中', start: 1.2, end: 1.4 }, { word: '再看', start: 1.6, end: 2.0 },
  { word: '缓存', start: 2.5, end: 2.9 }, { word: '3000', start: 3.2, end: 3.8 }, { word: '行', start: 3.8, end: 4.0 },
];
const spec = () => ({ grammar: 'y5_kinetic_type', duration: 6, cues: [
  { at: 0, kind: 'title', text: 'T' },
  { at: 1, kind: 'point', text: 'A', word: '缓存' },
  { at: 2, kind: 'point', text: 'B', word: '缓存', nth: 2, offset: -0.1 },
  { at: 3, kind: 'react', word: '3000', edge: 'end', offset: 0.5 },
  { at: 4, kind: 'insert', data: { hit: 4.5, hitWord: '3000' } },
] });

test('findWord: whole words, words split by the tokenizer, nth, edge', () => {
  assert.equal(findWord(WORDS, '缓存'), 0.6);                 // 缓|存命 joined
  assert.equal(findWord(WORDS, '缓存', 2), 2.5);
  assert.equal(findWord(WORDS, '缓存', 1, 'end'), 1.2);       // the end of the last word it touches
  assert.equal(findWord(WORDS, '再 看'), 1.6);                 // whitespace ignored, like OM.cue
  assert.equal(findWord(WORDS, '3000'), 3.2);
  assert.equal(findWord(WORDS, '没有'), null);
  assert.equal(findWord(WORDS, '缓存', 3), null);
  assert.equal(findWord([], '缓存'), null);
});

test('no narration: cues keep their own `at`, pace scales every time position', () => {
  const r = prepare(spec(), { pace: 1.5 });
  assert.deepEqual(r.spec.cues.map((q) => q.at), [0, 1.5, 3, 4.5, 6]);
  assert.equal(r.spec.cues[4].data.hit, 6.75);
  assert.equal(r.duration, 9);
  assert.equal(r.spec.duration, 9);
  assert.deepEqual(r.problems, []);
});

test('with narration: cues with `word` follow the words; the rest keep `at` (scaled); the film covers the voice', () => {
  const r = prepare(spec(), { pace: 2, words: WORDS, voiceEnd: 15 });
  const at = r.spec.cues.map((q) => +q.at.toFixed(3));
  assert.deepEqual(at, [0, 0.6, 2.4, 4.3, 8]);                 // title 0·2; 缓存 #1; 缓存 #2 − 0.1; end of 3000 + 0.5; insert 4·2
  assert.equal(r.spec.cues[4].data.hit, 3.2);                 // hitWord wins over hit
  assert.equal(r.duration, 15.5);                             // voiceEnd + 0.5 tail beats duration × pace (12)
  assert.equal(r.anchored.length, 3);
});

test('a resolver passed in (OM.cue in the browser) is tried first; when it throws, the joined-text search takes over', () => {
  const calls = [];
  const cue = (w, n) => { calls.push(w); if (w === '3000') return 9.9; throw new Error('no cue'); };
  const r = prepare(spec(), { words: WORDS, voiceEnd: 5, cue });
  assert.equal(r.spec.cues[3].at, 9.9 + 0.5);
  assert.equal(r.spec.cues[1].at, 0.6);
  assert.ok(calls.includes('缓存'));
});

test('a word that is not in the narration keeps its own time and is reported', () => {
  const s = spec(); s.cues[1].word = '不存在';
  const r = prepare(s, { words: WORDS, voiceEnd: 5 });
  assert.equal(r.spec.cues[1].at, 1);
  assert.equal(r.problems.length, 1);
  assert.match(r.problems[0], /不存在/);
});

test('the input spec is not mutated', () => {
  const s = spec(); prepare(s, { pace: 3, words: WORDS, voiceEnd: 5 });
  assert.deepEqual(s, spec());
});

// ---------- the grammar templates ----------
const TEMPLATES = ['math-3b1b', 'keynote-ui', 'finance-chart', 'kurzgesagt', 'vox-collage', 'whiteboard', 'storytime', 'kinetic-type'];
const FILES = { 'PuHui-Medium': 'NotoSansSC-500.woff', 'PuHui-Bold': 'NotoSansSC-700.woff', 'PuHui-Heavy': 'NotoSansSC-800.woff', 'PuHui-Black': 'NotoSansSC-900.woff',
  'CMU-rm': 'cmunrm.woff', 'CMU-it': 'cmunti.woff', 'EBGaramond-400i': 'EBGaramond-400i.woff', Inter: 'Inter-var.woff', RobotoCondensed: 'RobotoCondensed-var.woff', 'LXGWWenKai-500': 'LXGWWenKai-500.woff' };

test('the eight grammar templates exist', () => { for (const id of TEMPLATES) assert.ok(existsSync(join(PKG, 'templates', id, 'template.json')), id); });

for (const id of TEMPLATES) {
  test(`template ${id}: spec, variables, grammar script and copied files agree`, () => {
    const dir = join(PKG, 'templates', id), meta = JSON.parse(readFileSync(join(dir, 'template.json'), 'utf8'));
    const html = readFileSync(join(dir, 'index.html'), 'utf8');
    const vars = JSON.parse(/data-composition-variables='([^']*)'/.exec(html)[1]);
    const ids = new Set(vars.map((v) => v.id));
    const spec = JSON.parse(/<script type="application\/json" id="clip-spec">([\s\S]*?)<\/script>/.exec(html)[1]);
    assert.equal(spec.grammar, meta.grammar);
    assert.ok(html.includes(`vendor/clip/grammars/${meta.grammar}.js`));
    const used = [...JSON.stringify(spec).matchAll(/\{\{\s*([\w-]+)/g)].map((m) => m[1]);
    for (const u of used) assert.ok(ids.has(u), `spec uses undeclared variable ${u}`);
    for (const v of ids) assert.ok(used.includes(v) || html.includes(`V.${v}`), `variable ${v} is declared but used neither in the spec nor in apply()`);
    for (const v of vars) { assert.ok(v.label, `${v.id} has a label`); assert.ok('default' in v, `${v.id} has a default`); }
    for (const v of vars.filter((x) => /JSON/.test(x.label))) JSON.parse(v.default);
    for (const [from] of Object.entries(meta.copy)) assert.ok(existsSync(join(PKG, from)), `copy source ${from}`);
    const g = readFileSync(join(PKG, 'runtime/clip/grammars', meta.grammar + '.js'), 'utf8');
    const faces = JSON.parse(/faces: (\[[^\]]*\])/.exec(g)[1].replace(/'/g, '"').replace(/FONT/, '"LXGWWenKai-500"'));
    for (const f of faces) assert.equal(meta.copy[`fonts/${FILES[f]}`], `assets/fonts/${FILES[f]}`, `${id} copies the font for ${f}`);
    for (const q of spec.cues) if (q.image && !q.image.includes('{{')) assert.ok(existsSync(join(dir, q.image)), q.image);
    for (const v of vars.filter((x) => /^assets\//.test(String(x.default)))) assert.ok(existsSync(join(dir, v.default)), v.default);
  });
}
