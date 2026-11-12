"""Sonde : quelles sources gratuites de cotes repondent depuis GitHub Actions ? (aucun credit)"""
import json
import urllib.request

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
TESTS = {
    "unibet_nba": "https://eu-offering-api.kambicdn.com/offering/v2018/ubfr/listView/basketball/nba.json?lang=fr_FR&market=FR&useCombined=true",
    "unibet_tennis": "https://eu-offering-api.kambicdn.com/offering/v2018/ubfr/listView/tennis.json?lang=fr_FR&market=FR&useCombined=true",
    "unibet_ligue1": "https://eu-offering-api.kambicdn.com/offering/v2018/ubfr/listView/football/france/ligue_1.json?lang=fr_FR&market=FR&useCombined=true",
    "espn_nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "espn_atp": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard",
}
for name, url in TESTS.items():
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30) as r:
            d = json.load(r)
        if "events" in d and name.startswith("unibet"):
            evs = d["events"]
            print(name, "OK", len(evs), "evenements")
            for e in evs[:3]:
                ev = e["event"]
                offers = e.get("betOffers", [])
                odds = [(o.get("label") or o.get("englishLabel"), o["odds"] / 1000) for b in offers[:1] for o in b.get("outcomes", []) if "odds" in o]
                print("  ", ev.get("name"), ev.get("start"), "|", b.get("criterion", {}).get("label") if offers else "", odds)
            if evs:
                eid = evs[0]["event"]["id"]
                url2 = f"https://eu-offering-api.kambicdn.com/offering/v2018/ubfr/betoffer/event/{eid}.json?lang=fr_FR&market=FR"
                with urllib.request.urlopen(urllib.request.Request(url2, headers={"User-Agent": UA}), timeout=30) as r2:
                    d2 = json.load(r2)
                labs = sorted({b.get("criterion", {}).get("label", "?") for b in d2.get("betOffers", [])})
                print("   marches du 1er match :", len(labs), labs[:25])
        elif "events" in d:
            e = d["events"][:2]
            print(name, "OK", len(d["events"]), "evenements", [ (x.get("name"), (x.get("competitions") or [{}])[0].get("odds", [{}])[0:1]) for x in e])
        else:
            print(name, "OK mais format inconnu", list(d)[:8])
    except Exception as ex:
        print(name, "ECHEC", ex)
