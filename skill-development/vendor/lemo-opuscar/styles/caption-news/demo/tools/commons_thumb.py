"""Commons thumbnail download (for when the original is rate-limited with 429): python3 tools/commons_thumb.py "File:X.jpg" name width
Query imageinfo for thumburl + licence, then hand it to footage.py fetch <url> to record the source."""
import json, sys, time, urllib.request, urllib.parse, subprocess, os, re
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
t, name, w = sys.argv[1], sys.argv[2], sys.argv[3]
# Commons reliably serves only standard thumbnail widths; other widths keep failing with 429/errors: snap to the nearest standard width (0 = original)
STD = [330, 500, 960, 1280, 1920, 2560, 3840]
if w != "0":
    w = str(min(STD, key=lambda x: abs(x - int(w))))
qa = {"action": "query", "titles": t, "prop": "imageinfo", "iiprop": "url|extmetadata|size", "format": "json"}
if w != "0":
    qa["iiurlwidth"] = w
q = urllib.parse.urlencode(qa)
for k in range(6):
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers={"User-Agent": UA}), timeout=60).read())
        break
    except Exception as e:
        print("retry", e, file=sys.stderr); time.sleep(20 * (k + 1))
p = next(iter(d["query"]["pages"].values()))["imageinfo"][0]
m = p.get("extmetadata", {})
g = lambda k: re.sub("<[^>]+>", "", m.get(k, {}).get("value", "")).strip()
lic = g("LicenseShortName") or g("License")
credit = (g("Artist") or g("Credit"))[:200]
url = p["url"] if w == "0" else (p.get("thumburl") or p["url"])
print(url, lic, credit, p["width"], p["height"])
kit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "footage.py")
for k in range(5):
    r = subprocess.run(["python3", kit, "fetch", url, "--name", name, "--page", p["descriptionurl"], "--license", lic,
                        "--credit", credit, "--title", t, "--date", g("DateTimeOriginal")[:60]], capture_output=True, text=True)
    if r.returncode == 0: print(r.stdout.strip().splitlines()[-1]); break
    print("fetch retry", r.stderr.strip().splitlines()[-1:], file=sys.stderr); time.sleep(30 * (k + 1))
