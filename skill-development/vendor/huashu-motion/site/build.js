#!/usr/bin/env node
// node site/build.js → site/dist/: the huashu-motion gallery. Every example and template becomes a share page
// (the same output as `om export html`), and the front page lists them as cards that play on hover.
// Static, local-only: no outside fonts, scripts or requests. Titles and blurbs come from site/works.json,
// then a project's gallery.json / template.json, then its <title>.
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { REPO_URL, exportHtml, readMeta } from '../cli/lib/export.js';
import { openProject, readSource, scan } from '../cli/lib/project.js';

const SITE = dirname(fileURLToPath(import.meta.url));
const PKG = resolve(SITE, '..');
const DIST = join(SITE, 'dist');
const CONFIG = JSON.parse(readFileSync(join(SITE, 'works.json'), 'utf8'));
const SKILL = REPO_URL.replace(/^https:\/\/github\.com\//, '');

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const lang = (v, l) => (v && typeof v === 'object' ? v[l] ?? v.en ?? '' : v ?? '');
const t = (en, zh = en) => (en === zh ? esc(en) : `<span data-l="en">${esc(en)}</span><span data-l="zh">${esc(zh)}</span>`);
const tv = (v) => t(lang(v, 'en'), lang(v, 'zh'));
const dirs = (root) => (existsSync(root) ? readdirSync(root).filter((n) => existsSync(join(root, n, 'index.html'))).sort() : []);

// ---------- collect ----------
function collect() {
  const list = [];
  const order = CONFIG.order || [];
  const examples = dirs(join(PKG, 'examples')).sort((a, b) => ((order.indexOf(a) + 1 || 1e9) - (order.indexOf(b) + 1 || 1e9)) || a.localeCompare(b));
  for (const id of examples) list.push({ id, slug: id, kind: 'example', root: join(PKG, 'examples', id), conf: CONFIG.works?.[id] || {} });
  for (const id of dirs(join(PKG, 'templates'))) list.push({ id, slug: `template-${id}`, kind: 'template', root: join(PKG, 'templates', id), conf: CONFIG.templates?.[id] || {} });
  return list;
}

// A template is not a playable project until `om new` has pulled in what its template.json "copy" lists.
function materialize(work, stage) {
  if (work.kind !== 'template') return work.root;
  const target = join(stage, work.id);
  const r = spawnSync(process.execPath, [join(PKG, 'cli/om.js'), 'new', target, '--template', work.id], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error((r.stderr || r.stdout).trim().split('\n').pop());
  return target;
}

// ---------- build ----------
function build() {
  rmSync(DIST, { recursive: true, force: true }); // generated, never edited by hand (site/dist is gitignored)
  mkdirSync(join(DIST, 'assets/fonts'), { recursive: true });
  for (const f of ['Inter-var.woff', 'NotoSansSC-500.woff', 'NotoSansSC-700.woff', 'OFL.txt']) copyFileSync(join(PKG, 'fonts', f), join(DIST, 'assets/fonts', f));
  copyFileSync(join(PKG, 'runtime/om-player.js'), join(DIST, 'assets', 'om-player.js'));

  const stage = mkdtempSync(join(tmpdir(), 'om-site-'));
  const works = [];
  try {
    for (const w of collect()) {
      try {
        const root = materialize(w, stage);
        const project = openProject(root);
        const { html } = readSource(project);
        const s = scan(html);
        let meta = readMeta(root, html);
        if (w.kind === 'template') { try { meta = { ...meta, ...pickMeta(JSON.parse(readFileSync(join(w.root, 'template.json'), 'utf8'))) }; } catch {} }
        const title = w.conf.title || meta.title, description = w.conf.description || meta.description;
        exportHtml(project, { out: join(DIST, 'works', w.slug), title, description, name: w.kind === 'template' ? `${w.id}-template` : w.id, back: '../../index.html' });
        works.push({ ...w, title, description, width: s.width || 1920, height: s.height || 1080, duration: s.duration, audio: /<audio\b/i.test(html) });
        console.log(`  ✓ ${w.slug}`);
      } catch (e) {
        console.warn(`  ✗ ${w.slug}: ${e.message}`);
      }
    }
  } finally {
    rmSync(stage, { recursive: true, force: true }); // our own scratch copies of templates
  }
  if (!works.length) throw new Error('nothing to show: no example or template could be exported');
  writeFileSync(join(DIST, 'index.html'), page(works));
  console.log(`site/dist/index.html — ${works.length} works`);
}

const pickMeta = (m) => ({ ...(m.title && { title: String(m.title).replace(/\s*\(t\d+\)$/, '') }), ...((m.description || m.summary) && { description: m.description || m.summary }) });

// ---------- page ----------
function card(w) {
  const tags = [...(w.conf.tags || []), ...(w.kind === 'template' ? [['Template', '模板']] : []), ...(w.audio && !(w.conf.tags || []).includes('Voice') ? [['Sound', '有声']] : [])];
  return `
    <article class="card" data-film="works/${esc(w.slug)}/film/index.html" data-poster="${Number(w.conf.poster ?? 0.4)}" style="--ar: ${w.width} / ${w.height}">
      <div class="thumb"><div class="mount"></div><span class="dur" data-dur>${w.duration ? fmt(w.duration) : ''}</span></div>
      <div class="card-body">
        <h3>${tv(w.title)}</h3>
        <p>${tv(w.description)}</p>
        <div class="tags">${tags.map((x) => `<span>${Array.isArray(x) ? t(x[0], x[1]) : esc(x)}</span>`).join('')}</div>
      </div>
      <a class="cover" href="works/${esc(w.slug)}/index.html" aria-label="${esc(lang(w.title, 'en'))}"></a>
    </article>`;
}

function page(works) {
  const hero = works.find((w) => w.id === CONFIG.hero) || works[0];
  const copyBtn = (id) => `<button class="copy" data-copy="${id}">${t('Copy', '复制')}</button>`;
  return `<!doctype html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>huashu-motion — motion graphics made by your coding agent</title>
<meta name="description" content="Motion graphics made by your coding agent. Point at the frame to change it. Open source, runs locally, works with Claude Code, Codex, Cursor and Gemini CLI.">
<meta property="og:title" content="huashu-motion">
<meta property="og:description" content="Motion graphics made by your coding agent. Point at the frame to change it.">
<meta name="theme-color" content="#f6f5f2">
<script>(() => { let l; try { l = localStorage.getItem('om-lang'); } catch {} document.documentElement.dataset.lang = l || ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en'); })();</script>
<style>
@font-face { font-family: "Inter"; src: url("assets/fonts/Inter-var.woff") format("woff"); font-weight: 100 900; font-display: swap; }
@font-face { font-family: "Noto Sans SC"; src: url("assets/fonts/NotoSansSC-500.woff") format("woff"); font-weight: 400 600; font-display: swap; unicode-range: U+3000-303F, U+3400-9FFF, U+FF00-FFEF; }
@font-face { font-family: "Noto Sans SC"; src: url("assets/fonts/NotoSansSC-700.woff") format("woff"); font-weight: 700 900; font-display: swap; unicode-range: U+3000-303F, U+3400-9FFF, U+FF00-FFEF; }
:root {
  --paper: #f6f5f2; --paper-2: #efece6; --card: #fffefb; --line: #e6e3dc; --line-2: #d9d5cc;
  --ink: #1d1b18; --ink-2: #57524a; --ink-3: #8f897e; --accent: #d9480f; --accent-2: #f59f00;
  --stage: #1b1a17; --stage-2: #26241f; --stage-line: #34312b; --stage-ink: #f4f1eb; --stage-ink-2: #b4ada1;
  --sans: "Inter", "PingFang SC", "Noto Sans SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  --wrap: 1180px; --gutter: 32px;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
html[data-lang="en"] [data-l="zh"], html[data-lang="zh"] [data-l="en"] { display: none; }
html { scroll-behavior: smooth; }
html, body { margin: 0; background: var(--paper); color: var(--ink); }
body { font: 16px/1.6 var(--sans); -webkit-font-smoothing: antialiased; font-feature-settings: "cv11", "ss01"; overflow-x: hidden; }
a { color: inherit; }
button { font: inherit; color: inherit; border: 0; background: none; cursor: pointer; }
code, pre { font-family: var(--mono); }
.wrap { width: 100%; max-width: calc(var(--wrap) + var(--gutter) * 2); margin: 0 auto; padding: 0 var(--gutter); }

/* nav */
.nav { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--paper) 82%, transparent); backdrop-filter: saturate(1.4) blur(14px); -webkit-backdrop-filter: saturate(1.4) blur(14px); border-bottom: 1px solid transparent; transition: border-color .2s; }
.nav.scrolled { border-bottom-color: var(--line); }
.nav .wrap { display: flex; align-items: center; gap: 28px; height: 64px; }
.brand { display: inline-flex; align-items: center; gap: 9px; font-weight: 650; letter-spacing: -.015em; text-decoration: none; }
.logo { width: 20px; height: 20px; border-radius: 6px; background: conic-gradient(from 210deg, var(--accent), var(--accent-2), var(--accent)); box-shadow: inset 0 0 0 4.5px var(--paper), 0 0 0 1px var(--line); }
.links { display: flex; gap: 24px; margin-left: auto; font-size: 14px; color: var(--ink-2); }
.links a { text-decoration: none; } .links a:hover { color: var(--ink); }
.lang { display: inline-flex; padding: 3px; border-radius: 99px; background: var(--paper-2); box-shadow: inset 0 0 0 1px var(--line); font-size: 12px; }
.lang button { padding: 3px 10px; border-radius: 99px; color: var(--ink-3); }
html[data-lang="en"] .lang [data-set="en"], html[data-lang="zh"] .lang [data-set="zh"] { background: var(--card); color: var(--ink); box-shadow: 0 1px 2px #0000001a; }

/* hero */
.hero { padding: 88px 0 0; text-align: center; }
.kicker { display: inline-flex; align-items: center; gap: 10px; padding: 6px 14px 6px 8px; border-radius: 99px; background: var(--card); box-shadow: 0 0 0 1px var(--line), 0 1px 2px #0000000d; font-size: 13px; color: var(--ink-2); }
.kicker b { flex: none; white-space: nowrap; padding: 2px 8px; border-radius: 99px; background: var(--ink); color: #fff; font-size: 11.5px; font-weight: 600; letter-spacing: .02em; }
h1 { margin: 26px auto 0; font-size: clamp(40px, 6vw, 72px); line-height: 1.02; font-weight: 700; letter-spacing: -.042em; text-wrap: balance; }
html[data-lang="zh"] h1 { max-width: 13em; letter-spacing: -.02em; line-height: 1.12; }
h1 .soft { display: block; color: var(--ink-3); }
h1 .main { display: block; max-width: 15ch; margin: 0 auto; }
html[data-lang="zh"] h1 .main { max-width: none; }
.lede { max-width: 620px; margin: 24px auto 0; font-size: 18px; line-height: 1.6; color: var(--ink-2); text-wrap: pretty; }
.cta { display: flex; justify-content: center; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 34px; }
.cmd { position: relative; display: inline-flex; align-items: center; gap: 4px; height: 50px; padding: 0 6px 0 18px; border-radius: 12px; background: var(--ink); color: #f4f1eb; box-shadow: 0 10px 28px -12px #1d1b1899; font: 14.5px var(--mono); }
.cmd .p { color: #8f897e; margin-right: 6px; }
.cmd .copy { margin-left: 10px; height: 38px; padding: 0 14px; border-radius: 8px; background: #ffffff1a; color: #f4f1eb; font: 600 13px var(--sans); }
.cmd .copy:hover { background: #ffffff2b; }
.copy.done { background: #2f855a !important; color: #fff !important; }
.ghost { display: inline-flex; align-items: center; gap: 8px; height: 50px; padding: 0 20px; border-radius: 12px; color: var(--ink); font-weight: 550; text-decoration: none; box-shadow: inset 0 0 0 1px var(--line-2); }
.ghost:hover { background: var(--card); }

.showcase { margin: 64px auto 0; padding: 14px; border-radius: 22px; background: var(--stage); box-shadow: 0 50px 100px -40px #1d1b18a6, 0 18px 40px -20px #1d1b1866; }
.showcase .screen { position: relative; aspect-ratio: var(--ar); border-radius: 12px; overflow: hidden; background: #000; }
.showcase om-player { display: block; width: 100%; height: 100%; }
.showcase .caption { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 6px 2px; color: var(--stage-ink-2); font-size: 14px; text-align: left; }
.showcase .caption b { color: var(--stage-ink); font-weight: 600; margin-right: 8px; }
.showcase .caption a { flex: none; color: var(--stage-ink); text-decoration: none; font-weight: 550; }
.showcase .caption a:hover { color: #ff8a57; }
.filehint { max-width: 640px; margin: 22px auto 0; padding: 12px 16px; border-radius: 12px; background: #fff4e0; color: #6b4a12; font-size: 14px; box-shadow: inset 0 0 0 1px #f0dcb2; }
.filehint code { padding: 2px 8px; border-radius: 6px; background: #fff; font-size: 13px; user-select: all; }
.agents { margin: 30px 0 0; font-size: 13.5px; color: var(--ink-3); }
.agents span + span::before { content: "·"; margin: 0 10px; color: var(--line-2); }

/* sections */
section.block { padding: 120px 0 0; }
section[id] { scroll-margin-top: 40px; }
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 40px; margin-bottom: 40px; }
.eyebrow { font-size: 13px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
h2 { margin: 10px 0 0; font-size: clamp(30px, 3.6vw, 44px); line-height: 1.08; font-weight: 700; letter-spacing: -.035em; text-wrap: balance; }
html[data-lang="zh"] h2 { letter-spacing: -.015em; }
.head p { max-width: 430px; margin: 0; color: var(--ink-2); text-wrap: pretty; }

.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; counter-reset: step; }
.step { position: relative; padding: 26px 26px 24px; border-radius: 18px; background: var(--card); box-shadow: 0 0 0 1px var(--line); display: flex; flex-direction: column; }
.step .n { font: 600 13px var(--mono); color: var(--ink-3); }
.step h3 { margin: 18px 0 8px; font-size: 20px; line-height: 1.25; font-weight: 650; letter-spacing: -.02em; }
.step p { margin: 0; color: var(--ink-2); font-size: 15px; text-wrap: pretty; }
.step .say { margin-top: auto; padding-top: 22px; }
.say div { padding: 12px 14px; border-radius: 12px; background: var(--paper); box-shadow: inset 0 0 0 1px var(--line); font-size: 14px; line-height: 1.5; color: var(--ink); }
.say .mono { font: 13px/1.5 var(--mono); }
.say .pin { display: inline-grid; place-items: center; width: 20px; height: 20px; margin-right: 8px; vertical-align: -4px; border-radius: 10px 10px 10px 2px; background: var(--accent); color: #fff; font-size: 10px; font-weight: 700; transform: rotate(-45deg); }
.say .pin i { transform: rotate(45deg); font-style: normal; }

/* works */
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 28px 22px; }
.card { position: relative; display: flex; flex-direction: column; border-radius: 18px; background: var(--card); box-shadow: 0 0 0 1px var(--line); transition: transform .25s cubic-bezier(.2,.7,.2,1), box-shadow .25s; }
.card:hover { transform: translateY(-3px); box-shadow: 0 0 0 1px var(--line-2), 0 24px 50px -24px #1d1b1859; }
.thumb { position: relative; margin: 8px 8px 0; aspect-ratio: var(--ar); border-radius: 12px; overflow: hidden; background: var(--stage-2); }
.thumb::after { content: ""; position: absolute; inset: 0; border-radius: inherit; box-shadow: inset 0 0 0 1px #0000000f; pointer-events: none; }
.mount, .mount om-player { position: absolute; inset: 0; display: block; width: 100%; height: 100%; }
.mount { opacity: 0; transition: opacity .4s; } .card.ready .mount { opacity: 1; }
.thumb .dur { position: absolute; right: 10px; bottom: 10px; padding: 2px 8px; border-radius: 6px; background: #0000008c; color: #fff; font-size: 12px; font-weight: 550; font-variant-numeric: tabular-nums; backdrop-filter: blur(6px); }
.thumb .dur:empty { display: none; }
.card-body { padding: 16px 18px 18px; display: flex; flex-direction: column; flex: 1; }
.card h3 { margin: 0; font-size: 17px; font-weight: 650; letter-spacing: -.015em; }
.card p { margin: 6px 0 0; font-size: 14px; line-height: 1.55; color: var(--ink-2); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 14px; }
.tags span { padding: 2px 9px; border-radius: 99px; background: var(--paper-2); color: var(--ink-2); font-size: 12px; font-weight: 500; }
.cover { position: absolute; inset: 0; z-index: 2; border-radius: inherit; }
.cover:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

/* install */
.install { margin-top: 120px; padding: 96px 0; background: var(--stage); color: var(--stage-ink); }
.install .eyebrow { color: #ff8a57; }
.install .head p { color: var(--stage-ink-2); }
.cmds { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.cmdcard { padding: 24px; border-radius: 18px; background: var(--stage-2); box-shadow: inset 0 0 0 1px var(--stage-line); }
.cmdcard h3 { margin: 0; font-size: 16px; font-weight: 600; }
.cmdcard p { margin: 6px 0 18px; color: var(--stage-ink-2); font-size: 14.5px; }
.line { position: relative; display: flex; align-items: center; height: 50px; padding: 0 6px 0 16px; border-radius: 10px; background: #12110f; box-shadow: inset 0 0 0 1px var(--stage-line); font: 14px var(--mono); white-space: nowrap; overflow: hidden; }
.line code { flex: 1; min-width: 0; overflow-x: auto; scrollbar-width: none; } .line code::-webkit-scrollbar { display: none; }
.line .p { color: #7d776d; margin-right: 10px; }
.line .copy { flex: none; height: 38px; padding: 0 14px; border-radius: 8px; background: #ffffff14; color: var(--stage-ink); font: 600 13px var(--sans); }
.line .copy:hover { background: #ffffff24; }
.req { margin-top: 26px; color: var(--stage-ink-2); font-size: 14px; }
.req code { color: var(--stage-ink); }

footer { padding: 40px 0 48px; font-size: 14px; color: var(--ink-3); }
footer .wrap { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
footer nav { display: flex; gap: 22px; margin-left: auto; }
footer a { text-decoration: none; color: var(--ink-2); } footer a:hover { color: var(--ink); }

@media (max-width: 980px) {
  .steps { grid-template-columns: minmax(0, 1fr); }
  .grid { grid-template-columns: repeat(2, 1fr); }
  .cmds { grid-template-columns: minmax(0, 1fr); }
  .head { display: block; } .head p { margin-top: 14px; }
}
@media (max-width: 640px) {
  :root { --gutter: 16px; }
  .nav .wrap { height: 56px; gap: 14px; }
  .links { display: none; }
  .lang { margin-left: auto; }
  .hero { padding-top: 48px; }
  .kicker { font-size: 12px; text-align: left; border-radius: 16px; }
  h1 { font-size: clamp(34px, 10vw, 44px); }
  .lede { font-size: 16px; }
  .cta { flex-direction: column; align-items: stretch; gap: 10px; }
  .cmd, .ghost { justify-content: center; }
  .cmd { padding-left: 14px; font-size: 13.5px; }
  .showcase { margin-top: 44px; padding: 6px; border-radius: 14px; }
  .showcase .screen { border-radius: 9px; }
  .showcase .caption { flex-direction: column; align-items: flex-start; gap: 6px; padding: 12px 8px 6px; font-size: 13.5px; }
  .agents span { display: inline-block; }
  section.block { padding-top: 80px; }
  .grid { grid-template-columns: minmax(0, 1fr); }
  .install { margin-top: 80px; padding: 64px 0; }
  .cmdcard { padding: 18px; }
  .line { font-size: 13px; padding-left: 12px; }
  footer nav { margin-left: 0; width: 100%; }
}
</style>
<script src="assets/om-player.js"></script>
</head>
<body>
<header class="nav" id="nav">
  <div class="wrap">
    <a class="brand" href="#top"><span class="logo" aria-hidden="true"></span>huashu-motion</a>
    <nav class="links">
      <a href="#how">${t('How it works', '怎么用')}</a>
      <a href="#works">${t('Works', '作品')}</a>
      <a href="#install">${t('Install', '安装')}</a>
      <a href="${REPO_URL}">GitHub</a>
    </nav>
    <div class="lang" role="group" aria-label="Language"><button data-set="en">EN</button><button data-set="zh">中文</button></div>
  </div>
</header>

<main id="top">
  <section class="hero">
    <div class="wrap">
      <span class="kicker"><b>${t('Open source', '开源')}</b>${t('Runs locally · Any coding agent · No extra API key', '本地运行 · 任何编程 Agent · 不需要额外 API Key')}</span>
      <h1><span class="main">${t('Motion graphics made by your coding agent.', '让你自己的 Agent 做动画，')}</span> <span class="soft">${t('Point at the frame to change it.', '指着画面改。')}</span></h1>
      <p class="lede">${t('Your agent writes the film as code and opens the studio. You click the frame where something’s off and say what you want. It edits the source; the preview reloads on the same frame.', 'Agent 把片子写成代码，打开编辑器。你在画面上哪里不满意就点哪里，说一句想要什么。它改源码，预览停在原处刷新。')}</p>
      <div class="cta">
        <div class="cmd"><span class="p">$</span><code id="c-hero">npx huashu-motion demo</code>${copyBtn('c-hero')}</div>
        <a class="ghost" href="#works">${t('See the works', '看作品')} <span aria-hidden="true">↓</span></a>
      </div>
      <figure class="showcase" style="--ar: ${hero.width} / ${hero.height}; margin-inline: auto; max-width: var(--wrap)">
        <div class="screen"><om-player src="works/${esc(hero.slug)}/film/index.html" controls autoplay muted loop></om-player></div>
        <figcaption class="caption"><span><b>${tv(hero.title)}</b>${tv(hero.description)}</span><a href="works/${esc(hero.slug)}/index.html">${t('Open and remix', '打开并 Remix')} →</a></figcaption>
      </figure>
      <p class="filehint" id="filehint" hidden>${t('Opened as a file and the films stay blank? Some browsers block that. Serve the folder instead:', '直接双击打开、影片一片空白？有的浏览器不允许本地文件这样加载。换成在这个文件夹里运行：')} <code>npx serve .</code></p>
      <p class="agents"><span>Claude Code</span><span>Codex</span><span>Cursor</span><span>Gemini CLI</span><span>${t('any agent that can run a command', '任何能跑命令的 Agent')}</span></p>
    </div>
  </section>

  <section class="block" id="how">
    <div class="wrap">
      <div class="head">
        <div><div class="eyebrow">${t('How it works', '怎么用')}</div><h2>${t('Thirty seconds to get it.', '30 秒看懂。')}</h2></div>
        <p>${t('One index.html per film. GSAP, Canvas, SVG, Three.js — anything a browser can draw, rendered by your own Chrome. Nothing proprietary.', '每部片就是一个 index.html。GSAP、Canvas、SVG、Three.js，浏览器能画的都能用，用你自己的 Chrome 渲染，没有私有格式。')}</p>
      </div>
      <div class="steps">
        <div class="step"><span class="n">01</span><h3>${t('Ask your agent', '跟 Agent 说一句')}</h3><p>${t('Describe the film. Hand it the data if there is some.', '说清楚要什么片子，有数据就把数据给它。')}</p>
          <div class="say"><div>${t('“Make a 30-second explainer about why our signup rate doubled, using data/funnel.csv. Use huashu-motion.”', '「用 huashu-motion 把 data/funnel.csv 做成 30 秒解说，讲清楚注册率为什么翻倍。」')}</div></div></div>
        <div class="step"><span class="n">02</span><h3>${t('It writes the film as code', '它把片子写成代码')}</h3><p>${t('Then opens the studio and waits. Titles, numbers, colours and timings show up as fields you can edit yourself.', '然后打开编辑器等你。标题、数字、颜色、时长都变成右侧的字段，你可以直接改。')}</p>
          <div class="say"><div class="mono">om studio my-film</div></div></div>
        <div class="step"><span class="n">03</span><h3>${t('Point at the frame', '指着画面改')}</h3><p>${t('Press C, click where something’s off, type what you want. Every version is kept; ⌘Z undoes.', '按 C，点画面上不对的地方，写一句话。每个版本都留着，⌘Z 随时撤回。')}</p>
          <div class="say"><div><span class="pin"><i>1</i></span>${t('hold here a beat longer', '这里多停一拍')}</div></div></div>
      </div>
    </div>
  </section>

  <section class="block" id="works">
    <div class="wrap">
      <div class="head">
        <div><div class="eyebrow">${t('Works', '作品')}</div><h2>${t('Every film here is a folder of code.', '这里每一部片，都是一个代码文件夹。')}</h2></div>
        <p>${t('Hover to play. Open one, press “Remix in your agent”, and your agent takes it from the source.', '鼠标停上去就播放。点开任意一部，按「在你的 Agent 里 Remix」，你的 Agent 就从源码接着改。')}</p>
      </div>
      <div class="grid">${works.map(card).join('')}
      </div>
    </div>
  </section>

  <section class="install" id="install">
    <div class="wrap">
      <div class="head">
        <div><div class="eyebrow">${t('Install', '安装')}</div><h2>${t('Two commands. No account.', '两行命令，不用注册。')}</h2></div>
        <p>${t('It’s a skill plus a CLI. It works on whatever plan you already have; no extra API key.', '它是一个 skill 加一个命令行工具。你现在用什么订阅都能跑，不需要额外的 API Key。')}</p>
      </div>
      <div class="cmds">
        <div class="cmdcard"><h3>${t('Give your agent the skill', '给你的 Agent 装上 skill')}</h3><p>${t('Claude Code, Codex, Cursor, Gemini CLI and more.', 'Claude Code、Codex、Cursor、Gemini CLI 等都能用。')}</p>
          <div class="line"><span class="p">$</span><code id="c-skill">npx skills add ${esc(SKILL)}</code>${copyBtn('c-skill')}</div></div>
        <div class="cmdcard"><h3>${t('Or watch the demo first', '或者先看演示')}</h3><p>${t('Opens the showcase film in the studio. No renderer download.', '在编辑器里打开示例片，不需要下载渲染器。')}</p>
          <div class="line"><span class="p">$</span><code id="c-demo">npx huashu-motion demo</code>${copyBtn('c-demo')}</div></div>
      </div>
      <p class="req">${t('Needs Node 22+. Exporting MP4 also needs FFmpeg; the first export downloads the renderer.', '需要 Node 22 及以上。导出 MP4 还需要 FFmpeg，第一次导出会下载渲染器。')}</p>
    </div>
  </section>
</main>

<footer>
  <div class="wrap">
    <a class="brand" href="#top"><span class="logo" aria-hidden="true"></span>huashu-motion</a>
    <span>${t('MIT licensed. Made with huashu-motion.', 'MIT 开源。本站的片子都用 huashu-motion 做。')}</span>
    <nav><a href="${REPO_URL}">GitHub</a><a href="${REPO_URL}/blob/main/docs/CONTRACT.md">${t('The contract', '工程契约')}</a><a href="${REPO_URL}/blob/main/THIRD_PARTY.md">${t('Licenses', '许可')}</a></nav>
  </div>
</footer>

<script>
(() => {
  const root = document.documentElement;
  const setLang = (l) => { root.dataset.lang = l; root.lang = l === 'zh' ? 'zh-CN' : 'en'; try { localStorage.setItem('om-lang', l); } catch {} };
  setLang(root.dataset.lang === 'zh' ? 'zh' : 'en');
  document.querySelectorAll('[data-set]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.set)));

  const nav = document.getElementById('nav');
  const onScroll = () => nav.classList.toggle('scrolled', scrollY > 8);
  addEventListener('scroll', onScroll, { passive: true }); onScroll();

  document.querySelectorAll('.copy').forEach((b) => b.addEventListener('click', async () => {
    const text = document.getElementById(b.dataset.copy).textContent;
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch {
      const ta = Object.assign(document.createElement('textarea'), { value: text }); ta.style.cssText = 'position:fixed;opacity:0';
      document.body.append(ta); ta.select(); ok = document.execCommand('copy'); ta.remove();
    }
    if (!ok) return;
    const html = b.innerHTML; b.classList.add('done'); b.textContent = root.dataset.lang === 'zh' ? '已复制' : 'Copied';
    setTimeout(() => { b.classList.remove('done'); b.innerHTML = html; }, 1600);
  }));

  const heroPlayer = document.querySelector('.showcase om-player');
  if (location.protocol === 'file:') setTimeout(() => { if (!(heroPlayer.duration > 0)) document.getElementById('filehint').hidden = false; }, 8000);

  // Cards mount their player when they come near the screen, rest on a poster frame, and play on hover.
  const fmt = (t) => { const m = Math.floor(t / 60), s = Math.round(t - m * 60); return m + ':' + String(s).padStart(2, '0'); };
  const hover = matchMedia('(hover: hover)').matches;
  const mount = (card) => {
    const p = document.createElement('om-player');
    p.setAttribute('muted', ''); p.setAttribute('loop', ''); p.setAttribute('disable-click-to-play', '');
    p.setAttribute('src', card.dataset.film);
    const rest = () => p.seek((p.duration || 0) * Number(card.dataset.poster || 0.4));
    p.addEventListener('ready', () => {
      if (p.duration) card.querySelector('[data-dur]').textContent = fmt(p.duration);
      rest(); setTimeout(() => card.classList.add('ready'), 120);
    }, { once: true });
    card.querySelector('.mount').append(p);
    if (hover) {
      card.addEventListener('pointerenter', () => { if (p.duration) { p.seek(0); p.play(); } });
      card.addEventListener('pointerleave', () => { if (p.duration) { p.pause(); rest(); } });
    }
  };
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { io.unobserve(e.target); mount(e.target); } }), { rootMargin: '300px 0px' });
  document.querySelectorAll('.card').forEach((c) => io.observe(c));
})();
</script>
</body>
</html>
`;
}

function fmt(s) { const m = Math.floor(s / 60); return `${m}:${String(Math.round(s - m * 60)).padStart(2, '0')}`; }

build();
