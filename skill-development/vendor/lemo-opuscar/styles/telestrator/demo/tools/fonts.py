#!/usr/bin/env python3
"""Fetches subset woff2 files from Google Fonts (all OFL) into fonts/, covering only the characters actually used in the page and the timeline. If you change any text in the film, delete fonts/*.woff2 and fetch again."""
import re, sys, urllib.parse, urllib.request, os
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(D, 'index.html'), encoding='utf-8').read() + open(os.path.join(D, 'timeline.json'), encoding='utf-8').read()
chars = ''.join(sorted(set(src) - set('\n\r\t'))) + '0123456789.:′–—…→≈·'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
JOBS = [('sans500', 'Noto Sans SC:wght@500'), ('sans700', 'Noto Sans SC:wght@700'), ('sans900', 'Noto Sans SC:wght@900'),
        ('cond800i', 'Barlow Condensed:ital,wght@1,800'), ('cond600', 'Barlow Condensed:wght@600'),
        ('mono500', 'IBM Plex Mono:wght@500')]
os.makedirs(os.path.join(D, 'fonts'), exist_ok=True)
for name, fam in JOBS:
    url = 'https://fonts.googleapis.com/css2?' + urllib.parse.urlencode({'family': fam, 'text': chars, 'display': 'block'})
    css = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60).read().decode()
    urls = re.findall(r'url\((https://[^)]+)\)', css)
    if not urls: sys.exit(f'no font url for {fam}')
    data = urllib.request.urlopen(urllib.request.Request(urls[0], headers={'User-Agent': UA}), timeout=60).read()
    open(os.path.join(D, f'fonts/{name}.woff2'), 'wb').write(data); print(name, len(data), 'bytes', len(urls), 'part(s)')
