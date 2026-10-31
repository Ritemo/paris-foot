"""Test de l'appli dans un vrai navigateur (Chromium), avec des donnees d'exemple et sans reseau.

Lancement : python tests/test_app.py
Verifie : aucun plantage, chaque onglet a du contenu, jouer un ticket, corriger une cote,
composer un combine, reglement automatique par les scores ESPN, bilan, sauvegarde.
"""
import asyncio
import functools
import http.server
import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
NOW = datetime.now(timezone.utc).replace(microsecond=0)
iso = lambda d: d.isoformat().replace("+00:00", "Z")
day = lambda d: d.astimezone(timezone(timedelta(hours=1))).date().isoformat()


def sel(mk, label, odds, p, src="unibet"):
    return dict(market=mk, label=label, odds=odds, src=src, p=p, ev=round(p * odds - 1, 4))


def match(i, k, home, away):
    return dict(id=f"m{i}", league="Ligue 1", div="F1", kickoff=iso(k), day=day(k), home=home, away=away, fd_home=None, fd_away=None,
                lambdas=[1.5, 1.1], model=True,
                sel=[sel("1", f"Victoire {home}", 1.6, 0.58), sel("N", "Match nul", 3.8, 0.24), sel("2", f"Victoire {away}", 5.5, 0.18),
                     sel("+2.5", "Plus de 2,5 buts", 1.75, 0.53, "pmu"), sel("-2.5", "Moins de 2,5 buts", 2.05, 0.47, "pmu")])


def leg_of(m, mk):
    s = next(x for x in m["sel"] if x["market"] == mk)
    return dict(match_id=m["id"], league=m["league"], kickoff=m["kickoff"], home=m["home"], away=m["away"], fd_home=None, fd_away=None,
                div="F1", **s)


def combo(cid, kind, legs, stars=2, status="en attente", d=None):
    p, odds = 1.0, 1.0
    for l in legs:
        p *= l["p"]; odds *= l["odds"]
    return dict(id=cid, day=d or day(datetime.fromisoformat(legs[0]["kickoff"].replace("Z", "+00:00"))), kind=kind, legs=legs,
                odds=round(odds, 2), p=round(p, 4), cost=0.1, stars=stars, stake=1 if kind == "folie" else 2, status=status)


def fixtures():
    m1 = match(1, NOW + timedelta(hours=2), "Lens", "Lille")
    m2 = match(2, NOW + timedelta(hours=3), "Lyon", "Nice")
    m3 = match(3, NOW - timedelta(hours=3), "Rennes", "Nantes")       # termine : a regler par l'appli
    m4 = match(4, NOW - timedelta(hours=3, minutes=5), "Brest", "Metz")
    m5 = match(5, NOW + timedelta(hours=4), "Monaco", "Auxerre")
    m6 = match(6, NOW + timedelta(hours=5), "Paris SG", "Lorient")
    futur = combo("c-futur", "x2", [leg_of(m1, "1"), leg_of(m2, "+2.5")], stars=3)
    passe = combo("c-passe", "x2", [leg_of(m3, "1"), leg_of(m4, "-2.5")], stars=2)
    folie = combo("c-folie", "folie", [leg_of(m1, "2"), leg_of(m2, "N"), leg_of(m5, "2"), leg_of(m6, "N")], stars=0)
    old = []
    for i, st in enumerate(["gagne", "perdu", "perdu", "gagne"]):
        c = combo(f"old{i}", "x2", [leg_of(m3, "1"), leg_of(m4, "+2.5")], stars=1 + i % 3, status=st,
                  d=day(NOW - timedelta(days=2 + i)))
        for l in c["legs"]:
            l["won"] = st == "gagne"; l["score"] = "2-1"
        old.append(c)
    hist = {"combos": [futur, passe, folie] + old, "bilan": {"n": 4, "gagnes": 2, "reussite_reelle": 0.5, "reussite_annoncee": 0.3,
                                                              "bilan_2eur": 1.0, "mise_2eur": 8, "bilan_mise_suggeree": 1.0, "mise_suggeree_totale": 8}}
    today = {"generated_at": iso(NOW), "credits_remaining": 400, "combos": [futur, passe, folie], "matches": [m1, m2, m3, m4, m5, m6]}
    espn = {"events": [
        {"date": m3["kickoff"], "status": {"type": {"state": "post", "shortDetail": "FT"}},
         "competitions": [{"competitors": [{"homeAway": "home", "score": "2", "team": {"displayName": "Stade Rennais"}},
                                           {"homeAway": "away", "score": "0", "team": {"displayName": "Nantes"}}]}]},
        {"date": m4["kickoff"], "status": {"type": {"state": "post", "shortDetail": "FT"}},
         "competitions": [{"competitors": [{"homeAway": "home", "score": "1", "team": {"displayName": "Brest"}},
                                           {"homeAway": "away", "score": "0", "team": {"displayName": "Metz"}}]}]}]}
    return today, hist, {"credits_remaining": 400}, espn, passe


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=DOCS)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


async def main():
    today, hist, meta, espn, passe = fixtures()
    srv = serve()
    url = f"http://127.0.0.1:{srv.server_port}/"
    errors, posts, fails = [], [], []

    def check(cond, msg):
        print(("  ok   " if cond else "  ECHEC ") + msg)
        if not cond:
            fails.append(msg)

    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True, service_workers="block")
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))

        async def route(r):
            u = r.request.url
            if "/data/today.json" in u:
                return await r.fulfill(json=today)
            if "/data/history.json" in u:
                return await r.fulfill(json=hist)
            if "/data/meta.json" in u:
                return await r.fulfill(json=meta)
            if "site.api.espn.com" in u:
                return await r.fulfill(json=espn if "fra.1" in u else {"events": []}, headers={"access-control-allow-origin": "*"})
            if "ntfy.sh" in u:
                posts.append(r.request.post_data)
                return await r.fulfill(body="{}", headers={"access-control-allow-origin": "*"})
            if u.startswith(url):
                return await r.continue_()
            return await r.abort()  # polices et autres : hors ligne
        await pg.route("**/*", route)

        await pg.goto(url)
        await pg.wait_for_timeout(800)
        await pg.evaluate("localStorage.clear()")
        await pg.reload()
        await pg.wait_for_timeout(1000)

        print("Onglet Tickets")
        ids = await pg.eval_on_selector_all("#tab-combos [data-bet]", "e => e.map(x => x.dataset.bet)")
        check("c-futur" in ids and "c-folie" in ids, "les tickets jouables s'affichent")
        check("c-passe" not in ids, "un ticket dont un match a commencé est masqué")

        print("Jouer un ticket")
        await pg.click('#tab-combos [data-bet="c-futur"]')
        await pg.click('#dlg-steps button[data-v="3"]')
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(500)
        bet = await pg.evaluate("bets()['c-futur']")
        check(bet and bet["mise"] == 3 and bet.get("snap"), "le pari est enregistré avec sa mise et sa copie")
        check(any('"add"' in (x or "") and "c-futur" in (x or "") for x in posts), "le robot est prévenu du ticket joué")
        check(await pg.inner_text("#encours-badge") == "1", "pastille En cours à 1")

        print("Corriger une cote")
        await pg.click('.tabs button[data-tab="encours"]')
        await pg.click('#tab-encours .odd >> nth=0')
        await pg.fill("#dlg-input", "1.5")
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(300)
        odds = await pg.evaluate("bets()['c-futur'].odds")
        check(abs(odds - round(1.5 * 1.75, 2)) < 0.011, f"la cote du ticket joué suit la correction ({odds})")

        print("Composer un combiné")
        await pg.click('.tabs button[data-tab="matchs"]')
        await pg.click('[data-pick="m5"][data-market="1"]')
        await pg.click('[data-pick="m6"][data-market="+2.5"]')
        check(await pg.is_visible("#composer"), "le bandeau Mon combiné apparaît")
        await pg.click('[data-compose="play"]')
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(500)
        n_perso = await pg.evaluate("Object.keys(bets()).filter(k => k.startsWith('perso|')).length")
        check(n_perso == 1, "le combiné composé est joué")

        print("Règlement automatique par les scores")
        await pg.evaluate("(c) => { const b = bets(); b[c.id] = {mise: 2, odds: c.odds, date: c.day, snap: c}; localStorage.setItem('pf_bets', JSON.stringify(b)); }", passe)
        await pg.evaluate("refreshLive()")
        await pg.wait_for_timeout(800)
        st = await pg.evaluate("findCombo('c-passe').status")
        check(st == "gagne", f"un ticket terminé passe en gagné sans attendre le robot ({st})")

        print("Bilan")
        await pg.click('.tabs button[data-tab="bilan"]')
        await pg.wait_for_timeout(300)
        txt = await pg.inner_text("#tab-bilan")
        check("Gain réel" in txt and "Récupéré" in txt, "misé, récupéré et gain réel affichés")
        await pg.click('[data-bview="robot"]')
        await pg.wait_for_timeout(200)
        check(await pg.locator("#tab-bilan .grp").count() >= 2, "qualité des tickets par étoiles")

        print("Réglages et sauvegarde")
        await pg.click('.tabs button[data-tab="reglages"]')
        v = await pg.inner_text("#app-version")
        check(v not in ("", "?"), f"numéro de version affiché ({v})")
        async with pg.expect_download() as dl:
            await pg.evaluate("navigator.canShare = () => false")
            await pg.click("#export")
        data = json.loads(open(await (await dl.value).path(), encoding="utf-8").read())
        check(len(data["bets"]) == 3, "la sauvegarde contient les 3 paris")

        print("Tous les onglets")
        for t in ("combos", "encours", "matchs", "bilan", "reglages"):
            n = await pg.eval_on_selector(f"#tab-{t}", "e => e.innerText.trim().length")
            check(n > 40, f"onglet {t} non vide")

        check(not errors, "aucune erreur JavaScript" + (f" : {errors}" if errors else ""))
        await b.close()
    srv.shutdown()
    print("\n" + ("TOUT EST OK" if not fails else f"{len(fails)} ECHEC(S)"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
