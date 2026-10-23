'use strict';

// Deterministic frame renderer, not an editor or approval gate. The formal
// adapter must bind this brief to approved content before production use.
const fs = require('node:fs');
const PATTERNS = {
  replacement: ['establish', 'replace', 'compare'],
  threshold: ['establish', 'cross_threshold', 'raise_threshold'],
  delay: ['establish', 'wait', 'realize'],
  hierarchy: ['establish', 'reveal_layers', 'resolve'],
  feedback: ['establish', 'produce', 'feedback_return'],
};
const PLAN_KEYS = ['version', 'content_item_id', 'source_text', 'family', 'meaningful_change', 'subjects', 'actions', 'duration_frames', 'read_window', 'exit_window'];
function fail(message) { throw new Error(`Semantic scene: ${message}`); }
function exact(value, keys, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join('|') !== [...keys].sort().join('|')) fail(`${name} fields invalid`);
}
function text(value, name, max = 200) {
  if (typeof value !== 'string' || !value.trim() || Array.from(value).length > max ||
      /[\x00-\x1f\x7f]/u.test(value) || Array.from(value).some(c => {
        const point = c.codePointAt(0);
        return (point >= 0xd800 && point <= 0xdfff) || point === 0xfffe || point === 0xffff;
      })) fail(`${name} is invalid or exceeds ${max} characters`);
}
function integer(value, name, min = 0) {
  if (!Number.isSafeInteger(value) || value < min) fail(`${name} must be an integer >= ${min}`);
}
function ids(value, name, min = 1, max = 4) {
  if (!Array.isArray(value) || value.length < min || value.length > max) fail(`${name} capacity invalid`);
  value.forEach(id => text(id, name, 80));
  if (new Set(value).size !== value.length) fail(`${name} must be unique`);
}
function sameIds(actual, expected, name) {
  ids(actual, name);
  if (actual.length !== expected.length || !expected.every(id => actual.includes(id))) fail(`${name} does not match roles`);
}
function windowCheck(value, duration, name, keys = ['start_frame', 'end_frame']) {
  exact(value, keys, name);
  integer(value.start_frame, `${name}.start_frame`); integer(value.end_frame, `${name}.end_frame`, 1);
  if (value.start_frame >= value.end_frame || value.end_frame > duration) fail(`${name} outside shot`);
}

function roleContract(family, roles) {
  switch (family) {
    case 'replacement': {
      exact(roles, ['change_id', 'context_ids'], 'roles'); ids(roles.context_ids, 'context_ids', 1, 3);
      const all = [roles.change_id, ...roles.context_ids];
      return {all, preserved: roles.context_ids, targets: [all, [roles.change_id], all]};
    }
    case 'threshold': {
      exact(roles, ['capability_id', 'threshold_id'], 'roles');
      const all = [roles.capability_id, roles.threshold_id];
      return {all, preserved: [], targets: [all, [roles.capability_id], [roles.threshold_id]]};
    }
    case 'delay': {
      exact(roles, ['trigger_id', 'outcome_id'], 'roles');
      const all = [roles.trigger_id, roles.outcome_id];
      return {all, preserved: [roles.trigger_id], targets: [all, all, [roles.outcome_id]]};
    }
    case 'hierarchy': {
      exact(roles, ['layer_ids'], 'roles'); ids(roles.layer_ids, 'layer_ids', 2, 4);
      return {all: roles.layer_ids, preserved: [], targets: [[roles.layer_ids[0]], roles.layer_ids.slice(1), roles.layer_ids]};
    }
    case 'feedback': {
      exact(roles, ['source_id', 'result_id'], 'roles');
      const all = [roles.source_id, roles.result_id];
      return {all, preserved: [], targets: [[roles.source_id], [roles.result_id], [roles.source_id]]};
    }
    default: fail('unsupported family');
  }
}

function validateBrief(brief) {
  exact(brief, ['schema_version', 'canvas', 'title', 'motion', 'roles'], 'brief');
  if (brief.schema_version !== 1) fail('schema_version must be 1');
  text(brief.title, 'title', 12);
  exact(brief.canvas, ['width', 'height', 'fps', 'duration_in_frames'], 'canvas');
  const duration = brief.canvas.duration_in_frames;
  integer(duration, 'duration', 48);
  if (duration > 240 || brief.canvas.width !== 1080 || brief.canvas.height !== 1920 || brief.canvas.fps !== 24) fail('native canvas must be 1080x1920/24fps, 48-240 frames');
  const motion = brief.motion;
  exact(motion, PLAN_KEYS, 'motion');
  if (motion.version !== 1 || motion.duration_frames !== duration) fail('motion version/duration mismatch');
  text(motion.family, 'family', 20);
  text(motion.content_item_id, 'content_item_id'); text(motion.source_text, 'source_text', 10000);
  text(motion.meaningful_change, 'meaningful_change', 1000);
  const contract = roleContract(motion.family, brief.roles);
  ids(contract.all, 'role ids');
  if (!Array.isArray(motion.subjects) || motion.subjects.length !== contract.all.length) fail('subjects must equal roles');
  const subjectIds = motion.subjects.map(subject => {
    exact(subject, ['id', 'label', 'initial_state', 'final_state', 'preserve'], 'subject');
    text(subject.id, 'subject.id', 80); text(subject.label, 'subject.label', motion.family === 'threshold' ? 8 : 12);
    text(subject.initial_state, 'initial_state', 16); text(subject.final_state, 'final_state', 16);
    if (typeof subject.preserve !== 'boolean' || subject.preserve !== contract.preserved.includes(subject.id)) fail('preserve differs from role contract');
    if (subject.preserve && subject.initial_state !== subject.final_state) fail('preserved context changes state');
    if (!subject.preserve && subject.initial_state === subject.final_state) fail('changing subject needs different states');
    return subject.id;
  });
  sameIds(subjectIds, contract.all, 'subjects');
  if (!Array.isArray(motion.actions) || motion.actions.length !== 3) fail('three actions required');
  const actionIds = new Set();
  motion.actions.forEach((action, i) => {
    exact(action, ['id', 'operation', 'subject_ids', 'start_frame', 'end_frame', 'depends_on'], 'action');
    text(action.id, 'action.id', 80);
    if (actionIds.has(action.id)) fail('duplicate action id');
    actionIds.add(action.id);
    if (action.operation !== PATTERNS[motion.family][i]) fail('phase order mismatch');
    sameIds(action.subject_ids, contract.targets[i], 'action targets');
    ids(action.depends_on, 'depends_on', 0, 1);
    if (i === 0 ? action.depends_on.length !== 0 : action.depends_on.length !== 1 || action.depends_on[0] !== motion.actions[i - 1].id) fail('phase must depend on preceding action');
    windowCheck({start_frame: action.start_frame, end_frame: action.end_frame}, duration, 'action');
    if (i && action.start_frame < motion.actions[i - 1].end_frame) fail('actions overlap');
  });
  windowCheck(motion.read_window, duration, 'read_window', ['start_frame', 'end_frame', 'minimum_frames']);
  integer(motion.read_window.minimum_frames, 'minimum_frames', 1);
  if (motion.read_window.start_frame < motion.actions[2].end_frame || motion.read_window.end_frame - motion.read_window.start_frame < motion.read_window.minimum_frames) fail('insufficient reading window');
  windowCheck(motion.exit_window, duration, 'exit_window');
  if (motion.exit_window.start_frame !== motion.read_window.end_frame || motion.exit_window.end_frame !== duration || duration - motion.exit_window.start_frame < 2) fail('invalid external exit window');
  return JSON.parse(JSON.stringify(brief));
}

function clamp(value) { return Math.max(0, Math.min(1, value)); }
function phase(frame, action) { return clamp((frame - action.start_frame) / (action.end_frame - action.start_frame)); }

function frameState(brief, frame) {
  integer(frame, 'frame');
  if (frame > brief.canvas.duration_in_frames) fail('frame outside shot');
  const m = brief.motion, r = brief.roles;
  const [a, b, c] = m.actions.map(action => phase(frame, action));
  const subjects = new Map(m.subjects.map(subject => [subject.id, subject]));
  const result = {frame, family: m.family, artifact_alpha: 1,
    compositor_alpha: 1 - clamp((frame - m.exit_window.start_frame) / (m.duration_frames - 1 - m.exit_window.start_frame)),
    nodes: [], links: [], bars: [], rules: [], clock: null};
  function node(id, x, y, width, height, opacity, stateMix) {
    result.nodes.push({...subjects.get(id), x, y, width, height, opacity, state_mix: stateMix});
  }
  function link(id, d, progress) { result.links.push({id, d, progress}); }
  switch (m.family) {
    case 'replacement': {
      node(r.change_id, 100 + (b < .5 ? -48 * b : 48 * (1 - b)), 440,
        880, 300, a * Math.abs(1 - 2 * b), b);
      result.nodes[0].object_transition = true;
      r.context_ids.forEach((id, i) => node(id, 100, 810 + i * 210, 880, 190, a, 0));
      const [object, context] = result.nodes;
      link('comparison', `M ${object.x} ${object.y + object.height / 2} H 76 V ${context.y + context.height / 2} H ${context.x}`, c);
      break;
    }
    case 'threshold': {
      const top = 1100 - b * 420;
      result.bars.push({id: r.capability_id, x: 150, y: top, width: 320, height: 1280 - top, opacity: a});
      result.rules.push({id: r.threshold_id, x: 120, y: 900 - c * 340, width: 840, opacity: a});
      node(r.capability_id, 120, 1320, 400, 240, a, b);
      node(r.threshold_id, 560, 940 - c * 340, 400, 240, a, c);
      break;
    }
    case 'delay': {
      node(r.trigger_id, 100, 430, 880, 250, a, 0);
      node(r.outcome_id, 100, 1190, 880, 250, a, c);
      result.clock = {x: 540, y: 935, radius: 120, opacity: a, progress: b};
      const clock = result.clock, outcome = result.nodes[1];
      link('elapsed', `M ${clock.x} ${clock.y + clock.radius} L ${clock.x} ${outcome.y}`, c);
      break;
    }
    case 'hierarchy': {
      const step = {2: 620, 3: 370, 4: 250}[r.layer_ids.length];
      r.layer_ids.forEach((id, i) => {
        const opacity = i === 0 ? a : clamp(b * (r.layer_ids.length - 1) - (i - 1));
        node(id, 100, 430 + i * step, 880, 230, opacity, c);
        if (i) link(`layer-${i}`, `M 540 ${430 + (i - 1) * step + 230} L 540 ${430 + i * step}`, opacity);
      });
      break;
    }
    case 'feedback': {
      node(r.source_id, 180, 430, 680, 270, a, clamp((c - .75) * 4));
      node(r.result_id, 180, 1140, 680, 270, b, b);
      const [source, outcome] = result.nodes, center = source.x + source.width / 2;
      link('produce', `M ${center} ${source.y + source.height} L ${center} ${outcome.y}`, b);
      // Return reaches the source before its state begins to update.
      link('return', 'M 860 1275 C 1010 1275,1010 565,860 565', clamp(c / .75));
      break;
    }
    default: fail('unsupported family');
  }
  return result;
}

function esc(value) { return String(value).replace(/[&<>"']/gu, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}[char])); }
const VISUAL_SYSTEM = Object.freeze({
  id: 'semantic-poster-v2', paper: '#F4EFDF', paperLight: '#FFFCF2',
  navy: '#111B3A', yellow: '#FFD44D', coral: '#F45B50', cobalt: '#3154D9',
  green: '#103F31', ink: '#152033', muted: '#6D716D',
});
const FAMILY_META = Object.freeze({
  replacement: Object.freeze({eyebrow: 'CHANGE / CONTEXT', accent: '#F45B50', index: '01'}),
  threshold: Object.freeze({eyebrow: 'MOVING STANDARD', accent: '#3154D9', index: '02'}),
  delay: Object.freeze({eyebrow: 'TIME LAG', accent: '#E4A72B', index: '03'}),
  hierarchy: Object.freeze({eyebrow: 'CAPABILITY STACK', accent: '#103F31', index: '04'}),
  feedback: Object.freeze({eyebrow: 'FEEDBACK LOOP', accent: '#6A4BC3', index: '05'}),
});

function charUnits(char) { return /^[\x00-\xff]$/u.test(char) ? .58 : 1; }
function wrapCjk(value, width, size) {
  const limit = width / size, lines = [];
  let line = '', units = 0;
  for (const char of Array.from(value)) {
    const next = charUnits(char);
    if (line && units + next > limit) { lines.push(line); line = ''; units = 0; }
    line += char; units += next;
  }
  if (line) lines.push(line);
  return lines;
}
function textBlock(value, options) {
  const {x, y, width, maxLines, preferred, minimum, fill, opacity = 1,
    weight = 700, family = 'sans', lineHeight = 1.18, anchor = 'start'} = options;
  for (let size = preferred; size >= minimum; size -= 2) {
    const lines = wrapCjk(value, width, size);
    if (lines.length <= maxLines) {
      const klass = family === 'serif' ? 'serif' : family === 'mono' ? 'mono' : 'sans';
      return `<text class="${klass}" x="${x}" y="${y}" fill="${fill}" opacity="${opacity}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}" data-text-size="${size}">${lines.map((line, i) => `<tspan x="${x}" dy="${i ? size * lineHeight : 0}">${esc(line)}</tspan>`).join('')}</text>`;
    }
  }
  fail('text exceeds visual capacity');
}
function stateOpacities(node) {
  const mix = node.preserve ? 0 : node.state_mix;
  return node.object_transition
    ? {old: mix < .5 ? 1 : 0, fresh: mix > .5 ? 1 : 0}
    : {old: 1 - clamp(mix * 2), fresh: clamp((mix - .5) * 2)};
}
function nodeCard(node, box, accent, options = {}) {
  const {dark = false, rounded = 18, tilt = 0} = options;
  const palette = dark
    ? {fill: VISUAL_SYSTEM.navy, ink: VISUAL_SYSTEM.paperLight, muted: '#C8C9C2'}
    : {fill: VISUAL_SYSTEM.paperLight, ink: VISUAL_SYSTEM.ink, muted: VISUAL_SYSTEM.muted};
  const opacity = stateOpacities(node), inset = 30, compact = box.height < 190;
  const label = textBlock(node.label, {x: box.x + inset, y: box.y + (compact ? 38 : 52),
    width: box.width - inset * 2, maxLines: compact ? 1 : 2,
    preferred: compact ? 22 : 28, minimum: 20, fill: palette.muted, weight: 700});
  const bodyY = box.y + (compact ? 88 : 118);
  const oldText = textBlock(node.initial_state, {x: box.x + inset, y: bodyY,
    width: box.width - inset * 2, maxLines: 2,
    preferred: compact ? 36 : box.width < 430 ? 42 : 48,
    minimum: compact ? 26 : 30, lineHeight: compact ? 1.08 : 1.1,
    fill: palette.ink, opacity: opacity.old, weight: 800});
  const newText = textBlock(node.final_state, {x: box.x + inset, y: bodyY,
    width: box.width - inset * 2, maxLines: 2,
    preferred: compact ? 36 : box.width < 430 ? 42 : 48,
    minimum: compact ? 26 : 30, lineHeight: compact ? 1.08 : 1.1,
    fill: dark ? VISUAL_SYSTEM.yellow : accent, opacity: opacity.fresh, weight: 850});
  const transform = tilt ? ` transform="rotate(${tilt} ${box.x + box.width / 2} ${box.y + box.height / 2})"` : '';
  return `<g data-subject="${esc(node.id)}" data-role="content-unit" opacity="${node.opacity}"${transform}><rect x="${box.x + 12}" y="${box.y + 14}" width="${box.width}" height="${box.height}" rx="${rounded}" fill="${VISUAL_SYSTEM.navy}" opacity=".13"/><rect x="${box.x}" y="${box.y}" width="${box.width}" height="${box.height}" rx="${rounded}" fill="${palette.fill}" stroke="${VISUAL_SYSTEM.navy}" stroke-width="3"/><rect x="${box.x}" y="${box.y}" width="12" height="${box.height}" rx="6" fill="${accent}"/>${label}${oldText}${newText}</g>`;
}
function linkPath(link, color, width = 10, role = null) {
  return `<path${role ? ` data-role="${role}"` : ''} data-link="${esc(link.id)}" d="${link.d}" pathLength="1" stroke="${color}" stroke-width="${width}" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="1" stroke-dashoffset="${1 - link.progress}" opacity="${link.progress > 0 ? 1 : 0}"/>`;
}
function payoffCopy(brief) {
  const subjects = brief.motion.subjects, changed = subjects.filter(subject => !subject.preserve);
  switch (brief.motion.family) {
    case 'replacement': {
      const subject = changed[0]; return `${subject.label} → ${subject.final_state}`;
    }
    case 'threshold': return `${changed[0].final_state} / ${changed[1].final_state}`;
    case 'delay': return `${changed[0].label}：${changed[0].final_state}`;
    case 'hierarchy': {
      const subject = changed[changed.length - 1]; return `${subject.label}：${subject.final_state}`;
    }
    case 'feedback': return `${changed[0].final_state} → ${changed[1].final_state}`;
    default: fail('unsupported family');
  }
}
function payoffBlock(brief, accent, opacity) {
  const copy = payoffCopy(brief);
  return `<g data-role="payoff" opacity="${opacity}"><path d="M 64 1428 H 748" stroke="${VISUAL_SYSTEM.navy}" stroke-width="4"/><path d="M 64 1428 H 220" stroke="${accent}" stroke-width="12"/>${textBlock(copy, {x: 64, y: 1500, width: 690, maxLines: 2, preferred: 48, minimum: 34, fill: VISUAL_SYSTEM.navy, family: 'serif', weight: 800})}</g>`;
}
function sharedHeader(brief, meta) {
  return `<g data-role="header"><rect x="64" y="74" width="310" height="54" rx="27" fill="${VISUAL_SYSTEM.navy}"/>${textBlock(meta.eyebrow, {x: 92, y: 111, width: 254, maxLines: 1, preferred: 22, minimum: 18, fill: VISUAL_SYSTEM.paperLight, family: 'mono', weight: 750})}<text class="mono" x="1016" y="113" text-anchor="end" fill="${VISUAL_SYSTEM.navy}" font-size="24" font-weight="750">${meta.index} / 05</text>${textBlock(brief.title, {x: 64, y: 246, width: 900, maxLines: 2, preferred: 92, minimum: 64, fill: VISUAL_SYSTEM.navy, family: 'serif', weight: 850})}<path d="M 64 314 H 1016" stroke="${VISUAL_SYSTEM.navy}" stroke-width="4"/><path d="M 64 314 H 340" stroke="${meta.accent}" stroke-width="13"/></g>`;
}
function renderReplacement(brief, state) {
  const meta = FAMILY_META.replacement, change = state.nodes[0], contexts = state.nodes.slice(1);
  const stage = `<g data-role="replacement-stage"><path d="M 82 390 H 998 V 804 H 82 Z" fill="${VISUAL_SYSTEM.navy}"/><path d="M 82 390 H 566 L 510 804 H 82 Z" fill="${meta.accent}"/><path d="M 566 390 L 510 804" stroke="${VISUAL_SYSTEM.yellow}" stroke-width="12"/><text class="mono" x="122" y="448" fill="${VISUAL_SYSTEM.paperLight}" font-size="25" font-weight="750">BEFORE</text><text class="mono" x="700" y="448" fill="${VISUAL_SYSTEM.paperLight}" font-size="25" font-weight="750">AFTER</text>${nodeCard(change, {x: 146, y: 504, width: 786, height: 224}, meta.accent, {dark: true, index: 'CHANGE'})}</g>`;
  const stacked = contexts.length === 3, gap = 24;
  const width = contexts.length === 1 || stacked ? 916 : (916 - gap) / 2;
  const cards = contexts.map((node, i) => nodeCard(node, {
    x: stacked ? 82 : 82 + i * (width + gap), y: stacked ? 830 + i * 172 : 890,
    width, height: stacked ? 150 : 236,
  }, VISUAL_SYSTEM.cobalt, {index: `KEEP 0${i + 1}`})).join('');
  const context = `<g data-role="preserved-context"><text class="mono" x="82" y="${stacked ? 794 : 854}" fill="${VISUAL_SYSTEM.muted}" font-size="24" font-weight="750">CONTEXT STAYS</text>${cards}</g>`;
  let comparison = '';
  if (state.links[0]) {
    let d = `M 540 728 V ${stacked ? 830 : 890}`;
    if (contexts.length === 2) d = 'M 540 728 V 850 M 540 850 H 305 V 890 M 540 850 H 775 V 890';
    if (stacked) d += ' M 540 980 V 1002 M 540 1152 V 1174';
    comparison = linkPath({...state.links[0], d}, meta.accent, 8);
  }
  return stage + context + comparison + payoffBlock(brief, meta.accent, state.links[0]?.progress ?? 0);
}
function renderThreshold(brief, state) {
  const meta = FAMILY_META.threshold, ability = state.nodes[0], standard = state.nodes[1];
  const bar = state.bars[0], rule = state.rules[0];
  const capability = `<g data-role="capability-track"><rect x="82" y="390" width="470" height="880" rx="20" fill="${VISUAL_SYSTEM.navy}"/><path d="M 160 1170 V 500" stroke="${VISUAL_SYSTEM.paperLight}" stroke-width="3" opacity=".35"/><rect data-bar="${esc(bar.id)}" x="202" y="${bar.y - 150}" width="230" height="${1420 - bar.y}" rx="16" fill="${meta.accent}" opacity="${bar.opacity}"/><path d="M 202 ${bar.y - 150} H 432" stroke="${VISUAL_SYSTEM.yellow}" stroke-width="12"/>${nodeCard(ability, {x: 118, y: 1060, width: 398, height: 170}, meta.accent, {dark: true, index: 'ABILITY'})}</g>`;
  const threshold = `<g data-role="threshold-track"><rect x="584" y="390" width="414" height="880" rx="20" fill="${VISUAL_SYSTEM.paperLight}" stroke="${VISUAL_SYSTEM.navy}" stroke-width="3"/><g data-role="threshold-axis" data-axis-min-y="410" data-axis-max-y="970" opacity=".16"><path d="M 626 410 H 956 M 626 540 H 956 M 626 680 H 956 M 626 820 H 956 M 626 960 H 956" stroke="${VISUAL_SYSTEM.navy}" stroke-width="3" stroke-dasharray="10 12"/><path d="M 930 970 V 410 M 914 434 L 930 410 L 946 434" fill="none" stroke="${VISUAL_SYSTEM.navy}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></g><path data-rule="${esc(rule.id)}" d="M 626 ${rule.y - 150} H 956" stroke="${VISUAL_SYSTEM.coral}" stroke-width="12" opacity="${rule.opacity}"/><text class="mono" x="626" y="${rule.y - 178}" fill="${VISUAL_SYSTEM.coral}" font-size="24" font-weight="750">STANDARD</text>${nodeCard(standard, {x: 616, y: 1060, width: 350, height: 170}, VISUAL_SYSTEM.coral, {index: 'RULE'})}</g>`;
  const payoffOpacity = Math.max(standard.state_mix, ability.state_mix);
  return capability + threshold + payoffBlock(brief, meta.accent, payoffOpacity);
}
function renderDelay(brief, state) {
  const meta = FAMILY_META.delay, trigger = state.nodes[0], outcome = state.nodes[1], clock = state.clock;
  const triggerStage = `<g data-role="trigger-stage">${nodeCard(trigger, {x: 82, y: 390, width: 916, height: 210}, meta.accent, {index: 'TRIGGER'})}</g>`;
  const elapsed = `<g data-role="elapsed-stage" opacity="${clock.opacity}"><path d="M 140 820 H 940" stroke="${VISUAL_SYSTEM.navy}" stroke-width="4" opacity=".25"/><path d="M 140 820 H ${140 + 800 * clock.progress}" stroke="${meta.accent}" stroke-width="14"/><circle cx="${140 + 800 * clock.progress}" cy="820" r="24" fill="${VISUAL_SYSTEM.yellow}" stroke="${VISUAL_SYSTEM.navy}" stroke-width="5"/><g transform="translate(540 820)"><circle r="132" fill="${VISUAL_SYSTEM.paperLight}" stroke="${VISUAL_SYSTEM.navy}" stroke-width="4"/><circle r="108" fill="none" stroke="${meta.accent}" stroke-width="12" pathLength="1" stroke-dasharray="1" stroke-dashoffset="${1 - clock.progress}" transform="rotate(-90)"/><path d="M 0 0 L 0 -72" stroke="${VISUAL_SYSTEM.navy}" stroke-width="8" transform="rotate(${clock.progress * 360})"/><circle r="11" fill="${VISUAL_SYSTEM.navy}"/></g><text class="mono" x="140" y="1040" fill="${VISUAL_SYSTEM.muted}" font-size="25" font-weight="750">WAITING FOR RELEASE</text></g>`;
  const outcomeStage = `<g data-role="outcome-stage"><path d="M 98 1160 Q 540 ${1160 - 110 * outcome.state_mix} 982 1160" fill="none" stroke="${meta.accent}" stroke-width="8" opacity="${outcome.opacity}"/>${nodeCard(outcome, {x: 82, y: 1120, width: 916, height: 230}, meta.accent, {dark: true, index: 'OUTCOME'})}</g>`;
  const elapsedLink = state.links[0] ? linkPath({...state.links[0], d: 'M 540 952 V 1120'}, meta.accent, 8) : '';
  return triggerStage + elapsed + elapsedLink + outcomeStage + payoffBlock(brief, meta.accent, outcome.state_mix);
}
function renderHierarchy(brief, state) {
  const meta = FAMILY_META.hierarchy, count = state.nodes.length;
  const cardHeight = count === 4 ? 178 : count === 3 ? 214 : 250;
  const step = count === 4 ? 226 : count === 3 ? 274 : 340;
  const top = 420;
  const cards = state.nodes.map((node, i) => {
    const inset = i * 44, y = top + i * step;
    return nodeCard(node, {x: 82 + inset, y, width: 916 - inset * 2, height: cardHeight}, meta.accent,
      {dark: i === count - 1, index: `LEVEL 0${i + 1}`, tilt: i % 2 ? -.6 : .6});
  }).join('');
  const connectors = state.links.map((link, i) => {
    const from = top + i * step + cardHeight, to = top + (i + 1) * step;
    return `<g data-role="layer-connector">${linkPath({...link, d: `M 540 ${from} V ${to}`}, VISUAL_SYSTEM.yellow, 9)}<circle cx="540" cy="${(from + to) / 2}" r="12" fill="${VISUAL_SYSTEM.yellow}" opacity="${link.progress}"/></g>`;
  }).join('');
  return `<g data-role="layer-stack"><path d="M 120 390 L 960 390 L 1016 1358 L 64 1358 Z" fill="${meta.accent}" opacity=".08"/>${connectors}${cards}</g>` + payoffBlock(brief, meta.accent, Math.min(...state.nodes.map(node => node.state_mix)));
}
function renderFeedback(brief, state) {
  const meta = FAMILY_META.feedback, source = state.nodes[0], result = state.nodes[1];
  const sourceCard = nodeCard(source, {x: 118, y: 430, width: 844, height: 236}, meta.accent, {index: 'DECISION'});
  const resultCard = nodeCard(result, {x: 118, y: 1110, width: 844, height: 236}, meta.accent, {dark: true, index: 'PRACTICE'});
  const forward = `<g data-role="forward-path">${state.links[0] ? linkPath({...state.links[0], d: 'M 540 666 V 1110'}, VISUAL_SYSTEM.cobalt, 12) : ''}<text class="mono" x="390" y="882" fill="${VISUAL_SYSTEM.cobalt}" font-size="24" font-weight="750">PUT INTO PRACTICE</text></g>`;
  const returning = `<g data-role="return-path">${state.links[1] ? linkPath({...state.links[1], d: 'M 962 1228 C 1032 1228,1032 548,962 548'}, meta.accent, 12) : ''}<text class="mono" x="744" y="930" fill="${meta.accent}" font-size="24" font-weight="750">RETURN &amp; REVISE</text></g>`;
  return `<path d="M 540 784 A 232 232 0 1 1 539 784" fill="none" stroke="${VISUAL_SYSTEM.navy}" stroke-width="3" opacity=".12"/>${sourceCard}${forward}${resultCard}${returning}` + payoffBlock(brief, meta.accent, source.state_mix);
}

const FAMILY_RENDERERS = Object.freeze({replacement: renderReplacement, threshold: renderThreshold,
  delay: renderDelay, hierarchy: renderHierarchy, feedback: renderFeedback});
function svgFor(brief, frame) {
  const state = frameState(brief, frame), meta = FAMILY_META[state.family];
  const renderer = FAMILY_RENDERERS[state.family];
  if (!renderer || !meta) fail('unsupported family');
  const body = renderer(brief, state);
  // No wall clock, random decoration, baked fade, invented statistics or external asset.
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920" lang="zh-CN" data-family="${state.family}" data-visual-system="${VISUAL_SYSTEM.id}"><defs><pattern id="paper-grid" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M 48 0 H 0 V 48" fill="none" stroke="${VISUAL_SYSTEM.navy}" stroke-width="1" opacity=".055"/></pattern><filter id="soft-shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="12" flood-color="${VISUAL_SYSTEM.navy}" flood-opacity=".12"/></filter></defs><style>.sans{font-family:"PingFang SC","Noto Sans CJK SC",sans-serif}.serif{font-family:"Songti SC","Noto Serif CJK SC",serif}.mono{font-family:"SFMono-Regular","Roboto Mono",monospace}text{font-family:"PingFang SC","Noto Sans CJK SC",sans-serif}</style><rect width="1080" height="1920" fill="${VISUAL_SYSTEM.paper}"/><rect width="1080" height="1920" fill="url(#paper-grid)"/>${sharedHeader(brief, meta)}${body}</svg>`;
}

function htmlFor(input) {
  const brief = validateBrief(input);
  const data = JSON.stringify(brief).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
  // Embed the same pure functions, rather than maintaining another animation.
  const constants = `const VISUAL_SYSTEM=${JSON.stringify(VISUAL_SYSTEM)};const FAMILY_META=${JSON.stringify(FAMILY_META)};`;
  const functions = [fail, integer, clamp, phase, frameState, esc, charUnits, wrapCjk,
    textBlock, stateOpacities, nodeCard, linkPath, payoffCopy, payoffBlock, sharedHeader,
    renderReplacement, renderThreshold, renderDelay, renderHierarchy, renderFeedback, svgFor]
    .map(fn => fn.toString()).join('\n');
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>html,body{margin:0;width:1080px;height:1920px;overflow:hidden}svg{display:block}</style></head><body><main id="scene"></main><script>(()=>{${constants}${functions}\nconst FAMILY_RENDERERS=Object.freeze({replacement:renderReplacement,threshold:renderThreshold,delay:renderDelay,hierarchy:renderHierarchy,feedback:renderFeedback});const brief=${data};const scene=document.getElementById('scene');window.seekFrame=frame=>{const state=frameState(brief,frame);scene.innerHTML=svgFor(brief,frame);return state;};window.seekFrame(0);})();</script></body></html>`;
}

function readBrief() {
  const limit = 256 * 1024, buffer = Buffer.alloc(limit + 1);
  let size = 0;
  while (size <= limit) {
    const read = fs.readSync(0, buffer, size, buffer.length - size, null);
    if (!read) break;
    size += read;
  }
  if (size > limit) fail(`brief exceeds ${limit} bytes`);
  return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(buffer.subarray(0, size)));
}
function frameArgument(value) {
  if (!/^(0|[1-9][0-9]*)$/u.test(value)) fail('frame must be an integer');
  return Number(value);
}

if (require.main === module) {
  try {
    const brief = validateBrief(readBrief());
    const mode = process.argv[2], args = process.argv.slice(3);
    if (mode === '--validate' && !args.length) process.stdout.write(JSON.stringify(brief));
    else if (mode === '--html' && !args.length) process.stdout.write(htmlFor(brief));
    else if (mode === '--states' && args.length) process.stdout.write(JSON.stringify(args.map(f => frameState(brief, frameArgument(f)))));
    else if (mode === '--svg' && args.length === 1) process.stdout.write(svgFor(brief, frameArgument(args[0])));
    else fail('use --validate, --html, --states FRAME..., or --svg FRAME');
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
module.exports = {validateBrief, frameState, svgFor, htmlFor};
