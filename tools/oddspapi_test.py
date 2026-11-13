"""Test OddsPapi (2 requetes) : quels marches pour Unibet FR et pour un autre bookmaker francais ?"""
import json, os, urllib.error, urllib.request
KEY = os.environ["ODDSPAPI_KEY"]
def get(path, **q):
    q["apiKey"] = KEY
    url = "https://api.oddspapi.io/v4" + path + "?" + "&".join(f"{k}={v}" for k, v in q.items())
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "paris-foot"}), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("ERREUR", path, e.code, e.read()[:300]); return []
for bk in ("winamax.fr", "betclic.fr"):
    d = get("/odds-by-tournaments", bookmaker=bk, tournamentIds="34", oddsFormat="decimal")
    n = [len(((f.get("bookmakerOdds") or {}).get(bk) or {}).get("markets") or {}) for f in d]
    print(bk, len(d), "matchs, marches par match :", n[:12])
    if d:
        f = d[0]; m = ((f.get("bookmakerOdds") or {}).get(bk) or {}).get("markets") or {}
        print("  marches du 1er match :", list(m.keys())[:40])
