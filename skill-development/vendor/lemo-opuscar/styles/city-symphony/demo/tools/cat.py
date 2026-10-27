"""List Commons category members (with 429 back-off): python3 -I tools/cat.py "Category:X" [file|subcat] """
import json, sys, time, urllib.request, urllib.parse
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
def get(params):
    q = urllib.parse.urlencode({**params, "format": "json"})
    for k in range(6):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers={"User-Agent": UA}), timeout=60).read())
        except Exception as e:
            print("retry", e, file=sys.stderr); time.sleep(15 * (k + 1))
cat, typ = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "file")
if typ == "subcat":
    d = get({"action": "query", "list": "categorymembers", "cmtitle": cat, "cmtype": "subcat", "cmlimit": 200})
    for m in d["query"]["categorymembers"]: print(m["title"])
else:
    d = get({"action": "query", "generator": "categorymembers", "gcmtitle": cat, "gcmtype": "file", "gcmlimit": 100,
             "prop": "imageinfo", "iiprop": "size|mime|extmetadata"})
    for p in (d or {}).get("query", {}).get("pages", {}).values():
        ii = p["imageinfo"][0]; em = ii.get("extmetadata", {})
        print(f'{p["title"]}\t{ii.get("width")}x{ii.get("height")}\t{ii.get("duration",0):.0f}s\t{em.get("LicenseShortName",{}).get("value","")}')
