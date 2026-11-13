"""Sonde (1 credit) : The Odds API donne-t-elle des liens Unibet (match, ou ticket pre-rempli) ?"""
import json, os, urllib.request
url = ("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=fr&markets=h2h&oddsFormat=decimal"
       "&bookmakers=unibet_fr,betclic_fr,winamax_fr&includeLinks=true&includeSids=true&apiKey=" + os.environ["ODDS_API_KEY"])
r = urllib.request.urlopen(url, timeout=30)
print("credits restants", r.headers.get("x-requests-remaining"), "cout", r.headers.get("x-requests-last"))
for e in json.load(r)[:2]:
    print(e["home_team"], "-", e["away_team"])
    for b in e.get("bookmakers", []):
        print("  ", b["key"], "lien match:", b.get("link"), "sid:", b.get("sid"))
        for m in b.get("markets", []):
            print("     marche lien:", m.get("link"), "sid:", m.get("sid"))
            for o in m["outcomes"]:
                print("       ", o["name"], o["price"], "lien:", o.get("link"), "sid:", o.get("sid"))
