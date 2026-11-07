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

if __name__ == "__main__":
    unittest.main(verbosity=1)
