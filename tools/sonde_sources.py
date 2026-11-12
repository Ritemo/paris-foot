"""Sonde : les cotes Kambi « ub » sont-elles celles d'unibet.fr ? Comparaison avec The Odds API (1 credit)."""
import json, os, urllib.request
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
k = json.load(urllib.request.urlopen(urllib.request.Request("https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/basketball/nba.json?lang=fr_FR&market=FR", headers={"User-Agent": UA}), timeout=30))
kam = {}
for e in k["events"]:
    bo = e.get("betOffers", [])
    if bo:
        kam[e["event"]["name"]] = [o["odds"] / 1000 for o in bo[0]["outcomes"]]
url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=fr&markets=h2h&oddsFormat=decimal&bookmakers=unibet_fr&apiKey=" + os.environ["ODDS_API_KEY"]
oa = json.load(urllib.request.urlopen(url, timeout=30))
for ev in oa:
    for bk in ev["bookmakers"]:
        o = {x["name"]: x["price"] for x in bk["markets"][0]["outcomes"]}
        name = f"{ev['home_team']} - {ev['away_team']}"
        print("unibet.fr", name, o.get(ev["home_team"]), o.get(ev["away_team"]), "| kambi ub", kam.get(name))
