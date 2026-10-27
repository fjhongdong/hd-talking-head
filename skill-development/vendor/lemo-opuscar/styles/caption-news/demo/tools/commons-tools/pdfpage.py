"""Commons PDF/DJVU page via thumbnail API. preview: pdfpage.py prev "File:X.pdf" outdir w p1 p2 ...
fetch (recorded via footage.py): pdfpage.py fetch "File:X.pdf" page width name"""
import json, sys, time, urllib.parse, urllib.request, os, re, subprocess
UA = "lemo-opuscar/1.0 (https://github.com/lemomo-ai/lemo-opuscar)"
def info(t, page, w):
    q = urllib.parse.urlencode({"action": "query", "titles": t, "prop": "imageinfo", "iiprop": "url|extmetadata",
                                "iiurlwidth": w, "iiurlparam": f"page{page}-{w}px", "format": "json"})
    for k in range(6):
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request("https://commons.wikimedia.org/w/api.php?" + q, headers={"User-Agent": UA}), timeout=60).read())
            return next(iter(d["query"]["pages"].values()))["imageinfo"][0]
        except Exception as e:
            print("retry", e, file=sys.stderr); time.sleep(15 * (k + 1))
mode, t = sys.argv[1], sys.argv[2]
if mode == "prev":
    out, w = sys.argv[3], sys.argv[4]; os.makedirs(out, exist_ok=True)
    for p in sys.argv[5:]:
        u = info(t, p, w)["thumburl"]
        for k in range(5):
            try:
                open(f"{out}/pg{int(p):02d}.jpg", "wb").write(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read()); print(p); break
            except Exception as e:
                print("retry", e, file=sys.stderr); time.sleep(15 * (k + 1))
        time.sleep(3)
else:
    page, w, name = sys.argv[3], sys.argv[4], sys.argv[5]
    ii = info(t, page, w); m = ii.get("extmetadata", {})
    g = lambda k: re.sub("<[^>]+>", "", m.get(k, {}).get("value", "")).strip()
    kit = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../footage.py")
    for k in range(5):
        r = subprocess.run(["python3", kit, "fetch", ii["thumburl"], "--name", name, "--page", ii["descriptionurl"],
                            "--license", g("LicenseShortName") or g("License"), "--credit", (g("Artist") or g("Credit"))[:200],
                            "--title", f"{t} (page {page})", "--date", g("DateTimeOriginal")[:60]], capture_output=True, text=True)
        if r.returncode == 0: print(r.stdout.strip().splitlines()[-1]); break
        print("fetch retry", r.stderr.strip().splitlines()[-1:], file=sys.stderr); time.sleep(30 * (k + 1))
