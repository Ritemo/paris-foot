"""Sonde (aucun credit) : chemins Kambi tennis, marches d'un match ATP, structure ESPN tennis et NBA."""
import json, urllib.request
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=30))
K = "https://eu-offering-api.kambicdn.com/offering/v2018/ub"
Q = "lang=fr_FR&market=FR"
d = get(f"{K}/listView/tennis/all/all/all/matches.json?{Q}")
paths = {}
for e in d["events"]:
    p = tuple(x.get("termKey") for x in e["event"].get("path", []))
    paths.setdefault(p, []).append(e["event"]["name"])
for p, v in sorted(paths.items()):
    print("PATH", "/".join(p), len(v), v[0])
atp = [e for e in d["events"] if any(x.get("termKey") in ("atp", "wta") for x in e["event"].get("path", [])) and "/" not in e["event"]["name"]]
print("ATP/WTA simples", len(atp))
for e in atp[:1]:
    print("EVENT KEYS", list(e["event"].keys()))
    print("EVENT", json.dumps({k: e["event"][k] for k in ("id", "name", "homeName", "awayName", "start", "group", "path", "participants") if k in e["event"]})[:900])
    d2 = get(f"{K}/betoffer/event/{e['event']['id']}.json?{Q}")
    for b in d2.get("betOffers", [])[:40]:
        print("   ", b.get("criterion", {}).get("label"), "|", b.get("betOfferType", {}).get("englishName"), [(o.get("label"), o.get("line"), o.get("odds")) for o in b.get("outcomes", [])][:3], b.get("tags"))
e = get("https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard?dates=20261111")
ev = e["events"][0]
print("ESPN ATP event keys", list(ev.keys()), ev.get("name"))
g = ev.get("groupings", [])
print("groupings", len(g), [x.get("grouping", {}).get("displayName") for x in g])
c = g[0]["competitions"][0] if g else ev.get("competitions", [{}])[0]
print("COMP", json.dumps({k: c.get(k) for k in ("id", "date", "status", "competitors", "round", "type")})[:1500])
n = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261111")
c = n["events"][0]["competitions"][0]
print("NBA", n["events"][0]["name"], [(x["homeAway"], x["team"]["displayName"], x.get("score"), x.get("winner")) for x in c["competitors"]], c["status"]["type"]["name"], c["status"].get("displayClock"), c["status"].get("period"))
