# Assembles main.js = the first 109 lines of main_v1.js (palette / beat helpers / shared visuals, switched to 150 BPM and 93 bars) + the character library from main_v1 (robotDB … up to the stage section) + main_b.js (all scenes of the second and third cuts)
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
L = open('main_v1.js', encoding='utf-8').read().split('\n')
segA = '\n'.join(L[0:109]).replace('const BPM = 140,', 'const BPM = 150,').replace('const END_BAR = 61;', 'const END_BAR = 93;')
start = next(i for i, l in enumerate(L) if l.startswith('function robotDB')); end = next(i for i, l in enumerate(L) if l.startswith('// 舞台')) - 1
open('main.js', 'w', encoding='utf-8').write(segA + '\n' + '\n'.join(L[start:end]) + '\n' + open('main_b.js', encoding='utf-8').read())
