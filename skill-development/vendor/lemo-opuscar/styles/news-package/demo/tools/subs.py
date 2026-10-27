"""main.js CUES (Chinese line / English line) → out/cues.json → ../news-package.srt (external subtitles; nothing is burned into the picture)."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.environ.get('LIB', os.path.abspath(os.path.join(HERE, '../../..')))
src = open(os.path.join(HERE, 'main.js'), encoding='utf-8').read()
block = src[src.index('const CUES = ['):src.index('];', src.index('const CUES = ['))]
cues = []
for m in re.finditer(r"\[([\d.]+), ([\d.]+), '((?:[^'\\]|\\.)*)', (['\"])(.*?)\4\]", block):
    cues.append({'t0': float(m[1]), 't1': float(m[2]), 'text': m[3] + '\n' + m[5].replace("\\'", "'")})
for c in cues:
    zh, en = c['text'].split('\n')
    width = sum(1 if ord(ch) > 0x2e80 else .5 for ch in zh)        # CJK = 1, Latin/space = 0.5
    assert width <= 24 and len(en) <= 62, ('line too long for one line', c)
os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
p = os.path.join(HERE, 'out', 'cues.json'); json.dump(cues, open(p, 'w'), ensure_ascii=False, indent=1)
subprocess.run([sys.executable, os.path.join(LIB, 'core/render/srt.py'), p, os.path.join(HERE, '..', 'news-package.srt')], check=True)
print(len(cues), 'cues')
