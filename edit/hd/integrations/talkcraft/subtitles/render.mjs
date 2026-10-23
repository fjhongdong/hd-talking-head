#!/usr/bin/env node
import {createRequire} from 'node:module';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const runtime = path.resolve(here, '../runtime');
const require = createRequire(path.join(runtime, 'package.json'));
const {bundle} = require('@remotion/bundler');
const {renderMedia, selectComposition} = require('@remotion/renderer');

const fail = (message) => { throw new Error(`[TALKCRAFT_SUBTITLES_INVALID] ${message}`); };
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const keys = (v, expected) => v && typeof v === 'object' && !Array.isArray(v) && JSON.stringify(Object.keys(v).sort()) === JSON.stringify([...expected].sort());
const validUtf16Boundary = (text, offset) => offset >= 0 && offset <= text.length && !(offset > 0 && offset < text.length && text.charCodeAt(offset - 1) >= 0xd800 && text.charCodeAt(offset - 1) <= 0xdbff && text.charCodeAt(offset) >= 0xdc00 && text.charCodeAt(offset) <= 0xdfff);

const validate = (input) => {
  if (!keys(input, ['canvas', 'cues', 'schema_version']) || input.schema_version !== 1) fail('schema_version or top-level keys');
  if (!keys(input.canvas, ['fps', 'frames', 'height', 'width']) || input.canvas.width !== 1080 || input.canvas.height !== 1920 || input.canvas.fps !== 24 || !Number.isInteger(input.canvas.frames) || input.canvas.frames <= 0) fail('canvas must be 1080x1920 at 24fps');
  if (!Array.isArray(input.cues)) fail('cues must be an array');
  let previousEnd = 0;
  for (const cue of input.cues) {
    if (!keys(cue, ['cue_id', 'emphasis', 'end', 'placement', 'start', 'text', 'words']) || !['standard', 'above_avatar'].includes(cue.placement) || typeof cue.cue_id !== 'string' || typeof cue.text !== 'string' || !finite(cue.start) || !finite(cue.end) || cue.start < 0 || cue.end <= cue.start || cue.end * input.canvas.fps > input.canvas.frames + 1e-9 || cue.start < previousEnd) fail('cue timing or keys are invalid');
    previousEnd = cue.end;
    if (!Array.isArray(cue.words)) fail(`words invalid for ${cue.cue_id}`);
    let previousWordEnd = cue.start;
    let previousTextEnd = 0;
    for (const word of cue.words) {
      if (!keys(word, ['end', 'start', 'text_end', 'text_start']) || !finite(word.start) || !finite(word.end) || !Number.isInteger(word.text_start) || !Number.isInteger(word.text_end) || word.start < cue.start || word.end > cue.end || word.end <= word.start || word.text_start < previousTextEnd || word.text_end <= word.text_start || word.text_end > cue.text.length || !validUtf16Boundary(cue.text, word.text_start) || !validUtf16Boundary(cue.text, word.text_end) || word.start < previousWordEnd) fail(`word invalid for ${cue.cue_id}`);
      previousWordEnd = word.end;
      previousTextEnd = word.text_end;
    }
    if (cue.emphasis !== null) {
      const e = cue.emphasis;
      const matched = cue.words.filter((word) => word.text_start < e.text_end && word.text_end > e.text_start);
      if (!keys(e, ['end', 'start', 'text_end', 'text_start']) || !finite(e.start) || !finite(e.end) || !Number.isInteger(e.text_start) || !Number.isInteger(e.text_end) || e.start < cue.start || e.end > cue.end || e.end <= e.start || e.text_start < 0 || e.text_end <= e.text_start || e.text_end > cue.text.length || !validUtf16Boundary(cue.text, e.text_start) || !validUtf16Boundary(cue.text, e.text_end) || matched.length === 0 || matched[0].text_start > e.text_start || matched[matched.length - 1].text_end < e.text_end || matched[0].start !== e.start || matched[matched.length - 1].end !== e.end) fail(`emphasis must match source word timing for ${cue.cue_id}`);
    }
  }
  return input;
};

const arg = (name) => { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : null; };
const inputPath = arg('--input');
const outputPath = arg('--output');
if (!inputPath || !outputPath || process.argv.length !== 6 || process.argv[2] !== '--input' || process.argv[4] !== '--output') fail('usage: node render.mjs --input /abs/input.json --output /abs/subtitles.webm');
if (!path.isAbsolute(inputPath) || !path.isAbsolute(outputPath)) fail('input and output must be absolute paths');
const input = validate(JSON.parse(await readFile(inputPath, 'utf8')));
const serveUrl = await bundle({entryPoint: path.join(here, 'entry.tsx'), rootDir: here, webpackOverride: (config) => ({...config, resolve: {...config.resolve, modules: [path.join(runtime, 'node_modules'), ...(config.resolve?.modules ?? [])]}}), onProgress: () => {}});
const composition = await selectComposition({serveUrl, id: 'TalkCraftSubtitles', inputProps: input});
await renderMedia({
  composition, serveUrl, inputProps: input, outputLocation: outputPath,
  codec: 'vp9', pixelFormat: 'yuva420p', imageFormat: 'png', muted: true, concurrency: 2,
  ffmpegOverride: ({type, args}) => {
    if (type !== 'stitcher') return args;
    const crf = args.indexOf('-crf');
    const base = crf < 0 ? args : [...args.slice(0, crf), ...args.slice(crf + 2)];
    return [...base.slice(0, -1), '-deadline', 'realtime', '-cpu-used', '8', '-row-mt', '1', '-lossless', '1', base.at(-1)];
  },
});
