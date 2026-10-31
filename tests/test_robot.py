"""Tests du robot : reglement des paris, correspondance des equipes, notifications, combines.

Lancement : python tests/test_robot.py   (aucun acces reseau, aucun credit)
"""
import json
import os
import sys
import time
import unittest
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "robot"))
os.environ["NO_NOTIFY"] = "1"
import run  # noqa: E402
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
            self.assertAlmostEqual(c["odds"], round(float(__import__("numpy").prod([l["odds"] for l in c["legs"]])), 2), 2)
            if c["kind"] == "folie":
                self.assertTrue(15 <= c["odds"] <= 40)
                self.assertEqual(c["stake"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
