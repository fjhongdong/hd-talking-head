import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { openProject, readSource, writeSource, setVariables, readVariables, scan, undo, snapshot, OmError } from '../cli/lib/project.js';
import { addComment, claim, resolve, comments, pending } from '../cli/lib/inbox.js';

const HTML = `<!doctype html>
<html lang="zh" data-composition-variables='[{"id":"title","type":"string","label":"标题","default":"It&#39;s 你好"},{"id":"n","type":"number","label":"数","default":3,"min":0,"max":10},{"id":"c","type":"color","label":"色","default":"#112233"}]'>
<body><div data-composition-id="root" data-width="1920" data-height="1080" data-duration="4">
<h1 data-om-id="title" data-var-text="title">x</h1></div>
<script>tl.addLabel('scene:intro', 0); tl.addLabel("scene:end", 3)</script></body></html>
`;

const tmpProject = (html = HTML) => {
  const dir = mkdtempSync(join(tmpdir(), 'om-'));
  writeFileSync(join(dir, 'index.html'), html);
  return openProject(dir);
};

test('reads variables through html entities', () => {
  const vars = readVariables(HTML);
  assert.equal(vars[0].default, "It's 你好");
  assert.equal(vars.length, 3);
});

test('setVariables changes only the default values and the bound fallback text', () => {
  const out = setVariables(HTML, { title: "Q3 '增长' & more", n: '7' });
  const vars = readVariables(out);
  assert.equal(vars[0].default, "Q3 '增长' & more");
  assert.equal(vars[1].default, 7);
  const expected = HTML
    .replace('"default":"It&#39;s 你好"', '"default":"Q3 &#39;增长&#39; &amp; more"')
    .replace('"default":3,', '"default":7,')
    .replace('data-var-text="title">x</h1>', `data-var-text="title">Q3 '增长' &amp; more</h1>`);
  assert.equal(out, expected);
});

test('setVariables keeps hand formatting of the declaration and inserts a missing default', () => {
  const src = `<html data-composition-variables='[\n  { "id": "a", "type": "string", "label": "A", "default": "x" },\n  { "id": "b", "type": "number", "label": "B" }\n]'><body></body></html>`;
  const out = setVariables(src, { a: 'y', b: 2 });
  assert.equal(out, `<html data-composition-variables='[\n  { "id": "a", "type": "string", "label": "A", "default": "y" },\n  { "id": "b", "type": "number", "label": "B" ,"default":2}\n]'><body></body></html>`);
  assert.equal(readVariables(out)[1].default, 2);
});

test('setVariables validates types and ranges', () => {
  assert.throws(() => setVariables(HTML, { n: '11' }), OmError);
  assert.throws(() => setVariables(HTML, { n: 'abc' }), OmError);
  assert.throws(() => setVariables(HTML, { c: 'red' }), OmError);
  assert.throws(() => setVariables(HTML, { nope: 1 }), /unknown variable/);
});

test('double-quoted attribute round-trips', () => {
  const dq = HTML.replace(/'(\[.*\])'/, (_, j) => '"' + j.replace(/&#39;/g, "'").replace(/"/g, '&quot;') + '"');
  const out = setVariables(dq, { c: '#abcdef' });
  assert.equal(readVariables(out)[2].default, '#abcdef');
  assert.equal(readVariables(out)[0].default, "It's 你好");
});

test('scan finds objects, scenes and size', () => {
  const s = scan(HTML);
  assert.deepEqual(s.scenes.map((x) => x.id), ['intro', 'end']);
  assert.equal(s.objects[0].id, 'title');
  assert.equal(s.duration, 4);
});

test('writeSource refuses a stale token and undo walks back distinct versions', () => {
  const p = tmpProject();
  const { token } = readSource(p);
  const t2 = writeSource(p, setVariables(HTML, { n: 5 }), token, 'set n');
  assert.throws(() => writeSource(p, HTML, token, 'stale'), (e) => e.status === 409);
  // the agent edits the file directly; the studio watcher snapshots what it sees
  const agentHtml = readFileSync(p.index, 'utf8').replace('</body>', '<!-- agent --></body>');
  snapshot(p, readFileSync(p.index, 'utf8'), 'seen');
  writeFileSync(p.index, agentHtml);
  snapshot(p, agentHtml, 'seen');
  assert.ok(t2);
  undo(p);
  assert.equal(readVariables(readFileSync(p.index, 'utf8'))[1].default, 5);
  assert.ok(!readFileSync(p.index, 'utf8').includes('agent'));
  undo(p);
  assert.equal(readVariables(readFileSync(p.index, 'utf8'))[1].default, 3);
  assert.throws(() => undo(p), /nothing to undo/);
});

test('inbox folds comment → claim → done', () => {
  const p = tmpProject();
  const c = addComment(p, { text: '这里多停一拍', t: 2.5, x: 800, y: 400, target: 'title' });
  assert.equal(pending(p).length, 1);
  claim(p, c.id, 'claude');
  assert.equal(comments(p)[0].status, 'working');
  resolve(p, c.id, '延长了0.8秒');
  assert.equal(comments(p)[0].status, 'done');
  assert.equal(pending(p).length, 0);
  assert.throws(() => addComment(p, { text: '  ' }), /empty/);
});
