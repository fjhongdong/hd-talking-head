#!/bin/sh
# Font subsets (OFL, Google Fonts CSS API): the character set is taken automatically from main.js; after changing any on-screen text, delete fonts/*.woff2 and rerun
set -e
H=$(cd "$(dirname "$0")/.." && pwd); D=$H/fonts; mkdir -p "$D"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
TXT=$(python3 -c "
import urllib.parse,sys
s=open('$H/main.js',encoding='utf-8').read()
cs=set(c for c in s if ord(c)>126)|set(chr(i) for i in range(32,127))
print(urllib.parse.quote(''.join(sorted(cs))))")
font() { [ -s "$D/$2" ] && return 0
  url=$(curl -fsS -A "$UA" "https://fonts.googleapis.com/css2?$1&text=$TXT" | grep -o 'https://[^)]*' | head -1); curl -fsS -o "$D/$2" "$url"; echo "font $2"; }
font "family=Noto+Sans+SC:wght@900" sanssc900.woff2
font "family=Noto+Sans+SC:wght@700" sanssc700.woff2
font "family=Barlow+Condensed:wght@800" barlow800.woff2
font "family=Barlow+Condensed:wght@600" barlow600.woff2
font "family=Barlow+Condensed:ital,wght@1,600" barlow600i.woff2
font "family=IBM+Plex+Mono:wght@500" plexmono500.woff2
