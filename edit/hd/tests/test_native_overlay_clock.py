"""Real pinned HyperFrames runtime regression; no video export or service call."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from edit.hd.tools import overlay_alignment
from edit.hd.tools.relation_browser_watchdog import _group_has_live_members, _process_start_identity, _terminate_registered
from edit.hd.tools.overlay_alignment import bind_native_clock, bind_native_slots, _native_events, _clock_budgets

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / '参考项目/B-roll开源方案/hyperframes'
CHECKER = ROOT / 'skill-development/hd-talking-head/scripts/check_native_overlay_clock.mjs'


class NativeOverlayRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def entry(self, name, *, bad_clip=False, old_selector=False, hidden=False):
        directory = self.directory / name
        (directory / 'vendor').mkdir(parents=True)
        shutil.copyfile(SOURCE / 'skills/talking-head-recut/assets/vendor/gsap.min.js', directory / 'vendor/gsap.min.js')
        route = 'hyperframes/before-after-wipe'
        source = (SOURCE / 'registry/components/before-after-wipe/before-after-wipe.html').read_bytes()
        native = bind_native_slots(bind_native_clock(source, route, 4), {
            key: f'<div class="art {key}"><svg width="420" height="160"><rect width="410" height="150" fill="red"/></svg></div>'
            for key in ('before', 'after')})
        (directory / 'native.html').write_bytes(native)
        css = '''.baw-clip{inset:auto!important;left:60px!important;top:70px!important;width:960px!important;height:280px!important}
.baw-chip{top:12px!important;bottom:auto!important;font-size:72px!important;padding:0!important}
.baw-before .baw-chip{left:24px!important;right:auto!important}.baw-after .baw-chip{right:24px!important;left:auto!important}
.art{position:absolute;top:108px;width:420px;height:160px}.art.before{left:20px}.art.after{right:20px}
'''
        if not bad_clip:
            css += '.baw-after{clip-path:inset(0 0 0 calc((100 - var(--baw-split))*1%))!important}'
        if old_selector:
            css += '#root .baw-chip{font-size:72px}'
        if hidden:
            css += '.stage{opacity:0!important}'
        values = {'label_a': '只有提示词', 'label_b': '完整材料', 'wipe_at': .5, 'rest_split': 50, 'exit': 'fade'}
        (directory / 'index.html').write_text('<script src="vendor/gsap.min.js"></script><style>' + css +
            '</style><div class="stage" data-duration="4"><div class="mount" data-composition-id="before-after-wipe" ' +
            'data-composition-src="native.html" data-start="0" data-duration="4" data-track-index="1" data-width="1080" data-height="1920" ' +
            "data-variable-values='" + json.dumps(values, ensure_ascii=False) + "' " +
            'style="position:absolute;width:1080px;height:1920px;top:0;left:0"></div></div>')
        events, _ = _native_events(route, {'data-start': '0', 'data-variable-values': json.dumps(values)}, 24, 4)
        return {'entry_directory': str(directory), 'route': route, 'duration': 4, 'start': 0,
                'events': [{'slot': slot, 'kind': kind, 'text': text, 'time': time} for slot, kind, text, time in events]}

    def run_check(self, entries):
        work = self.directory / ('runtime-' + str(len(list(self.directory.glob('runtime-*')))))
        work.mkdir()
        budgets, _ = _clock_budgets(entries)
        return subprocess.run([shutil.which('node'), str(CHECKER)],
            input=json.dumps({'project_root': str(ROOT), 'work_directory': str(work),
                              'python_executable': sys.executable,
                              'entries': [{**entry, 'timeout_ms': round(budget * 1000)}
                                          for entry, budget in zip(entries, budgets)]}),
            capture_output=True, text=True, timeout=60)

    def grid_entry(self, name, *, exit='none', duration=116 / 24, early=False):
        directory = self.directory / name
        (directory / 'vendor').mkdir(parents=True)
        shutil.copyfile(SOURCE / 'skills/talking-head-recut/assets/vendor/gsap.min.js', directory / 'vendor/gsap.min.js')
        route = 'hyperframes/grid-card-assemble'
        source = (SOURCE / 'registry/components/grid-card-assemble/grid-card-assemble.html').read_bytes()
        native = bind_native_clock(source, route, duration)
        if early:
            # Fault injection only in this temporary fixture, never the registry.
            before, after = ((b'duration: TILE,', b'duration: 0.1,') if exit == 'none' else
                             (b'duration: OUT, ease:', b'duration: 0.1, ease:'))
            self.assertIn(before, native)
            native = native.replace(before, after)
        (directory / 'native.html').write_bytes(native)
        values = {'items': '半小时,忙到下班,正经活少', 'layout': 'grid', 'columns': 3,
                  'cues': '1.0416666666666667,2.25,3.375', 'exit': exit}
        (directory / 'index.html').write_text('<script src="vendor/gsap.min.js"></script><style>' +
            'html,body{margin:0;width:1080px;height:1920px}.stage{width:1080px;height:1920px}' +
            '.mount{position:absolute;left:60px;top:70px;width:960px;height:300px;overflow:hidden}' +
            '.gca-stage{width:960px!important;grid-auto-rows:230px!important;gap:14px!important}' +
            '.gca-label{font:800 64px/1.25 "PingFang SC",sans-serif!important;letter-spacing:0!important}' +
            '</style><div class="stage" data-composition-id="grid-host-' + name +
            '" data-no-timeline data-width="1080" data-height="1920" data-duration="' + str(duration) + '">' +
            '<div id="grid-mount" class="mount" data-composition-id="grid-card-assemble" data-composition-src="native.html" ' +
            'data-start="0" data-duration="' + str(duration) + '" data-track-index="0" ' +
            "data-variable-values='" + json.dumps(values, ensure_ascii=False) + "'></div></div>")
        events, _ = _native_events(route, {'data-start': '0', 'data-variable-values': json.dumps(values)}, 24, duration)
        return {'entry_directory': str(directory), 'route': route, 'duration': duration, 'start': 0,
                'events': [{'slot': s, 'kind': k, 'text': text, 'time': t} for s, k, text, t in events]}

    def test_grid_native_hold_has_actual_stable_frames_and_preserves_fade_and_other_routes(self):
        result = self.run_check([self.grid_entry('hold'), self.grid_entry('fade', exit='fade'), self.entry('wipe')])
        self.assertEqual(result.returncode, 0, result.stderr)
        hold, fade, wipe = json.loads(result.stdout)['entries']
        self.assertAlmostEqual(hold['timeline_duration'], 4.025)
        self.assertAlmostEqual(hold['requested_duration'], 116 / 24)
        evidence = hold['hold_check']
        self.assertGreaterEqual(evidence['frames_checked'], 12)
        self.assertEqual(len(evidence['pixel_samples']), 3)
        self.assertEqual(len({sample['sha256'] for sample in evidence['pixel_samples']}), 1)
        self.assertGreaterEqual(evidence['samples'][-1] - evidence['samples'][0], .5)
        for row, duration in ((fade, 116 / 24), (wipe, 4)):
            self.assertIsNone(row['hold_check'])
            self.assertAlmostEqual(row['timeline_duration'], duration)

    def test_grid_hold_does_not_accept_early_actions_short_reading_or_short_fade(self):
        for name, kwargs in [('early', {'early': True}), ('short-reading', {'duration': 4.4}),
                             ('short-fade', {'exit': 'fade', 'early': True})]:
            with self.subTest(name=name):
                result = self.run_check([self.grid_entry(name, **kwargs)])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('complete action and reading window' if name != 'short-fade'
                              else 'native duration differs', result.stderr)

    def test_actual_runtime_authors_each_entry_and_preserves_native_clock(self):
        rows = overlay_alignment._assembled_clocks([self.entry('first'), self.entry('second')])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['authored_root_id'], 'root')
            self.assertAlmostEqual(row['timeline_duration'], 4, places=5)
            self.assertTrue(row['temporary_duration_removed'])
            self.assertEqual(row['visibility_checks'][0]['graphic_count'], 1)
            self.assertLessEqual(row['sampled_frames'], 4 * 24 + 3)

    def test_right_content_with_left_clip_is_rejected(self):
        result = self.run_check([self.entry('bad-clip', bad_clip=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('after text is clipped or hidden', result.stderr)

    def test_old_root_selector_is_rejected(self):
        result = self.run_check([self.entry('old-selector', old_selector=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('host CSS targets rewritten #root', result.stderr)

    def test_hidden_ancestor_does_not_count_as_visible_text(self):
        result = self.run_check([self.entry('hidden', hidden=True)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('native content is never visible', result.stderr)

    def test_sampling_work_ignores_unrelated_host_frames(self):
        # Algorithm-only check complements the actual Chrome cases above.
        script = '''
import {SAMPLE} from CHECKER;
async function measure(hostTotal) {
 let time=0,seeks=0;
 const start=3,duration=1,rect={left:0,right:100,top:0,bottom:30};
 const root={parentElement:null,closest:()=>null,getBoundingClientRect:()=>rect,hasAttribute:()=>false,getAttribute:()=> 'root'};
 const mount={querySelectorAll:()=>[root],getAttribute:()=>String(start)};
 globalThis.window={__timelines:{'grid-card-assemble':{duration:()=>duration,time:()=>Math.max(0,Math.min(duration,time-start))}},
 __player:{getDuration:()=>hostTotal,getTime:()=>time,renderSeek:async t=>{time=t;seeks++;}}};
 globalThis.NodeFilter={SHOW_TEXT:4};
 globalThis.getComputedStyle=()=>({display:'block',visibility:'visible',opacity:time>=start&&time<=start+duration?'1':'0',overflowX:'visible',overflowY:'visible',clipPath:'none'});
 globalThis.document={querySelector:s=>s==='.stage'?{getAttribute:()=>String(hostTotal)}:mount,
 createTreeWalker:()=>{let first=true;return{nextNode:()=>first?(first=false,{textContent:'label',parentElement:root}):null};},
 createRange:()=>({selectNodeContents:()=>{},getBoundingClientRect:()=>rect})};
 return {...await SAMPLE({route:'hyperframes/grid-card-assemble',start,duration,events:[]},24),seeks};
}
console.log(JSON.stringify([await measure(10),await measure(120)]));
'''.replace('from CHECKER', 'from ' + json.dumps(CHECKER.as_uri()))
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in json.loads(result.stdout):
            self.assertEqual(row['sampled_frames'], 27)
            self.assertEqual(row['seeks'], 28)
            self.assertEqual(row['sampling_window'], {'first_frame': 71, 'last_frame': 97})
        small, small_total = _clock_budgets([{'duration': 4}])
        large, large_total = _clock_budgets([{'duration': 4}] * 8)
        self.assertGreater(large_total, small_total)
        self.assertEqual(large, small * 8)

    def test_deadlines_reclaim_started_preview_browser_and_work_directory(self):
        original_temporary, original_popen = tempfile.TemporaryDirectory, subprocess.Popen
        for mode in ('startup', 'entry', 'batch'):
            with self.subTest(mode=mode):
                entry = self.entry('stall-' + mode)
                index = Path(entry['entry_directory']) / 'index.html'
                index.write_text(index.read_text() + '<script>Object.defineProperty(document.fonts,"ready",{get:()=>new Promise(()=>{})})</script>')
                created, snapshots, failures = [], {}, []
                done = threading.Event()
                def capture(*args, **kwargs):
                    temporary = original_temporary(*args, **kwargs)
                    created.append(Path(temporary.name))
                    return temporary
                def run():
                    try:
                        overlay_alignment._assembled_clocks([entry])
                    except BaseException as error:
                        failures.append(error)
                    finally:
                        done.set()
                def launch(command, *args, **kwargs):
                    if mode == 'startup' and command[0] == shutil.which('node'):
                        # Fault injection: Chrome really starts, but the SDK
                        # never hands BrowserServer back to the checker.
                        script = 'import {createRequire} from "node:module";import {runCheck} from ' + json.dumps(CHECKER.as_uri()) + ';' + \
                            'const require=createRequire(import.meta.url);const {chromium}=require(' + json.dumps(str(ROOT / 'skill-development/runtime/adu-native/node_modules/playwright-core')) + ');' + \
                            'const launch=chromium.launchServer.bind(chromium);chromium.launchServer=async options=>{await launch(options);return new Promise(()=>{});};' + \
                            'let data="";for await(const chunk of process.stdin)data+=chunk;await runCheck(JSON.parse(data));'
                        command = [command[0], '--input-type=module', '-e', script]
                    return original_popen(command, *args, **kwargs)
                budgets = ([6], 20) if mode == 'entry' else ([60], 3 if mode == 'startup' else 8)
                with patch.object(overlay_alignment, '_clock_budgets', return_value=budgets), \
                     patch.object(overlay_alignment.tempfile, 'TemporaryDirectory', side_effect=capture), \
                     patch.object(overlay_alignment.subprocess, 'Popen', side_effect=launch):
                    worker = threading.Thread(target=run, daemon=True)
                    worker.start()
                    wait_until = time.monotonic() + 35
                    while not done.wait(.02) and time.monotonic() < wait_until:
                        if not created:
                            continue
                        for name in ('browser', 'progress'):
                            try:
                                snapshots[name] = json.loads((created[0] / (name + '.json')).read_text())
                            except (OSError, ValueError):
                                pass
                    worker.join(timeout=1)
                    self.assertFalse(worker.is_alive(), 'clock cleanup exceeded the test deadline')
                self.assertEqual(len(failures), 1)
                self.assertIsInstance(failures[0], ValueError)
                self.assertIn('deadline exceeded' if mode == 'entry' else 'timed out', str(failures[0]))
                self.assertIn('browser', snapshots, str(failures[0]))
                progress = snapshots['progress']
                self.assertIn(progress['phase'], {'browser_startup'} if mode == 'startup' else {'runtime_readiness', 'fonts_and_images'})
                self.assertFalse(_group_has_live_members(progress['checker_pid']))
                self.assertFalse(_group_has_live_members(snapshots['browser']['pid']))
                self.assertFalse(any(path.exists() for path in created))

    def test_browser_shim_does_not_exec_after_parent_final_registry_read(self):
        directory = self.directory / 'late-registration'
        directory.mkdir()
        fifo = directory / 'resume'
        os.mkfifo(fifo)
        marker, entered = directory / 'executed', directory / 'entered'
        executable = directory / 'fake-chrome'
        executable.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        executable.chmod(0o700)
        config = directory / 'launch.json'
        shim = CHECKER.with_name('clock_browser_exec.py')
        child_script = '''
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('clock_child',sys.argv[1]);child=importlib.util.module_from_spec(spec);spec.loader.exec_module(child)
identity=child._process_start_identity
entered,resume=Path(sys.argv[3]),Path(sys.argv[4])
def delayed(pid):
 entered.write_text('entered');resume.read_bytes();return identity(pid)
child._process_start_identity=delayed
sys.argv=[sys.argv[1],sys.argv[2]]
raise SystemExit(child.main())
'''
        parent_script = '''
import json,os,subprocess,sys,time
from pathlib import Path
config=Path(sys.argv[1]);config.write_text(json.dumps({'parent_pid':os.getpid(),'work_directory':str(config.parent),'executable':sys.argv[2]}))
child=subprocess.Popen([sys.executable,'-c',sys.argv[3],sys.argv[4],str(config),sys.argv[5],sys.argv[6]],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
deadline=time.monotonic()+5
while not Path(sys.argv[5]).exists() and time.monotonic()<deadline:time.sleep(.01)
print(child.pid)
'''
        result = subprocess.run([sys.executable, '-c', parent_script, str(config), str(executable),
            child_script, str(shim), str(entered), str(fifo)], capture_output=True, text=True, timeout=7)
        self.assertEqual(result.returncode, 0, result.stderr)
        pid = int(result.stdout.strip())
        identity = _process_start_identity(pid)
        try:
            self.assertTrue(entered.exists())
            self.assertFalse((directory / 'browser.json').exists())  # Parent's final read.
            with fifo.open('wb') as resume:
                resume.write(b'go')
            deadline = time.monotonic() + 5
            while _group_has_live_members(pid) and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertFalse(_group_has_live_members(pid))
            self.assertTrue((directory / 'browser.json').exists())  # Late registration.
            self.assertFalse(marker.exists())
        finally:
            if identity is not None:
                _terminate_registered({pid: identity})
