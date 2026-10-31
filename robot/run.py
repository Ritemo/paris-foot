"""Robot paris-foot : modele + cotes Unibet -> combines du jour, historique et bilan.

Lance par GitHub Actions (8h, 17h, ou a la demande). Ecrit dans docs/data/.
Variable d'environnement requise : ODDS_API_KEY.
"""
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from model import fit_poisson, score_matrix
from teams import to_fd

PARIS = ZoneInfo("Europe/Paris")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
API = "https://api.the-odds-api.com/v4"
KEY = os.environ.get("ODDS_API_KEY", "")

LEAGUES = {  # cle The Odds API -> (code football-data, nom affiche)
    "soccer_france_ligue_one": ("F1", "Ligue 1"),
    "soccer_epl": ("E0", "Premier League"),
    "soccer_spain_la_liga": ("SP1", "Liga"),
    "soccer_italy_serie_a": ("I1", "Serie A"),
    "soccer_germany_bundesliga": ("D1", "Bundesliga"),
    "soccer_uefa_champs_league": ("CL", "Ligue des champions"),  # pas d'historique football-data : probabilites du marche seules
}
FD_DIVS = ("F1", "E0", "SP1", "I1", "D1")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "combines-foot-ritemo-7k3q9x")
XI, MIX, W_MODEL = 0.0019, 0.5, 0.2      # reglages valides par le backtest
CREDIT_FLOOR_TOTALS = 40                   # en dessous : 1N2 seulement (1 credit / championnat)
CREDIT_FLOOR_ODDS = 12                     # en dessous : plus d'appel payant, on garde le cache
CREDIT_FLOOR_SCORES = 100                  # resultats via l'API seulement si assez de credits
NOW = datetime.now(timezone.utc)
credits = {"remaining": None, "used_run": 0}


# ---------------------------------------------------------------- utilitaires
def load(name, default):
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


def http_get(url, timeout=40):
    ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36" if "espn.com" in url else "paris-foot-robot"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def odds_api(path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    body, h = http_get(f"{API}{path}?apiKey={KEY}&{q}")
    h = {k.lower(): v for k, v in h.items()}
    if "x-requests-remaining" in h:
        credits["remaining"] = int(float(h["x-requests-remaining"]))
        credits["used_run"] += int(float(h.get("x-requests-last", 0)))
    return json.loads(body)


def season_codes(d):
    y = d.year % 100 if d.month >= 7 else d.year % 100 - 1
    return [f"{y - 1:02d}{y:02d}", f"{y:02d}{y + 1:02d}"]


def paris_day(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()


# ---------------------------------------------------------------- historique et modele
def load_history_fd():
    frames = []
    for div in FD_DIVS:
        for s in season_codes(NOW):
            try:
                body, _h = http_get(f"https://www.football-data.co.uk/mmz4281/{s}/{div}.csv")
                frames.append(pd.read_csv(io.BytesIO(body), encoding="utf-8-sig"))
            except Exception as e:  # saison pas encore publiee, etc.
                print("football-data", div, s, e, file=sys.stderr)
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)
    df = df.dropna(subset=["FTHG", "FTAG"])
    for c, g in (("HST", "FTHG"), ("AST", "FTAG")):
        df[c] = df[c].fillna(df[g] * 3)
    return df


def fit_league(g):
    k = (g.FTHG.sum() + g.FTAG.sum()) / max(g.HST.sum() + g.AST.sum(), 1)
    teams = sorted(set(g.HomeTeam) | set(g.AwayTeam))
    idx = {t: i for i, t in enumerate(teams)}
    w = np.exp(-XI * (pd.Timestamp(NOW.date()) - g.Date).dt.days.values)
    mu, home, att, de = fit_poisson(g.HomeTeam.map(idx).values, g.AwayTeam.map(idx).values,
                                    (1 - MIX) * g.FTHG.values + MIX * k * g.HST.values,
                                    (1 - MIX) * g.FTAG.values + MIX * k * g.AST.values, w, len(teams))
    counts = pd.concat([g.HomeTeam, g.AwayTeam]).value_counts().to_dict()
    return dict(idx=idx, mu=mu, home=home, att=att, de=de, counts=counts, names=set(teams))


def model_lambdas(m, h, a):
    if m is None or h is None or a is None or m["counts"].get(h, 0) < 5 or m["counts"].get(a, 0) < 5:
        return None
    i, j = m["idx"][h], m["idx"][a]
    return (float(np.exp(m["mu"] + m["home"] + m["att"][i] - m["de"][j])),
            float(np.exp(m["mu"] + m["att"][j] - m["de"][i])))


def market_lambdas(p1, p2, pover, line, start):
    """Lambdas qui reproduisent au mieux les probabilites du marche (1, 2, plus de X,5 buts)."""
    def err(x):
        mm = score_matrix(np.exp(x[0]), np.exp(x[1]))
        g = np.arange(mm.shape[0])
        e = (np.tril(mm, -1).sum() - p1) ** 2 + (np.triu(mm, 1).sum() - p2) ** 2
        if pover is not None:
            e += (mm[(g[:, None] + g[None, :]) > line].sum() - pover) ** 2
        return e
    r = minimize(err, np.log(start), method="Nelder-Mead", options=dict(xatol=1e-4, fatol=1e-9))
    return float(np.exp(r.x[0])), float(np.exp(r.x[1]))


def probs(mat, line=2.5):
    g = np.arange(mat.shape[0])
    diff = g[:, None] - g[None, :]
    tot = g[:, None] + g[None, :]
    return dict(p1=mat[diff > 0].sum(), pN=mat[diff == 0].sum(), p2=mat[diff < 0].sum(),
                pO=mat[tot > line].sum(), h1=mat[diff >= 2].sum(), h2=mat[diff <= -2].sum())


# ---------------------------------------------------------------- cotes
def fetch_odds(leagues_needed, cache):
    """Recupere les cotes en economisant les credits. Retourne {event_id: event}."""
    events = {}
    remaining = credits["remaining"]
    for sport in leagues_needed:
        if remaining is not None and remaining < CREDIT_FLOOR_ODDS:
            print("credits trop bas, cache utilise pour", sport, file=sys.stderr)
            continue
        markets = "h2h,totals" if (remaining is None or remaining >= CREDIT_FLOOR_TOTALS) else "h2h"
        try:
            data = odds_api(f"/sports/{sport}/odds", regions="fr", markets=markets, oddsFormat="decimal")
        except Exception as e:
            print("odds", sport, e, file=sys.stderr)
            continue
        remaining = credits["remaining"]
        for e in data:
            e["sport"] = sport
            e["fetched_at"] = NOW.isoformat()
            events[e["id"]] = e
    for eid, e in cache.items():  # completer avec le cache pour les matchs non actualises
        if eid not in events and e["commence_time"] > NOW.isoformat():
            events[eid] = e
    return events


def extract(e):
    """Cotes Unibet 1N2 + cotes buts (PMU, sinon NetBet, sinon autre bookmaker FR)."""
    out = {}
    books = {b["key"]: b for b in e.get("bookmakers", [])}
    src = "unibet" if "unibet_fr" in books else None
    order = ["unibet_fr", "betclic_fr", "winamax_fr", "pmu_fr", "netbet_fr"]
    for k in order:
        if k in books:
            for m in books[k]["markets"]:
                if m["key"] == "h2h" and "h2h" not in out:
                    o = {x["name"]: x["price"] for x in m["outcomes"]}
                    out["h2h"] = (o.get(e["home_team"]), o.get("Draw"), o.get(e["away_team"]))
                    out["h2h_src"] = "unibet" if k == "unibet_fr" else k.replace("_fr", "")
    for k in ["unibet_fr", "pmu_fr", "netbet_fr", "betclic_fr", "winamax_fr"]:
        if k in books and "totals" not in out:
            for m in books[k]["markets"]:
                if m["key"] == "totals":
                    pts = {}
                    for x in m["outcomes"]:
                        pts.setdefault(x.get("point"), {})[x["name"]] = x["price"]
                    full = {pt: o for pt, o in pts.items() if pt is not None and "Over" in o and "Under" in o}
                    if full:  # ligne principale : la plus equilibree
                        pt = min(full, key=lambda q: abs(full[q]["Over"] - full[q]["Under"]))
                        out["totals"] = (pt, full[pt]["Over"], full[pt]["Under"])
                        out["totals_src"] = k.replace("_fr", "")
    return out


# ---------------------------------------------------------------- selections et combines
def build_matches(events, models):
    matches = []
    for eid, e in events.items():
        if e["commence_time"] <= NOW.isoformat():
            continue
        div, lname = LEAGUES[e["sport"]]
        mdl = models.get(div)
        names = mdl["names"] if mdl else set()
        h, a = to_fd(e["home_team"], names), to_fd(e["away_team"], names)
        o = extract(e)
        if "h2h" not in o or None in o["h2h"]:
            continue
        o1, oN, o2 = o["h2h"]
        inv = 1 / o1 + 1 / oN + 1 / o2
        f1, f2 = 1 / o1 / inv, 1 / o2 / inv
        fO, line = None, 2.5
        if "totals" in o:
            line, oo, ou = o["totals"]
            fO = (1 / oo) / (1 / oo + 1 / ou)
        lm = model_lambdas(mdl, h, a)
        lmk = market_lambdas(f1, f2, fO, line, lm or (1.4, 1.1))
        mat = score_matrix(*lmk)
        if lm:
            mat = W_MODEL * score_matrix(*lm) + (1 - W_MODEL) * mat
        p = probs(mat, line)
        est = lambda pp: round(1 / (pp * inv), 2)  # cote estimee avec la marge Unibet du match
        lt = f"{line:g}".replace(".", ",")
        H, A = e["home_team"], e["away_team"]
        sel = [
            dict(market="1", label=f"Victoire {H}", odds=o1, src=o["h2h_src"], p=p["p1"]),
            dict(market="N", label="Match nul", odds=oN, src=o["h2h_src"], p=p["pN"]),
            dict(market="2", label=f"Victoire {A}", odds=o2, src=o["h2h_src"], p=p["p2"]),
        ]
        if "totals" in o:
            sel += [dict(market=f"+{line:g}", label=f"Plus de {lt} buts", odds=o["totals"][1], src=o["totals_src"], p=p["pO"]),
                    dict(market=f"-{line:g}", label=f"Moins de {lt} buts", odds=o["totals"][2], src=o["totals_src"], p=1 - p["pO"])]
        else:  # pas de cote : probabilite seule, cote estimee
            for mk, lab, pp in (("+2.5", "Plus de 2,5 buts", p["pO"]), ("-2.5", "Moins de 2,5 buts", 1 - p["pO"])):
                sel.append(dict(market=mk, label=lab, odds=est(pp), src="estimee", p=pp))
        for mk, team, pw, ph in (("H1", H, p["p1"], p["h1"]), ("H2", A, p["p2"], p["h2"])):
            if pw >= 0.55 and ph > 0.2:
                sel.append(dict(market=mk, label=f"{team} gagne par 2 buts ou + (handicap -1)",
                                odds=est(ph), src="estimee", p=ph))
        for s in sel:
            s["p"] = round(float(s["p"]), 4)
            s["ev"] = round(s["p"] * s["odds"] - 1, 4)
        matches.append(dict(id=eid, league=lname, div=div, kickoff=e["commence_time"], day=paris_day(e["commence_time"]),
                            home=H, away=A, fd_home=h, fd_away=a, lambdas=[round(x, 3) for x in lmk],
                            model=bool(lm), sel=sel))
    matches.sort(key=lambda m: m["kickoff"])
    return matches


def stars(p, cost):
    # seuils cales sur les marges reelles d'Unibet France (10 a 13 % par selection)
    if p >= 0.35 and cost <= 0.12:
        return 3
    if p >= 0.28 and cost <= 0.18:
        return 2
    return 1


def stake(p):
    return 1 if p < 0.25 else 2 if p < 0.35 else 3 if p < 0.45 else 4 if p < 0.55 else 5


def make_combo(day, kind, legs_list):
    p = float(np.prod([l["p"] for l in legs_list]))
    odds = float(np.prod([l["odds"] for l in legs_list]))
    ev = float(np.prod([1 + l["ev"] for l in legs_list]) - 1)
    cid = day + "|" + "|".join(sorted(f"{l['match_id']}:{l['market']}" for l in legs_list))
    return dict(id=cid, day=day, kind=kind, legs=legs_list, odds=round(odds, 2), p=round(p, 4),
                cost=round(-ev, 4), stars=stars(p, -ev), stake=stake(p), status="en attente")


def combos_for_day(day, matches):
    legs = []
    for m in matches:
        if m["day"] != day:
            continue
        for s in m["sel"]:
            legs.append(dict(match_id=m["id"], league=m["league"], kickoff=m["kickoff"], home=m["home"], away=m["away"],
                             fd_home=m["fd_home"], fd_away=m["fd_away"], div=m["div"], **s))
    rules = [("x2", 2, 1.30, 1.90, (1.6, 3.6)), ("x2", 2, 1.30, 1.90, (1.6, 3.6)), ("x3", 3, 1.20, 1.60, (1.9, 4.2))]
    chosen, used = [], set()
    for kind, n, lo, hi, rng in rules:
        pool = [l for l in legs if lo <= l["odds"] <= hi and l["p"] >= 0.5 and (l["match_id"], l["market"]) not in used]
        pool.sort(key=lambda l: -(l["ev"] + 0.3 * (l["p"] - 0.5) - (0.03 if l["src"] == "estimee" else 0)))
        pool = pool[:12]
        best = None
        for c in combinations(pool, n):
            if len({l["match_id"] for l in c}) < n or sum(l["src"] == "estimee" for l in c) > 1:
                continue
            cb = make_combo(day, kind, list(c))
            if not (rng[0] <= cb["odds"] <= rng[1]):
                continue
            score = -cb["cost"] + 0.3 * cb["p"]
            if best is None or score > best[0]:
                best = (score, cb)
        if best:
            chosen.append(best[1])
            used |= {(l["match_id"], l["market"]) for l in best[1]["legs"]}
    folie = folie_for_day(day, legs)
    if folie:
        chosen.append(folie)
    return chosen


def folie_for_day(day, legs):
    """Pari 'folie' : grosse cote (15 a 40) pour le fun, en choisissant les selections les moins taxees."""
    pool = [l for l in legs if 1.45 <= l["odds"] <= 4.5 and l["src"] != "estimee" and l["p"] >= 0.25]
    pool.sort(key=lambda l: -l["ev"])
    pool = pool[:14]
    best = None
    for n in (4, 5):
        for c in combinations(pool, n):
            if len({l["match_id"] for l in c}) < n:
                continue
            cb = make_combo(day, "folie", list(c))
            if not (15 <= cb["odds"] <= 40):
                continue
            score = -cb["cost"] + 0.5 * cb["p"]
            if best is None or score > best[0]:
                best = (score, cb)
    if not best:
        return None
    cb = best[1]
    cb["stake"] = 1
    cb["stars"] = 0
    return cb


# ---------------------------------------------------------------- resultats ESPN (gratuit, des la fin du match)
ESPN_LEAGUE = {"F1": "fra.1", "E0": "eng.1", "SP1": "esp.1", "I1": "ita.1", "D1": "ger.1", "CL": "uefa.champions"}


def _norm_team(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[-'.]", " ", s)
    s = re.sub(r"\b(fc|ac|as|afc|sc|rc|cf|ca|bc|tsg|vfb|vfl|fsv|ogc|ssc|us|ud|rcd|1|04|05|07|29)\b", " ", s)
    return [w for w in s.split() if len(w) > 1]


def _team_score(a, b):
    x, y = _norm_team(a), _norm_team(b)
    return sum(1 for w in x if any(v == w or (len(w) >= 4 and len(v) >= 4 and (v.startswith(w[:4]) or w.startswith(v[:4]))) for v in y))


def espn_scores(history):
    """Scores finaux ESPN pour les selections terminees encore sans resultat : {(match_id): (buts dom, buts ext)}."""
    pending = []
    for c in history["combos"]:
        if c["status"] != "en attente":
            continue
        for l in c["legs"]:
            k = datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00"))
            if "won" not in l and NOW - timedelta(days=4) < k < NOW - timedelta(minutes=100):
                pending.append(l)
    boards, out = {}, {}
    for l in pending:
        lg = ESPN_LEAGUE.get(l.get("div"))
        if not lg:
            continue
        d = l["kickoff"][:10].replace("-", "")
        if (lg, d) not in boards:
            try:
                body, _h = http_get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={d}")
                boards[(lg, d)] = json.loads(body).get("events", [])
            except Exception as e:
                print("espn", lg, d, e, file=sys.stderr)
                boards[(lg, d)] = []
        k = datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00"))
        best, best_s = None, 0
        for e in boards[(lg, d)]:
            try:
                ek = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                comp = e["competitions"][0]["competitors"]
                H = next(t for t in comp if t["homeAway"] == "home")
                A = next(t for t in comp if t["homeAway"] == "away")
            except Exception:
                continue
            if abs((ek - k).total_seconds()) > 1200:
                continue
            sc = _team_score(l["home"], H["team"]["displayName"]) + _team_score(l["away"], A["team"]["displayName"])
            if sc > best_s:
                best, best_s = (e, H, A), sc
        if best and best[0].get("status", {}).get("type", {}).get("state") == "post":
            out[l["match_id"]] = (int(best[1]["score"]), int(best[2]["score"]))
    return out


# ---------------------------------------------------------------- notifications (ntfy.sh, gratuit)
def notify(title, message, tags="soccer", priority=3):
    if not NTFY_TOPIC or os.environ.get("NO_NOTIFY") == "1":
        print("[notif]", title, "|", message)
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"), method="POST",
                                     headers={"Title": _hdr(title),
                                              "Tags": tags, "Priority": str(priority), "Click": "https://ritemo.github.io/paris-foot/"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print("ntfy", e, file=sys.stderr)


def _hdr(s):
    # en-tete HTTP : encodage RFC 2047 pour les accents
    import base64
    return "=?UTF-8?B?" + base64.b64encode(s.encode("utf-8")).decode() + "?="


def fr(x):
    return f"{x:.2f}".replace(".", ",")


def short(c):
    return " + ".join(f"{l['label']} ({l['home']}-{l['away']})" for l in c["legs"])


def sync_played(meta):
    """Tickets que tu as joues : l'appli les publie sur un canal ntfy prive, le robot les relit a chaque passage."""
    played = meta.get("played", {})
    before = json.dumps(played, sort_keys=True)
    try:
        body, _h = http_get(f"https://ntfy.sh/{NTFY_TOPIC}-joues/json?poll=1&since=all")
        evs = [json.loads(x) for x in body.decode("utf-8").splitlines() if x.strip()]
        for ev in sorted((e for e in evs if e.get("event") == "message"), key=lambda e: e.get("time", 0)):
            try:
                d = json.loads(ev["message"])
            except Exception:
                continue
            if d.get("action") == "add" and d.get("id"):
                old = played.get(d["id"], {})
                played[d["id"]] = {"mise": d.get("mise"), "odds": d.get("odds"), "t": ev.get("time"),
                                   "snap": old.get("snap") or d.get("snap")}
            elif d.get("action") == "remove":
                played.pop(d.get("id"), None)
    except Exception as e:
        print("ntfy joues", e, file=sys.stderr)
    limit = (NOW - timedelta(days=10)).timestamp()
    played = {k: v for k, v in played.items() if (v.get("t") or 0) > limit}
    meta["played"] = played
    return json.dumps(played, sort_keys=True) != before


def settle_perso(meta):
    """Combines composes par toi : le robot les regle aussi, pour te prevenir."""
    played = meta.get("played", {})
    persos = [v["snap"] for v in played.values() if v.get("snap") and v["snap"].get("status") == "en attente"]
    if not persos:
        return False
    h = {"combos": persos}
    before = {c["id"]: c["status"] for c in persos}
    settle(h, None, {}, espn_scores(h))
    notify_settled(before, h, played)
    return any(c["status"] != before[c["id"]] or any("won" in l for l in c["legs"]) for c in persos)


def notify_settled(before, history, played):
    """Un message par ticket JOUE qui vient d'etre regle (les autres restent silencieux)."""
    for c in history["combos"]:
        if c["id"] not in played or before.get(c["id"]) != "en attente" or c["status"] == "en attente":
            continue
        b = played[c["id"]]
        mise, odds = b.get("mise") or 0, b.get("odds") or c["odds"]
        kind = "Folie" if c["kind"] == "folie" else "Ton combiné" if c["kind"] == "perso" else f"Combiné de {len(c['legs'])}"
        if c["status"] == "gagne":
            notify(f"Ticket gagné : {fr(mise * odds)} € pour {fr(mise)} €", f"{kind} à {fr(odds)} : {short(c)}", "white_check_mark,tada", 4)
        else:
            lost = [l for l in c["legs"] if l.get("won") is False]
            why = ", ".join(f"{l['label']} ({l['home']} {l.get('score', '')} {l['away']})" for l in lost)
            notify(f"Ticket perdu, cote {fr(odds)}", f"{kind} : raté sur {why}", "x", 2)


def notify_new_day(day, combos):
    todays = [c for c in combos if c["day"] == day and not c.get("replaced")]
    if not todays:
        return
    best = max((c for c in todays if c["kind"] != "folie"), key=lambda c: c["p"], default=None)
    lines = [f"{len(todays)} tickets pour aujourd'hui."]
    if best:
        lines.append(f"Le plus sûr : cote {fr(best['odds'])}, {round(best['p'] * 100)} % de chance.")
    folie = next((c for c in todays if c["kind"] == "folie"), None)
    if folie:
        lines.append(f"Folie du jour : cote {fr(folie['odds'])}.")
    notify("Les tickets du jour sont prêts", " ".join(lines), "ticket", 3)


# ---------------------------------------------------------------- reglement juste / faux
def leg_result(l, hg, ag):
    m = l["market"]
    if m == "1":
        return hg > ag
    if m == "N":
        return hg == ag
    if m == "2":
        return hg < ag
    if m[0] in "+-" and m[1:].replace(".", "").isdigit():
        ln = float(m[1:])
        return hg + ag > ln if m[0] == "+" else hg + ag < ln
    if m == "H1":
        return hg - ag >= 2
    if m == "H2":
        return ag - hg >= 2
    return None


def find_score_fd(fd, l):
    if fd is None or not l.get("fd_home"):
        return None
    d = pd.Timestamp(paris_day(l["kickoff"]))
    r = fd[(fd.HomeTeam == l["fd_home"]) & (fd.AwayTeam == l["fd_away"]) & ((fd.Date - d).abs() <= pd.Timedelta(days=1))]
    if len(r):
        return int(r.iloc[0].FTHG), int(r.iloc[0].FTAG)
    return None


def settle(history, fd, api_scores, espn=None):
    espn = espn or {}
    for c in history["combos"]:
        if c["status"] not in ("en attente",):
            continue
        for l in c["legs"]:
            if "won" in l:
                continue
            sc = espn.get(l["match_id"])  # ESPN : uniquement des matchs termines
            if not sc and l["kickoff"] <= (NOW - timedelta(hours=2, minutes=15)).isoformat():
                sc = api_scores.get(l["match_id"]) or find_score_fd(fd, l)
            if sc:
                l["score"] = f"{sc[0]}-{sc[1]}"
                l["won"] = bool(leg_result(l, *sc))
        if any(l.get("won") is False for l in c["legs"]):
            c["status"] = "perdu"
        elif all(l.get("won") for l in c["legs"]):
            c["status"] = "gagne"
        if c["status"] != "en attente":
            c["settled_at"] = NOW.isoformat()


def fetch_api_scores(history, fd, espn=None):
    """Resultats via l'API (2 credits / championnat) seulement pour les matchs absents de football-data."""
    if NOW.astimezone(PARIS).hour >= 12 or (credits["remaining"] or 0) < CREDIT_FLOOR_SCORES:
        return {}
    need = set()
    for c in history["combos"]:
        if c["status"] != "en attente":
            continue
        for l in c["legs"]:
            ended = l["kickoff"] <= (NOW - timedelta(hours=2, minutes=15)).isoformat()
            recent = l["kickoff"] >= (NOW - timedelta(days=3)).isoformat()
            if "won" not in l and ended and recent and l["match_id"] not in (espn or {}) and find_score_fd(fd, l) is None:
                need.add(next(k for k, v in LEAGUES.items() if v[0] == l["div"]))
    out = {}
    for sport in need:
        try:
            for e in odds_api(f"/sports/{sport}/scores", daysFrom=3):
                if e.get("completed") and e.get("scores"):
                    s = {x["name"]: int(x["score"]) for x in e["scores"]}
                    out[e["id"]] = (s[e["home_team"]], s[e["away_team"]])
        except Exception as ex:
            print("scores", sport, ex, file=sys.stderr)
    return out


def bilan(history):
    allc = [c for c in history["combos"] if c["status"] in ("gagne", "perdu") and not c.get("replaced")]
    done = [c for c in allc if c["kind"] != "folie"]  # les folies ont leur propre ligne
    out = dict(n=len(done), gagnes=sum(c["status"] == "gagne" for c in done))
    if allc:
        for k in ("x2", "x3", "folie"):
            sub = [c for c in allc if c["kind"] == k]
            if sub:
                out[k] = dict(n=len(sub), gagnes=sum(c["status"] == "gagne" for c in sub),
                              reussite_annoncee=round(float(np.mean([c["p"] for c in sub])), 3),
                              bilan=round(sum((c["odds"] - 1) * c["stake"] if c["status"] == "gagne" else -c["stake"] for c in sub), 2))
    if done:
        out["reussite_reelle"] = round(out["gagnes"] / len(done), 3)
        out["reussite_annoncee"] = round(float(np.mean([c["p"] for c in done])), 3)
        g2 = sum((c["odds"] - 1) * 2 if c["status"] == "gagne" else -2 for c in done)
        gs = sum((c["odds"] - 1) * c["stake"] if c["status"] == "gagne" else -c["stake"] for c in done)
        out["bilan_2eur"] = round(g2, 2)
        out["mise_2eur"] = 2 * len(done)
        out["bilan_mise_suggeree"] = round(gs, 2)
        out["mise_suggeree_totale"] = sum(c["stake"] for c in done)
    return out


# ---------------------------------------------------------------- programme principal
ODDS_SLOTS = ((7, 30), (16, 30))  # heures de Paris ou les cotes sont actualisees (credits)


def odds_due(meta):
    if os.environ.get("FORCE") == "1":
        return True
    last = meta.get("last_odds_run")
    now_p = NOW.astimezone(PARIS)
    for h, m in ODDS_SLOTS:
        slot = now_p.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= now_p and (not last or datetime.fromisoformat(last) < slot):
            return True
    return False


def results_only(meta, history):
    """Passage gratuit : resultats ESPN seulement, on n'ecrit que si quelque chose a change."""
    before = json.dumps(history, sort_keys=True, default=str)
    meta_changed = sync_played(meta)
    meta_changed |= settle_perso(meta)
    status_before = {c["id"]: c["status"] for c in history["combos"]}
    settle(history, None, {}, espn_scores(history))
    notify_settled(status_before, history, meta.get("played", {}))
    if json.dumps(history, sort_keys=True, default=str) == before:
        if meta_changed:
            save("meta.json", meta)
        print("rien de nouveau")
        return
    history["bilan"] = bilan(history)
    history["updated"] = NOW.isoformat()
    by_id = {c["id"]: c for c in history["combos"]}
    today_data = load("today.json", {})
    today_data["combos"] = [by_id.get(c["id"], c) for c in today_data.get("combos", [])]
    save("history.json", history)
    save("today.json", today_data)
    meta["last_results_run"] = NOW.isoformat()
    save("meta.json", meta)
    print("resultats mis a jour")


def main():
    meta = load("meta.json", {})
    history = load("history.json", {"combos": []})
    if not odds_due(meta):
        return results_only(meta, history)
    if not KEY:
        sys.exit("ODDS_API_KEY manquante")
    cache = load("odds_cache.json", {})
    credits["remaining"] = meta.get("credits_remaining")

    fd = load_history_fd()
    models = {}
    for div in FD_DIVS:
        g = fd[(fd.Div == div) & (fd.Date < pd.Timestamp(NOW.date()))]
        if len(g) > 50:
            models[div] = fit_league(g)

    # 1. quels championnats jouent d'ici la fin de demain ? (appel gratuit)
    today = NOW.astimezone(PARIS).date()
    horizon = datetime.combine(today + timedelta(days=2), datetime.min.time(), PARIS).astimezone(timezone.utc)
    needed = []
    for sport in LEAGUES:
        try:
            ev = odds_api(f"/sports/{sport}/events")
        except Exception as e:
            print("events", sport, e, file=sys.stderr)
            continue
        if any(NOW.isoformat() < x["commence_time"] < horizon.isoformat() for x in ev):
            needed.append(sport)

    # 2. cotes (payant, seulement si necessaire)
    events = fetch_odds(needed, cache)
    cache = {k: v for k, v in events.items() if v["commence_time"] > (NOW - timedelta(days=1)).isoformat()}
    matches = build_matches(events, models)

    # 3. combines : provisoires jusqu'au premier passage du jour J, ensuite figes
    days = sorted({m["day"] for m in matches if m["day"] <= (today + timedelta(days=1)).isoformat()})
    frozen = set(meta.get("frozen_days", []))
    for day in days:
        if day in frozen:
            # journee deja figee : on ajoute seulement une folie si elle manque (matchs a venir uniquement)
            if not any(c["day"] == day and c["kind"] == "folie" for c in history["combos"]):
                legs = [dict(match_id=m["id"], league=m["league"], kickoff=m["kickoff"], home=m["home"], away=m["away"],
                             fd_home=m["fd_home"], fd_away=m["fd_away"], div=m["div"], **s)
                        for m in matches if m["day"] == day for s in m["sel"]]
                f = folie_for_day(day, legs)
                if f:
                    f["proposed_at"] = NOW.isoformat()
                    history["combos"].append(f)
            continue
        new = combos_for_day(day, matches)
        new_ids = {c["id"] for c in new}
        old = [c for c in history["combos"] if c["day"] == day and c.get("status") == "en attente" and not c.get("replaced")]
        for c in old:  # un ticket deja propose n'est jamais efface : il reste suivi (tu l'as peut-etre joue)
            if c["id"] in new_ids:
                new = [n for n in new if n["id"] != c["id"]]  # identique : on garde l'ancien tel quel
            else:
                c["replaced"] = True
        for c in new:
            c["proposed_at"] = NOW.isoformat()
        history["combos"] += new
        if day == today.isoformat():
            frozen.add(day)
            notify_new_day(day, history["combos"])

    # 4. resultats et bilan
    espn = espn_scores(history)
    api_scores = fetch_api_scores(history, fd, espn)
    sync_played(meta)
    settle_perso(meta)
    status_before = {c["id"]: c["status"] for c in history["combos"]}
    settle(history, fd, api_scores, espn)
    notify_settled(status_before, history, meta.get("played", {}))
    history["combos"].sort(key=lambda c: (c["day"], c["kind"]), reverse=True)
    history["bilan"] = bilan(history)
    history["updated"] = NOW.isoformat()

    current = [c for c in history["combos"] if c["day"] >= today.isoformat() and not c.get("replaced")]
    meta.update(credits_remaining=credits["remaining"], credits_used_last_run=credits["used_run"],
                last_run=NOW.isoformat(), last_odds_run=NOW.isoformat(), frozen_days=sorted(d for d in frozen if d >= (today - timedelta(days=7)).isoformat()),
                leagues=[v[1] for v in LEAGUES.values()])
    save("today.json", dict(generated_at=NOW.isoformat(), credits_remaining=credits["remaining"],
                            combos=sorted(current, key=lambda c: (c["day"], c["kind"] == "folie", c["kind"])),
                            matches=[m for m in matches if m["day"] <= (today + timedelta(days=2)).isoformat()]))
    save("history.json", history)
    save("odds_cache.json", cache)
    save("meta.json", meta)
    print(f"{len(matches)} matchs, {len(current)} combines, credits restants {credits['remaining']} "
          f"(utilises : {credits['used_run']})")


if __name__ == "__main__":
    main()
