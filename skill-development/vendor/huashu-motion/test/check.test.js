import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { findChrome } from '../cli/lib/browser.js';
import { checkPage, checkSource } from '../cli/lib/check.js';
import { makeFilm } from './fixture-film.js';

const codes = (found, level) => found.filter((f) => !level || f.level === level).map((f) => f.code);

test('check (source): a clean film has no errors, and the om-score is not read as JavaScript', () => {
  const { project } = makeFilm({ sound: false });
  assert.deepEqual(codes(checkSource(project), 'error'), []);
});

test('check (source): the mistakes that break a render are errors, clock and random use are warnings', () => {
  const { project, index } = makeFilm({
    sound: false,
    body: '<img src="assets/nope.png"><b data-var-text="ghost">x</b><i id="twice"></i><i id="twice"></i>',
    script: 'gsap.to("#box", { left: 200, duration: 1 }); const r = Math.random(); const d = Date.now();',
  });
  writeFileSync(join(index, '..', 'draft.html'), '<div data-composition-id="draft" data-width="10" data-height="10"></div>');
  const found = checkSource(project);
  for (const c of ['missing-file', 'unknown-variable', 'duplicate-id', 'layout-motion', 'several-compositions']) assert.ok(codes(found, 'error').includes(c), `${c} in ${JSON.stringify(found)}`);
  for (const c of ['random', 'clock']) assert.ok(codes(found, 'warning').includes(c), c);
  assert.ok(found.find((f) => f.code === 'layout-motion').line > 1, 'points at the line');
});

test('check (source): a script that does not parse is an error with its line', () => {
  const { project } = makeFilm({ sound: false, script: 'const a = ;' });
  const f = checkSource(project).find((x) => x.code === 'script-syntax');
  assert.ok(f && f.line > 10, JSON.stringify(f));
});

test('check (page): frames that depend on what was played before are found; a clean film passes', { skip: !findChrome() && 'no Chrome' }, async () => {
  const clean = makeFilm({ sound: false, video: false });
  assert.deepEqual(codes(await checkPage(clean.project, { samples: 6 }), 'error'), []);
  // the box only moves after the timeline has been played through 0.3 s: jumping straight to a later time misses that
  const { project } = makeFilm({ sound: false, video: false, script: 'let armed = false; const real = window.__timelines.film.seek; window.__timelines.film.seek = (t) => { if (t > 0.2 && t < 0.4) armed = true; real(armed ? t : 0); };' });
  const found = await checkPage(project, { samples: 30 });
  assert.ok(codes(found).includes('history-dependent'), JSON.stringify(found));
});

test('check (source): Array.from with an arrow that returns layout, and a file name with a literal %, are not errors', () => {
  const { project } = makeFilm({ sound: false, body: '<div style="background:url(assets/100%.png)"></div>', script: 'const rows = Array.from({ length: 3 }, (_, i) => ({ top: i * 10, height: 8 }));' });
  writeFileSync(join(project.root, 'assets', '100%.png'), '');
  assert.deepEqual(codes(checkSource(project), 'error'), []);
});
