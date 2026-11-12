"""Sonde (aucun credit) : structure Kambi NBA / tennis et tableaux ESPN, sauvegardes en artefact."""
import json, os, urllib.request
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
os.makedirs("sonde", exist_ok=True)
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30))
K = "https://eu-offering-api.kambicdn.com/offering/v2018/ub"
Q = "lang=fr_FR&market=FR"
for name, path in [("nba", "/listView/basketball/nba/all/all/matches.json"), ("tennis", "/listView/tennis/all/all/all/matches.json")]:
    d = get(f"{K}{path}?{Q}")
    json.dump(d, open(f"sonde/kambi_{name}.json", "w"))
    evs = d.get("events", [])
    print(name, len(evs), "evenements")
    for e in evs[:40]:
        ev = e["event"]
        print("  ", ev.get("group"), "|", ev.get("path", [{}])[-1].get("englishName") if ev.get("path") else "", "|", ev["name"], ev.get("start"), ev.get("state"))
    if evs:
        eid = evs[0]["event"]["id"]
        d2 = get(f"{K}/betoffer/event/{eid}.json?{Q}")
        json.dump(d2, open(f"sonde/kambi_{name}_event.json", "w"))
        for b in d2.get("betOffers", [])[:60]:
            print("     ", b.get("criterion", {}).get("label"), "|", b.get("criterion", {}).get("englishLabel"), "|", b.get("betOfferType", {}).get("englishName"),
                  [(o.get("label"), o.get("line"), o.get("odds")) for o in b.get("outcomes", [])][:4], "main" if b.get("tags") and "MAIN_LINE" in b.get("tags") else b.get("tags"))
for name, u in [("espn_nba", "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261111"),
                ("espn_atp", "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=20261111"),
                ("espn_wta", "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard?dates=20261108")]:
    d = get(u)
    json.dump(d, open(f"sonde/{name}.json", "w"))
    print(name, len(d.get("events", [])))
