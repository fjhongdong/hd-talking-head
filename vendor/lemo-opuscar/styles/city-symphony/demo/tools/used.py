"""From the shot list, work out which seconds of each source are used and where they sit in the film, write that back into the `used` field of SOURCES.jsonl, then generate SOURCES.md.
Usage: python tools/used.py"""
import os, sys, json, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.chdir(os.path.join(HERE, '..'))
from shots import SHOTS, CLIPS, GRID_STAGES
from prep import speed_curve
from timeline import GRID, BRAKE

RAW = {'sky': 'sky23', 'nyim': 'nyim', 'b99': 'br1899', 'empty': 'empty', 'pcm': 'pcm', 'cav': 'cav', 'mbn': 'mbn', 'fw': 'fw16',
       'kel': 'kel', 'sun': 'sunfox', 'earth': 'earth'}
use = {}


def add(name, s): use.setdefault(name, []).append(s)


def span(cid):
    c = CLIPS[cid]; e = speed_curve(c['speed'], c['n'])
    return c['s0'], c['s0'] + e[-1]


for s in SHOTS:
    k = s['kind']
    if k == 'clip':
        a, b = span(s['id']); sp = CLIPS[s['id']]['speed']
        sp = f'{sp}×' if isinstance(sp, (int, float)) else '速度坡 ' + '→'.join(f'{v}×' for _, v in sp)
        add(RAW[CLIPS[s['id']]['src']], f"{a:.1f}–{b:.1f} s（{sp}）→ 片中 {s['t0']:.2f}–{s['t1']:.2f}")
    elif k == 'photo':
        for nm in s['names']: add(nm, f"片中 {s['t0']:.2f}–{s['t1']:.2f}")
    elif k == 'split':
        for side in ('left', 'right'):
            a, b = span(s[side]); add(RAW[CLIPS[s[side]]['src']], f"{a:.1f}–{b:.1f} s（分屏{'左' if side == 'left' else '右'}）→ 片中 {s['t0']:.2f}–{s['t1']:.2f}")
    elif k == 'flicker':
        for cid in (s['a'], s['b']):
            a, b = span(cid); add('sky23', f"{a:.0f}–{b:.0f} s（日夜每 2 帧交替）→ 片中 {s['t0']:.2f}–{s['t1']:.2f}")
    elif k == 'page':
        add('lg380', f"片中 {s['t0']:.2f}–{s['t1']:.2f} 书页；引文出自本页第 6 节")
pool = sorted({c for st in GRID_STAGES for c in st[3]})
for cid in pool:
    a, b = span(cid); add(RAW[CLIPS[cid]['src']], f"{a:.1f}–{b:.1f} s（网格格子）→ 片中 {GRID:.1f}–{BRAKE:.1f}")

recs = [json.loads(l) for l in open('SOURCES.jsonl') if l.strip()]
for r in recs:
    r['used'] = use.get(r['name'], [])
    if r['name'] in ('nyim',): r['used'].append('全部镜头居中放大 1.18 倍，把作者左上角台标推出画外')
    if r['name'] == 'fw16' and r['used']: r['used'].append('以上秒数从截取段（原片 100–200 s）起算，原片时间 = +100 s')
    if r['name'] == 'empty' and r['used']: r['used'].append('裁成 1804×1014（左 58 px 起、顶端对齐）再放大，把右下角水印裁出画外')
open('SOURCES.jsonl', 'w').write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in recs))
unused = [r['name'] for r in recs if not r['used']]
if unused: print('⚠ 没用到：', unused)
subprocess.run(['python3', 'tools/footage.py', 'md'], check=True)
