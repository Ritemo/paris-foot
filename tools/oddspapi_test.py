"""Test OddsPapi (3 a 4 requetes sur 250 par mois) : cotes Unibet FR des prochains matchs, a comparer avec l'appli Unibet."""
import json
import os
import urllib.request

KEY = os.environ["ODDSPAPI_KEY"]
API = "https://api.oddspapi.io/v4"


def get(path, **q):
    q["apiKey"] = KEY
    url = f"{API}{path}?" + "&".join(f"{k}={v}" for k, v in q.items())
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "paris-foot"}), timeout=40) as r:
        print("  [requete]", path, "| quota :", {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()})
        return json.load(r)


tours = get("/tournaments", sportId=10)
want = ["Ligue 1", "Premier League", "LaLiga", "Serie A", "Bundesliga", "UEFA Champions League", "UEFA Europa League"]
print("Exemple de tournoi :", json.dumps(tours[0])[:300] if isinstance(tours, list) and tours else str(tours)[:300])
ids = []
for t in tours if isinstance(tours, list) else []:
    name, cat = t.get("tournamentName") or t.get("name"), t.get("categoryName") or t.get("category", "")
    if name in want and (name != "Premier League" or "England" in str(cat)) and (name != "Ligue 1" or "France" in str(cat)) \
            and (name != "Bundesliga" or "Germany" in str(cat)) and (name != "Serie A" or "Italy" in str(cat)):
        ids.append(str(t.get("tournamentId") or t.get("id")))
        print("  tournoi", name, cat, t.get("tournamentId") or t.get("id"), "matchs a venir :", t.get("upcomingFixtures"))
markets = get("/markets", sportId=10)
mname = {}
for m in markets if isinstance(markets, list) else []:
    mname[str(m.get("marketId"))] = f"{m.get('marketName')} {m.get('handicap', '')}".strip()
    for o in m.get("outcomes", []):
        mname[f"{m.get('marketId')}/{o.get('outcomeId')}"] = o.get("outcomeName")
data = get("/odds-by-tournaments", bookmaker="unibet.fr", tournamentIds=",".join(ids[:7]), oddsFormat="decimal")
fixtures = data if isinstance(data, list) else data.get("data", data)
print(len(fixtures), "matchs avec cotes Unibet FR")
for f in fixtures[:12]:
    print("\n", f.get("participant1Name"), "-", f.get("participant2Name"), f.get("startTime"), f.get("tournamentName", ""))
    bk = (f.get("bookmakerOdds") or {}).get("unibet.fr") or {}
    for mid, m in (bk.get("markets") or {}).items():
        outs = []
        for oid, o in (m.get("outcomes") or {}).items():
            pl = o.get("players", {}).get("0", o)
            outs.append(f"{mname.get(f'{mid}/{oid}', oid)}={pl.get('price')}")
        print("   ", mname.get(str(mid), mid), "|", ", ".join(outs))
