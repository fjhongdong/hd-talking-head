import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const PKG = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// An npm user gets only package.json "files". A folder the CLI reads from the package root but the list
// leaves out works in the repository and breaks after install (fonts/ was missing: `om fonts` failed).
test('package: every top-level folder the CLI reads from the package root is published', () => {
  const files = JSON.parse(readFileSync(join(PKG, 'package.json'), 'utf8')).files;
  const src = (dir) => readdirSync(join(PKG, dir), { recursive: true }).filter((f) => /\.(js|mjs)$/.test(f)).map((f) => readFileSync(join(PKG, dir, f), 'utf8')).join('\n');
  const code = src('cli');
  const used = new Set([...code.matchAll(/join\(PKG,\s*'([\w-]+)(?=['\/])/g)].map((m) => m[1]));
  for (const d of used) assert.ok(files.includes(d), `"${d}" is read via join(PKG, '${d}…') but not in package.json files`);
  assert.ok(used.has('fonts'));
});
