import assert from 'node:assert/strict';
import {cp, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {validateAduTextGeometry} from '../scripts/adu_text_geometry.mjs';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const require = createRequire(import.meta.url);
const {chromium} = require(path.join(project, 'skill-development/runtime/adu-native/node_modules/playwright-core'));
const temp = await mkdtemp(path.join(os.tmpdir(), 'adu-geometry-test-'));
const browser = await chromium.launch({executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true, args: ['--allow-file-access-from-files']});
try {
  const board = path.join(temp, 'board');
  await cp(path.join(project, 'skill-development/vendor/adu-motion-video/template'), board, {recursive: true});
  for (const [name, text] of Object.entries({'talkmap.js': 'window.TALKF=[];window.TALKMAP=[];',
    'face.js': 'window.FACE={};', 'subs.js': 'window.SUBS=[];', 'wall.js': 'window.WALL=[];'})) {
    await writeFile(path.join(board, name), text);
  }
  await writeFile(path.join(board, 'config.js'), await readFile(path.join(board, 'config.js'), 'utf8') +
    '\nObject.assign(CONFIG,{brand:"",account:"",demo:false,subtitles:false,end:7,talkFrames:0,race:{labels:[],keys:[0,7]}});');
  await writeFile(path.join(board, 'scenes.js'), 'TPL.compare({t0:0,t1:7,left:{title:"独家秘籍",items:["藏提示词"]},' +
    'right:{title:"制作过程",items:["公开"]},stamp:"越来越难",leftAt:0,rightAt:0.666667,strikeAt:4.666667,bg:"paper",cam:"none",race:false,tag:" ",trans:null});');
  await writeFile(path.join(temp, 'index.html'), '<style>body{margin:0}iframe{border:0;position:absolute;top:430px;' +
    'width:1920px;height:1080px;transform:scale(.5625);transform-origin:top left}</style><iframe id="board" src="board/index.html"></iframe>');
  const page = await browser.newPage({viewport: {width: 1080, height: 1920}});
  await page.route('**/*', route => route.request().url().startsWith('file:') ? route.continue() : route.abort());
  await page.goto(pathToFileURL(path.join(temp, 'index.html')).href);
  await page.waitForFunction(() => !!document.querySelector('iframe').contentWindow.renderAt);
  await page.evaluate(async () => {await document.querySelector('iframe').contentWindow.READY;});
  for (const [title, body, passes] of [[80, 60, false], [64, 48, true], [64, 56, true]]) {
    await page.evaluate(async ({title, body}) => {
      const frame = document.querySelector('iframe');
      let style = frame.contentDocument.getElementById('test-fonts');
      if (!style) {style = frame.contentDocument.createElement('style'); style.id = 'test-fonts'; frame.contentDocument.head.appendChild(style);}
      style.textContent = `.card > div:nth-child(2){font-size:${title/.5625}px!important}.card > div:nth-child(n+3){font-size:${body/.5625}px!important}`;
      await frame.contentDocument.fonts.ready;
      frame.contentWindow.renderAt(2);
    }, {title, body});
    const check = () => page.evaluate(source => {
      const validate = (0, eval)('(' + source + ')');
      return validate(document.querySelector('iframe'));
    }, validateAduTextGeometry.toString());
    if (passes) {
      const result = await check();
      assert.equal(result.coordinate_space, 'final_canvas');
      assert.equal(result.boxes.length, 4);
      assert.ok(result.boxes.every(box => box.left >= 0 && box.right <= 1080 && box.top >= 430));
    } else {
      await assert.rejects(check, /overlapping glyphs/);
    }
    assert.equal(await page.evaluate(() => document.querySelector('iframe').contentDocument.querySelectorAll('.card span').length), 0);
    process.stdout.write(`${title}/${body}: ${passes ? 'clear glyphs accepted' : 'collision rejected'}\n`);
  }
} finally {
  await browser.close();
  await rm(temp, {recursive: true, force: true});
}
