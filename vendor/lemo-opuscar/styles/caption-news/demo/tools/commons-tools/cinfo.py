"""Look up size, licence, author and description for several Commons files at once (fewer requests, avoids 429). Usage: python3 cinfo.py titles.txt"""
import json, sys, time, re, urllib.request, urllib.parse
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
titles = [l.strip() for l in open(sys.argv[1]) if l.strip()]
g = lambda m, k: re.sub("<[^>]+>", "", m.get(k, {}).get("value", "")).strip()
for i in range(0, len(titles), 40):
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join(titles[i:i+40]), "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "format": "json"})
    for k in range(5):
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers={"User-Agent": UA}), timeout=60).read()); break
        except Exception as e:
            print("retry", e, file=sys.stderr); time.sleep(20 * (k + 1))
    for p in d["query"]["pages"].values():
        ii = (p.get("imageinfo") or [{}])[0]; m = ii.get("extmetadata", {})
        print(f"{p['title']}\n   {ii.get('size',0)/1e6:.0f}MB {ii.get('width')}x{ii.get('height')} {ii.get('duration',0) or 0:.0f}s | {g(m,'LicenseShortName')} | {g(m,'Artist')[:80]} | {g(m,'ImageDescription')[:260]}")
    time.sleep(3)
