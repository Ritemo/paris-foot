"""Tests du robot : reglement des paris, correspondance des equipes, notifications, combines.

Lancement : python tests/test_robot.py   (aucun acces reseau, aucun credit)
"""
import json
import os
import sys
import time
import unittest
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "robot"))
os.environ["NO_NOTIFY"] = "1"
import run  # noqa: E402
import learn  # noqa: E402
from teams import to_fd  # noqa: E402


def leg(market, **kw):
    d = dict(match_id=kw.pop("mid", "m1"), market=market, label=market, home="Lens", away="Lille", league="Ligue 1",
             div="F1", kickoff=kw.pop("kickoff", "2026-10-25T16:00:00Z"), odds=1.8, p=0.55, ev=-0.05, src="unibet")
    d.update(kw)
    return d


class Reglement(unittest.TestCase):
    def test_1n2(self):
        self.assertTrue(run.leg_result(leg("1"), 2, 1))
        self.assertFalse(run.leg_result(leg("1"), 1, 1))
        self.assertTrue(run.leg_result(leg("N"), 0, 0))
        self.assertTrue(run.leg_result(leg("2"), 0, 3))

    def test_buts(self):
        self.assertTrue(run.leg_result(leg("+2.5"), 2, 1))
        self.assertFalse(run.leg_result(leg("+2.5"), 1, 1))
        self.assertTrue(run.leg_result(leg("-3.5"), 2, 1))
        self.assertFalse(run.leg_result(leg("-3.5"), 3, 1))
        self.assertTrue(run.leg_result(leg("+1.5"), 1, 1))
        self.assertFalse(run.leg_result(leg("-4.5"), 4, 1))

    def test_handicap(self):
        self.assertTrue(run.leg_result(leg("H1"), 3, 1))
        self.assertFalse(run.leg_result(leg("H1"), 2, 1))
        self.assertTrue(run.leg_result(leg("H2"), 0, 2))

    def test_double_chance_et_btts(self):
        self.assertTrue(run.leg_result(leg("1N"), 1, 1)); self.assertFalse(run.leg_result(leg("1N"), 0, 1))
        self.assertTrue(run.leg_result(leg("N2"), 0, 2)); self.assertTrue(run.leg_result(leg("12"), 3, 1))
        self.assertFalse(run.leg_result(leg("12"), 2, 2))
        self.assertTrue(run.leg_result(leg("BTTS"), 1, 1)); self.assertFalse(run.leg_result(leg("BTTS"), 2, 0))
        self.assertTrue(run.leg_result(leg("NBTTS"), 2, 0))

    def test_etoiles(self):
        # cote 2,0 (style par defaut, cible ~2,1), 5 % de marge par selection : tres interessant
        self.assertEqual(run.stars(0.95 ** 2 / 2.0, 1 - 0.95 ** 2, 2), 3)
        # meme cote, 12 % de marge par selection : le prix fait baisser la note
        self.assertEqual(run.stars(0.88 ** 2 / 2.0, 1 - 0.88 ** 2, 2), 2)
        # cote 6 alors que le style vise ~2 : hors de ton style
        self.assertEqual(run.stars(0.95 ** 3 / 6.0, 1 - 0.95 ** 3, 3), 1)
        # le style « gros gain » fait monter les grosses cotes
        self.assertGreater(run.interest(0.95 ** 3 / 4.0, 1 - 0.95 ** 3, 3, style=1), run.interest(0.95 ** 3 / 4.0, 1 - 0.95 ** 3, 3, style=0))

    def test_settle_combine(self):
        legs = [leg("1", mid="a"), leg("-3.5", mid="b")]
        h = {"combos": [dict(id="t", status="en attente", legs=legs, kind="x2", odds=3, p=.3, stake=2, day="2026-10-25")]}
        run.settle(h, None, {}, {"a": (2, 0), "b": (1, 1)})
        self.assertEqual(h["combos"][0]["status"], "gagne")
        legs2 = [leg("1", mid="a"), leg("-3.5", mid="b")]
        h2 = {"combos": [dict(id="u", status="en attente", legs=legs2, kind="x2", odds=3, p=.3, stake=2, day="2026-10-25")]}
        run.settle(h2, None, {}, {"a": (2, 0), "b": (3, 2)})
        self.assertEqual(h2["combos"][0]["status"], "perdu")
        self.assertEqual(legs2[1]["score"], "3-2")

    def test_settle_partiel(self):
        legs = [leg("1", mid="a"), leg("+2.5", mid="b")]
        h = {"combos": [dict(id="t", status="en attente", legs=legs, kind="x2", odds=3, p=.3, stake=2, day="2026-10-25")]}
        run.settle(h, None, {}, {"a": (2, 0)})
        self.assertEqual(h["combos"][0]["status"], "en attente")
        self.assertTrue(legs[0]["won"])
        self.assertNotIn("won", legs[1])


class Equipes(unittest.TestCase):
    def test_espn(self):
        for a, b in [("Paris Saint Germain", "Paris Saint-Germain"), ("FC Schalke 04", "Schalke 04"),
                     ("Borussia Monchengladbach", "Borussia Mönchengladbach"), ("Inter Milan", "Internazionale"),
                     ("RC Lens", "Lens"), ("Atlético Madrid", "Atlético Madrid"), ("AS Monaco", "AS Monaco")]:
            self.assertGreater(run._team_score(a, b), 0, f"{a} / {b}")
        self.assertEqual(run._team_score("Lens", "Lille"), 0)

    def test_football_data(self):
        names = {"Paris SG", "Lens", "Monaco", "Nott'm Forest", "Ath Madrid", "M'gladbach"}
        self.assertEqual(to_fd("Paris Saint Germain", names), "Paris SG")
        self.assertEqual(to_fd("RC Lens", names), "Lens")
        self.assertEqual(to_fd("Nottingham Forest", names), "Nott'm Forest")
        self.assertEqual(to_fd("Borussia Monchengladbach", names), "M'gladbach")


class Notifications(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._notify = run.notify
        run.notify = lambda title, msg, *a: self.sent.append(title)

    def tearDown(self):
        run.notify = self._notify

    def test_seulement_les_tickets_joues(self):
        h = {"combos": [dict(id="A", kind="x2", odds=2.5, status="gagne", legs=[leg("1", won=True, score="1-0")]),
                        dict(id="B", kind="x2", odds=2.0, status="perdu", legs=[leg("1", won=False, score="0-1")])]}
        run.notify_settled({"A": "en attente", "B": "en attente"}, h, {"A": {"mise": 2, "odds": 2.5}})
        self.assertEqual(len(self.sent), 1)
        self.assertIn("5,00", self.sent[0])

    def test_pas_de_doublon(self):
        h = {"combos": [dict(id="A", kind="x2", odds=2.5, status="gagne", legs=[leg("1", won=True)])]}
        run.notify_settled({"A": "gagne"}, h, {"A": {"mise": 2, "odds": 2.5}})
        self.assertEqual(self.sent, [])

    def test_sync_joues(self):
        now = time.time()
        msgs = [{"event": "message", "time": now - 50, "message": json.dumps({"action": "add", "id": "A", "mise": 2, "odds": 2.5})},
                {"event": "message", "time": now - 40, "message": json.dumps({"action": "add", "id": "B", "mise": 1, "odds": 30})},
                {"event": "message", "time": now - 30, "message": json.dumps({"action": "remove", "id": "B"})}]
        old = run.http_get
        run.http_get = lambda url, **k: ("\n".join(json.dumps(m) for m in msgs).encode(), {})
        try:
            meta = {}
            run.sync_played(meta)
            self.assertEqual(set(meta["played"]), {"A"})
        finally:
            run.http_get = old


class Championnats(unittest.TestCase):
    def test_coupes_europe(self):
        self.assertIn("soccer_uefa_europa_league", run.LEAGUES)
        self.assertEqual(run.ESPN_LEAGUE["EL"], "uefa.europa")
        self.assertEqual(run.ESPN_LEAGUE["CL"], "uefa.champions")


class ArrondiUnibet(unittest.TestCase):
    def test_cote_totale(self):
        legs = [dict(odds=1.70, p=.5, ev=0, match_id="a", market="1"), dict(odds=1.45, p=.5, ev=0, match_id="b", market="1")]
        self.assertEqual(run.make_combo("2026-11-03", "x2", legs)["odds"], 2.47)


class Combines(unittest.TestCase):
    def match(self, i, o1, oN, o2, p1, pN):
        sel = [dict(market="1", label="Victoire", odds=o1, src="unibet", p=p1),
               dict(market="N", label="Nul", odds=oN, src="unibet", p=pN),
               dict(market="2", label="Victoire ext", odds=o2, src="unibet", p=1 - p1 - pN),
               dict(market="+2.5", label="Plus de 2,5 buts", odds=1.7, src="pmu", p=0.56),
               dict(market="-2.5", label="Moins de 2,5 buts", odds=2.1, src="pmu", p=0.44)]
        for s in sel:
            s["ev"] = s["p"] * s["odds"] - 1
        k = (run.NOW + timedelta(hours=3 + i)).isoformat()
        return dict(id=f"m{i}", league="Ligue 1", div="F1", kickoff=k, day="2026-11-01", home=f"H{i}", away=f"A{i}",
                    fd_home=None, fd_away=None, sel=sel)

    def test_combines_du_jour(self):
        ms = [self.match(i, 1.4 + i * 0.1, 4.0, 6.0, 0.62 - i * 0.03, 0.22) for i in range(8)]
        cs = run.combos_for_day("2026-11-01", ms)
        kinds = [c["kind"] for c in cs]
        self.assertIn("x2", kinds)
        for c in cs:
            self.assertEqual(len({l["match_id"] for l in c["legs"]}), len(c["legs"]), "deux selections du meme match")
            prod = float(__import__("numpy").prod([l["odds"] for l in c["legs"]]))
            self.assertLessEqual(abs(c["odds"] - prod), 0.005 + 1e-9)
            if c["kind"] == "folie":
                self.assertTrue(15 <= c["odds"] <= 40)
                self.assertEqual(c["stake"], 1)


class Apprentissage(unittest.TestCase):
    """Amelioration continue (learn.py) : jeux synthetiques, aucun reseau."""

    def store(self, n, pm_good, bias=0.0, seed=1):
        import numpy as np
        rng = np.random.default_rng(seed)
        st = learn.new_store()
        for i in range(n):
            lh, la = rng.uniform(0.8, 2.2), rng.uniform(0.6, 1.8)
            truth = learn.vec(run.score_matrix(lh, la))
            noisy = learn.vec(run.score_matrix(lh * rng.uniform(0.75, 1.3), la * rng.uniform(0.75, 1.3)))
            pk = noisy if pm_good else truth
            pm = truth if pm_good else noisy
            hg, ag = int(rng.poisson(lh)), int(rng.poisson(la))
            if bias and rng.random() < bias and hg == ag:   # moins de nuls que prevu
                hg += 1
            d = (run.NOW - timedelta(days=int(rng.integers(1, 300)))).date().isoformat()
            st["preds"][f"x{i}"] = dict(d=d, k=d + "T15:00:00Z", div="F1", lg="Ligue 1", h="A", a="B", pm=pm, pk=pk, pr=pk,
                                        res=[hg, ag], src="backtest")
        return st

    def test_poids_suit_le_meilleur(self):
        bon = learn.learn_params(self.store(1500, pm_good=True), run.NOW)
        mauvais = learn.learn_params(self.store(1500, pm_good=False), run.NOW)
        self.assertGreater(bon["w_model"], learn.W_PRIOR)
        self.assertLess(mauvais["w_model"], learn.W_PRIOR)
        self.assertLessEqual(bon["w_model"], learn.W_MAX)

    def test_prudence_petit_echantillon(self):
        p = learn.learn_params(self.store(60, pm_good=False), run.NOW)
        self.assertGreater(p["w_model"], 0.12)                       # 60 matchs : on bouge a peine
        self.assertTrue(all(v == 0 for v in p["offsets"].values()))  # pas de correction sur si peu

    def test_correction_si_ecart_net(self):
        p = learn.learn_params(self.store(2500, pm_good=False, bias=0.5), run.NOW)
        self.assertLess(p["offsets"]["nul"], 0)                      # nuls surestimes : correction a la baisse
        self.assertGreaterEqual(p["offsets"]["nul"], -learn.CAL_MAX)
        sain = learn.learn_params(self.store(2500, pm_good=False), run.NOW)
        self.assertEqual(sain["offsets"]["nul"], 0.0)                # pas d'ecart : pas de correction

    def test_ajustement_coherent(self):
        p = run.probs(run.score_matrix(1.5, 1.1))
        q = learn.adjust_probs(p, {"nul": -0.2, "buts": 0.1, "hcp": -0.2})
        self.assertAlmostEqual(q["p1"] + q["pN"] + q["p2"], 1, places=6)
        self.assertLess(q["pN"], p["pN"]); self.assertGreater(q["pO"], p["pO"])
        self.assertLessEqual(q["h1"], q["p1"])
        self.assertIs(learn.adjust_probs(p, {}), p)

    def test_metriques_et_tickets(self):
        st = self.store(400, pm_good=False)
        st["preds"]["futur"] = dict(d="2099-01-01", k="2099-01-01T15:00:00Z", div="F1", lg="Ligue 1", h="A", a="B",
                                    pm=None, pk=[.4, .3, .3, .7, .5, .3, .5, .2, .1], pr=[.4, .3, .3, .7, .5, .3, .5, .2, .1], src="live")
        prm = learn.learn_params(st, run.NOW)
        h = {"combos": [dict(id=str(i), kind="x2", status="gagne" if i < 3 else "perdu", p=0.35, replaced=False,
                             legs=[leg("1", won=i < 5), leg("+2.5", mid="m2", won=True)]) for i in range(13)]}
        m = learn.metrics(st, prm, h, run.NOW)
        self.assertEqual(m["counts"]["pending"], 1)
        self.assertEqual(len(m["families"]), 6)
        self.assertTrue(m["calibration"] and m["lessons"])
        t = m["tickets"]["tickets"]
        self.assertEqual((t["n"], t["observes"]), (13, 3))
        self.assertEqual(learn.verdict(t["z"]), "hasard")             # 3 sur 13 pour 4,6 attendus : la chance
        json.dumps(m)                                                 # ecrivable tel quel dans model.json

    def test_journal_ne_reecrit_pas_un_match_regle(self):
        st = learn.new_store()
        st["preds"]["a"] = dict(d="2026-11-01", res=[1, 0])
        learn.record(st, "a", dict(d="2026-11-01"), None, [.5] * 9, [.5] * 9)
        self.assertEqual(st["preds"]["a"]["res"], [1, 0])



class TestCredits(unittest.TestCase):
    def test_apres_midi_selon_credits(self):
        now = datetime(2026, 11, 7, 16, 45, tzinfo=run.PARIS)
        self.assertTrue(run.afternoon_affordable({"credits_remaining": 380}, now))
        self.assertFalse(run.afternoon_affordable({"credits_remaining": 200}, now))
        self.assertTrue(run.afternoon_affordable({"credits_remaining": 40}, datetime(2026, 11, 29, 16, 45, tzinfo=run.PARIS)))


class TestKickoff(unittest.TestCase):
    def test_une_notif_par_match_joue(self):
        now = run.NOW
        leg = {"match_id": "mk", "home": "Toulouse", "away": "Strasbourg", "label": "Plus de 2,5 buts",
               "kickoff": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")}
        c1 = {"id": "t1", "status": "en attente", "legs": [dict(leg)]}
        c2 = {"id": "t2", "status": "en attente", "legs": [dict(leg, label="Toulouse ou nul")]}
        loin = {"id": "t3", "status": "en attente", "legs": [dict(leg, match_id="m2", kickoff=(now + timedelta(hours=3)).isoformat())]}
        meta = {"played": {"t1": {"mise": 2}, "t2": {"mise": 1, "snap": c2}, "t3": {"mise": 1}}}
        sent = []
        old = run.notify
        run.notify = lambda title, msg, *a, **k: sent.append((title, msg))
        try:
            self.assertTrue(run.notify_kickoffs(meta, {"combos": [c1, loin]}))
            self.assertFalse(run.notify_kickoffs(meta, {"combos": [c1, loin]}))   # pas deux fois
        finally:
            run.notify = old
        self.assertEqual(len(sent), 1)
        self.assertIn("Toulouse - Strasbourg", sent[0][0])
        self.assertIn("Plus de 2,5 buts, Toulouse ou nul", sent[0][1])


class TestRecap(unittest.TestCase):
    def test_recap_dimanche_soir(self):
        old_now, old_notify = run.NOW, run.notify
        sent = []
        run.NOW = datetime(2026, 11, 8, 23, 20, tzinfo=run.PARIS)
        run.notify = lambda title, msg, *a, **k: sent.append((title, msg))
        try:
            leg = {"label": "Plus de 2,5 buts", "home": "A", "away": "B"}
            g = {"id": "g", "day": "2026-11-07", "kind": "x2", "status": "gagne", "odds": 2.5, "legs": [leg]}
            p = {"id": "p", "day": "2026-11-08", "kind": "x2", "status": "perdu", "odds": 2.0, "legs": [leg]}
            vieux = {"id": "v", "day": "2026-11-01", "kind": "x2", "status": "gagne", "odds": 3.0, "legs": [leg]}
            meta = {"played": {"g": {"mise": 2, "odds": 2.5}, "p": {"mise": 1, "odds": 2.0}, "v": {"mise": 5, "odds": 3.0}}}
            h = {"combos": [g, p, vieux]}
            self.assertTrue(run.weekly_recap(meta, h))
            self.assertFalse(run.weekly_recap(meta, h))   # une seule fois par semaine
            run.NOW = datetime(2026, 11, 8, 20, 0, tzinfo=run.PARIS)
            self.assertFalse(run.weekly_recap({"played": meta["played"]}, h))   # trop tot
        finally:
            run.NOW, run.notify = old_now, old_notify
        self.assertEqual(len(sent), 1)
        self.assertIn("du 2 au 8 novembre : +2,00 €", sent[0][0])
        self.assertIn("Misé 3,00 €, récupéré 5,00 €", sent[0][1])
        self.assertIn("robot : 1 gagné sur 2", sent[0][1])


class TestBackup(unittest.TestCase):
    def test_reassemble_les_morceaux(self):
        import tempfile
        old_get, old_data = run.http_get, run.DATA
        run.DATA = tempfile.mkdtemp()
        def ev(t, d):
            return json.dumps({"event": "message", "time": t, "message": json.dumps(d) if isinstance(d, dict) else d})
        msgs = [ev(10, {"b": "aa", "i": 1, "n": 2, "d": "CD=="}), ev(9, {"b": "aa", "i": 0, "n": 2, "d": "1.AB"}),
                ev(11, {"b": "bb", "i": 0, "n": 3, "d": "1.XX"}),          # incomplete
                ev(12, "pas du json"), ev(13, {"b": "cc", "i": 0, "n": 1, "d": "<script>"})]   # rejete
        run.http_get = lambda url, **k: ("\n".join(msgs).encode(), {})
        try:
            self.assertTrue(run.sync_backup())
            self.assertFalse(run.sync_backup())   # deja range
            saves = run.load("backup.json", {})["saves"]
        finally:
            run.http_get, run.DATA = old_get, old_data
        self.assertEqual([(s["id"], s["blob"]) for s in saves], [("aa", "1.ABCD==")])


class TestAutresSports(unittest.TestCase):
    def test_cote_estimee_charge_l_outsider(self):
        est = run.fr_estimate([0.788, 0.212], 1.139)
        self.assertAlmostEqual(sum(1 / x for x in est), 1.139, delta=0.01)
        self.assertLess(est[0], 1 / 0.788)               # favori un peu moins paye
        self.assertLess(est[1] / (1 / 0.212), est[0] / (1 / 0.788))   # outsider bien plus taxe (comme unibet.fr)

    def test_handicap_points(self):
        self.assertTrue(run.leg_result({"market": "HC1:-7.5"}, 110, 100))
        self.assertFalse(run.leg_result({"market": "HC1:-7.5"}, 105, 100))
        self.assertTrue(run.leg_result({"market": "HC2:+7.5"}, 105, 100))
        self.assertTrue(run.leg_result({"market": "+220.5"}, 112, 110))

    def test_nba_depuis_espn(self):
        k = (run.NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%MZ")
        ev = {"events": [{"id": "1", "date": k, "competitions": [{"status": {"type": {"state": "pre"}}, "competitors": [
            {"homeAway": "home", "team": {"displayName": "Philadelphia 76ers", "shortDisplayName": "76ers"}},
            {"homeAway": "away", "team": {"displayName": "Toronto Raptors", "shortDisplayName": "Raptors"}}],
            "odds": [{"moneyline": {"home": {"close": {"odds": "-270"}}, "away": {"close": {"odds": "+221"}}},
                      "pointSpread": {"home": {"close": {"line": "-7.5", "odds": "-103"}}, "away": {"close": {"line": "+7.5", "odds": "-118"}}},
                      "total": {"over": {"close": {"line": "o223.5", "odds": "-112"}}, "under": {"close": {"line": "u223.5", "odds": "-108"}}}}]}]}]}
        old = run.http_get
        run.http_get = lambda url, **kw: (json.dumps(ev).encode(), {})
        try:
            ms = run.nba_matches(run.NOW + timedelta(days=2), {("Philadelphia 76ers", "Toronto Raptors"): (1.34, 2.85)})
        finally:
            run.http_get = old
        self.assertEqual(len(ms), 1)
        sel = {s["market"]: s for s in ms[0]["sel"]}
        self.assertEqual((sel["1"]["odds"], sel["1"]["src"]), (1.34, "unibet"))
        self.assertIn("HC1:-7.5", sel)
        self.assertIn("+223.5", sel)
        self.assertEqual(sel["HC1:-7.5"]["src"], "estimee")
        self.assertEqual(ms[0]["sport"], "basket")

    def test_tennis_resultat_espn(self):
        k = "2026-11-11T10:00Z"
        comp = {"date": k, "status": {"type": {"completed": True, "state": "post"}}, "competitors": [
            {"athlete": {"displayName": "Ugo Humbert"}, "winner": False, "linescores": [{"winner": True}, {"winner": False}, {"winner": False}]},
            {"athlete": {"displayName": "Lorenzo Musetti"}, "winner": True, "linescores": [{"winner": False}, {"winner": True}, {"winner": True}]}]}
        boards = {("tennis/atp", d): [{"groupings": [{"grouping": {"displayName": "Men's Singles"}, "competitions": [comp]}]}] for d in ("20261110", "20261111", "20261112")}
        l = {"div": "ATP", "kickoff": "2026-11-11T09:30:00Z", "home": "Lorenzo Musetti", "away": "Ugo Humbert", "market": "1"}
        self.assertEqual(run.espn_other_score(l, boards), (2, 1))

    def test_un_sport_par_ticket(self):
        k = (run.NOW + timedelta(hours=5)).isoformat()
        day = run.paris_day(k)
        def m(i, sport, odds):
            return {"id": f"m{i}", "sport": sport, "league": sport, "div": sport, "kickoff": k, "day": day, "home": f"H{i}", "away": f"A{i}",
                    "fd_home": None, "fd_away": None, "sel": [{"market": "1", "label": "x", "odds": odds, "src": "unibet", "p": 0.97 / odds, "ev": -0.03}]}
        ms = [m(1, "foot", 1.5), m(2, "foot", 1.6), m(3, "basket", 1.5), m(4, "basket", 1.55), m(5, "tennis", 1.45)]
        cands, _ = run.candidates(day, ms)
        self.assertTrue(cands)
        for c in cands:   # chaque ticket : un seul sport, sauf ceux marques « mix »
            self.assertEqual(len({l["sport"] for l in c["legs"]}) > 1, bool(c.get("mix")))
        self.assertTrue(any(c.get("mix") for c in cands))
        for c in run.combos_for_day(day, ms):   # les tickets du robot restent d'un seul sport
            self.assertFalse(c.get("mix"))
        self.assertTrue(any(c.get("mix") for c in run.alts_for_day(day, ms, set())))


class TestOddsPapi(unittest.TestCase):
    def test_actualise_le_1n2_unibet(self):
        k = "2026-11-21T15:00:00Z"
        events = {"a": {"home_team": "Paris Saint Germain", "away_team": "Le Havre", "commence_time": k,
                        "bookmakers": [{"key": "unibet_fr", "markets": [{"key": "h2h", "outcomes": [{"name": "Paris Saint Germain", "price": 1.2}]},
                                                                         {"key": "totals", "outcomes": []}]}]},
                  "b": {"home_team": "Lyon", "away_team": "Nice", "commence_time": k, "bookmakers": []},
                  "c": {"home_team": "Brest", "away_team": "Metz", "commence_time": k, "bookmakers": []}}
        ops = [{"start": "2026-11-21T15:00:00.000Z", "home": "Paris Saint-Germain", "away": "Le Havre AC", "odds": (1.27, 4.5, 5.8)},
               {"start": "2026-11-21T15:05:00.000Z", "home": "Olympique Lyonnais", "away": "OGC Nice", "odds": (2.0, 3.3, 2.65)}]
        self.assertEqual(run.apply_op(events, ops), 2)
        o = run.extract(events["a"])
        self.assertEqual(o["h2h"], (1.27, 4.5, 5.8))
        self.assertEqual(o["h2h_src"], "unibet")
        self.assertIn("totals", [m["key"] for m in events["a"]["bookmakers"][0]["markets"]])   # les buts restent
        self.assertEqual(run.extract(events["b"])["h2h"], (2.0, 3.3, 2.65))
        self.assertNotIn("h2h", run.extract(events["c"]))   # pas trouve : inchange

    def test_quota_du_mois(self):
        meta = {"oddspapi": {"month": run.NOW.strftime("%Y-%m"), "used": run.OP_LIMIT}}
        with self.assertRaises(RuntimeError):
            run.op_get(meta, "/sports")


class TestCorrections(unittest.TestCase):
    def test_apprend_des_cotes_saisies(self):
        import tempfile
        old_get, old_data = run.http_get, run.DATA
        run.DATA = tempfile.mkdtemp()
        msgs = [json.dumps({"event": "message", "id": f"e{i}", "time": i, "message": json.dumps(
            {"sport": "foot", "k": "total", "src": "pmu", "est": 1.80, "real": 1.72})}) for i in range(6)]
        msgs.append(json.dumps({"event": "message", "id": "faux", "time": 9, "message": json.dumps(
            {"sport": "foot", "k": "total", "src": "pmu", "est": 1.80, "real": 9.0})}))   # aberrant : ignore
        run.http_get = lambda url, **k: ("\n".join(msgs).encode(), {})
        try:
            adj = run.sync_corrections()
        finally:
            run.http_get, run.DATA = old_get, old_data
        self.assertAlmostEqual(adj["foot|total|pmu"], round(1.72 / 1.80, 3))
        m = {"sport": "foot", "sel": [{"market": "+2.5", "odds": 1.80, "src": "pmu", "p": 0.53, "ev": 0},
                                      {"market": "1", "odds": 1.60, "src": "unibet", "p": 0.6, "ev": 0}]}
        run.apply_adjust([m], adj)
        self.assertEqual(m["sel"][0]["odds"], 1.72)
        self.assertEqual(m["sel"][0]["raw_odds"], 1.80)
        self.assertEqual(m["sel"][1]["odds"], 1.60)   # les cotes Unibet ne bougent pas


class TestJournalAutres(unittest.TestCase):
    def test_journal_et_resume(self):
        import tempfile
        old_data, old_score = run.DATA, run.espn_other_score
        run.DATA = tempfile.mkdtemp()
        k = (run.NOW - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
        ms = [{"id": f"nba-{i}", "sport": "basket", "div": "NBA", "kickoff": k, "home": f"H{i}", "away": f"A{i}",
               "sel": [{"market": "1", "p": 0.7, "odds": 1.35}]} for i in range(4)]
        run.espn_other_score = lambda l, boards: (110, 100) if l["home"] != "H3" else (90, 100)
        try:
            s = run.other_journal(ms)
        finally:
            run.DATA, run.espn_other_score = old_data, old_score
        self.assertEqual(s["basket"]["n"], 4)
        self.assertEqual(s["basket"]["fav"], 0.75)
        self.assertEqual(s["basket"]["bins"][0]["f"], 0.75)


class TestChiffrement(unittest.TestCase):
    def test_paris_joues_chiffres(self):
        import tempfile
        old = (run.CODE, run.DATA, run.http_get)
        run.CODE, run.DATA = "4X8DQ9NE7SR7F6JK", tempfile.mkdtemp()
        try:
            meta = {"played": {"t1": {"mise": 2, "odds": 2.1, "t": run.NOW.timestamp()}}}
            run.save_meta(meta)
            raw = run.load("meta.json", {})
            self.assertNotIn("played", raw)
            self.assertNotIn("2.1", json.dumps(raw))
            self.assertTrue(raw["played_enc"])
            m2 = run.load_meta()
            self.assertEqual(m2["played"]["t1"]["mise"], 2)
            # message chiffre accepte, message en clair ignore une fois le chiffrement installe depuis plus de 2 jours
            enc = json.dumps({"enc": run.seal({"action": "add", "id": "t2", "mise": 1.31, "odds": 2})})
            clair = json.dumps({"action": "add", "id": "faux", "mise": 50, "odds": 2})
            t = run.NOW.timestamp()
            evs = [json.dumps({"event": "message", "time": t, "message": enc}), json.dumps({"event": "message", "time": t, "message": clair})]
            run.http_get = lambda url, **k: ("\n".join(evs).encode(), {})
            m2["enc_since"] = (run.NOW - timedelta(days=5)).isoformat()
            run.sync_played(m2)
            self.assertIn("t2", m2["played"])
            self.assertNotIn("faux", m2["played"])
        finally:
            run.CODE, run.DATA, run.http_get = old


class TestPassageComplet(unittest.TestCase):
    """Un passage complet du robot (cotes, matchs, combines, fichiers), avec des API simulees : aucun appel reseau."""

    def test_passage_complet(self):
        import tempfile
        import numpy as np
        import pandas as pd
        rng = np.random.default_rng(1)
        teams = ["Lyon", "Nice", "Lens", "Lille", "Rennes", "Nantes", "Brest", "Metz"]
        rows = []
        for i in range(140):
            h, a = rng.choice(teams, 2, replace=False)
            rows.append(dict(Div="F1", Date=pd.Timestamp(run.NOW.date()) - pd.Timedelta(days=3 + i), HomeTeam=h, AwayTeam=a,
                             FTHG=int(rng.poisson(1.5)), FTAG=int(rng.poisson(1.1)), HST=int(rng.poisson(5)), AST=int(rng.poisson(4))))
        fd = pd.DataFrame(rows)
        k1 = (run.NOW + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        k2 = (run.NOW + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        def ev(i, h, a, k):
            return {"id": f"ev{i}", "sport_key": "soccer_france_ligue_one", "commence_time": k, "home_team": h, "away_team": a, "bookmakers": [
                {"key": "unibet_fr", "link": "https://www.unibet.fr/paris-football/x", "markets": [{"key": "h2h", "outcomes": [
                    {"name": h, "price": 1.75}, {"name": "Draw", "price": 3.6}, {"name": a, "price": 4.4}]}]},
                {"key": "pmu_fr", "markets": [{"key": "totals", "outcomes": [{"name": "Over", "point": 2.5, "price": 1.8}, {"name": "Under", "point": 2.5, "price": 1.95}]}]}]}
        events = [ev(1, "Lyon", "Nice", k1), ev(2, "Lens", "Lille", k2), ev(3, "Rennes", "Nantes", k2), ev(4, "Brest", "Metz", k1)]
        calls = []
        def fake_get(url, **kw):
            calls.append(url)
            h = {"x-requests-remaining": "300", "x-requests-last": "2"}
            if "the-odds-api.com" in url:
                if "/soccer_france_ligue_one/events" in url:
                    return json.dumps([{"commence_time": k1}]).encode(), h
                if "/soccer_france_ligue_one/odds" in url:
                    return json.dumps(events).encode(), h
                return b"[]", h
            if "espn.com" in url:
                return json.dumps({"events": [], "sports": [{"leagues": [{"teams": []}]}]}).encode(), {}
            return b"", {}
        old = (run.DATA, run.http_get, run.load_history_fd, run.seed_learning, os.environ.get("FORCE"), run.KEY, run.OP_KEY)
        run.DATA = tempfile.mkdtemp()
        run.http_get, run.load_history_fd = fake_get, (lambda n=2: fd)
        run.seed_learning = lambda store: store.update(seeded=True)
        run.KEY, run.OP_KEY = "test", ""
        os.environ["FORCE"] = "1"
        try:
            run.main()
            today = run.load("today.json", {})
            meta = run.load("meta.json", {})
        finally:
            run.DATA, run.http_get, run.load_history_fd, run.seed_learning, force, run.KEY, run.OP_KEY = old
            if force is None:
                os.environ.pop("FORCE", None)
            else:
                os.environ["FORCE"] = force
        self.assertEqual(len([m for m in today["matches"] if m.get("league") == "Ligue 1"]), 4)
        m = today["matches"][0]
        self.assertTrue(m["link"].startswith("https://www.unibet.fr/") and m["odds_at"])
        self.assertTrue({"1", "N", "2", "+2.5"} <= {s["market"] for s in m["sel"]})
        self.assertTrue(today["combos"] or today.get("alts"))
        self.assertEqual(meta.get("full_day"), run.NOW.astimezone(run.PARIS).date().isoformat())
        self.assertFalse(any("api.oddspapi.io" in u for u in calls))

if __name__ == "__main__":
    unittest.main(verbosity=1)
