"""Test OddsPapi (3 a 4 requetes sur 250 par mois) : cotes Unibet FR des prochains matchs, a comparer avec l'appli Unibet."""
import json
import os
import urllib.error
import urllib.request

KEY = os.environ["ODDSPAPI_KEY"]
API = "https://api.oddspapi.io/v4"


def get(path, **q):
    q["apiKey"] = KEY
    url = f"{API}{path}?" + "&".join(f"{k}={v}" for k, v in q.items())
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "paris-foot"}), timeout=40) as r:
            print("  [requete]", path, q.get("bookmaker", ""), "| quota :", {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()})
            return json.load(r)
    except urllib.error.HTTPError as e:
        print("  [ERREUR]", path, {k: v for k, v in q.items() if k != "apiKey"}, e.code, e.read()[:400])
        return None


tours = [{"tournamentId": i, "tournamentName": n, "categoryName": c} for i, n, c in
         [(7, "UEFA Champions League", "International Clubs"), (8, "LaLiga", "Spain"), (17, "Premier League", "England"),
          (23, "Serie A", "Italy"), (34, "Ligue 1", "France"), (35, "Bundesliga", "Germany"), (679, "UEFA Europa League", "International Clubs")]]
want = ["Ligue 1", "Premier League", "LaLiga", "Serie A", "Bundesliga", "UEFA Champions League", "UEFA Europa League"]
print("Exemple de tournoi :", json.dumps(tours[0])[:300] if isinstance(tours, list) and tours else str(tours)[:300])
ids = []
for t in tours if isinstance(tours, list) else []:
    name, cat = t.get("tournamentName") or t.get("name"), t.get("categoryName") or t.get("category", "")
    if name in want and (name != "Premier League" or "England" in str(cat)) and (name != "Ligue 1" or "France" in str(cat)) \
            and (name != "Bundesliga" or "Germany" in str(cat)) and (name != "Serie A" or "Italy" in str(cat)):
        ids.append(str(t.get("tournamentId") or t.get("id")))
        print("  tournoi", name, cat, t.get("tournamentId") or t.get("id"), "matchs a venir :", t.get("upcomingFixtures"))
markets = get("/markets", sportId=10) or []
mname = {}
for m in markets if isinstance(markets, list) else []:
    mname[str(m.get("marketId"))] = f"{m.get('marketName')} {m.get('handicap', '')}".strip()
    for o in m.get("outcomes", []):
        mname[f"{m.get('marketId')}/{o.get('outcomeId')}"] = o.get("outcomeName")
data = None
for bkm, tids in (("unibet.fr", "34,17"), ("unibet-fr", "34,17"), ("unibet.fr", "34")):
    data = get("/odds-by-tournaments", bookmaker=bkm, tournamentIds=tids, oddsFormat="decimal")
    if data is not None:
        print("OK avec", bkm, tids)
        break
data = data or []
fixtures = data if isinstance(data, list) else data.get("data", data)
print(len(fixtures), "matchs avec cotes Unibet FR")
for f in fixtures[:12]:
    print("\n", f.get("participant1Name"), "-", f.get("participant2Name"), f.get("startTime"), f.get("tournamentName", ""))
    bo = f.get("bookmakerOdds") or {}
    if f is fixtures[0]:
        print("   cles du match :", list(f.keys()), "bookmakers :", list(bo.keys())[:5], json.dumps(f)[:600])
    bk = bo.get("unibet.fr") or bo.get("unibet-fr") or (list(bo.values())[0] if bo else {})
    for mid, m in (bk.get("markets") or {}).items():
        outs = []
        for oid, o in (m.get("outcomes") or {}).items():
            pl = o.get("players", {}).get("0", o)
            outs.append(f"{mname.get(f'{mid}/{oid}', oid)}={pl.get('price')}")
        print("   ", mname.get(str(mid), mid), "|", ", ".join(outs))
