// Aura — Hear the Light · Glass Product Render style demo
import * as THREE from 'three';
import { makePost } from '/core/three/post.js';
import { clamp, seg, eio, eo, ei, ss, lerp, hash } from '/core/lib.js';
import { DUR, T, SHOTS, shotAt, KICKS, MACRO_SWEEPS, VO, BEAT, SFX } from './story.js';
import { makeBud, makeCase, explode, setPulses, AURA_A, AURA_B, CASE } from './product.js';
import { makeStudio } from './studio.js';
import { RectAreaLightUniformsLib } from 'three/addons/lights/RectAreaLightUniformsLib.js';

const QS = new URLSearchParams(location.search), NOSUB = QS.has('nosub');
const W = 1920, H = 1080;
const renderer = new THREE.WebGLRenderer({ antialias: false, preserveDrawingBuffer: true });
renderer.setPixelRatio(2); renderer.setSize(W, H);
renderer.toneMapping = QS.has('agx') ? THREE.AgXToneMapping : THREE.NeutralToneMapping; renderer.toneMappingExposure = QS.has('agx') ? 1.15 : 1.1;
document.getElementById('stage').appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color('#000000');
const camera = new THREE.PerspectiveCamera(28, W / H, 1, 3000);
const post = makePost(renderer, scene, camera, W, H, { ssaa: 2, ao: false });
post.bloom.strength = .2; post.bloom.threshold = 1.1; post.bloom.radius = .4;
post.vig.uniforms.amt.value = .3; post.vig.uniforms.contrast.value = .12; post.vig.uniforms.sat.value = 1.0;

const studio = makeStudio(renderer, scene);
const box = makeCase(); scene.add(box.root);
const buds = [makeBud(-1), makeBud(1)]; buds.forEach(b => scene.add(b.root));
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const Y = V(0, 1, 0);

// —— Pose helpers ——
function pose(bud, pos, dir, roll = 0) {
  bud.root.position.copy(pos);
  bud.root.quaternion.setFromUnitVectors(Y, dir.clone().normalize());
  bud.root.rotateY(roll);
}
const cradle = i => box.cradles[i].clone();
const LID_OPEN = 1.72;   // lid stands up at about 99°
// Top softbox (a real area light): key light for the metal and PCB in the exploded view
RectAreaLightUniformsLib.init();
const topBox = new THREE.RectAreaLight('#ffffff', 0, 90, 40); scene.add(topBox);
box.edge.userData.U.uA.value = new THREE.Color('#cdefff'); box.edge.userData.U.uB.value = new THREE.Color('#e2d8ff');

// —— Light: drum hits → light-pattern pulses ——
function kickState(t, list, span = 1.6) { return list.filter(k => t >= k.t && t - k.t < span).slice(-3); }
function budLight(bud, t, mode) {
  // mode: 0 = off, 1 = breathing (standby), 2 = sound visualisation
  let ring = [], sp = [], base = 0, flash = 0;
  if (mode === 1) base = .008 + .012 * (.5 + .5 * Math.sin(t * 2.4));
  if (mode >= 2) {
    const ks = kickState(t, KICKS);
    for (const k of ks) {
      const dt = t - k.t, A = (k.big ? 12 : 8) * Math.exp(-dt / .55), off = bud.side > 0 ? 0 : .5;
      ring.push({ p: .25 + off + dt * .6, w: .03, a: A, h: clamp(dt * 1.1) }, { p: .25 + off - dt * .6, w: -.03, a: A, h: clamp(dt * 1.1) });
      sp.push({ p: dt / .42, w: .05, a: (k.big ? 12 : 8) * Math.exp(-dt / .6), h: clamp(dt * 1.4) });
      flash += (k.big ? 1.6 : 1) * Math.exp(-dt / .12);
    }
    base = .015 + flash * .05;
  }
  if (mode === 3) {   // steady on: two beams slowly travel round the light-guide ring (layered over the afterglow of the last drum hit)
    const ph = t * .22 + (bud.side > 0 ? 0 : .5);
    ring.push({ p: ph, w: .035, a: 9, h: .15 }, { p: ph + .5, w: .035, a: 9, h: .8 }); sp.push({ p: (t * .7) % 1.3, w: .06, a: 6, h: .4 }); base = .04 + flash * .35;
  }
  setPulses(bud.ring, ring, base);
  setPulses(bud.spiral, sp, mode >= 2 ? .008 + flash * .04 : base * .5);
  bud.glow.intensity = mode >= 2 ? 6 + flash * 90 : 0;
  bud.glow.color.copy(AURA_A).lerp(AURA_B, clamp(flash * .5)).lerp(new THREE.Color('#ffffff'), .35);
  return flash;
}

// —— Cameras and staging (each shot is posed independently: a product film doesn't need spatial continuity across shots) ——
const SW = (t, a, b2) => { const u = seg(t, a, b2); return u > 0 && u < 1 ? u : null; };
function frame(t) {
  const [t0, t1, name] = shotAt(t), u = seg(t, t0, t1);
  let pos, look, fov = 28, focus = null, aper = 300;
  const envO = { left: 1, right: 1, top: 1, front: 1, back: 1, key: 0 };
  let bg = 0, glowI = 0, topI = 0, topAt = null;
  let sweep = null, lid = 0, caseVis = true, modes = [0, 0], bloom = .16, spot = .02, vis = [1, 1];
  const caus = [0, 0];   // caustic strength each earbud throws on the floor
  let waves = true;

  // Earbuds sit in their cradles by default
  pose(buds[0], cradle(0), Y, .4); pose(buds[1], cradle(1), Y, -.3);
  explode(buds[0], 0); explode(buds[1], 0);

  switch (name) {
    case 'dark': {   // black: only two light sweeps trace the case's outline
      const amb = ss(seg(t, .9, 3.5));   // opens fully black: the ambient rim light only slowly comes up after the first light sweep
      Object.assign(envO, { left: .07 * amb, right: .07 * amb, top: .03 * amb, front: 0, back: .12 * amb });
      const s1 = SW(t, ...T.sweep1), s2 = SW(t, ...T.sweep2);
      if (s1 != null) sweep = { x: lerp(-1, 1, s1), I: 7 * Math.sin(s1 * Math.PI) };
      if (s2 != null) sweep = { x: lerp(1, -1, s2), I: 7 * Math.sin(s2 * Math.PI), tilt: .25 };
      pos = V(-68, 5, 116).lerp(V(-60, 3, 104), eio(u)); look = V(0, 10, 0); fov = 30; focus = V(-10, 0, 20); aper = 150;
      modes = [1, 1]; spot = 0; break;
    }
    case 'open': {   // lid swings slowly open: high three-quarter angle, slow orbit
      lid = eio(seg(t, ...T.lidOpen)) * LID_OPEN; glowI = .15 * ss(seg(t, 6, 7.6)); bg = .25;
      const az = lerp(.45, .8, eio(u)), el = .42, d = 200;
      pos = V(Math.sin(az) * Math.cos(el) * d, Math.sin(el) * d, Math.cos(az) * Math.cos(el) * d); look = V(-2, 10, -8); fov = 27; focus = V(0, 0, 0); aper = 260;
      modes = [1, 1]; break;
    }
    case 'macroA': {   // macro: right earbud lifts off its magnetic cradle, camera hugging the glass dome
      lid = LID_OPEN; glowI = .15;
      const lu = eio(seg(t, ...T.lift)), p = cradle(1).add(V(0, 18 * lu, 0));
      pose(buds[1], p, V(-.25 * lu, 1, .35 * lu), -.3 + lu * .6);
      const c = p.clone();
      pos = c.clone().add(V(-30, 22, 34).lerp(V(-22, 16, 30), eio(u))); look = c.clone().add(V(-1, 2, 1)); fov = 30;
      focus = c.clone().add(V(-4, 5, 5)).lerp(c.clone().add(V(0, 1, 0)), ss(seg(t, 8.9, 9.6))); aper = 900;   // focus pull: glass surface → driver unit
      modes = [1, 1]; break;
    }
    case 'macroB': {   // macro: orbit round the side — titanium waistband, frosted back shell, ear tip
      caseVis = false; vis = [0, 1];
      const p = V(0, 18, 0); pose(buds[1], p, V(.9, .35, .2), t * .35);
      const az = lerp(-.3, .35, eio(u));
      pos = p.clone().add(V(Math.sin(az) * 42, 6, Math.cos(az) * 42)); look = p.clone().add(V(0, -1, 0)); fov = 30; focus = p.clone().add(V(Math.sin(az) * 8, 0, Math.cos(az) * 8)); aper = 700;
      modes = [0, 1]; caus[1] = .3; break;
    }
    case 'explode': {   // slow-motion exploded view → hover → snaps together at 16.0 (the drop) → light pattern lights up for the first time
      caseVis = false; vis = [0, 1]; Object.assign(envO, { left: 1.4, right: 1.4, top: 1.5, front: .6, back: 1.6, key: 1.3 }); bg = .9;
      // parts line up on a diagonal with depth: axis at ~40° to the line of sight (near parts bigger, far smaller), tilted slightly upward
      const p = V(0, 20, 0), A0 = .35, toC = V(Math.sin(A0), 0, Math.cos(A0)), side = V(Math.cos(A0), 0, -Math.sin(A0));
      const dir = toC.clone().multiplyScalar(Math.cos(.7)).addScaledVector(side, -Math.sin(.7)).add(V(0, .22, 0)).normalize();
      let e;
      if (t < 15.0) e = eo(seg(t, 12.0, 15.0)) * 1.0;
      else if (t < 15.75) e = 1 + .03 * seg(t, 15.0, 15.75);
      else if (t < T.snap) e = 1.03 * (1 - ei(seg(t, 15.75, T.snap)));
      else e = 0;
      pose(buds[1], p, dir, .3); explode(buds[1], e, (t - 12) * 1.4);
      const az = lerp(.26, .44, eio(seg(t, 12, 17))), d = lerp(94, 86, eio(u));
      const push = eo(seg(t, T.snap, T.snap + .9));   // after the snap the camera carries on into a push-in
      pos = p.clone().add(V(Math.sin(az) * (d - 40 * push), 12 - 4 * push, Math.cos(az) * (d - 40 * push))); look = p.clone().addScaledVector(dir, 3 * e).add(V(0, -1, 0)); fov = 34; focus = p.clone().addScaledVector(dir, 6 * e); aper = lerp(70, 160, push);
      topI = 5; topAt = p;
      if (t >= T.snap) { const k = Math.exp(-(t - T.snap) / .08), fr = Math.floor(t * 24); pos.add(V(hash(fr) - .5, hash(fr + 9) - .5, 0).multiplyScalar(k * 2.2)); }
      modes = [0, t >= T.snap ? 2 : 0]; caus[1] = t >= T.snap ? .6 : 0; break;
    }
    case 'front': {   // front hero shot: the light ring races round the light-guide ring
      caseVis = false; vis = [0, 1];
      const p = V(0, 18, 0); pose(buds[1], p, V(.12, .5, 1), .3 + t * .1);
      pos = p.clone().add(V(10, 14, 62).lerp(V(6, 12, 54), eio(u))); look = p.clone(); fov = 28; focus = p.clone().add(V(0, 2, 5)); aper = 300;
      modes = [0, 2]; caus[1] = .6; break;
    }
    case 'channels': {   // macro top-down: the light pattern flows from centre to edge along the spiral light-guide channels
      caseVis = false; vis = [0, 1];
      const p = V(0, 18, 0); pose(buds[1], p, V(0, 1, .25), .3 + t * .12);
      pos = p.clone().add(V(-6, 30, 16).lerp(V(-3, 26, 13), eio(u))); look = p.clone().add(V(0, 3, 0)); fov = 32; focus = p.clone().add(V(0, 5, 1)); aper = 700;
      modes = [0, 2]; caus[1] = .6; break;
    }
    case 'pair': {   // the pair: left earbud lifts in to join at 20.0, left and right pulse alternately
      caseVis = false;
      const lu = eio(seg(t, ...T.liftL));
      pose(buds[1], V(16, 20, 0), V(.2, .6, 1), .3 + t * .1);
      pose(buds[0], V(lerp(-75, -16, lu), 20, lerp(-20, 0, lu)), V(-.2, .6, 1), .4 - t * .1);
      pos = V(-18, 30, 120).lerp(V(-8, 26, 108), eio(u)); look = V(0, 12, 0); fov = 28; focus = V(0, 18, 0); aper = 200;
      modes = [lu > .5 ? 2 : 0, 2]; caus[0] = .6 * lu; caus[1] = .6; break;
    }
    case 'caustics': {   // high top-down: the glass focuses light onto the black floor, one sound-wave ring expanding per drum hit
      caseVis = false;
      pose(buds[1], V(16, 20, 0), V(.2, 1, .3), .3 + t * .1);
      pose(buds[0], V(-16, 20, 0), V(-.2, 1, .3), .4 - t * .1);
      const az = lerp(-.25, .1, eio(u));
      pos = V(Math.sin(az) * 70, 150, Math.cos(az) * 70); look = V(0, -8, 0); fov = 34; focus = V(0, 10, 0); aper = 160;
      modes = [2, 2]; caus[0] = caus[1] = .7; spot = .05; break;
    }
    case 'reveal': case 'end': {   // reveal: both earbuds hover above the open case, a final light sweep, they drop back into their cradles
      lid = LID_OPEN;
      const su = eio(seg(t, ...T.settle));
      const w = seg(t, 24, 32), we = eio(seg(t, 27.6, 29.6)), az = lerp(-.26, -.06, eio(w)), el = lerp(.2, .28, eio(w)), d = lerp(228, 244, w) + 26 * we;
      pos = V(Math.sin(az) * Math.cos(el) * d, Math.sin(el) * d, Math.cos(az) * Math.cos(el) * d); look = V(0, lerp(31, 26, we), -6); fov = 27; focus = V(0, 10, 0); aper = 160;
      // while hovering, turned three-quarters to camera (showing the lens front and light-guide ring); straightened when dropping into the cradle
      [0, 1].forEach(i => {
        const bp = cradle(i).add(V(0, 17 * (1 - su), 0)), toC = pos.clone().sub(bp).normalize();
        const dir = V(0, 1, 0).multiplyScalar(.7).addScaledVector(toC, .75).add(V(i ? .12 : -.12, 0, 0)).normalize().lerp(Y, su);
        pose(buds[i], bp, dir, i ? -.3 : .4);
      });
      glowI = .35 + .65 * ss(seg(t, T.settle[1], T.settle[1] + .6)); bg = 1.1; Object.assign(envO, { back: 2.6, left: 1.3, right: 1.3, front: 0 });
      const s = SW(t, 24.0, 25.3); if (s != null) sweep = { x: lerp(-1, 1, s), I: 6 * Math.sin(s * Math.PI) };
      modes = [3, 3]; spot = .04; bloom = .3; envO.top = 1.5;
      if (name === 'end') { Object.assign(envO, { left: .6, right: .6, top: .5, front: 0, back: 1.2 }); glowI = 1; bg = 1.1 - .4 * seg(t, 28, 32); }
      break;
    }
  }
  // Macro section: one short light sweep per beat (locked to the kick)
  if (name === 'macroA' || name === 'macroB') for (const st of MACRO_SWEEPS) { const s = SW(t, st, st + .45); if (s != null) sweep = { x: lerp(-1, 1, s), I: 5 * Math.sin(s * Math.PI), tilt: -.35 }; }

  box.root.visible = caseVis; buds.forEach((b, i) => b.root.visible = !!vis[i]);
  box.lidPivot.rotation.x = -lid; box.lidPivot.visible = box.hinge.visible = name !== 'macroA';
  box.setGlow(glowI);
  scene.backgroundIntensity = bg; studio.U.uBgI.value = bg;
  topBox.intensity = topI; if (topAt) { topBox.position.copy(topAt).add(V(0, 60, 30)); topBox.lookAt(topAt); }
  // Light
  let fl = 0;
  buds.forEach((b, i) => { fl += budLight(b, t, modes[i]); });
  // Light-guide strip inside the case base: faintly lit when the lid opens; at the end, after the earbuds drop into their cradles, a soft glow shows through the frosted glass like charging
  const caseGlow = name === 'open' ? ss(seg(t, 5.5, 7.5)) * .3 : name === 'dark' ? 0 : name === 'reveal' || name === 'end' ? .5 + .5 * ss(seg(t, T.settle[1], T.settle[1] + .6)) : .3;
  setPulses(box.edge, [], .02 + .08 * caseGlow);
  camera.position.copy(pos); camera.fov = fov; camera.updateProjectionMatrix(); camera.lookAt(look);
  const az = Math.atan2(camera.position.x, camera.position.z);
  if (sweep) sweep.az = az + Math.PI;   // light strip travels along an arc behind the camera → reflected highlight sweeps across the glass
  studio.updateEnv(Object.assign(envO, { sweep: sweep || { I: 0 }, aura: { I: caseVis ? 0 : fl * .9, col: AURA_A } }));
  post.dof.focus = focus ? camera.position.distanceTo(focus) : 100; post.dof.aper = aper; post.dof.maxCoc = 14;
  post.bloom.strength = bloom + fl * .05;
  // Floor caustics + sound waves
  const U = studio.U; U.uTime.value = t * .6; U.uSpot.value = spot; 
  const swI = sweep ? sweep.I / 7 : 0;
  buds.forEach((b, i) => {
    const p = b.root.position, h = p.y - studio.FLOOR.y, vis = b.root.visible && (caseVis ? 0 : 1);
    U.uC.value[i].set(p.x, p.z, 10 + h * .3, vis * (caus[i] * (.35 + fl * .5) + swI * .6));
  });
  U.uC.value[2].set(0, 0, 1, 0);
  let wi = 0;
  for (const wv of U.uWave.value) wv.set(0, 0, 0, 0);
  if (waves && !caseVis) for (const k of KICKS) {
    const dt = t - k.t; if (dt < 0 || dt > 2.2) continue;
    buds.forEach((b, i) => { if (modes[i] !== 2 || wi >= 12) return; const p = b.root.position; U.uWave.value[wi++].set(p.x, p.z, 8 + 55 * dt, (k.big ? .7 : .38) * Math.exp(-dt / .6)); });
  }
  return name;
}

// —— 2D layer: title, subtitles (frosted-glass bar), end card ——
const ov = document.getElementById('ov'), g = ov.getContext('2d');
let DURS = {};
try { const r = await fetch('voices/dur.json'); if (r.ok) DURS = await r.json(); } catch (e) { }
const voDur = v => DURS[v.id] ?? v.text.length * .065;
await document.fonts.load('200 100px "Inter Tight"'); await document.fonts.load('300 40px "Inter Tight"'); await document.fonts.load('500 20px "Inter Tight"');

function spaced(text, x, y, font, spacing, align = 'center') {
  g.font = font; g.letterSpacing = spacing + 'px'; g.textAlign = align; g.textBaseline = 'middle';
  // letterSpacing adds one extra space at the end: add back half of it when centring
  g.fillText(text, align === 'center' ? x + spacing / 2 : x, y); g.letterSpacing = '0px';
}
// Light-sweep text: a diagonal highlight band sweeps across the letters (in sync with the picture's light sweeps)
function glintText(text, y, font, spacing, a, gx) {
  g.save(); g.globalAlpha = a; g.fillStyle = 'rgba(236,242,248,.92)'; spaced(text, W / 2, y, font, spacing); g.restore();
  if (gx == null) return;
  g.save(); g.globalCompositeOperation = 'source-atop';
  const gr = g.createLinearGradient(gx - 160, 0, gx + 160, 0);
  gr.addColorStop(0, 'rgba(255,255,255,0)'); gr.addColorStop(.42, 'rgba(160,230,255,.0)'); gr.addColorStop(.5, 'rgba(255,255,255,1)'); gr.addColorStop(.58, 'rgba(200,170,255,.0)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr; g.fillRect(0, y - 120, W, 240); g.restore();
}
function subtitle(text, a) {
  g.font = '300 40px "Inter Tight"'; g.letterSpacing = '1px';
  const tw = g.measureText(text).width, pw = tw + 96, ph = 76, x = (W - pw) / 2, y = H - 128;
  g.save(); g.globalAlpha = a;
  // Frosted glass: blur the 3D picture and clip it into a rounded bar, then add a 1px highlight edge + a little chromatic dispersion on the top edge
  g.save(); g.beginPath(); g.roundRect(x, y, pw, ph, 38); g.clip(); g.filter = 'blur(18px) brightness(1.25)';
  g.drawImage(renderer.domElement, 0, 0, W, H); g.filter = 'none';
  g.fillStyle = 'rgba(210,225,240,.10)'; g.fillRect(x, y, pw, ph); g.restore();
  g.lineWidth = 1.2; const eg = g.createLinearGradient(x, y, x + pw, y + ph);
  eg.addColorStop(0, 'rgba(255,255,255,.55)'); eg.addColorStop(.5, 'rgba(255,255,255,.12)'); eg.addColorStop(1, 'rgba(255,255,255,.35)');
  g.strokeStyle = eg; g.beginPath(); g.roundRect(x + .5, y + .5, pw - 1, ph - 1, 38); g.stroke();
  g.strokeStyle = 'rgba(98,220,255,.35)'; g.beginPath(); g.moveTo(x + 40, y + 1.5); g.lineTo(x + pw * .45, y + 1.5); g.stroke();
  g.strokeStyle = 'rgba(169,139,255,.3)'; g.beginPath(); g.moveTo(x + pw * .45, y + 1.5); g.lineTo(x + pw - 40, y + 1.5); g.stroke();
  g.fillStyle = 'rgba(245,248,252,.96)'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, W / 2 + .5, y + ph / 2 + 1);
  g.letterSpacing = '0px'; g.restore();
}
function hud(t) {
  g.clearRect(0, 0, W, H);
  if (t < .5) { g.fillStyle = `rgba(0,0,0,${1 - ss(seg(t, .1, .5))})`; g.fillRect(0, 0, W, H); }
  if (NOSUB) return;
  // Opening title: AURA, with a light sweep across the letters
  if (t >= T.title[0] && t < T.title[1]) {
    const a = ss(seg(t, T.title[0], T.title[0] + .6)) * (1 - ss(seg(t, T.title[1] - .5, T.title[1])));
    const s2 = seg(t, ...T.sweep2), gx = s2 > 0 && s2 < 1 ? lerp(W * .75, W * .25, s2) : null;
    glintText('AURA', 250, '200 132px "Inter Tight"', 64, a, gx);
    g.save(); g.globalAlpha = a * .7; g.fillStyle = '#cfd8e0'; spaced('A GLASS PRODUCT FILM', W / 2, 345, '400 18px "Inter Tight"', 9); g.restore();
  }
  // Subtitles
  if (t < T.end) {
    const v = VO.find(v => t >= v.t - .05 && t < v.t + Math.max(1.9, voDur(v) + .7));
    if (v && v.id !== 'v3' && v.id !== 'v4') {
      const e = v.t + Math.max(1.9, voDur(v) + .7), a = ss(seg(t, v.t - .05, v.t + .15)) * (1 - ss(seg(t, e - .2, e)));
      subtitle(v.text, a);
    }
  }
  // Ending: product name + slogan (the narration is exactly these two lines, so the text replaces the subtitle bar)
  if (t >= T.name[0] && t < T.end + 4) {
    const a = ss(seg(t, T.name[0], T.name[0] + .8));
    const sw = seg(t, 24.0, 25.3), gx = sw > 0 && sw < 1 ? lerp(W * .2, W * .8, sw) : null;
    // small 'Meet': keeps the burned-in text matching the narration "Meet Aura." (fades out when "hear the light" appears)
    const am = ss(seg(t, 24.5, 24.9)) * (1 - ss(seg(t, 26.2, 26.8)));
    g.save(); g.globalAlpha = am * .85; g.fillStyle = '#cfd8e0'; spaced('MEET', W / 2, 78, '500 20px "Inter Tight"', 10); g.restore();
    glintText('AURA', 150, '200 112px "Inter Tight"', 56, a, gx);
    const a2 = ss(seg(t, 25.8, 26.4));
    g.save(); g.globalAlpha = a2; g.fillStyle = '#e6edf3'; spaced('Hear the light.', W / 2, 238, '300 38px "Inter Tight"', 2); g.restore();
  }
  // End card
  if (t >= T.end) {
    const a = ss(seg(t, T.end, T.end + .6));
    // the title stays up top throughout; credits fade in from the bottom (the product stays unobscured); everything fades to black over the last half second
    const gr = g.createLinearGradient(0, H - 260, 0, H); gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, `rgba(0,0,0,${.7 * a})`);
    g.fillStyle = gr; g.fillRect(0, H - 260, W, 260);
    g.save(); g.globalAlpha = ss(seg(t, T.end + .3, T.end + 1.0));
    g.fillStyle = 'rgba(255,255,255,.22)'; g.fillRect(W / 2 - 60, H - 118, 120, 1);
    g.fillStyle = '#c3ccd5'; spaced('GLASS PRODUCT RENDER', W / 2, H - 86, '500 19px "Inter Tight"', 8);
    g.fillStyle = '#8f9aa6'; spaced('LemoLab × Claude Opus 5.5', W / 2, H - 50, '300 21px "Inter Tight"', 2);
    g.restore();
    const fo = seg(t, DUR - .6, DUR); if (fo > 0) { g.fillStyle = `rgba(0,0,0,${ss(fo)})`; g.fillRect(0, 0, W, H); }
  }
}

// —— Render entry point ——
window.render = t => {
  frame(t);
  scene.updateMatrixWorld(); camera.updateMatrixWorld();   // the mirror reflection uses matrixWorld: it must be updated first, otherwise it uses the previous frame's camera
  studio.reflect(camera);
  post.composer.render();
  hud(t);
};
window.DUR = DUR;
window.EV = [...SFX, ...VO.map(v => ({ t: v.t, type: 'vo', id: v.id, text: v.text }))];
// Subtitles (same data as the burned-in ones): display span = max(1.9 s, speech + 0.7 s)
window.SUBS = VO.map(v => ({ t0: v.t, t1: v.t + Math.max(1.9, voDur(v) + .7), text: v.text }));
window.READY = true;
