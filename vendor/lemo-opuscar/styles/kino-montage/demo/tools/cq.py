"""Commons API query with patient retry (shared IP is rate limited).
usage: python3 cq.py search "<query>" [video|image|any] [n]
       python3 cq.py cat "Category:Xxx" [n]
       python3 cq.py info "File:X.jpg"
"""
import json, sys, time, urllib.request, urllib.parse, re
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
def get(params):
    q = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({**params, "format": "json"})
    for k in range(8):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": UA}), timeout=60).read())
        except Exception as e:
            print("retry", e, file=sys.stderr); time.sleep(15 * (k + 1))
    raise SystemExit("gave up")
g = lambda m, k: re.sub("<[^>]+>", "", m.get(k, {}).get("value", "")).strip()
def show(pages):
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]; m = ii.get("extmetadata", {})
        dur = f"{ii.get('duration', 0):.0f}s " if ii.get("duration") else ""
        print(f"{p['title']}\t{ii.get('width')}x{ii.get('height')} {dur}{ii.get('mime','')}\t{g(m,'LicenseShortName')}\t{g(m,'DateTimeOriginal')[:30]}\t{g(m,'Artist')[:50]}")
cmd = sys.argv[1]
II = {"prop": "imageinfo", "iiprop": "size|mime|extmetadata|url"}
if cmd == "search":
    ft = {"video": " filetype:video", "image": " filetype:bitmap", "audio": " filetype:audio"}.get(sys.argv[3] if len(sys.argv) > 3 else "any", "")
    n = sys.argv[4] if len(sys.argv) > 4 else "25"
    d = get({"action": "query", "generator": "search", "gsrsearch": sys.argv[2] + ft, "gsrnamespace": 6, "gsrlimit": n, **II})
    show(d.get("query", {}).get("pages", {}))
elif cmd == "cat":
    n = sys.argv[3] if len(sys.argv) > 3 else "100"
    d = get({"action": "query", "generator": "categorymembers", "gcmtitle": sys.argv[2], "gcmlimit": n, "gcmtype": "file|subcat", **II})
    show(d.get("query", {}).get("pages", {}))
elif cmd == "info":
    d = get({"action": "query", "titles": sys.argv[2], **II})
    p = next(iter(d["query"]["pages"].values())); ii = p["imageinfo"][0]; m = ii["extmetadata"]
    for k in ["LicenseShortName", "UsageTerms", "Artist", "Credit", "DateTimeOriginal", "ImageDescription", "ObjectName"]:
        print(k, ":", g(m, k)[:400])
    print("url:", ii["url"], ii["width"], ii["height"]); print("page:", ii.get("descriptionurl"))
