'use strict';

const fs = require('node:fs');

const ROOT_KEYS = ['schema_version', 'canvas', 'motion', 'title', 'source_ids', 'hub_id'];
const PLAN_KEYS = ['version', 'content_item_id', 'source_text', 'family', 'meaningful_change', 'subjects', 'actions', 'duration_frames', 'read_window', 'exit_window'];
const ACTION_KEYS = ['id', 'operation', 'subject_ids', 'start_frame', 'end_frame', 'depends_on'];
const OPS = ['reveal_sources', 'draw_connections', 'reveal_hub'];

function fail(message) { throw new Error(`Relation motion brief: ${message}`); }
function exact(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join('|') !== [...keys].sort().join('|')) fail(`${label} fields are invalid`);
  return value;
}
function text(value, label, max = 200) {
  if (typeof value !== 'string' || !value.trim() || Array.from(value).length > max || /[\x00-\x1f\x7f]/u.test(value)) fail(`${label} must be a nonempty single-line string`);
  return value;
}
function clamp(value) { return Math.max(0, Math.min(1, value)); }
function phaseProgress(frame, action) { return clamp((frame - action.start_frame) / (action.end_frame - action.start_frame)); }
function integer(value, label, min = 0) {
  if (!Number.isInteger(value) || value < min) fail(`${label} must be an integer >= ${min}`);
  return value;
}
function ids(value, label, min = 1) {
  if (!Array.isArray(value) || value.length < min || value.some(item => typeof item !== 'string' || !item.trim()) || new Set(value).size !== value.length) fail(`${label} must contain unique ids`);
  return value;
}
function window(value, duration, label) {
  exact(value, ['start_frame', 'end_frame'], label);
  integer(value.start_frame, `${label}.start_frame`); integer(value.end_frame, `${label}.end_frame`, 1);
  if (value.start_frame >= value.end_frame || value.end_frame > duration) fail(`${label} is outside duration`);
}

function validateBrief(brief) {
  exact(brief, ROOT_KEYS, 'root');
  if (brief.schema_version !== 1) fail('schema_version must be 1');
  exact(brief.canvas, ['width', 'height', 'fps', 'duration_in_frames'], 'canvas');
  if (brief.canvas.width !== 1080 || brief.canvas.height !== 1920 || brief.canvas.fps !== 24) fail('canvas must be 1080x1920/24fps');
  const duration = integer(brief.canvas.duration_in_frames, 'canvas.duration_in_frames', 48);
  if (duration > 240) fail('canvas.duration_in_frames must be <= 240');
  text(brief.title, 'title', 12);
  const sourceIds = ids(brief.source_ids, 'source_ids', 2);
  if (sourceIds.length > 4) fail('source_ids must contain 2-4 ids');
  text(brief.hub_id, 'hub_id', 80);
  if (sourceIds.includes(brief.hub_id)) fail('hub_id must differ from source_ids');
  const motion = exact(brief.motion, PLAN_KEYS, 'motion');
  if (motion.version !== 1 || motion.family !== 'relation') fail('motion must be relation version 1');
  text(motion.content_item_id, 'motion.content_item_id'); text(motion.source_text, 'motion.source_text'); text(motion.meaningful_change, 'motion.meaningful_change');
  if (motion.duration_frames !== duration) fail('motion.duration_frames must match canvas');
  if (!Array.isArray(motion.subjects) || motion.subjects.length < 1) fail('motion.subjects must be nonempty');
  const subjects = motion.subjects;
  const subjectIds = subjects.map(s => { exact(s, ['id', 'label', 'initial_state', 'final_state', 'preserve'], 'subject'); text(s.id, 'subject.id', 80); text(s.label, 'subject.label', s.id === brief.hub_id ? 4 : 8); text(s.initial_state, 'subject.initial_state'); text(s.final_state, 'subject.final_state'); if (s.preserve !== false) fail('relation subjects cannot be preserved'); return s.id; });
  if (new Set(subjectIds).size !== subjectIds.length) fail('motion.subjects must contain unique ids');
  if (new Set(subjectIds).size !== subjectIds.length || new Set(subjectIds).size !== sourceIds.length + 1 || !sourceIds.every(id => subjectIds.includes(id)) || !subjectIds.includes(brief.hub_id)) fail('subjects must be exactly source_ids plus hub_id');
  if (!Array.isArray(motion.actions) || motion.actions.length !== 3) fail('relation requires three actions');
  let previousEnd = 0;
  const actionIds = new Set();
  motion.actions.forEach((action, index) => {
    exact(action, ACTION_KEYS, 'action'); text(action.id, 'action.id', 80); if (actionIds.has(action.id)) fail('action ids must be unique'); actionIds.add(action.id);
    if (action.operation !== OPS[index]) fail('relation action order is invalid');
    ids(action.subject_ids, 'action.subject_ids'); ids(action.depends_on, 'action.depends_on', 0);
    integer(action.start_frame, 'action.start_frame'); integer(action.end_frame, 'action.end_frame', 1);
    if (action.start_frame >= action.end_frame || action.end_frame > duration || action.start_frame < previousEnd) fail('actions must be ordered, local half-open windows');
    if ((!index && action.depends_on.length !== 0) || (index && (action.depends_on.length !== 1 || action.depends_on[0] !== motion.actions[index - 1].id))) fail('actions must depend on preceding phase');
    if (index === 0 && (action.subject_ids.length !== sourceIds.length || !sourceIds.every(id => action.subject_ids.includes(id)))) fail('reveal_sources must target exactly source_ids');
    if (index === 1 && (action.subject_ids.length !== sourceIds.length + 1 || !sourceIds.every(id => action.subject_ids.includes(id)) || !action.subject_ids.includes(brief.hub_id))) fail('draw_connections must target sources and hub');
    if (index === 2 && (action.subject_ids.length !== 1 || action.subject_ids[0] !== brief.hub_id)) fail('reveal_hub must target hub only');
    previousEnd = action.end_frame;
  });
  exact(motion.read_window, ['start_frame', 'end_frame', 'minimum_frames'], 'read_window'); window({start_frame: motion.read_window.start_frame, end_frame: motion.read_window.end_frame}, duration, 'read_window'); integer(motion.read_window.minimum_frames, 'read_window.minimum_frames', 1);
  if (motion.read_window.start_frame < previousEnd || motion.read_window.end_frame - motion.read_window.start_frame < motion.read_window.minimum_frames) fail('read window is too short or overlaps actions');
  window(motion.exit_window, duration, 'exit_window');
  if (motion.exit_window.end_frame - motion.exit_window.start_frame < 2) fail('external exit needs at least two encoded frames');
  if (motion.exit_window.start_frame !== motion.read_window.end_frame || motion.exit_window.end_frame !== duration) fail('exit must follow reading to shot boundary');
  return {schema_version: 1, canvas: brief.canvas, title: brief.title, source_ids: sourceIds, hub_id: brief.hub_id, motion, layout: layout(sourceIds.length)};
}
function layout(count) {
  const hub = {left: 700, top: 850, width: 280, height: 280};
  const centerY = hub.top + hub.height / 2;
  // Fewer sources form a compact group; four sources use the full portrait body.
  const span = count === 2 ? 500 : count === 3 ? 740 : 920;
  const ys = Array.from({length: count}, (_, i) => centerY - span / 2 + i * (span / (count - 1)));
  const sources = ys.map(y => ({left: 80, top: y - 110, width: 380, height: 220, right: 460, centerY: y}));
  return {sources, hub, paths: sources.map(source => ({start: [source.right, source.centerY], end: [hub.left, centerY]}))};
}

function frameState(checked, frame) {
  const duration = checked.canvas.duration_in_frames; integer(frame, 'frame'); if (frame > duration) fail('frame is outside shot');
  if (frame === duration) return {frame, source_progress: 1, connector_progress: 1, hub_progress: 1, artifact_alpha: 1, compositor_alpha: 0};
  const [sources, connections, hub] = checked.motion.actions;
  return {frame, source_progress: phaseProgress(frame, sources), connector_progress: phaseProgress(frame, connections), hub_progress: phaseProgress(frame, hub), artifact_alpha: 1, compositor_alpha: 1 - phaseProgress(frame, {...checked.motion.exit_window, end_frame: duration - 1})};
}
function esc(value) { return String(value).replace(/[&<>"']/gu, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function safeScriptJson(value) { return JSON.stringify(value).replace(/</gu, '\\u003c').replace(/\u2028/gu, '\\u2028').replace(/\u2029/gu, '\\u2029'); }
function htmlFor(checked) {
  const labels = Object.fromEntries(checked.motion.subjects.map(s => [s.id, s.label]));
  const titleSize = Math.min(112, Math.floor(920 / Array.from(checked.title).length));
  const posterStyle = `<style id="relation-poster-style">
    #stage{background-color:#f4efdf;background-image:radial-gradient(#173b2c12 1px,transparent 1px);background-size:24px 24px;color:#173b2c;font-family:"PingFang SC","Noto Sans CJK SC",sans-serif}
    #stage h1{top:128px;font-family:"Songti SC","Noto Serif CJK SC",serif;font-size:${titleSize}px;font-weight:900;padding-bottom:36px;border-bottom:5px solid #173b2c}
    #stage .source{background:#fffdf4;border:3px solid #173b2c;border-radius:6px 16px 8px 12px;box-shadow:9px 10px 0 #173b2c20;font-weight:600}
    #stage .source::before{content:"";position:absolute;left:24px;top:24px;width:34px;height:7px;background:#173b2c}
    #stage .connector{stroke:#173b2c;stroke-width:6;stroke-linecap:round}
    #stage .hub{background:#d8f46b;color:#173b2c;border:4px solid #173b2c;border-radius:48% 52% 47% 53%;box-shadow:10px 12px 0 #173b2c20;font-size:44px;font-weight:700}
  </style>`;
  const sources = posterStyle + checked.source_ids.map((id, i) => {
    const p = checked.layout.sources[i];
    const fontSize = Array.from(labels[id]).length <= 6 ? 52 : 36;
    return `<div class="source" data-id="${esc(id)}" style="left:${p.left}px;top:${p.top}px;width:${p.width}px;height:${p.height}px;font-size:${fontSize}px">${esc(labels[id])}</div>`;
  }).join('');
  const paths = checked.layout.paths.map(p => `<path class="connector" pathLength="1" d="M ${p.start[0]} ${p.start[1]} C 560 ${p.start[1]}, 620 ${p.end[1]}, ${p.end[0]} ${p.end[1]}"/>`).join('');
  const motionJson = safeScriptJson(checked.motion);
  // The H.264 artifact is opaque. Only the final compositor may reveal A-roll;
  // fading this DOM would bake the dark HTML background into the video.
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${esc(checked.title)}</title><style>html,body{margin:0;background:#071611;color:#f7f3e8}#stage{position:relative;width:1080px;height:1920px;overflow:hidden;font:36px sans-serif;background:linear-gradient(145deg,#06140f,#0b2b21)}h1{position:absolute;left:64px;top:80px;width:952px;margin:0;font-size:64px;line-height:1.5;white-space:nowrap}.source{position:absolute;box-sizing:border-box;display:flex;align-items:center;justify-content:center;opacity:0;padding:20px;background:#f7f3e8;color:#10271e;border-radius:18px;line-height:1.2;white-space:nowrap}.links{position:absolute;inset:0;width:1080px;height:1920px;z-index:1}.connector{fill:none;stroke:#baff65;stroke-width:8;stroke-dasharray:1;stroke-dashoffset:1}.source,.hub{z-index:2}.hub{position:absolute;box-sizing:border-box;display:flex;align-items:center;justify-content:center;opacity:0;left:${checked.layout.hub.left}px;top:${checked.layout.hub.top}px;width:${checked.layout.hub.width}px;height:${checked.layout.hub.height}px;padding:30px;text-align:center;line-height:1.2;border:5px solid #baff65;border-radius:50%;white-space:nowrap}</style><div id="stage"><h1>${esc(checked.title)}</h1><main>${sources}<svg class="links" viewBox="0 0 1080 1920">${paths}</svg><div class="hub" id="hub">${esc(labels[checked.hub_id])}</div></main></div><script>const MOTION=${motionJson};function clamp(v){return Math.max(0,Math.min(1,v))}function phaseProgress(f,a){return clamp((f-a.start_frame)/(a.end_frame-a.start_frame))}function seekFrame(frame){if(!Number.isInteger(frame)||frame<0||frame>MOTION.duration_frames)throw new Error('frame outside shot');const s=MOTION.actions[0],c=MOTION.actions[1],h=MOTION.actions[2],a=1-phaseProgress(frame,{...MOTION.exit_window,end_frame:MOTION.duration_frames-1}),end=frame===MOTION.duration_frames;document.querySelectorAll('.source').forEach(e=>e.style.opacity=phaseProgress(frame,s));document.querySelectorAll('.connector').forEach(e=>e.style.strokeDashoffset=String(1-phaseProgress(frame,c)));document.querySelector('#hub').style.opacity=phaseProgress(frame,h);document.querySelector('#stage').style.opacity=1;return {frame,source_progress:phaseProgress(frame,s),connector_progress:phaseProgress(frame,c),hub_progress:phaseProgress(frame,h),artifact_alpha:1,compositor_alpha:end?0:a}}seekFrame(0);</script></html>`;
}

if (require.main === module) { try { const mode = process.argv[2]; const brief = JSON.parse(fs.readFileSync(0, 'utf8')); const checked = validateBrief(brief); if (mode === '--validate') process.stdout.write(JSON.stringify(checked)); else if (mode === '--html') process.stdout.write(htmlFor(checked)); else if (mode === '--state') process.stdout.write(JSON.stringify(frameState(checked, Number(process.argv[3])))); else fail('use --validate, --html or --state'); } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; } }
module.exports = {validateBrief, htmlFor, frameState, layout, phaseProgress};
