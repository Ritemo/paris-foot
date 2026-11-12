"""Mesure la marge des bookmakers francais (Unibet en tete) sport par sport, avec The Odds API.
Usage (GitHub Actions, atelier « Marges ») : liste gratuite des sports, puis 1 credit par competition mesuree.
Marge = 1 - 1 / somme(1/cote) sur le marche « vainqueur » (h2h)."""
import json
import os
import statistics
import urllib.request

KEY = os.environ["ODDS_API_KEY"]
BOOKS = ["unibet_fr", "betclic_fr", "winamax_fr", "pmu_fr"]
MAX = int(os.environ.get("MAX_COMP", "8"))


def get(path, **q):
    q["apiKey"] = KEY
    url = "https://api.the-odds-api.com/v4" + path + "?" + "&".join(f"{k}={v}" for k, v in q.items())
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "paris-foot-marges"}), timeout=40) as r:
        return json.load(r), r.headers.get("x-requests-remaining")


sports, _ = get("/sports")
groups = ("Basketball", "Tennis", "Handball", "Ice Hockey", "Rugby Union", "Volleyball")
active = [s for s in sports if s["group"] in groups and s.get("active") and not s.get("has_outrights")]
print("Competitions ouvertes :", ", ".join(f"{s['key']}" for s in active))
# une ou deux competitions par sport, les plus suivies d'abord
prefer = ["basketball_nba", "basketball_euroleague", "tennis_atp", "tennis_wta", "handball", "icehockey_nhl", "rugbyunion"]
chosen = []
for p in prefer:
    for s in active:
        if s["key"].startswith(p) and s not in chosen and sum(c["key"].startswith(p) for c in chosen) < 1:
            chosen.append(s)
chosen = chosen[:MAX]
res = {}
for s in chosen:
    data, left = get(f"/sports/{s['key']}/odds", regions="fr", markets="h2h", oddsFormat="decimal")
    per = {b: [] for b in BOOKS}
    for ev in data:
        for bk in ev.get("bookmakers", []):
            if bk["key"] not in per:
                continue
            for m in bk["markets"]:
                if m["key"] == "h2h" and len(m["outcomes"]) >= 2:
                    per[bk["key"]].append(sum(1 / o["price"] for o in m["outcomes"]))
    res[s["key"]] = {b: (len(v), round((1 - 1 / statistics.median(v)) * 100, 1)) for b, v in per.items() if v}
    print(f"{s['group']:12} {s['title']:30} {len(data):3} matchs  " + "  ".join(f"{b.replace('_fr','')} {m} % ({n})" for b, (n, m) in res[s['key']].items()) + f"   [credits restants {left}]")
print("RESULTATS", json.dumps(res))
