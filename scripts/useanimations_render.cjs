// The official Lottie data owns the animation. This host only positions it,
// samples it on the parent timeline and optionally shows a spoken label.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const args = process.argv.slice(2);
function argument(name) {
  const index = args.indexOf(name);
  if (index < 0 || !args[index + 1]) throw new Error('Missing ' + name);
  return args[index + 1];
}

async function render() {
  const brief = JSON.parse(fs.readFileSync(argument('--brief'), 'utf8'));
  const data = JSON.parse(fs.readFileSync(argument('--icon'), 'utf8'));
  const { chromium } = require(argument('--playwright'));
  const { width, height, frames, fps } = brief.composition;
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'useanimations-render-'));
  let browser;

  try {
    browser = await chromium.launch({ headless: true, executablePath: argument('--chrome') });
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    await page.setContent(`<meta charset="utf-8"><style>
      html, body { margin: 0; background: transparent; }
      #card {
        position: absolute; display: inline-flex; align-items: center;
        background: #fffefa; border-radius: 22px; color: #182638;
      }
      #tile {
        display: grid; place-items: center; background: #fff0d9;
        border-radius: 20px; flex: none; overflow: hidden;
      }
      #card.complete #tile { background: #dff2e8; }
      #icon { width: 78%; height: 78%; }
      #label {
        font: 700 48px/1.25 'PingFang SC', sans-serif;
        padding: 0 24px; white-space: nowrap;
      }
    </style><div id="card"><div id="tile"><div id="icon"></div></div>
    <span id="label" hidden></span></div>`);
    await page.addScriptTag({ path: argument('--lottie') });
    await page.evaluate(async ({ brief, data }) => {
      const card = document.getElementById('card');
      const tile = document.getElementById('tile');
      const label = document.getElementById('label');
      const { x, y, size } = brief.layout;
      Object.assign(card.style, { left: x + 'px', top: y + 'px' });
      Object.assign(tile.style, { width: size + 'px', height: size + 'px' });
      const animation = lottie.loadAnimation({
        container: document.getElementById('icon'), renderer: 'svg',
        loop: false, autoplay: false, animationData: data,
      });
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Lottie load timed out')), 10000);
        animation.addEventListener('DOMLoaded', () => {
          clearTimeout(timeout);
          resolve();
        });
      });
      await document.fonts.ready;
      const { width, height, fps } = brief.composition;
      const zone = brief.parent_safe_zone;
      function showLabel(text, completed) {
        label.textContent = text;
        label.hidden = !text;
        card.classList.toggle('complete', completed);
      }
      for (const { text } of brief.labels) {
        showLabel(text, false);
        const box = card.getBoundingClientRect();
        if (box.left < zone.left || box.top < zone.top || box.right > width - zone.right
            || box.bottom > height - zone.bottom) {
          throw new Error('Visible useAnimations label exceeds the parent safe zone');
        }
      }
      window.renderOverlay = frame => {
        const nativeFrame = Math.min(animation.totalFrames - 0.001, frame * animation.frameRate / fps);
        animation.goToAndStop(nativeFrame, true);
        const state = brief.labels.findLastIndex(item => item.start_frame <= frame);
        showLabel(state >= 0 ? brief.labels[state].text : '', state > 0);
      };
    }, { brief, data });

    for (let frame = 0; frame < frames; frame += 1) {
      await page.evaluate(frame => window.renderOverlay(frame), frame);
      await page.screenshot({
        path: path.join(directory, String(frame).padStart(6, '0') + '.png'),
        omitBackground: true,
      });
    }
    const encoded = spawnSync(argument('--ffmpeg'), [
      '-v', 'error', '-framerate', String(fps), '-i', path.join(directory, '%06d.png'),
      '-c:v', 'prores_ks', '-profile:v', '4', '-pix_fmt', 'yuva444p10le',
      '-an', '-y', argument('--output'),
    ], { stdio: 'inherit' });
    if (encoded.error) throw encoded.error;
    if (encoded.status !== 0) throw new Error('FFmpeg failed: ' + encoded.status);
  } finally {
    if (browser) await browser.close();
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

render().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
