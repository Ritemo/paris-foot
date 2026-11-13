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
                lambdas=[1.5, 1.1], model=True, link=f"https://www.unibet.fr/paris-football/france/ligue-1/{i}/match",
                sel=[sel("1", f"Victoire {home}", 1.6, 0.58), sel("N", "Match nul", 3.8, 0.24), sel("2", f"Victoire {away}", 5.5, 0.18),
                     sel("+2.5", "Plus de 2,5 buts", 1.75, 0.53, "pmu"), sel("-2.5", "Moins de 2,5 buts", 2.05, 0.47, "pmu"),
                     sel("1N", f"{home} ou nul", 1.22, 0.82, "estimee"), sel("12", "Pas de match nul", 1.18, 0.76, "estimee"),
                     sel("N2", f"{away} ou nul", 2.3, 0.42, "estimee"), sel("BTTS", "Les deux équipes marquent", 1.8, 0.5, "estimee"),
                     sel("NBTTS", "Une équipe au moins ne marque pas", 1.85, 0.5, "estimee"),
                     sel("+1.5", "Plus de 1,5 buts", 1.25, 0.76, "estimee"), sel("-1.5", "Moins de 1,5 buts", 3.6, 0.24, "estimee")])


def nba(i, k, home, away):
    return dict(id=f"nba-{i}", sport="basket", league="NBA", div="NBA", kickoff=iso(k), day=day(k), home=home, away=away, fd_home=None, fd_away=None,
                sel=[sel("1", f"Victoire {home}", 1.34, 0.70), sel("2", f"Victoire {away}", 2.85, 0.30),
                     sel("HC1:-7.5", "76ers handicap -7,5", 1.80, 0.50, "estimee"), sel("HC2:+7.5", "Raptors handicap +7,5", 1.75, 0.50, "estimee"),
                     sel("+220.5", "Plus de 220,5 points", 1.78, 0.51, "estimee"), sel("-220.5", "Moins de 220,5 points", 1.76, 0.49, "estimee")])


def tennis(i, k, home, away):
    return dict(id=f"ten-{i}", sport="tennis", league="ATP", event="Stockholm Open", div="ATP", kickoff=iso(k), day=day(k), home=home, away=away,
                fd_home=None, fd_away=None, sel=[sel("1", f"Victoire {home}", 1.62, 0.56), sel("2", f"Victoire {away}", 2.20, 0.44, "estimee")])


def leg_of(m, mk):
    s = next(x for x in m["sel"] if x["market"] == mk)
    return dict(match_id=m["id"], league=m["league"], kickoff=m["kickoff"], home=m["home"], away=m["away"], fd_home=None, fd_away=None,
                div=m["div"], sport=m.get("sport", "foot"), link=m.get("link"), **s)


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
        c = combo(f"old{i}", "x2", [leg_of(m3, "1"), leg_of(m4, ["+2.5", "1N", "N2", "12"][i])], stars=1 + i % 3, status=st,
                  d=day(NOW - timedelta(days=2 + i // 2)))
        for l in c["legs"]:
            l["won"] = st == "gagne"; l["score"] = "2-1"
        if st == "perdu":
            c["legs"][0]["won"] = True   # perdu à cause du 2e match seulement
        old.append(c)
    hist = {"combos": [futur, passe, folie] + old, "bilan": {"n": 4, "gagnes": 2, "reussite_reelle": 0.5, "reussite_annoncee": 0.3,
                                                              "bilan_2eur": 1.0, "mise_2eur": 8, "bilan_mise_suggeree": 1.0, "mise_suggeree_totale": 8}}
    alt = dict(combo("c-alt", "x2", [leg_of(m1, "+2.5"), leg_of(m2, "1")]), alt=True)
    m7 = nba(7, NOW - timedelta(minutes=40), "Philadelphia 76ers", "Toronto Raptors")   # en cours
    m8 = nba(8, NOW + timedelta(hours=6), "Boston Celtics", "Miami Heat")
    m9 = tennis(9, NOW + timedelta(hours=2, minutes=30), "Lorenzo Musetti", "Ugo Humbert")
    mix = dict(combo("c-mix", "x2", [leg_of(m5, "1"), leg_of(m9, "1")]), alt=True, mix=True)
    today = {"generated_at": iso(NOW), "credits_remaining": 400, "combos": [futur, passe, folie], "alts": [alt, mix],
             "matches": [m1, m2, m3, m4, m5, m6, m7, m8, m9]}
    espn = {"events": [
        {"date": m3["kickoff"], "status": {"type": {"state": "post", "shortDetail": "FT"}},
         "competitions": [{"competitors": [{"homeAway": "home", "score": "2", "team": {"displayName": "Stade Rennais"}},
                                           {"homeAway": "away", "score": "0", "team": {"displayName": "Nantes"}}]}]},
        {"date": m4["kickoff"], "status": {"type": {"state": "post", "shortDetail": "FT"}},
         "competitions": [{"competitors": [{"homeAway": "home", "score": "1", "team": {"displayName": "Brest"}},
                                           {"homeAway": "away", "score": "0", "team": {"displayName": "Metz"}}]}]}]}
    espn_nba = {"events": [{"date": m7["kickoff"], "status": {"type": {"state": "in", "shortDetail": "Q3 5:12"}},
        "competitions": [{"competitors": [{"homeAway": "home", "score": "88", "team": {"displayName": "Philadelphia 76ers"}},
                                          {"homeAway": "away", "score": "80", "team": {"displayName": "Toronto Raptors"}}]}]}]}
    espn["nba"] = espn_nba
    espn["m7"] = m7
    return today, hist, {"credits_remaining": 400}, espn, passe


MODEL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_sample.json"), encoding="utf-8"))


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
    errors, posts, fails, bk_posts = [], [], [], []

    def check(cond, msg):
        print(("  ok   " if cond else "  ECHEC ") + msg)
        if not cond:
            fails.append(msg)

    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True, service_workers="block")
        await ctx.add_init_script("window.__noCelebrate = true")
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
            if "/data/model.json" in u:
                return await r.fulfill(json=MODEL)
            if "/data/other_learning.json" in u:
                return await r.fulfill(json={"summary": {"basket": {"n": 12, "brier": 0.21, "fav": 0.667, "bins": [{"p": 0.7, "f": 0.75, "n": 8}, {"p": 0.3, "f": 0.25, "n": 4}]}}})
            if "/data/logos.json" in u:
                return await r.fulfill(json={"Rennes": {"logo": "https://a.espncdn.com/i/teamlogos/soccer/500/169.png", "color": "#e13327"},
                                             "Nantes": {"logo": "https://a.espncdn.com/i/teamlogos/soccer/500/165.png", "color": "#fcd405"}})
            if "a.espncdn.com" in u:
                c = "#e13327" if "169" in u else "#fcd405"
                return await r.fulfill(body=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M1 1h8v5l-4 3-4-3z" fill="{c}"/></svg>', content_type="image/svg+xml")
            if "site.api.espn.com" in u:
                body = espn if "fra.1" in u else espn["nba"] if "basketball/nba" in u else {"events": []}
                return await r.fulfill(json={"events": body["events"]}, headers={"access-control-allow-origin": "*"})
            if "/data/backup.json" in u:   # le robot range les morceaux reçus
                groups = {}
                for x in bk_posts:
                    d = json.loads(x); groups.setdefault(d["b"], {})[d["i"]] = (d["n"], d["d"])
                saves = [{"id": k, "t": 1000 + n, "blob": "".join(v[i][1] for i in range(len(v)))} for n, (k, v) in enumerate(groups.items())
                         if len(v) == list(v.values())[0][0]]
                return await r.fulfill(json={"saves": saves})
            if "ntfy.sh" in u and "-sauvegarde" in u:
                bk_posts.append(r.request.post_data)
                return await r.fulfill(body="{}", headers={"access-control-allow-origin": "*"})
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
        check(await pg.locator("#tab-combos a.ub-link[target=_blank]").count() >= 2, "bouton Unibet sur les matchs des tickets")
        check("c-alt" in ids and await pg.locator("#tab-combos .alt-tag").count() == 1, "un autre candidat du robot est proposé selon ton style")

        check(await pg.locator("#tab-combos .rank").count() >= 1 and "du jour sur" in await pg.inner_text("#tab-combos"), "rang du jour affiché sur les tickets")
        check("intéressant" in await pg.inner_text("#tab-combos .stars >> nth=0"), "étoiles avec leur libellé d'intérêt")
        check(await pg.locator("#tab-combos .mix").count() >= 1, "jauges prix et chance sur les tickets")
        check(await pg.locator("#style").count() == 1 and await pg.locator("[data-pw]").count() == 3, "curseur de style de jeu et importance du prix")
        await pg.evaluate("const r = document.getElementById('style'); r.value = 100; r.dispatchEvent(new Event('input', {bubbles: true}))")
        await pg.wait_for_timeout(300)
        check(abs(await pg.evaluate("style()") - 1) < 1e-9 and "4,5" in await pg.inner_text("#bal-label"), "le style se règle et s'enregistre")
        await pg.click('[data-pw="0.7"]')
        check(await pg.evaluate("priceW()") == 0.7, "l'importance du prix se règle")
        await pg.click('[data-pw="0.5"]')
        await pg.evaluate("const r = document.getElementById('style'); r.value = 25; r.dispatchEvent(new Event('input', {bubbles: true}))")
        await pg.wait_for_timeout(300)
        print("Jouer un ticket")
        await pg.click('#tab-combos [data-bet="c-futur"]')
        check(await pg.is_visible("#dlg-odds") and await pg.locator("#odds-rows input").count() >= 1, "les cotes non Unibet sont à vérifier avant de jouer")
        check(await pg.locator("#odds-rows a.ub-open[href^='https://www.unibet.fr/']").count() >= 1, "lien vers le match sur Unibet dans la vérification des cotes")
        nonuni = await pg.evaluate("findCombo('c-futur').legs.map((l, i) => l.src !== 'unibet' ? i : -1).filter(i => i >= 0)")
        orig = await pg.evaluate(f"findCombo('c-futur').legs[{nonuni[0]}].odds")
        await pg.fill("#odds-rows input >> nth=0", "9,99")
        check("," in await pg.inner_text("#odds-total"), "cote totale recalculée pendant la saisie")
        await pg.fill("#odds-rows input >> nth=0", str(orig).replace(".", ","))
        check("," in await pg.inner_text("#odds-total"), "cote totale recalculée pendant la saisie")
        await pg.click('#dlg-odds button[value="ok"]'); await pg.wait_for_timeout(200)
        check(await pg.evaluate(f"overrides()['c-futur'][{nonuni[0]}]") == orig, "la cote Unibet saisie est enregistrée")
        await pg.click('#dlg-steps button[data-v="3"]')
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(500)
        bet = await pg.evaluate("bets()['c-futur']")
        check(bet and bet["mise"] == 3 and bet.get("snap"), "le pari est enregistré avec sa mise et sa copie")
        check(any('"add"' in (x or "") and "c-futur" in (x or "") for x in posts), "le robot est prévenu du ticket joué")
        check(await pg.inner_text("#encours-badge") == "1", "pastille En cours à 1")
        await pg.click('.tabs button[data-tab="encours"]')
        await pg.click('#tab-encours [data-bet="c-futur"]')
        await pg.fill("#dlg-input", "1,31"); await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(300)
        check(await pg.evaluate("bets()['c-futur'].mise") == 1.31, "mise libre au centime (1,31 €)")
        check("1,31 €" in await pg.inner_text("#tab-encours"), "la mise s'affiche avec ses centimes")
        await pg.click('#tab-encours [data-bet="c-futur"]')
        await pg.click('#dlg-steps button[data-v="3"]'); await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(300)
        pg.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.click('#tab-encours [data-act="cancel"][data-id="c-futur"]'); await pg.wait_for_timeout(300)
        check(await pg.evaluate("!bets()['c-futur']"), "annuler un pari")
        await pg.click(".toast.undo button"); await pg.wait_for_timeout(300)
        check(await pg.evaluate("bets()['c-futur'] && bets()['c-futur'].mise === 3"), "rétablir un pari annulé")
        await pg.click('#tab-encours [data-act="edit"][data-id="c-futur"]')
        await pg.fill("#dlg-input", "2,5"); await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(300)
        check(await pg.evaluate("bets()['c-futur'].mise") == 2.5, "bouton Changer la mise")
        box = await pg.locator('#tab-encours .ticket >> nth=0').locator(".bet-actions").bounding_box()
        check(box and box["height"] > 10, f"les boutons de correction sont visibles ({box})")
        if os.environ.get("SHOTS"):
            await pg.evaluate("document.querySelectorAll('.toast').forEach(t => t.remove())")
            await pg.locator('#tab-encours .ticket >> nth=0').screenshot(path=os.environ["SHOTS"] + "/joue.png")
        await pg.click('#tab-encours [data-act="edit"][data-id="c-futur"]')
        await pg.click('#dlg-steps button[data-v="3"]'); await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(300)
        await pg.click('.tabs button[data-tab="combos"]')

        print("Corriger une cote")
        await pg.click('.tabs button[data-tab="encours"]')
        await pg.click('#tab-encours .odd >> nth=0')
        await pg.fill("#dlg-input", "1.5")
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(300)
        odds = await pg.evaluate("bets()['c-futur'].odds")
        check(abs(odds - 2.63) < 1e-9, f"la cote du ticket joué suit la correction, arrondie comme Unibet ({odds})")

        print("Composer un combiné")
        await pg.click('.tabs button[data-tab="matchs"]')
        await pg.click('[data-pick="m5"][data-market="1"]')
        check(await pg.locator('#tab-matchs .chip').count() >= 2, "filtres par championnat")
        check(not await pg.is_visible('[data-pick="m6"][data-market="BTTS"]'), "les autres paris sont repliés")
        await pg.click('[data-more="m6"]')
        await pg.click('[data-pick="m6"][data-market="BTTS"]')
        check(await pg.locator('#tab-matchs .mk-title').count() >= 3, "double chance, les deux équipes marquent et seuils de buts affichés")
        check(await pg.is_visible("#composer"), "le bandeau Mon combiné apparaît")
        check(await pg.locator("#composer .stars i").count() == 3, "le combiné composé est noté en étoiles")
        await pg.click('[data-compose="play"]')
        await pg.click('#dlg-odds button[value="skip"]')
        await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(500)
        n_perso = await pg.evaluate("Object.keys(bets()).filter(k => k.startsWith('perso|')).length")
        check(n_perso == 1, "le combiné composé est joué")
        pid = await pg.evaluate("Object.keys(bets()).find(k => k.startsWith('perso|'))")
        await pg.click(f'#tab-encours [data-act="change"][data-id="{pid}"]'); await pg.wait_for_timeout(400)
        check(await pg.evaluate("!Object.keys(bets()).some(k => k.startsWith('perso|'))") and await pg.is_visible("#composer"),
              "changer les sélections d'un combiné perso le remet en composition")
        await pg.click('[data-compose="play"]'); await pg.click('#dlg-odds button[value="skip"]'); await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(500)

        print("Règlement automatique par les scores")
        await pg.evaluate("(c) => { const b = bets(); b[c.id] = {mise: 2, odds: c.odds, date: c.day, snap: c}; localStorage.setItem('pf_bets', JSON.stringify(b)); }", passe)
        await pg.evaluate("refreshLive()")
        await pg.wait_for_timeout(800)
        st = await pg.evaluate("findCombo('c-passe').status")
        check(st == "gagne", f"un ticket terminé passe en gagné sans attendre le robot ({st})")

        await pg.evaluate("(c) => { const b = bets(); b[c.id] = {mise: 2, odds: c.odds, date: c.day, snap: c}; localStorage.setItem('pf_bets', JSON.stringify(b)); renderAll(); }", hist["combos"][3])
        print("Bankroll")
        await pg.click('.tabs button[data-tab="bilan"]')
        check(await pg.evaluate("bank().moves[0].amount") == 30, "bankroll créée d'office avec un départ de 30 €")
        await pg.click('[data-bank="init"]')
        check(await pg.input_value("#dlg-input") == "30", "bouton Départ : 30 € proposés")
        await pg.click('#dlg button[value="ok"]'); await pg.wait_for_timeout(200)
        br = await pg.evaluate("bankroll()")
        # tous les paris comptent : c-futur 3 € et perso en jeu, c-passe et old0 gagnés (2 € chacun)
        exp = 30 + 2 * (passe["odds"] - 1) + 2 * (hist["combos"][3]["odds"] - 1) - br["engaged"]
        check(abs(br["value"] - exp) < 0.01 and br["engaged"] > 3, f"disponible = 30 + gains - pertes - en jeu ({br['value']:.2f} vs {exp:.2f}, en jeu {br['engaged']}, {br['gains']:.2f}, {br['pertes']})")
        await pg.click('[data-bank="depot"]'); await pg.fill("#dlg-input", "20"); await pg.click('#dlg button[value="ok"]')
        await pg.wait_for_timeout(200)
        br2 = await pg.evaluate("bankroll()")
        check(abs(br2["value"] - br["value"] - 20) < 0.01, "un dépôt s'ajoute au disponible")
        check("Bankroll" in await pg.inner_text("#budget-strip"), "bankroll dans le bandeau")
        print("Logos et navigation")
        await pg.click('.tabs button[data-tab="matchs"]')
        n_logo = await pg.evaluate("[...document.querySelectorAll('#tab-matchs .crest.has-logo img')].filter(i => i.complete && i.naturalWidth > 0).length")
        check(n_logo >= 1, f"logos des clubs affichés ({n_logo})")
        check(await pg.locator("#tab-matchs .crest:not(.has-logo)").count() >= 1, "initiales pour les clubs sans logo")
        await pg.click('#tab-matchs .chip:not([data-league=""]) >> nth=0')
        check(await pg.locator("#tab-matchs .chip.on").count() == 1, "un championnat filtré")
        await pg.click('#tab-matchs .chip[data-league=""]')
        await pg.evaluate("showTab('bilan')")
        check(await pg.locator('.tabs button.active[data-tab="bilan"]').count() == 1, "changement d'onglet par code (glisser)")
        print("Tickets terminés match par match")
        await pg.evaluate("const b = bets(); b['old1'] = {mise: 2, odds: 2, date: 'x', ts: 1, snap: findCombo('old1')}; LS.set('pf_bets', b); renderAll()")
        await pg.click('.tabs button[data-tab="bilan"]')
        hl = pg.locator("#tab-bilan .hist-legs")
        check(await hl.locator("li.w").count() >= 1 and await hl.locator("li.l").count() >= 1, "ticket perdu : chaque match avec bon ou mauvais")
        check("2-1" in await pg.inner_text("#tab-bilan .hist-legs li.l >> nth=0"), "score de chaque match affiché")
        await pg.evaluate("const b = bets(); delete b['old1']; LS.set('pf_bets', b); renderAll()")
        print("Sauvegarde automatique")
        n_bets = await pg.evaluate("Object.keys(bets()).length")
        await pg.evaluate("LS.set('pf_backup_sent', {})")
        check(await pg.evaluate("sendBackup()"), "la sauvegarde part chiffrée vers le robot")
        check(bk_posts and not any("c-futur" in (x or "") or '"mise"' in (x or "") for x in bk_posts), "rien n'est lisible en clair dans la sauvegarde")
        check(not await pg.evaluate("sendBackup()"), "pas de renvoi si rien n'a changé")
        code = await pg.evaluate("backupCode()")
        check(len(code) == 19 and code.count("-") == 3, "code de récupération au format XXXX-XXXX-XXXX-XXXX")
        await pg.evaluate("localStorage.removeItem('pf_bets'); localStorage.removeItem('pf_backup_code'); renderAll()")
        pg.once("dialog", lambda d: asyncio.ensure_future(d.accept("FAUX-CODE-0000-0000")))
        await pg.evaluate("restoreFromCloud()"); await pg.wait_for_timeout(300)
        check(await pg.evaluate("Object.keys(bets()).length") == 0, "un mauvais code n'ouvre rien")
        pg.once("dialog", lambda d: asyncio.ensure_future(d.accept(code.lower().replace("-", " "))))
        await pg.evaluate("restoreFromCloud()"); await pg.wait_for_timeout(500)
        check(await pg.evaluate("Object.keys(bets()).length") == n_bets and await pg.evaluate("backupCode()") == code, f"récupération de tous les paris avec le code ({n_bets})")
        print("NBA et tennis")
        await pg.click('.tabs button[data-tab="combos"]')
        ids = await pg.evaluate("[...document.querySelectorAll('#tab-combos [data-bet]')].map(b => b.dataset.bet)")
        check("c-mix" not in ids, "pas de ticket multisport sans le demander")
        await pg.click("#mix-toggle"); await pg.wait_for_timeout(300)
        ids = await pg.evaluate("[...document.querySelectorAll('#tab-combos [data-bet]')].map(b => b.dataset.bet)")
        check("c-mix" in ids and "multisport" in await pg.inner_text("#tab-combos"), "ticket multisport proposé quand on le demande")
        await pg.click("#mix-toggle"); await pg.wait_for_timeout(200)
        await pg.click('.tabs button[data-tab="matchs"]')
        chips = await pg.locator("#tab-matchs .chip").all_inner_texts()
        check(any("NBA" in c for c in chips) and any("ATP" in c for c in chips), "filtres NBA et tennis dans Matchs")
        check("Stockholm Open" in await pg.inner_text("#tab-matchs"), "nom du tournoi de tennis affiché")
        await pg.click('[data-more="nba-8"]')
        check("Handicap en points" in await pg.inner_text("#tab-matchs") and "Total de points" in await pg.inner_text("#tab-matchs"), "marchés NBA : handicap et total de points")
        await pg.evaluate("LS.set('pf_draft', {}); renderAll()")
        await pg.click('[data-pick="nba-8"][data-market="1"]')
        await pg.click('[data-pick="ten-9"][data-market="1"]')
        await pg.click('[data-pick="m5"][data-market="1"]')
        check("3 sélections" in await pg.inner_text("#composer"), "combiné mélangeant foot, NBA et tennis sur demande")
        await pg.evaluate("LS.set('pf_draft', {}); renderAll()")
        m7 = espn["m7"]
        await pg.evaluate("""(m) => { const l = { match_id: m.id, league: m.league, kickoff: m.kickoff, home: m.home, away: m.away, div: m.div, sport: m.sport,
            market: '+220.5', label: 'Plus de 220,5 points', odds: 1.78, src: 'estimee', p: 0.51, ev: -0.09 };
            const c = { id: 'perso|nba', day: m.day, kind: 'perso', legs: [l], odds: 1.78, p: 0.51, cost: 0.09, stars: 0, stake: 1, status: 'en attente' };
            const b = bets(); b[c.id] = { mise: 1, odds: 1.78, date: 'x', ts: Date.now(), snap: c }; LS.set('pf_bets', b); }""", m7)
        await pg.evaluate("refreshLive()"); await pg.wait_for_timeout(500)
        await pg.click('.tabs button[data-tab="encours"]')
        txt = await pg.inner_text("#tab-encours")
        check("88 - 80" in txt and "points" in txt, "suivi en direct d'un match NBA, en points")
        check(await pg.locator('#tab-encours .live[data-score]').count() == 0 or "88-80" not in await pg.evaluate("[...document.querySelectorAll('.live[data-score]')].map(x => x.dataset.score).join()"),
              "pas de flash « BUT ! » au basket")
        await pg.evaluate("const b = bets(); delete b['perso|nba']; LS.set('pf_bets', b); renderAll()")
        print("Mise inhabituelle")
        w = await pg.evaluate("""(() => { const save = LS.get('pf_bets', {}); const b = {};
            ['old1', 'old2'].forEach((id, i) => b[id] = { mise: 2, odds: 2, ts: 100 + i, snap: findCombo(id) });
            b['c-passe'] = { mise: 2, odds: 2, ts: 99, snap: Object.assign({}, findCombo('c-passe'), { status: 'perdu' }) };
            b['x4'] = { mise: 2, odds: 2, ts: 1 };
            LS.set('pf_bets', b); const r = [stakeWarning(5), stakeWarning(2)]; LS.set('pf_bets', save); return r; })()""")
        check("3 derniers tickets sont perdus" in w[0] and w[1] == "", "rappel si la mise grimpe après 3 pertes, rien sinon")
        print("Paris joués chiffrés")
        n0 = len(posts)
        await pg.evaluate("(async () => { meta.played_enc = true; meta.code_check = await codeCheck(); await publishPlayed('add', 'c-futur', bets()['c-futur']); })()")
        await pg.wait_for_timeout(500)
        last = posts[-1] if len(posts) > n0 else ""
        check('"enc"' in last and "c-futur" not in last, "pari joué envoyé chiffré quand le robot a le même code")
        await pg.evaluate("meta.code_check = 'xxxxxxxx'; renderBackupStatus()")
        await pg.wait_for_timeout(200)
        check("ne correspond pas" in await pg.inner_text("#bk-robot"), "alerte si le code du téléphone diffère de celui du robot")
        await pg.evaluate("meta.played_enc = false")
        print("Animations")
        await pg.evaluate("window.__noCelebrate = false; LS.set('pf_celebrated', [])")
        await pg.evaluate("document.querySelectorAll('.celebrate').forEach(e => e.remove()); renderAll()")
        await pg.wait_for_timeout(400)
        check(await pg.locator(".celebrate .cel-amount").count() == 1, "écran de célébration pour un ticket gagné")
        if os.environ.get("SHOTS"): await pg.wait_for_timeout(1200); await pg.screenshot(path=os.environ["SHOTS"] + "/celebration.png")
        await pg.click(".celebrate .cel-ok"); await pg.wait_for_timeout(400)
        await pg.evaluate("renderAll()"); await pg.wait_for_timeout(200)
        check(await pg.locator(".celebrate").count() == 0, "la célébration ne revient pas une fois vue")
        await pg.click('.tabs button[data-tab="combos"]')
        await pg.click("#tab-combos .sim-btn >> nth=0"); await pg.wait_for_timeout(300)
        check(await pg.locator(".sim-grid i").count() == 100, "simulation de 100 paris")
        if os.environ.get("SHOTS"): await pg.wait_for_timeout(2500); await pg.screenshot(path=os.environ["SHOTS"] + "/simulation.png")
        await pg.click(".sim .cel-ok"); await pg.wait_for_timeout(300)
        await pg.click('.tabs button[data-tab="bilan"]')
        print("Bilan")
        await pg.click('.tabs button[data-tab="bilan"]')
        await pg.wait_for_timeout(300)
        txt = await pg.inner_text("#tab-bilan")
        check("Gain réel" in txt and "Récupéré" in txt, "misé, récupéré et gain réel affichés")
        check("Rentabilité" in txt and "Attendue" in txt, "rentabilité réelle et attendue affichées")
        check("Tickets que tu as laissés" in txt, "comparaison tickets joués / laissés (ton flair)")
        check("Tickets passés sans toi" in txt and "Gagnants non joués" in txt, "tickets gagnants non joués affichés")
        n_g = await pg.locator(".gf-needle").count(); check(n_g == 1, f"jauge du flair affichée ({n_g})")
        await pg.click('[data-bview="robot"]')
        await pg.wait_for_timeout(200)
        check(await pg.locator("#tab-bilan .grp").count() >= 2, "qualité des tickets par étoiles")

        print("Onglet Modèle")
        await pg.click('.tabs button[data-tab="modele"]')
        await pg.wait_for_timeout(200)
        txt = await pg.inner_text("#tab-modele")
        check("Ce que le robot apprend" in txt and "Poids du modèle maison" in txt, "leçons et indicateurs affichés")
        check(await pg.locator("#tab-modele .mchart svg").count() >= 2, "graphiques de calibration et d'évolution")
        check(await pg.locator("#tab-modele .vchip").count() >= 6, "verdicts hasard / à surveiller par type de pari")
        check("Le piège des petites séries" in txt, "lecture des écarts sur les tickets")
        await pg.click("#tab-modele .mchart .hit >> nth=0")
        check("Annoncé" in await pg.inner_text("#tab-modele .mchart .tip >> nth=0"), "détail d'un point au toucher")
        check(await pg.locator("#tab-modele .brief-item").count() >= 4, "résumé En bref en tête de l'onglet")
        check("Le favori annoncé a gagné 67 %" in await pg.inner_text("#tab-modele"), "NBA et tennis dans l'onglet Modèle")
        check(await pg.locator("#tab-modele .mkpi .info").count() == 4, "un bouton d'explication par métrique")
        await pg.click("#tab-modele .mkpi .info >> nth=1")
        check("mélangent" in await pg.inner_text(".info-pop"), "explication du poids du modèle maison")
        if os.environ.get("SHOTS"): await pg.wait_for_timeout(400); await pg.screenshot(path=os.environ["SHOTS"] + "/info.png")
        if os.environ.get("SHOTS"):
            await pg.evaluate("document.querySelector('.info-pop')?.remove(); window.scrollTo(0,0)"); await pg.set_viewport_size({"width": 390, "height": 1400})
            await pg.screenshot(path=os.environ["SHOTS"] + "/bref.png"); await pg.set_viewport_size({"width": 390, "height": 844})
        await pg.click("#tab-modele h2.section-title >> nth=0")
        check(await pg.locator(".info-pop").count() == 0, "l'explication se ferme en touchant ailleurs")
        w = await pg.evaluate("document.documentElement.scrollWidth")
        check(w <= 390, f"pas de défilement horizontal ({w}px)")

        print("Réglages et sauvegarde")
        await pg.click('.tabs button[data-tab="reglages"]')
        v = await pg.inner_text("#app-version")
        check(v not in ("", "?"), f"numéro de version affiché ({v})")
        async with pg.expect_download() as dl:
            await pg.evaluate("navigator.canShare = () => false")
            await pg.click("#export")
        data = json.loads(open(await (await dl.value).path(), encoding="utf-8").read())
        check(len(data["bets"]) == 4 and data.get("bank"), "la sauvegarde contient les 4 paris et la bankroll")

        print("Tous les onglets")
        for t in ("combos", "encours", "matchs", "bilan", "modele", "reglages"):
            n = await pg.eval_on_selector(f"#tab-{t}", "e => e.innerText.trim().length")
            check(n > 40, f"onglet {t} non vide")

        check(not errors, "aucune erreur JavaScript" + (f" : {errors}" if errors else ""))
        await b.close()
    srv.shutdown()
    print("\n" + ("TOUT EST OK" if not fails else f"{len(fails)} ECHEC(S)"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
