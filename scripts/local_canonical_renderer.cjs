'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

const IDS = new Set([
  'process-relations',
  'viewpoint-comparison',
  'evidence-source',
  'timeline-progression',
  'quote-thesis-artword',
]);
const COMMON = ['eyebrow', 'title', 'footer', 'avatar_image'];
const ACTION = {
  entry: {start: 0.00, end: 0.20},
  build: {start: 0.20, end: 0.72},
  stable: {start: 0.72, end: 0.90},
  exit: {start: 0.90, end: 1.00},
};
const LAYOUT = {
  safe_zone: {top: 96, bottom: 210, left: 64, right: 64},
  avatar_slot: {x: 796, y: 1460, width: 220, height: 220},
};

function actionSequence(compositionId) {
  const events = {
    'process-relations': [
      ['source_nodes_visible', .42], ['connections_drawing', .48],
      ['connections_complete', .66], ['center_visible', .76], ['result_visible', .86],
    ],
    'viewpoint-comparison': [
      ['left_view_visible', .26], ['right_view_visible', .41],
      ['dimension_visible', .54], ['conclusion_visible', .68],
    ],
    'evidence-source': [
      ['source_label_visible', .20], ['main_media_visible', .36],
      ['observations_visible', .65],
    ],
    'timeline-progression': [
      ['first_stage_visible', .28], ['all_stages_visible', .60],
      ['connection_complete', .66], ['conclusion_visible', .71],
    ],
    'quote-thesis-artword': [
      ['thesis_visible', .38], ['supports_visible', .62], ['takeaway_stable', .72],
    ],
  }[compositionId];
  return events.map(([event, at]) => ({event, at}));
}

function fail(message) {
  throw new Error(`Local canonical brief: ${message}`);
}

function exact(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join('|') !== [...keys].sort().join('|')) {
    fail(`${label} fields must be exactly ${[...keys].sort().join(', ')}`);
  }
}

function text(value, label, maximum) {
  if (typeof value !== 'string' || !value.trim() || /[\x00-\x1f\x7f]/u.test(value) ||
      [...value].length > maximum) {
    fail(`${label} must be a nonempty single line of at most ${maximum} characters`);
  }
  return value;
}

function image(value, label, allowEmpty = false) {
  if (allowEmpty && value === '') return value;
  if (typeof value !== 'string' || !/^data:image\/(?:png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$/u.test(value)) {
    fail(`${label} must be an inline base64 image`);
  }
  return value;
}

function media(value, kind, label) {
  const pattern = kind === 'video'
    ? /^data:video\/mp4;base64,[A-Za-z0-9+/]+={0,2}$/u
    : /^data:image\/(?:png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$/u;
  if (typeof value !== 'string' || !pattern.test(value)) {
    fail(`${label} must match data.media.kind`);
  }
  return value;
}

function stringList(value, label, minimum, maximum, itemMaximum) {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) {
    fail(`${label} must contain ${minimum}-${maximum} items`);
  }
  value.forEach((item, index) => text(item, `${label}[${index}]`, itemMaximum));
  return value;
}

function validateBrief(brief) {
  exact(brief, ['schema_version', 'canvas', 'composition_id', 'template_request', 'props'], 'root');
  if (brief.schema_version !== 1) fail('schema_version must be 1');
  exact(brief.canvas, ['width', 'height', 'fps', 'duration_in_frames'], 'canvas');
  if (brief.canvas.width !== 1080 || brief.canvas.height !== 1920 || brief.canvas.fps !== 24 ||
      !Number.isInteger(brief.canvas.duration_in_frames) ||
      brief.canvas.duration_in_frames < 48 || brief.canvas.duration_in_frames > 240) {
    fail('canvas must be native 1080x1920/24fps and 48-240 frames');
  }
  if (!IDS.has(brief.composition_id)) fail('unsupported composition_id');
  exact(brief.template_request,
    ['semantic_family', 'information_units', 'numeric_values', 'numeric_scale'], 'template_request');
  const request = brief.template_request;
  text(request.semantic_family, 'template_request.semantic_family', 40);
  if (!Number.isInteger(request.information_units) || request.information_units < 1) {
    fail('template_request.information_units must be positive');
  }
  if (!Array.isArray(request.numeric_values) || request.numeric_values.length !== 0 ||
      request.numeric_scale !== 'not_applicable') {
    fail('local canonical templates require empty numeric_values and not_applicable scale');
  }
  exact(brief.props, ['data'], 'props');
  const data = brief.props.data;
  const visible = [];
  const common = () => {
    visible.push(text(data.eyebrow, 'data.eyebrow', 18));
    visible.push(text(data.title, 'data.title', 16));
    visible.push(text(data.footer, 'data.footer', 28));
    image(data.avatar_image, 'data.avatar_image', true);
  };
  if (brief.composition_id === 'process-relations') {
    exact(data, [...COMMON, 'sources', 'center', 'result'], 'data');
    common();
    visible.push(...stringList(data.sources, 'data.sources', 2, 4, 9));
    visible.push(text(data.center, 'data.center', 8), text(data.result, 'data.result', 10));
    if (request.information_units !== data.sources.length) fail('information_units must match sources');
  } else if (brief.composition_id === 'viewpoint-comparison') {
    exact(data, [...COMMON, 'left', 'right', 'dimension', 'conclusion'], 'data');
    common();
    for (const side of ['left', 'right']) {
      exact(data[side], ['label', 'headline', 'points'], `data.${side}`);
      visible.push(text(data[side].label, `data.${side}.label`, 8));
      visible.push(text(data[side].headline, `data.${side}.headline`, 8));
      visible.push(...stringList(data[side].points, `data.${side}.points`, 2, 4, 10));
    }
    visible.push(text(data.dimension, 'data.dimension', 18));
    visible.push(text(data.conclusion, 'data.conclusion', 16));
    const total = data.left.points.length + data.right.points.length;
    if (request.information_units !== total) fail('information_units must match comparison points');
  } else if (brief.composition_id === 'evidence-source') {
    exact(data, [...COMMON, 'source_label', 'media', 'observations'], 'data');
    common();
    visible.push(text(data.source_label, 'data.source_label', 12));
    exact(data.media, ['kind', 'data_uri', 'caption'], 'data.media');
    if (!['image', 'video'].includes(data.media.kind)) fail('data.media.kind must be image or video');
    media(data.media.data_uri, data.media.kind, 'data.media.data_uri');
    visible.push(text(data.media.caption, 'data.media.caption', 20));
    visible.push(...stringList(data.observations, 'data.observations', 1, 3, 14));
    if (request.information_units !== data.observations.length) fail('information_units must match observations');
  } else if (brief.composition_id === 'timeline-progression') {
    exact(data, [...COMMON, 'stages', 'conclusion'], 'data');
    common();
    if (!Array.isArray(data.stages) || data.stages.length < 3 || data.stages.length > 6) {
      fail('data.stages must contain 3-6 items');
    }
    for (const [index, stage] of data.stages.entries()) {
      exact(stage, ['label', 'detail'], `data.stages[${index}]`);
      visible.push(text(stage.label, `data.stages[${index}].label`, 8));
      visible.push(text(stage.detail, `data.stages[${index}].detail`, 12));
    }
    visible.push(text(data.conclusion, 'data.conclusion', 16));
    if (request.information_units !== data.stages.length) fail('information_units must match stages');
  } else {
    exact(data, [...COMMON, 'thesis', 'supports'], 'data');
    common();
    visible.push(text(data.thesis, 'data.thesis', 16));
    visible.push(...stringList(data.supports, 'data.supports', 1, 2, 18));
    if (request.information_units !== data.supports.length) fail('information_units must match supports');
  }
  return {
    schema_version: 1,
    canvas: brief.canvas,
    composition_id: brief.composition_id,
    template_request: request,
    props: {data},
    layout_contract: LAYOUT,
    action_timeline: ACTION,
    action_sequence: actionSequence(brief.composition_id),
    visible_text: visible,
  };
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/gu, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function commonMarkup(data) {
  const avatar = data.avatar_image ?
    `<div id="avatar"><img src="${escapeHtml(data.avatar_image)}"></div>` : '';
  return `<header class="header entry"><div class="eyebrow">${escapeHtml(data.eyebrow)}</div>` +
    `<h1>${escapeHtml(data.title)}</h1></header>${avatar}` +
    `<footer class="footer result"><span></span><p>${escapeHtml(data.footer)}</p></footer>`;
}

function processMarkup(data) {
  const start = 480 - (data.sources.length - 1) * 100;
  const positions = data.sources.map((_, index) => start + index * 200);
  const sources = data.sources.map((value, index) =>
    `<div class="source card" style="top:${positions[index]}px"><i></i>${escapeHtml(value)}</div>`
  ).join('');
  const paths = data.sources.map((_, index) => {
    const y = positions[index] + 60;
    return `<path class="connector" d="M 329 ${y} C 475 ${y}, 500 480, 590 480"/>`;
  }).join('');
  return `<main class="process panel"><div class="micro-grid"></div>${sources}` +
    `<svg class="links" viewBox="0 0 952 1080">${paths}</svg>` +
    `<div class="center-node result"><b>${escapeHtml(data.center)}</b><span></span></div>` +
    `<div class="result-card result"><em></em><strong>${escapeHtml(data.result)}</strong></div></main>`;
}

function comparisonMarkup(data) {
  const side = (name, value) => `<section class="compare-side ${name} card">` +
    `<small>${escapeHtml(value.label)}</small><h2>${escapeHtml(value.headline)}</h2>` +
    value.points.map(point => `<p class="point">${escapeHtml(point)}</p>`).join('') + '</section>';
  return `<main class="comparison"><div class="dimension entry">${escapeHtml(data.dimension)}</div>` +
    `${side('left', data.left)}${side('right', data.right)}` +
    `<div class="conclusion result">${escapeHtml(data.conclusion)}</div></main>`;
}

function evidenceMarkup(data, duration) {
  const media = data.media.kind === 'video'
    ? `<video id="evidence-video" src="${escapeHtml(data.media.data_uri)}" data-start="0" data-duration="${duration}" muted playsinline></video>`
    : `<img src="${escapeHtml(data.media.data_uri)}">`;
  return `<main class="evidence"><div class="source-label entry">${escapeHtml(data.source_label)}</div>` +
    `<figure class="media card">${media}` +
    `<figcaption>${escapeHtml(data.media.caption)}</figcaption></figure>` +
    `<div class="observations">${data.observations.map(value =>
      `<div class="observation result"><i></i>${escapeHtml(value)}</div>`).join('')}</div></main>`;
}

function timelineMarkup(data) {
  const count = data.stages.length;
  const stages = data.stages.map((stage, index) => {
    const y = 150 + index * (700 / Math.max(1, count - 1));
    const right = index % 2 === 1;
    return `<div class="timeline-stage card ${right ? 'right' : 'left'}" style="top:${y}px">` +
      `<i></i><div><b>${escapeHtml(stage.label)}</b><p>${escapeHtml(stage.detail)}</p></div></div>`;
  }).join('');
  return `<main class="timeline"><div class="timeline-line connector"></div>${stages}` +
    `<div class="timeline-result result">${escapeHtml(data.conclusion)}</div></main>`;
}

function quoteMarkup(data) {
  return `<main class="quote"><div class="spark entry">✦</div>` +
    `<div class="thesis card"><span>${escapeHtml(data.thesis)}</span></div>` +
    `<div class="supports">${data.supports.map((value, index) =>
      `<p class="support result s${index}">${escapeHtml(value)}</p>`).join('')}</div>` +
    `<div class="scribble connector"></div></main>`;
}

function timelineScript(checked, duration) {
  const id = checked.composition_id;
  const lines = [
    `var D=${duration};var tl=gsap.timeline({paused:true});`,
    "tl.fromTo('#stage',{autoAlpha:0},{autoAlpha:1,duration:D*.16,ease:'power2.out'},0);",
    "tl.fromTo('.header',{autoAlpha:0,y:40},{autoAlpha:1,y:0,duration:D*.13,ease:'power3.out'},D*.08);",
  ];
  if (id === 'process-relations') {
    lines.push(
      "tl.fromTo('.source',{autoAlpha:0,x:-45},{autoAlpha:1,x:0,duration:D*.11,stagger:D*.035,ease:'power3.out'},D*.20);",
      "tl.to('.connector',{strokeDashoffset:0,duration:D*.14,stagger:D*.025,ease:'power2.inOut'},D*.44);",
      "tl.fromTo('.center-node',{autoAlpha:0,scale:.78},{autoAlpha:1,scale:1,duration:D*.10,ease:'back.out(1.4)'},D*.66);",
      "tl.fromTo('.result-card',{autoAlpha:0,x:45,rotation:-6},{autoAlpha:1,x:0,rotation:-2.5,duration:D*.10,ease:'back.out(1.25)'},D*.76);",
    );
  } else if (id === 'viewpoint-comparison') {
    lines.push(
      "tl.fromTo('.compare-side.left',{autoAlpha:0,x:-55,rotation:-2},{autoAlpha:1,x:0,rotation:0,duration:D*.13,ease:'power3.out'},D*.18);",
      "tl.fromTo('.compare-side.right',{autoAlpha:0,x:55,rotation:2},{autoAlpha:1,x:0,rotation:0,duration:D*.13,ease:'power3.out'},D*.33);",
      "tl.fromTo('.dimension',{autoAlpha:0,y:-20},{autoAlpha:1,y:0,duration:D*.09,ease:'power2.out'},D*.48);",
      "tl.fromTo('.conclusion',{autoAlpha:0,y:30,scale:.97},{autoAlpha:1,y:0,scale:1,duration:D*.10,ease:'back.out(1.2)'},D*.62);",
    );
  } else if (id === 'evidence-source') {
    lines.push(
      "tl.fromTo('.source-label',{autoAlpha:0,x:-30},{autoAlpha:1,x:0,duration:D*.09,ease:'power2.out'},D*.14);",
      "tl.fromTo('.media',{autoAlpha:0,y:45,scale:.97},{autoAlpha:1,y:0,scale:1,duration:D*.15,ease:'power3.out'},D*.23);",
      "tl.fromTo('.observation',{autoAlpha:0,x:35},{autoAlpha:1,x:0,duration:D*.10,stagger:D*.045,ease:'power3.out'},D*.52);",
    );
  } else if (id === 'timeline-progression') {
    lines.push(
      "tl.fromTo('.timeline-line',{autoAlpha:0,scaleY:0},{autoAlpha:1,scaleY:1,duration:D*.42,ease:'power2.inOut'},D*.20);",
      "tl.fromTo('.timeline-stage',{autoAlpha:0,y:28,scale:.97},{autoAlpha:1,y:0,scale:1,duration:D*.09,stagger:D*.065,ease:'back.out(1.2)'},D*.22);",
      "tl.fromTo('.timeline-result',{autoAlpha:0,y:24},{autoAlpha:1,y:0,duration:D*.09,ease:'power3.out'},D*.66);",
    );
  } else {
    lines.push(
      "tl.fromTo('.spark',{autoAlpha:0,scale:.3,rotation:-40},{autoAlpha:1,scale:1,rotation:0,duration:D*.12,ease:'back.out(1.6)'},D*.15);",
      "tl.fromTo('.thesis',{autoAlpha:0,y:45,rotation:-7,scale:.94},{autoAlpha:1,y:0,rotation:-2,scale:1,duration:D*.16,ease:'power3.out'},D*.22);",
      "tl.fromTo('.support',{autoAlpha:0,x:-35},{autoAlpha:1,x:0,duration:D*.10,stagger:D*.05,ease:'power3.out'},D*.48);",
      "tl.to('.scribble',{strokeDashoffset:0,scaleX:1,duration:D*.12,ease:'power2.out'},D*.58);",
    );
  }
  lines.push(
    "tl.fromTo('.footer',{autoAlpha:0,y:24},{autoAlpha:1,y:0,duration:D*.07,ease:'power2.out'},D*.82);",
    "tl.to('#stage',{autoAlpha:0,y:-12,duration:D*.10,ease:'power2.inOut'},D*.90);",
    "tl.to({}, {duration:.001},D-.001);",
    `window.__timelines['${id}']=tl;`,
  );
  return lines.join('');
}

function htmlFor(checked, gsapName) {
  const {data} = checked.props;
  const duration = checked.canvas.duration_in_frames / 24;
  const renderer = {
    'process-relations': processMarkup,
    'viewpoint-comparison': comparisonMarkup,
    'evidence-source': evidenceMarkup,
    'timeline-progression': timelineMarkup,
    'quote-thesis-artword': quoteMarkup,
  }[checked.composition_id];
  const body = checked.composition_id === 'evidence-source'
    ? evidenceMarkup(data, duration)
    : renderer(data);
  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">` +
    `<meta name="viewport" content="width=1080,height=1920"><title>${escapeHtml(data.title)}</title>` +
    `<script src="${escapeHtml(gsapName)}"></script><style>
@font-face{font-family:"PingFang SC";src:local("PingFang SC")}@font-face{font-family:"Hiragino Sans GB";src:local("Hiragino Sans GB")}@font-face{font-family:"Microsoft YaHei";src:local("Microsoft YaHei")}@font-face{font-family:"Songti SC";src:local("Songti SC")}
*{box-sizing:border-box}html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#071611}
body{font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#f7f3e8}
#stage{position:relative;width:1080px;height:1920px;overflow:hidden;background:radial-gradient(circle at 80% 18%,rgba(130,255,179,.2),transparent 28%),linear-gradient(145deg,#06140f,#0b2b21 58%,#06130f)}
#stage:before{content:"";position:absolute;inset:0;opacity:.26;background-image:linear-gradient(rgba(179,255,209,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(179,255,209,.08) 1px,transparent 1px);background-size:48px 48px}
.header{position:absolute;z-index:5;left:64px;right:64px;top:96px}.eyebrow{display:inline-block;padding:12px 24px;border:2px solid #baff65;border-radius:999px;color:#baff65;font-size:24px;font-weight:700;letter-spacing:3px}
h1{margin:34px 0 0;max-width:930px;font-size:76px;line-height:1.12;letter-spacing:-3px}
.panel{position:absolute;left:64px;top:390px;width:952px;height:1080px;border:1px solid rgba(186,255,101,.28);border-radius:42px;background:rgba(3,24,17,.62);box-shadow:0 35px 100px rgba(0,0,0,.32),inset 0 0 80px rgba(100,255,170,.04)}
.card{box-shadow:0 24px 55px rgba(0,0,0,.28)}
.footer{position:absolute;left:304px;right:64px;top:1600px;z-index:6}.footer span{display:block;height:4px;background:#baff65;margin-bottom:24px}.footer p{margin:0;font-family:"Songti SC",serif;font-size:34px;line-height:1.35}
#avatar{position:absolute;left:796px;top:1460px;width:220px;height:220px;border-radius:50%;border:7px solid #f7f3e8;overflow:hidden;z-index:9;box-shadow:0 25px 45px rgba(0,0,0,.36)}#avatar img{width:100%;height:100%;object-fit:cover;object-position:center 38%}
.micro-grid{position:absolute;inset:0;border-radius:42px;background-image:radial-gradient(rgba(186,255,101,.18) 1.4px,transparent 1.4px);background-size:24px 24px;opacity:.28}
.source{position:absolute;left:54px;width:275px;height:120px;padding:37px 24px 0 55px;background:#f7f3e8;color:#10271e;font-size:31px;font-weight:700;border-radius:18px;z-index:2}.source i{position:absolute;left:22px;top:44px;width:16px;height:16px;border-radius:50%;background:#baff65;box-shadow:0 0 0 10px rgba(186,255,101,.18)}
.links{position:absolute;inset:0;width:100%;height:100%;overflow:visible;z-index:1}.connector{fill:none;stroke:#baff65;stroke-width:7;stroke-linecap:round;stroke-dasharray:1200;stroke-dashoffset:1200}
.center-node{position:absolute;left:590px;top:355px;width:250px;height:250px;border-radius:50%;border:5px solid #baff65;background:#09291e;display:flex;align-items:center;justify-content:center;font-size:33px;box-shadow:0 0 0 25px rgba(186,255,101,.08),0 0 70px rgba(186,255,101,.18);z-index:3}.center-node span{position:absolute;inset:25px;border:1px solid rgba(186,255,101,.35);border-radius:50%}
.result-card{position:absolute;right:55px;top:760px;width:340px;height:150px;background:#ffd968;color:#15231d;transform:rotate(-2.5deg);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:34px;z-index:4}.result-card em{position:absolute;left:-28px;top:62px;width:35px;height:35px;background:#ffd968;transform:rotate(45deg)}
.comparison{position:absolute;left:64px;top:410px;width:952px;height:1050px}.dimension{font-size:28px;color:#17251e;background:#baff65;padding:14px 24px;display:inline-block;border-radius:999px}.compare-side{position:absolute;top:105px;width:450px;height:720px;border-radius:32px;padding:42px}.compare-side.left{left:0;background:linear-gradient(160deg,#ff665d,#c72e42)}.compare-side.right{right:0;background:linear-gradient(160deg,#4868ff,#1736a8)}.compare-side small{font-size:23px;letter-spacing:3px}.compare-side h2{font-size:58px;margin:30px 0 48px}.point{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);padding:22px 24px;border-radius:18px;font-size:30px}.conclusion{position:absolute;left:90px;right:90px;bottom:35px;text-align:center;padding:30px;background:#f7f3e8;color:#14241d;border-radius:22px;font-family:"Songti SC",serif;font-size:39px}
.evidence{position:absolute;left:64px;top:410px;width:952px;height:1100px}.source-label{display:inline-block;padding:12px 22px;border:2px solid #ffd968;border-radius:999px;color:#ffd968;font-size:26px}.media{position:absolute;left:0;right:0;top:90px;height:650px;margin:0;border-radius:30px;overflow:hidden;background:#132d27;border:2px solid rgba(255,255,255,.15)}.media img,.media video{width:100%;height:100%;object-fit:cover}.media figcaption{position:absolute;left:28px;bottom:28px;padding:16px 22px;background:rgba(4,18,14,.82);border-left:6px solid #ffd968;border-radius:10px;font-size:30px}.observations{position:absolute;left:0;right:0;top:790px;display:grid;gap:18px}.observation{padding:25px 30px;background:rgba(247,243,232,.96);color:#15261e;border-radius:18px;font-size:31px;font-weight:700}.observation i{display:inline-block;width:15px;height:15px;background:#ff6a64;border-radius:50%;margin-right:20px}
.timeline{position:absolute;left:64px;top:390px;width:952px;height:1110px}.timeline-line{position:absolute;left:468px;top:95px;width:12px;height:820px;border-radius:8px;background:#7de0d0;transform-origin:top}.timeline-stage{position:absolute;width:395px;height:130px;border-radius:22px;padding:26px 28px;background:rgba(247,243,232,.96);color:#10231b;display:flex;gap:22px}.timeline-stage.left{left:0}.timeline-stage.right{right:0}.timeline-stage i{width:24px;height:24px;flex:none;border-radius:50%;background:#7657ff;box-shadow:0 0 0 9px rgba(118,87,255,.15)}.timeline-stage b{font-size:31px}.timeline-stage p{margin:9px 0 0;font-size:24px;color:#53645d}.timeline-result{position:absolute;left:190px;right:190px;bottom:0;text-align:center;padding:26px;border:2px solid #7de0d0;border-radius:999px;font-size:32px}
.quote{position:absolute;left:64px;top:420px;width:952px;height:1070px}.quote:before{content:"";position:absolute;inset:0;border-radius:44px;background:linear-gradient(150deg,#2d205c,#5b3fd5 65%,#302278);box-shadow:0 35px 100px rgba(0,0,0,.35)}.spark{position:absolute;right:65px;top:50px;color:#ffd968;font-size:100px}.thesis{position:absolute;left:55px;right:55px;top:210px;height:390px;border:3px solid #f7f3e8;border-radius:28px;display:flex;align-items:center;justify-content:center;padding:45px;transform:rotate(-2deg);background:rgba(255,255,255,.06)}.thesis span{font-family:"Songti SC",serif;font-weight:800;font-size:70px;line-height:1.16;text-align:center;text-shadow:9px 9px 0 #ff5b66}.supports{position:absolute;left:90px;right:90px;top:680px}.support{margin:20px 0;padding:20px 28px;background:#f7f3e8;color:#1d1834;font-size:31px;font-weight:700;border-radius:12px}.support.s0{transform:rotate(1.6deg)}.support.s1{transform:translateX(45px) rotate(-1.4deg)}.scribble{position:absolute;left:130px;bottom:80px;width:650px;height:10px;border-radius:10px;background:#ffd968;transform:rotate(-3deg)}
</style></head><body><div id="stage" data-composition-id="${checked.composition_id}" data-duration="${duration}" data-width="1080" data-height="1920">${commonMarkup(data)}${body}</div>
<script>window.__timelines=window.__timelines||{};(function(){${timelineScript(checked, duration)}})();</script></body></html>`;
}

function sha(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function safeRegistry(skillRoot, relative, expectedSha, compositionId, rendererVersion) {
  if (typeof relative !== 'string' || path.isAbsolute(relative) || relative.split('/').includes('..')) {
    fail('registry path must stay inside the Skill');
  }
  const root = fs.realpathSync(skillRoot);
  const registry = fs.realpathSync(path.join(root, relative));
  if (registry !== root && !registry.startsWith(root + path.sep)) {
    fail('registry path escapes the Skill');
  }
  const bytes = fs.readFileSync(registry);
  if (sha(bytes) !== expectedSha) fail('template registry changed; rebind');
  const records = JSON.parse(bytes).templates.filter(item =>
    item.template_origin === 'verified_local_canonical' && item.render_contract &&
    item.render_contract.composition_id === compositionId);
  if (records.length !== 1) fail('composition is not uniquely registered as local canonical');
  const record = records[0];
  if (record.upstream.project !== 'hd-talking-head-local-canonical' ||
      record.upstream.repository !== '.' || record.render_contract.engine !== 'HyperFrames' ||
      record.source_entrypoint !== 'scripts/local_canonical_renderer.cjs' ||
      record.source_sha256 !== sha(fs.readFileSync(path.join(root, record.source_entrypoint)))) {
    fail('registered local canonical source identity changed');
  }
  for (const source of record.source_files) {
    if (sha(fs.readFileSync(path.join(root, source.path))) !== source.sha256) {
      fail(`registered source changed: ${source.path}`);
    }
  }
  if (!rendererVersion) fail('renderer version is required');
}

function options(args) {
  const basic = ['--brief', '--output', '--runtime-root', '--browser'];
  const formal = [...basic, '--skill-root', '--registry-path', '--registry-sha256', '--renderer-version'];
  const names = args.length === basic.length * 2 ? basic : formal;
  if (args.length !== names.length * 2 || names.some((name, index) => args[index * 2] !== name)) {
    fail('use the approved local canonical adapter argument order');
  }
  return Object.fromEntries(names.map((name, index) => [name.slice(2), args[index * 2 + 1]]));
}

function render(args) {
  const opt = options(args);
  const checked = validateBrief(JSON.parse(fs.readFileSync(opt.brief, 'utf8')));
  const runtime = fs.realpathSync(opt['runtime-root']);
  const browser = fs.realpathSync(opt.browser);
  fs.accessSync(browser, fs.constants.X_OK);
  const cli = path.join(runtime, 'packages/cli/src/cli.ts');
  const tsx = path.join(runtime, 'node_modules/tsx/dist/cli.mjs');
  const gsap = path.join(runtime, 'skills/talking-head-recut/assets/vendor/gsap.min.js');
  for (const item of [cli, tsx, gsap]) fs.accessSync(item, fs.constants.R_OK);
  const packageJson = JSON.parse(fs.readFileSync(path.join(runtime, 'packages/cli/package.json')));
  if (opt['renderer-version'] && packageJson.version !== opt['renderer-version']) {
    fail('HyperFrames renderer version drift');
  }
  if (opt['registry-path']) {
    safeRegistry(
      opt['skill-root'], opt['registry-path'], opt['registry-sha256'],
      checked.composition_id, opt['renderer-version'],
    );
  }
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'hd-local-canonical-'));
  try {
    const gsapName = 'gsap.min.js';
    fs.copyFileSync(gsap, path.join(temp, gsapName));
    const pageBrief = JSON.parse(JSON.stringify(checked));
    if (checked.composition_id === 'evidence-source' &&
        checked.props.data.media.kind === 'video') {
      const relativeVideo = 'evidence-media.mp4';
      const encoded = checked.props.data.media.data_uri.split(',', 2)[1];
      fs.writeFileSync(path.join(temp, relativeVideo), Buffer.from(encoded, 'base64'), {flag: 'wx'});
      pageBrief.props.data.media.data_uri = relativeVideo;
    }
    const html = htmlFor(pageBrief, gsapName);
    const name = `${checked.composition_id}.html`;
    fs.writeFileSync(path.join(temp, name), html, {flag: 'wx'});
    const rendered = path.join(temp, 'render.mp4');
    const result = spawnSync(process.execPath, [
      tsx, cli, 'render', temp, '--composition', name, '--output', rendered,
      '--fps', '24', '--quality', 'high', '--workers', '1', '--strict',
      '--low-memory-mode', '--no-browser-gpu', '--no-best-effort',
    ], {
      cwd: '/', encoding: 'utf8', maxBuffer: 4 * 1024 * 1024,
      env: {...process.env, HYPERFRAMES_BROWSER_PATH: browser,
        HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1'},
    });
    if (result.error) throw result.error;
    if (result.status !== 0) fail(`HyperFrames render failed (${result.status}): ${(result.stderr || result.stdout).slice(-4000)}`);
    if (!fs.existsSync(rendered) || fs.statSync(rendered).size === 0) fail('renderer produced no MP4');
    fs.copyFileSync(rendered, opt.output);
    process.stdout.write(JSON.stringify({
      composition_id: checked.composition_id,
      frames: checked.canvas.duration_in_frames,
      fps: 24,
      workers: 1,
      muted: true,
      action_timeline: ACTION,
    }));
  } finally {
    fs.rmSync(temp, {recursive: true, force: true});
  }
}

module.exports = {validateBrief, htmlFor, actionSequence, IDS, ACTION, LAYOUT};
try {
  if (process.argv.length === 3 && process.argv[2] === '--validate') {
    process.stdout.write(JSON.stringify(validateBrief(JSON.parse(fs.readFileSync(0, 'utf8')))));
  } else if (require.main === module || process.argv[1] === '-') {
    render(process.argv.slice(2));
  }
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
