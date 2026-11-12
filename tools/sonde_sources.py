"""Sonde : l'offre Unibet (Kambi) repond-elle depuis GitHub Actions ? (aucun credit)"""
import json
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
HOSTS = ["https://eu-offering-api.kambicdn.com", "https://eu1.offering-api.kambicdn.com", "https://eu.offering-api.kambicdn.com"]
OPS = ["ubfr", "ub", "unibetfr"]
PATHS = ["/listView/basketball/nba.json", "/listView/tennis/all/all/all/matches.json", "/listView/basketball/nba/all/all/matches.json"]
QS = ["lang=fr_FR&market=FR", "lang=fr_FR&market=FR&client_id=2&channel_id=1&useCombined=true", "lang=en_GB&market=GB&client_id=2&channel_id=1"]
seen = 0
for h in HOSTS:
    for op in OPS:
        for p in PATHS:
            for q in QS:
                url = f"{h}/offering/v2018/{op}{p}?{q}"
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "Origin": "https://www.unibet.fr", "Referer": "https://www.unibet.fr/"}), timeout=20) as r:
                        d = json.load(r)
                    evs = d.get("events", [])
                    print("OK", url, len(evs))
                    for e in evs[:2]:
                        bo = e.get("betOffers", [])
                        print("   ", e["event"].get("name"), [(o.get("label"), o.get("odds", 0) / 1000) for b in bo[:1] for o in b.get("outcomes", [])])
                    seen += 1
                except urllib.error.HTTPError as ex:
                    body = ex.read()[:160]
                    print(ex.code, url, body)
                except Exception as ex:
                    print("ERR", url, ex)
                if seen >= 3:
                    raise SystemExit
