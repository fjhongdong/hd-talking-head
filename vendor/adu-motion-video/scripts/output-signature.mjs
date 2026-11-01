/** Fixed top-right output-clock / official circle signature, shared by previews and exports. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

export const signatureAssets = Object.freeze({
  lighter: ['motiongit-circle-lighter.webm', '1a4dc17a2ea86f4cf6b2745b3ee91d89dbae061e812cf78691d2680362776e0d'],
  path: ['motiongit-circle-path.webm', '9e9212233683817eef1ed474a192fbf797700f499839f7c7a3e2b96e1fe5ba8e'],
});

export function signatureWindows(duration) {
  if (!Number.isFinite(duration) || duration <= 0) throw Error('Signature requires a positive output duration');
  const span = Math.min(5.5, Math.max(duration * .7, duration - .4));
  const start = duration >= 14 ? 8 : Math.max(0, duration - span - Math.min(.5, duration * .1));
  const windows = [];
  for (let at = start; at < duration; at += 30) {
    if (duration >= 14 && at + span > duration + 1e-6) break;
    const end = Math.min(at + span, duration - Math.min(.1, duration * .05));
    if (end > at) windows.push({ start: at, end, fade: Math.min(.4, (end - at) / 3) });
  }
  return windows;
}

function decodeAssets(directory, size) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'motiongit-signature-'));
  const result = {};
  try {
    for (const [tone, [name, expected]] of Object.entries(signatureAssets)) {
      const source = path.join(directory, name);
      if (crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex') !== expected) {
        throw Error('Official signature asset changed: ' + name);
      }
      const target = path.join(temporary, tone);
      fs.mkdirSync(target);
      execFileSync('ffmpeg', ['-v', 'error', '-nostdin', '-threads', '1', '-c:v', 'libvpx-vp9', '-i', source,
        '-an', '-vf', `fps=24,scale=${size}:${size}`, '-frames:v', '144', '-threads:v', '1', path.join(target, '%03d.png')],
      { stdio: ['ignore', 'ignore', 'pipe'], timeout: 60000 });
      result[tone] = fs.readdirSync(target).filter(n => n.endsWith('.png')).sort()
        .map(n => 'data:image/png;base64,' + fs.readFileSync(path.join(target, n)).toString('base64'));
      if (result[tone].length < 132) throw Error('Incomplete signature animation: ' + name);
    }
    return result;
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

export async function createSignature(page, options) {
  const { width, height, duration, fps = 60, selector = 'canvas', mode = 'canvas' } = options;
  if (![width, height, fps].every(n => Number.isFinite(n) && n > 0)) throw Error('Invalid signature output geometry');
  const windows = signatureWindows(duration);
  const directory = options.assets ?? fileURLToPath(new URL('../template/brand/', import.meta.url));
  const frames = decodeAssets(directory, Math.max(96, Math.ceil(Math.min(width, height) * .06)));
  await page.evaluate(async data => {
    if (window.__motiongitSignature) throw Error('Duplicate automatic signature layer');
    const { width: W, height: H, selector, mode, windows, fps, frames, sourceHud } = data;
    const target = document.querySelector(selector);
    if (!target) throw Error('Signature capture surface is missing: ' + selector);
    const scene = mode === 'canvas' ? target.getContext('2d') : null;
    if (mode === 'canvas' && !scene) throw Error('Signature requires the actual 2D output canvas');
    const scale = Math.min(W, H) / 1080;
    const portrait = H > W, fontSize = (portrait ? 32 : 22) * scale;
    const diameter = 56 * scale, right = (portrait ? 96 : 64) * scale, top = (portrait ? 88 : 52) * scale;
    const slot = { x: W - right - 160 * scale, y: top - 10 * scale, w: 196 * scale, h: 76 * scale };
    const layer = document.createElement('canvas');
    layer.width = W; layer.height = H;
    layer.dataset.motiongitSignature = 'output-clock-circle/1';
    const ctx = layer.getContext('2d');
    if (sourceHud && window.MOTIONGIT_SOURCE_HUD_ADAPTED !== sourceHud) throw Error('Declared source HUD adaptation was not consumed');
    if (!scene) {
      // The capture viewport is authoritative, even for a cropped legacy stage.
      layer.style.cssText = `position:fixed;left:0;top:0;width:${W}px;height:${H}px;z-index:2147483646;pointer-events:none`;
      document.documentElement.append(layer);
    }
    const images = {};
    for (const [tone, sources] of Object.entries(frames)) {
      images[tone] = await Promise.all(sources.map(src => new Promise((resolve, reject) => {
        const image = new Image(); image.onload = () => resolve(image); image.onerror = () => reject(Error('Signature frame failed')); image.src = src;
      })));
    }
    // Source clocks are decoration only: replace corner clocks, preserve brands,
    // chapter text and all clocks outside this small output corner. Revisit local
    // iframe documents on every seek because auto-compositions load lazily.
    const clockText = s => /^\d{1,2}:\d{2}(?::\d{2}){0,2}(?:[.:]\d+)?$/.test(s);
    const adapted = new WeakSet(), shifted = new Set();
    function documents(doc = document) {
      const all = [doc];
      for (const frame of doc.querySelectorAll('iframe')) {
        try { if (frame.contentDocument) all.push(...documents(frame.contentDocument)); } catch {}
      }
      return all;
    }
    function hideSourceClocks() {
      if (scene) return;
      for (const node of shifted) node.style.removeProperty('translate');
      shifted.clear();
      for (const doc of documents()) {
        const view = doc.defaultView, root = doc.querySelector('#stage') || doc.body;
        if (!root || !view) continue;
        if (!doc.querySelector('style[data-motiongit-source-hud]')) {
          const style = doc.createElement('style'); style.dataset.motiongitSourceHud = 'true';
          style.textContent = '[data-motiongit-source-clock],#vivid-clock,#vivid-mark{display:none!important}';
          doc.head.append(style);
        }
        const bounds = root.getBoundingClientRect(), sx = bounds.width / W;
        if (!bounds.width || !bounds.height) continue;
        const containers = new Set();
        for (const node of root.querySelectorAll('span,small,time,[class*="clock"],[class*="timecode"],#clock,#timecode,#tc,.tc,.time')) {
          const box = node.getBoundingClientRect(), text = node.textContent.trim();
          const sourceHud = node.closest('.tc') || (node.closest('#hud') && !node.matches('.rt'));
          if ((!sourceHud && box.left < bounds.left + bounds.width * .65) || box.top > bounds.top + bounds.height * .13 ||
              !clockText(text) || parseFloat(view.getComputedStyle(node).fontSize) > 40) continue;
          node.dataset.motiongitSourceClock = 'true';
          const container = node.closest('.e,.it');
          if (container && container !== root && container.querySelector('b')) containers.add(container);
        }
        // A clock span shares its HUD with the user's brand; keep that brand and
        // move only the small HUD container away from the reserved circle slot.
        for (const node of root.querySelectorAll('[data-motiongit-source-clock]')) {
          const container = node.closest('.e,.it');
          if (container?.querySelector('b')) containers.add(container);
        }
        for (const node of containers) {
          const box = node.getBoundingClientRect();
          const limit = bounds.left + (slot.x - 20 * scale) * sx;
          if (box.right > limit && box.top < bounds.top + (slot.y + slot.h) * sx) {
            const ratio = box.width / node.offsetWidth || sx;
            node.style.setProperty('translate', -Math.max(0, box.right - limit) / ratio + 'px 0', 'important');
            shifted.add(node);
          }
        }
        for (const surface of root.querySelectorAll('canvas')) {
          if (surface === layer || adapted.has(surface)) continue;
          const context = surface.getContext('2d');
          if (!context) continue;
          adapted.add(surface);
          const original = context.fillText;
          context.fillText = function (text, x, y, ...args) {
            const m = this.getTransform(), gx = m.a*x + m.c*y + m.e, gy = m.b*x + m.d*y + m.f;
            if ((clockText(String(text).trim()) || /^(?:SCALE\s+1:1\s+)?T\+\d/.test(String(text))) && gx > W*.65 && gy < H*.13) return;
            return original.call(this, text, x, y, ...args);
          };
        }
      }
    }
    hideSourceClocks();
    let saved = null;
    function before() {
      if (scene && saved) scene.putImageData(saved, Math.floor(slot.x), Math.floor(slot.y));
      if (!scene) layer.style.visibility = 'hidden';
    }
    function luminance(pixels) {
      let sum = 0, count = 0;
      for (let i = 0; i < pixels.length; i += 16) { sum += .2126 * pixels[i] + .7152 * pixels[i + 1] + .0722 * pixels[i + 2]; count++; }
      return sum / Math.max(1, count);
    }
    async function draw(time, sample) {
      // Quantize to the final output frame; source choreography time is deliberately not used.
      const t = Math.floor(time * fps + 1e-6) / fps;
      const event = windows.find(w => t >= w.start && t < w.end);
      const envelope = event ? Math.max(0, Math.min(1, (t - event.start) / event.fade, (event.end - t) / event.fade)) : 0;
      let light;
      if (scene) {
        saved = scene.getImageData(Math.floor(slot.x), Math.floor(slot.y), Math.ceil(slot.w), Math.ceil(slot.h));
        light = luminance(saved.data) >= 140;
      } else {
        const bitmap = await createImageBitmap(await (await fetch(sample)).blob());
        const probe = document.createElement('canvas'); probe.width = bitmap.width; probe.height = bitmap.height;
        const p = probe.getContext('2d'); p.drawImage(bitmap, 0, 0); light = luminance(p.getImageData(0, 0, probe.width, probe.height).data) >= 140;
        bitmap.close();
      }
      const tone = light ? 'path' : 'lighter';
      ctx.clearRect(0, 0, W, H);
      const centerX = W - right - diameter / 2, centerY = top + diameter / 2;
      ctx.save(); ctx.globalAlpha = 1 - envelope;
      ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Consolas, monospace`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.lineWidth = 3 * scale; ctx.strokeStyle = light ? 'rgba(255,255,255,.7)' : 'rgba(0,0,0,.7)';
      ctx.fillStyle = light ? '#20242a' : '#dbe2ea';
      const seconds = Math.floor(t), clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
      ctx.strokeText(clock, centerX, centerY); ctx.fillText(clock, centerX, centerY);
      ctx.restore();
      if (event && envelope > 0) {
        const assetTime = (t - event.start) * 5.5 / (event.end - event.start);
        const frame = Math.min(images[tone].length - 1, Math.floor(assetTime * 24));
        ctx.save(); ctx.globalAlpha = .52 * envelope;
        ctx.drawImage(images[tone][frame], centerX - diameter / 2, top, diameter, diameter); ctx.restore();
      }
      if (scene) {
        scene.save(); scene.resetTransform(); scene.globalAlpha = 1; scene.globalCompositeOperation = 'source-over';
        scene.drawImage(layer, 0, 0); scene.restore();
      } else layer.style.visibility = 'visible';
      window.MOTIONGIT_SIGNATURE_STATE = { time: t, clock, envelope, clockOpacity: 1 - envelope,
        ornamentOpacity: .52 * envelope, corner: 'top-right', tone, diameter, centerX, centerY, clockFontSize: fontSize, rightInset: right, topInset: top, event: event ?? null };
    }
    window.__motiongitSignature = { before, draw, slot, scene: !!scene, hideSourceClocks };
  }, { width, height, duration, fps, selector, mode, windows, frames, sourceHud: options.sourceHud ?? null });
  return {
    before: () => page.evaluate(() => { window.__motiongitSignature.before(); window.__motiongitSignature.hideSourceClocks(); }),
    async draw(time) {
      const state = await page.evaluate(() => {
        window.__motiongitSignature.hideSourceClocks();
        return { scene: window.__motiongitSignature.scene, slot: window.__motiongitSignature.slot };
      });
      let sample;
      if (!state.scene) {
        sample = 'data:image/png;base64,' + (await page.screenshot({ type: 'png', clip: {
          x: state.slot.x, y: state.slot.y,
          width: state.slot.w, height: state.slot.h } })).toString('base64');
      }
      await page.evaluate(({ time, sample }) => window.__motiongitSignature.draw(time, sample), { time, sample });
    },
    receipt: { schema: 'motiongit.output-signature/1', width, height, duration, fps, windows, runtimeSha256: crypto.createHash('sha256').update(fs.readFileSync(fileURLToPath(import.meta.url))).digest('hex'), corner: 'top-right', shape: 'circle',
      portraitInsetsAt1080: { right: 96, top: 88 }, landscapeInsetsAt1080: { right: 64, top: 52 },
      assets: Object.fromEntries(Object.entries(signatureAssets).map(([tone, [file, sha256]]) => [tone, { file, sha256 }])) },
  };
}
