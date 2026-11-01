#!/usr/bin/env python3
"""Optional Chinese narration with Doubao TTS 2.0 (Volcengine seed-tts-2.0). The library default is Kokoro (core/tts/tts.py).

Needs your own API key in the environment: DOUBAO_API_KEY (Volcengine speech console → API Key).
The key is read at run time only; it is never printed or written anywhere.

Reads lines.json: [{id, text, say?, speaker?, speech_rate?}] — `say` is what is spoken when it differs
from `text` (names respelled for the voice, numbers written out); speech_rate −50…100, 0 = normal.
Writes <out>/<id>.wav (24 kHz mono, leading/trailing silence trimmed) and <out>/dur.json — the same
outputs as core/tts/tts.py, so core/tts/asr_check.py works on them. Each line is cached by
(speaker, rate, text) in <out>/.doubao/; delete a cached mp3 to get a new take (every take differs).

Usage: python3 tts_doubao.py lines.json out_dir [--speaker zh_male_m191_uranus_bigtts] [ids …]
"""
import argparse, base64, hashlib, json, os, subprocess, sys, urllib.request, uuid
import numpy as np

URL = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional'
RESOURCE = 'seed-tts-2.0'          # 2.0 voices only: zh_*_uranus_bigtts


def synth(key, text, speaker, rate, path):
    body = json.dumps({'user': {'uid': 'lemo-opuscar'}, 'req_params': {'text': text, 'speaker': speaker,
            'audio_params': {'format': 'mp3', 'sample_rate': 24000, 'speech_rate': rate}}}).encode()
    req = urllib.request.Request(URL, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'X-Api-Key': key, 'X-Api-Resource-Id': RESOURCE, 'X-Api-Request-Id': str(uuid.uuid4())})
    audio = bytearray()
    with urllib.request.urlopen(req, timeout=120) as r:
        dec = json.JSONDecoder(); buf = r.read().decode('utf-8', 'ignore'); i = 0
        while i < len(buf):                                  # the reply is a stream of JSON objects
            while i < len(buf) and buf[i] in ' \r\n\t': i += 1
            if i >= len(buf): break
            obj, i = dec.raw_decode(buf, i)
            if obj.get('data'): audio += base64.b64decode(obj['data'])
            elif obj.get('code') not in (None, 0, 20000000):
                raise SystemExit(f"Doubao error {obj.get('code')}: {str(obj.get('message'))[:160]}")
    if len(audio) < 1000: raise SystemExit('Doubao returned no audio')
    open(path, 'wb').write(audio)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('lines'); ap.add_argument('out'); ap.add_argument('ids', nargs='*')
    ap.add_argument('--speaker', default='zh_male_m191_uranus_bigtts')
    a = ap.parse_args()
    key = os.environ.get('DOUBAO_API_KEY', '')
    if not key: raise SystemExit('set DOUBAO_API_KEY (your own Doubao TTS key), or use core/tts/tts.py (Kokoro)')
    lines = json.load(open(a.lines, encoding='utf-8'))
    cache = os.path.join(a.out, '.doubao'); os.makedirs(cache, exist_ok=True)
    durp = os.path.join(a.out, 'dur.json'); dur = json.load(open(durp)) if os.path.exists(durp) else {}
    import soundfile as sf
    for L in lines:
        if a.ids and L['id'] not in a.ids: continue
        say, spk, rate = L.get('say', L['text']), L.get('speaker', a.speaker), int(L.get('speech_rate', 0))
        h = hashlib.sha1(f'{spk}|{rate}|{say}'.encode()).hexdigest()[:10]
        mp3 = os.path.join(cache, f"{L['id']}-{h}.mp3")
        if not os.path.exists(mp3): synth(key, say, spk, rate, mp3)
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', mp3, '-ac', '1', '-ar', '24000', '-f', 's16le', '-'], capture_output=True, check=True).stdout
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
        e = np.sqrt(np.convolve(x ** 2, np.ones(240) / 240, 'same'))
        on = np.where(e > 10 ** (-42 / 20))[0]
        y = x[max(0, on[0] - 240):min(len(x), on[-1] + 2400)].copy(); f = min(len(y), 1200); y[-f:] *= np.linspace(1, 0, f)
        sf.write(os.path.join(a.out, f"{L['id']}.wav"), y, 24000, subtype='PCM_16')
        dur[L['id']] = round(len(y) / 24000, 3)
        print(f"{L['id']:4s} {spk} rate {rate:+d}  {dur[L['id']]:.2f} s  {say}")
    json.dump(dur, open(durp, 'w'), indent=1)


if __name__ == '__main__':
    main()
