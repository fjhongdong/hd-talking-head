# export cues.json from the VO subtitle ranges in story.js (same data as the burned-in subtitles)
import re, json, os
D = 'styles/one-line/demo'
src = open(os.path.join(D, 'story.js')).read()
cues = []
for m in re.finditer(r"text: '([^']+)'.*?sub: \[([\d.]+), ([\d.]+)\]", src):
    cues.append({'t0': float(m.group(2)), 't1': float(m.group(3)), 'text': m.group(1)})
json.dump(cues, open(os.path.join(D, 'cues.json'), 'w'), indent=1)
print(len(cues), 'cues')
