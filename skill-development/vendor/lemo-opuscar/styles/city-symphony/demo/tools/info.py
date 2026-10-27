"""Commons file descriptions (with back-off): python3 -I tools/info.py "File:A" "File:B" ..."""
import json, sys, time, re, urllib.request, urllib.parse
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
q = urllib.parse.urlencode({"action": "query", "titles": "|".join(sys.argv[1:]), "prop": "imageinfo|videoinfo",
     "iiprop": "size|extmetadata|url", "viprop": "derivatives", "format": "json"})
for k in range(6):
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers={"User-Agent": UA}), timeout=60).read()); break
    except Exception as e:
        print("retry", e, file=sys.stderr); time.sleep(15 * (k + 1))
for p in d["query"]["pages"].values():
    ii = p["imageinfo"][0]; em = ii.get("extmetadata", {})
    g = lambda k: re.sub("<[^>]+>", "", em.get(k, {}).get("value", "")).strip()
    print("##", p["title"], ii.get("width"), ii.get("height"), round(ii.get("size",0)/1e6,1), "MB", g("LicenseShortName"))
    print("  artist:", g("Artist")[:150], "| date:", g("DateTimeOriginal")[:40])
    print("  desc:", g("ImageDescription")[:500].replace("\n", " "))
    for dv in p.get("videoinfo", [{}])[0].get("derivatives", []):
        if "1080p" in dv.get("src","") or "720p" in dv.get("src",""): print("  deriv:", dv["src"])
