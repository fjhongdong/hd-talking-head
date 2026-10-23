import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  splitSentences, tokenize, weight, placeWords, placeSentence, wordsOf, parseSilences, speechIntervals,
  sentenceSpans, alignChars, charTimes, asrChars, captionLines, toSrt, cueTerms, missingCues, applyVoice, pickVoice,
} from '../cli/lib/voice.js';

const SCRIPT = 'huashu-motion，一句话出片。你只要说出想法，Agent就把画面做出来。\n哪里不满意，指着画面改，它当场重做！改完一键导出，配音和字幕都对齐。';

const monotonic = (words, from, to) => {
  let last = from;
  for (const w of words) {
    assert.ok(w.start >= last - 1e-9, `${w.word} starts ${w.start} before ${last}`);
    assert.ok(w.end >= w.start, `${w.word} ends before it starts`);
    assert.ok(w.end <= to + 1e-9, `${w.word} ends ${w.end} after ${to}`);
    last = w.end;
  }
};

test('splitSentences cuts at 。！？；, newlines and English full stops, keeps punctuation', () => {
  assert.deepEqual(splitSentences(SCRIPT), [
    'huashu-motion，一句话出片。', '你只要说出想法，Agent就把画面做出来。', '哪里不满意，指着画面改，它当场重做！', '改完一键导出，配音和字幕都对齐。',
  ]);
  assert.deepEqual(splitSentences('It costs 3.5 dollars. Fine?\n“好。”然后\n\n。'), ['It costs 3.5 dollars.', 'Fine?', '“好。”', '然后']);
});

test('tokenize keeps Latin runs and cue terms whole, words are Intl.Segmenter words', () => {
  const words = (s, keep) => tokenize(s, keep).filter((t) => t.word).map((t) => t.text);
  assert.deepEqual(words('huashu-motion，一句话出片。', ['一句话']), ['huashu-motion', '一句话', '出', '片']);
  assert.ok(words('把 GPT-5 的成本降低 30%，只要 3.5 秒').includes('GPT-5'));
  assert.ok(words('把 GPT-5 的成本降低 30%，只要 3.5 秒').includes('3.5'));
  // ICU splits 缓存命中 as 缓|存命|中; a cue term repairs it.
  assert.ok(!words('缓存命中之后').includes('缓存'));
  assert.ok(words('缓存命中之后', ['缓存']).includes('缓存'));
  assert.equal(tokenize('画面', []).map((t) => t.text).join(''), '画面');
});

test('weights: Han characters and digits count one, Latin by vowel groups, punctuation a sliver', () => {
  assert.equal(weight({ text: '画面', word: true }), 2);
  assert.equal(weight({ text: 'Agent', word: true }), 2);
  assert.equal(weight({ text: '30', word: true }), 2);
  assert.equal(weight({ text: '，', word: false }), 0.1);
  assert.equal(weight({ text: ' ', word: false }), 0);
});

test('placeWords: monotonic, inside the spans, never inside a silence, last word ends at speech end', () => {
  const spans = [[0.2, 1.0], [1.6, 2.4]];
  const placed = placeWords(tokenize('你只要说出想法，Agent就把画面做出来。'), spans);
  const words = placed.filter((t) => t.word).map((t) => ({ word: t.text, ...t }));
  monotonic(words, 0.2, 2.4);
  assert.equal(words[0].start, 0.2);
  for (const w of words) assert.ok(!(w.start > 1.0 && w.start < 1.6), `${w.word} starts inside the pause`);
});

test('placeSentence snaps a comma onto the pause inside the sentence', () => {
  const placed = placeSentence(tokenize('huashu-motion，一句话出片。', ['一句话']), [[0, 1], [1.4, 2]]);
  const by = Object.fromEntries(placed.filter((t) => t.word).map((t) => [t.text, t]));
  assert.equal(by['huashu-motion'].end, 1);
  assert.equal(by['一句话'].start, 1.4);
  assert.equal(by['片'].end, 2);
});

test('silencedetect parsing and its complement', () => {
  const log = '[silencedetect @ 0x1] silence_start: 1.2\n[silencedetect @ 0x1] silence_end: 1.5 | silence_duration: 0.3\n[silencedetect] silence_start: 3.9';
  const sil = parseSilences(log, 4.2);
  assert.deepEqual(sil, [[1.2, 1.5], [3.9, 4.2]]);
  assert.deepEqual(speechIntervals(sil, 4.2), [[0, 1.2], [1.5, 3.9]]);
  assert.deepEqual(speechIntervals([], 2), [[0, 2]]);
});

test('sentenceSpans puts sentence edges on the pauses nearest to where the text weights predict', () => {
  // three sentences of equal weight; speech has a short comma pause and two long sentence pauses
  const intervals = [[0, 1], [1.1, 2], [2.6, 3.4], [3.5, 4.4], [5, 6]];
  const spans = sentenceSpans([5, 4, 3], intervals);
  assert.equal(spans.length, 3);
  assert.deepEqual(spans[0].at(-1), [1.1, 2]);
  assert.deepEqual(spans[1][0], [2.6, 3.4]);
  assert.deepEqual(spans[2], [[5, 6]]);
});

test('alignChars and charTimes survive substitutions from ASR', () => {
  const script = [...'改完一键导出'];
  const heard = [...'改完意见导出'].map((ch, i) => ({ ch, start: i * 0.2, end: i * 0.2 + 0.15 }));
  const m = alignChars(script, heard.map((c) => c.ch));
  assert.deepEqual(m, [0, 1, -1, -1, 4, 5]);
  const { times, matched } = charTimes(script, heard);
  assert.equal(matched, 4 / 6);
  assert.equal(times[4].start, 0.8);
  assert.ok(times[2].start >= times[1].end && times[3].end <= times[4].start);
});

test('asrChars reads whisper.cpp full JSON and skips special tokens', () => {
  const json = { transcription: [{ text: '指着画面', offsets: { from: 0, to: 1000 }, tokens: [
    { text: '[_BEG_]', offsets: { from: 0, to: 0 } }, { text: '指', offsets: { from: 0, to: 200 } },
    { text: '着画', offsets: { from: 200, to: 600 } }, { text: '面', offsets: { from: 600, to: 1000 } }] }] };
  const cs = asrChars(json);
  assert.deepEqual(cs.map((c) => c.ch).join(''), '指着画面');
  assert.equal(cs[2].start, 0.4);
});

test('captions: ≤16 visible characters, cut at commas, never across sentences', () => {
  const long = 'huashu-motion的编辑器会把你指着的那个对象、所在的分镜和当前时间一起发给Agent，它改完之后画面会自动刷新。';
  const sentences = splitSentences(SCRIPT + long).map((s, i) => ({ text: s, tokens: placeSentence(tokenize(s), [[i * 5, i * 5 + 4]]) }));
  const lines = sentences.flatMap((s) => captionLines(s, 16));
  for (const l of lines) {
    const width = [...l.text].reduce((n, c) => n + (/[\p{L}\p{N}]/u.test(c) ? (/[\x00-\x7f]/.test(c) ? 0.5 : 1) : 0), 0);
    assert.ok(width <= 16, `"${l.text}" is ${width} wide`);
    assert.ok(!/[。，]$/.test(l.text));
  }
  // every line sits inside one sentence's time range
  for (const l of lines) assert.ok(sentences.some((s, i) => l.start >= i * 5 && l.end <= i * 5 + 4));
  const srt = toSrt(sentences);
  assert.match(srt, /^1\n00:00:00,000 --> 00:00:0\d,\d{3}\n/);
  assert.equal(srt.split('\n\n').length, lines.length);
});

test('cueTerms and missingCues mirror OM.cue', () => {
  const html = `tl.to(a, {}, OM.cue('一句话') - 0.2); tl.to(b, {}, OM.cue("画面", 2)); OM.cue(\`导出\`, 1, 'end'); OM.cue('缺席')`;
  assert.deepEqual(cueTerms(html), [{ term: '一句话', nth: 1 }, { term: '画面', nth: 2 }, { term: '导出', nth: 1 }, { term: '缺席', nth: 1 }]);
  const words = [{ word: '一句话' }, { word: '画面' }, { word: '导出' }];
  assert.deepEqual(missingCues(words, cueTerms(html)).map((m) => m.term), ['画面', '缺席']);
});

const HTML = `<!doctype html>
<html lang="zh" data-composition-variables='[{"id":"t","type":"string","label":"t","default":"x"}]'>
<head><meta charset="utf-8"><script src="vendor/gsap.min.js"></script></head>
<body>
<div id="film" data-composition-id="film" data-width="1920" data-height="1080" data-duration="8">
  <h1>hi</h1>
</div>
<script>const t = OM.cue('画面');</script>
</body></html>
`;

const SENTENCES = [{ text: '指着画面改。', tokens: placeSentence(tokenize('指着画面改。'), [[0.1, 1.2]]) }];

test('applyVoice inserts audio + cues once and is idempotent', () => {
  const a = applyVoice(HTML, { src: 'assets/voice.wav', duration: 9.27, sentences: SENTENCES, meta: { precision: 'tts' } });
  const b = applyVoice(a.html, { src: 'assets/voice.wav', duration: 9.27, sentences: SENTENCES, meta: { precision: 'tts' } });
  assert.equal(b.html, a.html);
  assert.equal(a.html.match(/<audio/g).length, 1);
  assert.equal(a.html.match(/id="om-cues"/g).length, 1);
  assert.match(a.html, /<audio id="om-voice" src="assets\/voice.wav" data-start="0" data-duration="9.27" data-track-index="\d+" data-volume="1"><\/audio>/);
  assert.ok(!/crossorigin/.test(a.html));
  // cues sit before the scripts that read them, and inside the root comes the audio
  assert.ok(a.html.indexOf('om-cues') < a.html.indexOf("OM.cue('画面')"));
  assert.ok(a.html.indexOf('om-voice') > a.html.indexOf('data-composition-id'));
  const cues = JSON.parse(/<script type="application\/json" id="om-cues">([\s\S]*?)<\/script>/.exec(a.html)[1]);
  assert.deepEqual(cues.words.map((w) => w.word), ['指', '着', '画面', '改']);
  assert.equal(cues.precision, 'tts');
  // the composition is shorter than the voice: reported, not changed
  assert.equal(a.rootDuration, 8);
  assert.equal(a.newDuration, 8);
  assert.match(a.html, /data-duration="8"/);
});

test('applyVoice keeps the user\'s data-start/volume, shifts cues by data-start, and --fit extends the root', () => {
  const a = applyVoice(HTML, { src: 'assets/voice.wav', duration: 9.27, sentences: SENTENCES });
  const tweaked = a.html.replace('data-start="0"', 'data-start="1.5"').replace('data-volume="1"', 'data-volume="0.8"');
  const b = applyVoice(tweaked, { src: 'assets/voice.wav', duration: 9.27, sentences: SENTENCES, fit: true });
  assert.match(b.html, /data-start="1.5"/);
  assert.match(b.html, /data-volume="0.8"/);
  assert.equal(b.words[0].start, 1.6);
  assert.equal(b.newDuration, 11.3); // 1.5 + 9.27 + 0.5, rounded up to 0.1
  assert.match(b.html, /data-composition-id="film" data-width="1920" data-height="1080" data-duration="11.3"/);
  const c = applyVoice(b.html, { src: 'assets/voice.wav', duration: 2, sentences: SENTENCES, fit: true });
  assert.equal(c.newDuration, 11.3); // --fit never shortens
});

test('applyVoice escapes </script> inside cue words', () => {
  const s = [{ text: 'x', tokens: [{ text: '</script>', word: true, start: 0, end: 1 }] }];
  const a = applyVoice(HTML, { src: 'assets/voice.wav', duration: 1, sentences: s });
  assert.equal(a.html.match(/<\/script>/g).length, HTML.match(/<\/script>/g).length + 1);
});

test('default voice: Chinese on macOS uses say:Tingting, elsewhere Kokoro', () => {
  assert.deepEqual(pickVoice(undefined, '你好', 'darwin'), { engine: 'say', id: 'Tingting' });
  assert.deepEqual(pickVoice(undefined, '你好', 'linux'), { engine: 'kokoro', id: 'zf_xiaobei' });
  assert.deepEqual(pickVoice(undefined, 'hello', 'darwin'), { engine: 'kokoro', id: 'af_heart' });
  assert.deepEqual(pickVoice('say:Meijia', '你好'), { engine: 'say', id: 'Meijia' });
  assert.deepEqual(pickVoice('zf_xiaobei', '你好'), { engine: 'kokoro', id: 'zf_xiaobei' });
});

test('wordsOf flattens timed words across sentences, in order', () => {
  const sentences = splitSentences(SCRIPT).map((s, i) => ({ text: s, tokens: placeSentence(tokenize(s), [[i * 3, i * 3 + 2.5]]) }));
  const words = wordsOf(sentences);
  monotonic(words, 0, 11.5);
  assert.equal(words[0].word, 'huashu-motion');
});

test('applyVoice never adds a data-duration to a root that has none (length follows the timeline)', () => {
  const html = HTML.replace(' data-duration="8"', '');
  const a = applyVoice(html, { src: 'assets/voice.wav', duration: 9.27, sentences: SENTENCES, fit: true });
  assert.equal(a.rootDuration, null);
  assert.equal(a.newDuration, null);
  assert.match(a.html, /data-composition-id="film" data-width="1920" data-height="1080">/);
});

test('cueTerms ignores examples inside comments', () => {
  const html = `<!-- OM.cue('词') --><script>/* OM.cue('块') */ // OM.cue('行')\nconst u = "https://x"; tl.to(a, {}, cue('真的'))</script>`;
  assert.deepEqual(cueTerms(html).map((c) => c.term), ['真的']);
});

test('applyVoice ignores tags quoted inside HTML comments', () => {
  const html = HTML.replace('<body>', '<body>\n<!-- om voice writes <audio id="om-voice"> and <script id="om-cues"> here -->');
  const a = applyVoice(html, { src: 'assets/voice.wav', duration: 3, sentences: SENTENCES });
  assert.ok(a.html.includes('<!-- om voice writes <audio id="om-voice"> and <script id="om-cues"> here -->'));
  assert.equal(a.html.match(/<audio id="om-voice" src=/g).length, 1);
  assert.equal(applyVoice(a.html, { src: 'assets/voice.wav', duration: 3, sentences: SENTENCES }).html, a.html);
});
