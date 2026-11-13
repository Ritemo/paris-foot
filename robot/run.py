"""Robot paris-foot : modele + cotes Unibet -> combines du jour, historique et bilan.

Lance par GitHub Actions (8h, 17h, ou a la demande). Ecrit dans docs/data/.
Variable d'environnement requise : ODDS_API_KEY.
"""
import io
import json
import math
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import learn
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
    "soccer_uefa_europa_league": ("EL", "Ligue Europa"),
}
FD_DIVS = ("F1", "E0", "SP1", "I1", "D1")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "combines-foot-ritemo-7k3q9x")
XI, MIX, W_MODEL = 0.0019, 0.5, 0.2      # reglages valides par le backtest
CREDIT_FLOOR_TOTALS = 40                   # en dessous : 1N2 seulement (1 credit / championnat)
CREDIT_FLOOR_ODDS = 12                     # en dessous : plus d'appel payant, on garde le cache
CREDIT_FLOOR_SCORES = 100                  # resultats via l'API seulement si assez de credits
NOW = datetime.now(timezone.utc)
credits = {"remaining": None, "used_run": 0}
PARAMS = {"w_model": W_MODEL, "offsets": {}}   # remplace a chaque passage par ce que le robot a appris (learn.py)


# ---------------------------------------------------------------- utilitaires
def load(name, default):
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(name, obj, compact=False):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), default=str)
        else:
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


def season_codes(d, n=2):
    y = d.year % 100 if d.month >= 7 else d.year % 100 - 1
    return [f"{y - k:02d}{y - k + 1:02d}" for k in range(n - 1, -1, -1)]


def paris_day(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()


# ---------------------------------------------------------------- historique et modele
def load_history_fd(n_seasons=2):
    frames = []
    for div in FD_DIVS:
        for s in season_codes(NOW, n_seasons):
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


def fit_league(g, ref=None):
    k = (g.FTHG.sum() + g.FTAG.sum()) / max(g.HST.sum() + g.AST.sum(), 1)
    teams = sorted(set(g.HomeTeam) | set(g.AwayTeam))
    idx = {t: i for i, t in enumerate(teams)}
    w = np.exp(-XI * ((ref if ref is not None else pd.Timestamp(NOW.date())) - g.Date).dt.days.values)
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
                pO=mat[tot > line].sum(), h1=mat[diff >= 2].sum(), h2=mat[diff <= -2].sum(),
                btts=mat[1:, 1:].sum(), over={ln: mat[tot > ln].sum() for ln in (1.5, 2.5, 3.5)})


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
            data = odds_api(f"/sports/{sport}/odds", regions="fr", markets=markets, oddsFormat="decimal", includeLinks="true")
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
    if books.get("unibet_fr", {}).get("link"):   # page du match sur unibet.fr (fournie par The Odds API)
        out["link"] = books["unibet_fr"]["link"]
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


# ---------------------------------------------------------------- NBA et tennis
# Chances : cotes peu margees (DraftKings via ESPN pour la NBA, moyenne des bookmakers FR pour le tennis), marge retiree.
# Cote Unibet : la vraie quand The Odds API la donne (vainqueur), sinon estimee avec la marge habituelle d'unibet.fr,
# repartie comme le fait le bookmaker (davantage sur l'outsider : methode « puissance »).
FR_OVERROUND = {"basket": 1.139, "tennis": 1.144}   # mesure du 12/11/2026 : 12,2 % et 12,6 % de marge Unibet
OTHER_MAX_TOURNAMENTS = 2                           # tennis : 1 credit par tournoi et par releve


def am2dec(a):
    v = float(str(a).replace("+", ""))
    return 1 + v / 100 if v > 0 else 1 + 100 / abs(v)


def fair(odds_list):
    inv = [1 / o for o in odds_list]
    t = sum(inv)
    return [x / t for x in inv]


def fr_estimate(ps, overround):
    """Cotes estimees : p_i^a dont la somme vaut la marge totale d'Unibet (a < 1 charge davantage l'outsider)."""
    lo, hi = 0.3, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if sum(p ** mid for p in ps) > overround:
            lo = mid
        else:
            hi = mid
    a = (lo + hi) / 2
    return [float(round(1 / p ** a, 2)) for p in ps]


def _sel(market, label, odds, src, p):
    return dict(market=market, label=label, odds=float(odds), src=src, p=round(float(p), 4), ev=round(float(p) * float(odds) - 1, 4))


def _lt(x):
    return f"{x:g}".replace(".", ",")


def nba_matches(horizon, unibet):
    """Matchs NBA a venir avec cotes DraftKings (ESPN, gratuit). unibet : {(dom, ext): (cote dom, cote ext)}."""
    out, seen = [], set()
    for d in sorted({(NOW + timedelta(days=i)).strftime("%Y%m%d") for i in (0, 1)}):
        try:
            body, _h = http_get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}")
            evs = json.loads(body).get("events", [])
        except Exception as e:
            print("espn nba", d, e, file=sys.stderr)
            continue
        for e in evs:
            try:
                comp = e["competitions"][0]
                k = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                if e["id"] in seen or not (NOW < k < horizon) or comp["status"]["type"]["state"] != "pre":
                    continue
                H = next(t for t in comp["competitors"] if t["homeAway"] == "home")["team"]
                A = next(t for t in comp["competitors"] if t["homeAway"] == "away")["team"]
                o = (comp.get("odds") or [{}])[0]
                ml = o.get("moneyline", {})
                pf = fair([am2dec(ml["home"]["close"]["odds"]), am2dec(ml["away"]["close"]["odds"])])
            except Exception:
                continue
            seen.add(e["id"])
            h, a = H["displayName"], A["displayName"]
            hs, as_ = H.get("shortDisplayName") or h, A.get("shortDisplayName") or a
            ub = unibet.get((h, a))
            est = fr_estimate(pf, FR_OVERROUND["basket"])
            sel = [_sel("1", f"Victoire {h}", ub[0] if ub else est[0], "unibet" if ub else "estimee", pf[0]),
                   _sel("2", f"Victoire {a}", ub[1] if ub else est[1], "unibet" if ub else "estimee", pf[1])]
            try:  # handicap principal
                sp = o["pointSpread"]
                lh, la = float(sp["home"]["close"]["line"]), float(sp["away"]["close"]["line"])
                ps = fair([am2dec(sp["home"]["close"]["odds"]), am2dec(sp["away"]["close"]["odds"])])
                es = fr_estimate(ps, FR_OVERROUND["basket"])
                sel += [_sel(f"HC1:{lh:+g}", f"{hs} handicap {lh:+g}".replace(".", ","), es[0], "estimee", ps[0]),
                        _sel(f"HC2:{la:+g}", f"{as_} handicap {la:+g}".replace(".", ","), es[1], "estimee", ps[1])]
            except Exception:
                pass
            try:  # total de points principal
                tt = o["total"]
                ln = float(str(tt["over"]["close"]["line"]).lstrip("ou"))
                pt = fair([am2dec(tt["over"]["close"]["odds"]), am2dec(tt["under"]["close"]["odds"])])
                et = fr_estimate(pt, FR_OVERROUND["basket"])
                sel += [_sel(f"+{ln:g}", f"Plus de {_lt(ln)} points", et[0], "estimee", pt[0]),
                        _sel(f"-{ln:g}", f"Moins de {_lt(ln)} points", et[1], "estimee", pt[1])]
            except Exception:
                pass
            sel = [x for x in sel if 0.03 < x["p"] < 0.97 and x["odds"] >= 1.04]
            out.append(dict(id=f"nba-{e['id']}", sport="basket", league="NBA", div="NBA", kickoff=k.isoformat().replace("+00:00", "Z"),
                            day=paris_day(k.isoformat()), home=h, away=a, fd_home=None, fd_away=None, sel=sel, link=ub[2] if ub and len(ub) > 2 else None))
    return out


def nba_unibet():
    """Vraie cote Unibet du vainqueur NBA (1 credit)."""
    out = {}
    try:
        for e in odds_api("/sports/basketball_nba/odds", regions="fr", markets="h2h", oddsFormat="decimal", bookmakers="unibet_fr", includeLinks="true"):
            for b in e.get("bookmakers", []):
                o = {x["name"]: x["price"] for x in b["markets"][0]["outcomes"]}
                if e["home_team"] in o and e["away_team"] in o:
                    out[(e["home_team"], e["away_team"])] = (o[e["home_team"]], o[e["away_team"]], b.get("link"))
    except Exception as ex:
        print("nba unibet", ex, file=sys.stderr)
    return out


def tennis_matches(horizon):
    """Tournois ATP / WTA en cours : vainqueur du match (1 credit par tournoi)."""
    try:
        sports = odds_api("/sports")
    except Exception as e:
        print("sports", e, file=sys.stderr)
        return []
    keys = [x for x in sports if x["key"].startswith(("tennis_atp", "tennis_wta")) and x.get("active") and not x.get("has_outrights")
            and "doubles" not in x["key"]]
    picked = []
    for x in keys:
        try:
            ev = odds_api(f"/sports/{x['key']}/events")   # gratuit
        except Exception:
            continue
        n = sum(NOW.isoformat() < y["commence_time"] < horizon.isoformat() for y in ev)
        if n:
            picked.append((n, x))
    out = []
    for _n, x in sorted(picked, key=lambda t: -t[0])[:OTHER_MAX_TOURNAMENTS]:
        if (credits["remaining"] or 0) < CREDIT_FLOOR_TOTALS:
            break
        try:
            data = odds_api(f"/sports/{x['key']}/odds", regions="fr", markets="h2h", oddsFormat="decimal", includeLinks="true")
        except Exception as e:
            print("tennis", x["key"], e, file=sys.stderr)
            continue
        tour = "ATP" if x["key"].startswith("tennis_atp") else "WTA"
        for e in data:
            if not (NOW.isoformat() < e["commence_time"] < horizon.isoformat()):
                continue
            h, a = e["home_team"], e["away_team"]
            prs, ub, link = [], None, None
            for b in e.get("bookmakers", []):
                o = {y["name"]: y["price"] for y in b["markets"][0]["outcomes"]}
                if h in o and a in o:
                    prs.append(fair([o[h], o[a]]))
                    if b["key"] == "unibet_fr":
                        ub, link = (o[h], o[a]), b.get("link")
            if not prs:
                continue
            pf = [sum(q[0] for q in prs) / len(prs), sum(q[1] for q in prs) / len(prs)]
            est = fr_estimate(pf, FR_OVERROUND["tennis"])
            sel = [_sel("1", f"Victoire {h}", ub[0] if ub else est[0], "unibet" if ub else "estimee", pf[0]),
                   _sel("2", f"Victoire {a}", ub[1] if ub else est[1], "unibet" if ub else "estimee", pf[1])]
            sel = [s_ for s_ in sel if 0.03 < s_["p"] < 0.97 and s_["odds"] >= 1.04]
            out.append(dict(id=e["id"], sport="tennis", league=tour, event=x["title"], div=tour, kickoff=e["commence_time"],
                            day=paris_day(e["commence_time"]), home=h, away=a, fd_home=None, fd_away=None, sel=sel, link=link))
    return out


def other_sports(prev_matches, horizon, paid):
    """NBA et tennis. paid=False : on reprend les matchs du releve precedent (aucun credit)."""
    if not paid or (credits["remaining"] or 0) < CREDIT_FLOOR_TOTALS:
        return [m for m in prev_matches if m.get("sport") in ("basket", "tennis") and m["kickoff"] > NOW.isoformat()]
    out = []
    try:
        out += nba_matches(horizon, nba_unibet())
    except Exception as e:
        print("nba", e, file=sys.stderr)
    try:
        out += tennis_matches(horizon)
    except Exception as e:
        print("tennis", e, file=sys.stderr)
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
        mk_mat = score_matrix(*lmk)
        md_mat = score_matrix(*lm) if lm else None
        w = PARAMS["w_model"]
        mat = w * md_mat + (1 - w) * mk_mat if lm else mk_mat
        p = learn.adjust_probs(probs(mat, line), PARAMS.get("offsets"))   # corrections apprises sur les matchs passes
        est = lambda pp: float(round(1 / (float(pp) * inv), 2))  # cote estimee avec la marge Unibet du match
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
        # double chance, les deux equipes marquent, autres seuils de buts : cotes estimees (marge Unibet du match)
        sel += [dict(market="1N", label=f"{H} ou nul", odds=est(p["p1"] + p["pN"]), src="estimee", p=p["p1"] + p["pN"]),
                dict(market="N2", label=f"{A} ou nul", odds=est(p["p2"] + p["pN"]), src="estimee", p=p["p2"] + p["pN"]),
                dict(market="12", label="Pas de match nul", odds=est(p["p1"] + p["p2"]), src="estimee", p=p["p1"] + p["p2"]),
                dict(market="BTTS", label="Les deux équipes marquent", odds=est(p["btts"]), src="estimee", p=p["btts"]),
                dict(market="NBTTS", label="Une équipe au moins ne marque pas", odds=est(1 - p["btts"]), src="estimee", p=1 - p["btts"])]
        for ln, po in p["over"].items():
            if abs(ln - line) < 1e-6 and "totals" in o:
                continue  # deja present avec une vraie cote
            lab = f"{ln:g}".replace(".", ",")
            sel += [dict(market=f"+{ln:g}", label=f"Plus de {lab} buts", odds=est(po), src="estimee", p=po),
                    dict(market=f"-{ln:g}", label=f"Moins de {lab} buts", odds=est(1 - po), src="estimee", p=1 - po)]
        sel = [x for x in sel if 0.03 < x["p"] < 0.97 and x["odds"] >= 1.04]
        for mk, team, pw, ph in (("H1", H, p["p1"], p["h1"]), ("H2", A, p["p2"], p["h2"])):
            if pw >= 0.55 and ph > 0.2:
                sel.append(dict(market=mk, label=f"{team} gagne par 2 buts ou + (handicap -1)",
                                odds=est(ph), src="estimee", p=ph))
        for s in sel:
            s["p"] = round(float(s["p"]), 4)
            s["ev"] = round(s["p"] * s["odds"] - 1, 4)
        matches.append(dict(id=eid, league=lname, div=div, kickoff=e["commence_time"], day=paris_day(e["commence_time"]),
                            home=H, away=A, fd_home=h, fd_away=a, lambdas=[round(x, 3) for x in lmk],
                            model=bool(lm), sel=sel, link=o.get("link"),
                            _lp=dict(pm=learn.vec(md_mat) if lm else None, pk=learn.vec(mk_mat),
                                     pr=learn.adjust_vec(learn.vec(mat), PARAMS.get("offsets")).tolist())))
    matches.sort(key=lambda m: m["kickoff"])
    return matches


STYLE = 0.25    # style de jeu : 0 = petit gain sur (cote ~1,7), 1 = gros gain (cote ~4,5) ; reglable dans l'appli
PRICE_W = 0.5   # poids du prix dans la note (le reste va au style de jeu)
STYLE_LO, STYLE_HI = 1.7, 4.5


def interest(p, cost, n=2, wp=PRICE_W, style=STYLE):
    """Interet d'un ticket, de 0 a 1. Meme formule que l'appli.
    - prix : marge du bookmaker ramenee a une selection (4 % = excellent, 13 % = cher) ;
    - style : la cote du ticket est-elle proche de celle que tu vises (petit gain sur ou gros gain) ?
      La cote visee va de 1,7 a 4,5 ; une cote deux fois plus haute ou plus basse que la cible ne marque plus."""
    per_leg = 1 - (1 - max(cost, 0)) ** (1 / max(n, 1))
    price = min(1.0, max(0.0, (0.13 - per_leg) / 0.09))
    odds = (1 - cost) / max(p, 1e-9)
    target = math.exp(math.log(STYLE_LO) + style * math.log(STYLE_HI / STYLE_LO))
    fit = max(0.0, 1 - abs(math.log(odds / target)) / math.log(2))
    return wp * price + (1 - wp) * fit


def stars(p, cost, n=2):
    """3 etoiles = tres interessant (>= 0,62), 2 = interessant (>= 0,45), 1 = peu interessant."""
    s = interest(p, cost, n)
    return 3 if s >= 0.62 else 2 if s >= 0.45 else 1


def stake(p):
    return 1 if p < 0.25 else 2 if p < 0.35 else 3 if p < 0.45 else 4 if p < 0.55 else 5


def make_combo(day, kind, legs_list):
    p = float(np.prod([l["p"] for l in legs_list]))
    odds = float(np.prod([l["odds"] for l in legs_list]))
    ev = float(np.prod([1 + l["ev"] for l in legs_list]) - 1)
    cid = day + "|" + "|".join(sorted(f"{l['match_id']}:{l['market']}" for l in legs_list))
    odds_u = math.floor(odds * 100 + 0.5 + 1e-6) / 100  # cote totale arrondie comme Unibet (2,465 -> 2,47)
    return dict(id=cid, day=day, kind=kind, legs=legs_list, odds=odds_u, p=round(p, 4),
                cost=round(-ev, 4), stars=stars(p, -ev, len(legs_list)), stake=stake(p), status="en attente")


def day_legs(day, matches):
    legs = []
    for m in matches:
        if m["day"] != day:
            continue
        for s in m["sel"]:
            legs.append(dict(match_id=m["id"], league=m["league"], kickoff=m["kickoff"], home=m["home"], away=m["away"],
                             fd_home=m["fd_home"], fd_away=m["fd_away"], div=m["div"], sport=m.get("sport", "foot"), link=m.get("link"), **s))
    return legs


def candidates(day, matches):
    """Tous les combines possibles (2 ou 3 selections) du jour."""
    legs = day_legs(day, matches)
    # cotes de 1,6 a 7 pour couvrir tous les styles de jeu, du petit gain sur au gros gain
    rules = [("x2", 2, 1.25, 2.60, (1.6, 5.5)), ("x3", 3, 1.20, 2.00, (1.9, 7.0))]
    cands = []
    sports = sorted({l["sport"] for l in legs})
    groups = sports + (["mix"] if len(sports) > 1 else [])   # « mix » : tickets melangeant les sports, proposes seulement si tu le demandes
    for (kind, n, lo, hi, rng), sport in [(r, sp) for r in rules for sp in groups]:
        pool = [l for l in legs if (sport == "mix" or l["sport"] == sport) and lo <= l["odds"] <= hi and l["p"] >= 0.36]
        pool.sort(key=lambda l: -(l["ev"] - (0.03 if l["src"] == "estimee" else 0)))   # les selections les moins taxees
        for c in combinations(pool[:18], n):
            # foot : une seule cote estimee par ticket (estimee par notre modele) ; NBA et tennis : estimees depuis des cotes du marche
            if len({l["match_id"] for l in c}) < n or sum(l["src"] == "estimee" and l["sport"] == "foot" for l in c) > 1:
                continue
            if sport == "mix" and len({l["sport"] for l in c}) < 2:
                continue
            cb = make_combo(day, kind, list(c))
            if sport == "mix":
                cb["mix"] = True
            if rng[0] <= cb["odds"] <= rng[1]:
                cands.append(cb)
    return cands, legs


def combos_for_day(day, matches):
    """Les 3 meilleurs combines selon le style de jeu et le poids du prix par defaut, sans selection en commun, plus la folie."""
    cands, legs = candidates(day, matches)
    # a note egale, les tickets aux cotes Unibet passent devant (moins de cotes a verifier a la main), comme dans l'appli
    uni = lambda cb: 0.03 * sum(l["src"] == "unibet" for l in cb["legs"]) / len(cb["legs"])
    cands = sorted([c for c in cands if not c.get("mix")], key=lambda cb: -(interest(cb["p"], cb["cost"], len(cb["legs"])) + uni(cb)))
    chosen, used = [], set()
    for cb in cands:
        keys = {(l["match_id"], l["market"]) for l in cb["legs"]}
        if keys & used:
            continue
        chosen.append(cb)
        used |= keys
        if len(chosen) == 3:
            break
    folie = folie_for_day(day, legs)
    if folie:
        chosen.append(folie)
    return chosen


def alts_for_day(day, matches, exclude):
    """Autres bons candidats, pour que l'appli choisisse les meilleurs selon TON style de jeu et le poids du prix."""
    cands, _legs = candidates(day, matches)
    out = {}
    for group in (False, True):   # tickets d'un seul sport, puis tickets melanges (affiches si tu le demandes)
        pool = [c for c in cands if bool(c.get("mix")) == group]
        for st in (0, 0.25, 0.5, 0.75, 1):
            for wp in (0.3, 0.5, 0.7):
                for cb in sorted(pool, key=lambda cb: -interest(cb["p"], cb["cost"], len(cb["legs"]), wp, st))[:5]:
                    if cb["id"] not in exclude:
                        out[cb["id"]] = dict(cb, alt=True)
    return list(out.values())


def folie_for_day(day, legs):
    """Pari 'folie' : grosse cote (15 a 40) pour le fun, en choisissant les selections les moins taxees."""
    pool = [l for l in legs if 1.45 <= l["odds"] <= 4.5 and l["src"] != "estimee" and l["p"] >= 0.25 and l.get("sport", "foot") == "foot"]
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
ESPN_LEAGUE = {"F1": "fra.1", "E0": "eng.1", "SP1": "esp.1", "I1": "ita.1", "D1": "ger.1", "CL": "uefa.champions", "EL": "uefa.europa"}


def _norm_team(s):
    s = s.translate(str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "đ": "d", "æ": "ae", "ß": "ss", "/": " "}))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[-'.]", " ", s)
    s = re.sub(r"\b(fc|ac|as|afc|sc|rc|cf|ca|bc|tsg|vfb|vfl|fsv|ogc|ssc|us|ud|rcd|1|04|05|07|29)\b", " ", s)
    return [w for w in s.split() if len(w) > 1]


def _team_score(a, b):
    x, y = _norm_team(a), _norm_team(b)
    return sum(1 for w in x if any(v == w or (len(w) >= 4 and len(v) >= 4 and (v.startswith(w[:4]) or w.startswith(v[:4]))) for v in y))


def _team_match(name, team):
    """Ressemblance entre un nom d'equipe (The Odds API) et une equipe ESPN."""
    cands = [team.get(k) for k in ("displayName", "shortDisplayName", "name", "location") if team.get(k)]
    a = " ".join(_norm_team(name))
    return max(_team_score(name, c) + SequenceMatcher(None, a, " ".join(_norm_team(c))).ratio() for c in cands)


# noms que la ressemblance ne suffit pas a relier (The Odds API -> ESPN)
LOGO_ALIAS = {"1. FC Köln": "FC Cologne"}


def update_logos(history, today_data):
    """Logos et couleurs des clubs (ESPN, gratuit) : docs/data/logos.json, {nom: {logo, color}}.
    On ne contacte ESPN que pour les equipes encore inconnues (et une fois par jour au plus pour les introuvables)."""
    logos = load("logos.json", {})
    miss = logos.setdefault("_miss", {})
    day = NOW.date().isoformat()
    want = {}
    for c in history.get("combos", []) + today_data.get("combos", []):
        for l in c["legs"]:
            for t in (l["home"], l["away"]):
                want.setdefault(t, l.get("div"))
    for m in today_data.get("matches", []):
        for t in (m["home"], m["away"]):
            want.setdefault(t, m.get("div"))
    todo = {t: d for t, d in want.items() if t not in logos and miss.get(t) != day}
    if not todo:
        return False
    teams = {}
    for div in sorted({d for d in todo.values() if d in ESPN_LEAGUE or d == "NBA"}):
        try:
            path = "basketball/nba" if div == "NBA" else f"soccer/{ESPN_LEAGUE[div]}"
            body, _h = http_get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams")
            teams[div] = [x["team"] for x in json.loads(body)["sports"][0]["leagues"][0]["teams"]]
        except Exception as e:
            print("logos", div, e, file=sys.stderr)
    for t, div in todo.items():
        pool = teams.get(div, [])
        alias = LOGO_ALIAS.get(t)
        best = next((x for x in pool if alias and x.get("displayName") == alias), None) or max(pool, key=lambda x: _team_match(t, x), default=None)
        if best and (alias == best.get("displayName") or _team_match(t, best) >= 1.5) and best.get("logos"):
            logos[t] = {"logo": best["logos"][0]["href"].replace("/500/", "/500/"), "color": "#" + best.get("color", "1a7a4c"), "espn": best.get("displayName")}
            miss.pop(t, None)
        else:
            miss[t] = day
    save("logos.json", logos)
    return True


ESPN_OTHER = {"NBA": "basketball/nba", "ATP": "tennis/atp", "WTA": "tennis/wta"}


def _board(path, d, boards):
    if (path, d) not in boards:
        try:
            body, _h = http_get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d}")
            boards[(path, d)] = json.loads(body).get("events", [])
        except Exception as e:
            print("espn", path, d, e, file=sys.stderr)
            boards[(path, d)] = []
    return boards[(path, d)]


def _name_of(c):
    return (c.get("athlete") or {}).get("displayName") or (c.get("team") or {}).get("displayName") or c.get("displayName") or ""


def espn_other_score(l, boards):
    """Score final NBA (points) ou tennis (sets gagnes) d'une selection, ou None si pas encore termine."""
    path = ESPN_OTHER[l["div"]]
    k = datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00"))
    days = sorted({(k + timedelta(days=i)).strftime("%Y%m%d") for i in (-1, 0, 1)})
    comps = []
    for d in days:
        for e in _board(path, d, boards):
            if path.startswith("tennis"):
                for g in e.get("groupings", []):
                    if "Singles" in (g.get("grouping") or {}).get("displayName", ""):
                        comps += g.get("competitions", [])
            else:
                comps += e.get("competitions", [])[:1]
    best, best_s = None, 0
    for c in comps:
        try:
            ck = datetime.fromisoformat(c["date"].replace("Z", "+00:00"))
        except Exception:
            continue
        if abs((ck - k).total_seconds()) > (36 * 3600 if path.startswith("tennis") else 3 * 3600):
            continue
        cs = c.get("competitors", [])
        if len(cs) != 2:
            continue
        # chaque joueur ou equipe de la selection avec son adversaire ESPN, dans un sens ou dans l'autre
        n0, n1 = _name_of(cs[0]), _name_of(cs[1])
        direct = _team_score(l["home"], n0) + _team_score(l["away"], n1)
        swap = _team_score(l["home"], n1) + _team_score(l["away"], n0)
        sc = max(direct, swap)
        if sc > best_s and min(_team_score(l["home"], n1 if swap > direct else n0), _team_score(l["away"], n0 if swap > direct else n1)) > 0:
            best, best_s = (c, (cs[1], cs[0]) if swap > direct else (cs[0], cs[1])), sc
    if not best:
        return None
    c, (H, A) = best
    if not (c.get("status", {}).get("type", {}).get("completed") or c.get("status", {}).get("type", {}).get("state") == "post"):
        return None
    if path.startswith("tennis"):
        h = sum(1 for x in H.get("linescores", []) if x.get("winner"))
        a = sum(1 for x in A.get("linescores", []) if x.get("winner"))
        if H.get("winner") and h <= a:   # abandon : le vainqueur designe compte
            h = a + 1
        if A.get("winner") and a <= h:
            a = h + 1
        return h, a
    return int(float(H["score"])), int(float(A["score"]))


def espn_scores(history):
    """Scores finaux ESPN pour les selections terminees encore sans resultat : {(match_id): (buts dom, buts ext)}."""
    pending = []
    for c in history["combos"]:
        if all("won" in l for l in c["legs"]):  # un ticket perdu garde ses autres matchs a regler, pour l'affichage
            continue
        for l in c["legs"]:
            k = datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00"))
            if "won" not in l and NOW - timedelta(days=4) < k < NOW - timedelta(minutes=100):
                pending.append(l)
    boards, out = {}, {}
    for l in pending:
        if l.get("div") in ESPN_OTHER:
            try:
                sc = espn_other_score(l, boards)
            except Exception as e:
                print("espn", l.get("div"), e, file=sys.stderr)
                sc = None
            if sc:
                out[l["match_id"]] = sc
            continue
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


BACKUP_KEEP = 6


def sync_backup():
    """Sauvegardes de l'appli : chiffrees sur le telephone (le robot ne peut pas les lire), envoyees en morceaux
    sur ntfy (qui ne garde les messages que 12 h). Le robot les reassemble et les range dans docs/data/backup.json."""
    store = load("backup.json", {"saves": []})
    known = {x["id"] for x in store["saves"]}
    try:
        body, _h = http_get(f"https://ntfy.sh/{NTFY_TOPIC}-sauvegarde/json?poll=1&since=all")
    except Exception as e:
        print("ntfy sauvegarde", e, file=sys.stderr)
        return False
    groups = {}
    for line in body.decode("utf-8").splitlines():
        try:
            ev = json.loads(line)
            if ev.get("event") != "message":
                continue
            d = json.loads(ev["message"])
            bid, i, n, part = str(d["b"])[:16], int(d["i"]), int(d["n"]), str(d["d"])
        except Exception:
            continue
        if not (0 <= i < n <= 200) or not re.fullmatch(r"[A-Za-z0-9+/=.]*", part):
            continue
        g = groups.setdefault(bid, {"n": n, "parts": {}, "t": 0})
        g["parts"][i] = part
        g["t"] = max(g["t"], ev.get("time", 0))
    added = False
    for bid, g in groups.items():
        if bid in known or len(g["parts"]) != g["n"]:
            continue
        blob = "".join(g["parts"][i] for i in range(g["n"]))
        if not blob.startswith("1.") or len(blob) > 600_000:
            continue
        store["saves"].append({"id": bid, "t": g["t"], "blob": blob})
        added = True
    if not added:
        return False
    store["saves"] = sorted(store["saves"], key=lambda x: x["t"])[-BACKUP_KEEP:]
    save("backup.json", store)
    return True


def settle_perso(meta):
    """Combines composes par toi : le robot les regle aussi, pour te prevenir."""
    played = meta.get("played", {})
    persos = [v["snap"] for v in played.values() if v.get("snap") and not all("won" in l for l in v["snap"]["legs"])]
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


KICK_BEFORE, KICK_AFTER = timedelta(minutes=12), timedelta(minutes=30)


def notify_kickoffs(meta, history):
    """Une notification quand un match de tes tickets joues va commencer (le robot passe toutes les 15 min).
    Un match present dans plusieurs tickets n'est annonce qu'une fois. Renvoie True si meta a change."""
    played = meta.get("played", {})
    sent = meta.setdefault("kick_sent", {})
    hist = {c["id"]: c for c in history["combos"]}
    due = {}
    for cid, b in played.items():
        c = hist.get(cid) or b.get("snap")
        if not c or c.get("status") == "perdu":
            continue
        for l in c["legs"]:
            k = datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00"))
            if "won" in l or l["match_id"] in sent or not (k - KICK_BEFORE <= NOW <= k + KICK_AFTER):
                continue
            due.setdefault(l["match_id"], {"leg": l, "k": k, "labels": []})["labels"].append(l["label"])
    if not due:
        return False
    items = sorted(due.values(), key=lambda x: x["k"])
    lines = [f"{x['k'].astimezone(PARIS):%Hh%M} {x['leg']['home']} - {x['leg']['away']} : {', '.join(dict.fromkeys(x['labels']))}" for x in items]
    started = all(x["k"] <= NOW for x in items)
    first = items[0]
    head = "C'est parti" if started else "Coup d'envoi imminent"
    what = f"{first['leg']['home']} - {first['leg']['away']}" if len(items) == 1 else f"{len(items)} de tes matchs"
    notify(f"{head} : {what}", "\n".join(lines), "stopwatch,soccer", 3)
    for mid in due:
        sent[mid] = NOW.isoformat()
    limit = (NOW - timedelta(days=3)).isoformat()
    meta["kick_sent"] = {k: v for k, v in sent.items() if v > limit}
    return True


def weekly_recap(meta, history, force=False):
    """Le dimanche soir (a partir de 23h15, ou le lundi matin en rattrapage) : le bilan de ta semaine. Renvoie True si envoye."""
    now_p = NOW.astimezone(PARIS)
    if now_p.weekday() == 6 and (now_p.hour, now_p.minute) >= (23, 15):
        monday = (now_p - timedelta(days=6)).date()
    elif now_p.weekday() == 0 and now_p.hour < 12:
        monday = (now_p - timedelta(days=7)).date()
    elif not force:
        return False
    else:
        monday = (now_p - timedelta(days=now_p.weekday())).date()
    week = f"{monday.isocalendar()[0]}-W{monday.isocalendar()[1]:02d}"
    if meta.get("recap_week") == week and not force:
        return False
    days = {(monday + timedelta(days=i)).isoformat() for i in range(7)}
    hist = {c["id"]: c for c in history["combos"]}
    mine = []
    for cid, b in meta.get("played", {}).items():
        c = hist.get(cid) or b.get("snap")
        if c and c.get("day") in days:
            mine.append((c, b.get("mise") or 0, b.get("odds") or c["odds"]))
    meta["recap_week"] = week
    if not mine:
        return False
    done = [x for x in mine if x[0]["status"] != "en attente"]
    won = [x for x in done if x[0]["status"] == "gagne"]
    mise = sum(m for _c, m, _o in done)
    back = sum(m * o for _c, m, o in won)
    net = back - mise
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    sunday = monday + timedelta(days=6)
    lines = [f"{len(done)} ticket{'s' if len(done) > 1 else ''} terminé{'s' if len(done) > 1 else ''}, {len(won)} gagné{'s' if len(won) > 1 else ''}."]
    if done:
        lines.append(f"Misé {fr(mise)} €, récupéré {fr(back)} €, résultat {'+' if net >= 0 else '−'}{fr(abs(net))} €.")
    if won:
        c, m, o = max(won, key=lambda x: x[1] * x[2])
        lines.append(f"Meilleur ticket : cote {fr(o)}, {fr(m * o)} € récupérés ({short(c)}).")
    pending = len(mine) - len(done)
    if pending:
        lines.append(f"Encore en cours : {pending}.")
    robot = [c for c in history["combos"] if c["day"] in days and c["kind"] != "folie" and not c.get("replaced") and c["status"] != "en attente"]
    if robot:
        rw = sum(c["status"] == "gagne" for c in robot)
        lines.append(f"Les tickets proposés par le robot : {rw} gagné{'s' if rw > 1 else ''} sur {len(robot)}.")
    title = f"Ta semaine du {monday.day} au {sunday.day} {mois[sunday.month - 1]} : {'+' if net >= 0 else '−'}{fr(abs(net))} €"
    notify(title, "\n".join(lines), "bar_chart", 3)
    return True


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
    if m == "1N":
        return hg >= ag
    if m == "N2":
        return hg <= ag
    if m == "12":
        return hg != ag
    if m == "BTTS":
        return hg > 0 and ag > 0
    if m == "NBTTS":
        return hg == 0 or ag == 0
    if m == "H1":
        return hg - ag >= 2
    if m == "H2":
        return ag - hg >= 2
    if m.startswith(("HC1:", "HC2:")):   # handicap en points (NBA) : l'equipe gagne avec le handicap ajoute a son score
        ln = float(m[4:])
        return hg + ln > ag if m[2] == "1" else ag + ln > hg
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
        if all("won" in l for l in c["legs"]):
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
        if c["status"] != "en attente" and not c.get("settled_at"):
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
            sport = next((k for k, v in LEAGUES.items() if v[0] == l["div"]), None)   # foot seulement (NBA, tennis : ESPN)
            if sport and "won" not in l and ended and recent and l["match_id"] not in (espn or {}) and find_score_fd(fd, l) is None:
                need.add(sport)
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


# ---------------------------------------------------------------- amelioration continue (voir learn.py)
FD_NAMES = {"F1": "Ligue 1", "E0": "Premier League", "SP1": "Liga", "I1": "Serie A", "D1": "Bundesliga"}


def _fd_market(r):
    """Probabilites du marche a partir des cotes moyennes publiees par football-data (marge retiree)."""
    try:
        o = [float(r[c]) for c in ("AvgH", "AvgD", "AvgA")]
        inv = sum(1 / x for x in o)
        f1, f2 = 1 / o[0] / inv, 1 / o[2] / inv
        fO = None
        if pd.notna(r.get("Avg>2.5")) and pd.notna(r.get("Avg<2.5")):
            oo, ou = float(r["Avg>2.5"]), float(r["Avg<2.5"])
            fO = (1 / oo) / (1 / oo + 1 / ou)
        return f1, f2, fO
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None


def seed_learning(store, days=400):
    """Amorcage, une seule fois : rejoue les ~13 derniers mois semaine par semaine, comme si le robot avait tourne
    (modele reentraine chaque semaine sur le passe seulement, reglages reappris chaque mois sur le passe seulement)."""
    fd = load_history_fd(3)
    start = pd.Timestamp(NOW.date()) - pd.Timedelta(days=days)
    end = pd.Timestamp(NOW.date())
    for div in FD_DIVS:
        g = fd[fd.Div == div].sort_values("Date")
        wk = start
        while wk < end:
            test = g[(g.Date >= wk) & (g.Date < wk + pd.Timedelta(days=7))]
            train = g[g.Date < wk]
            if len(test):
                mdl = fit_league(train, ref=wk) if len(train) > 50 else None
                for _i, r in test.iterrows():
                    mk = _fd_market(r)
                    if not mk:
                        continue
                    f1, f2, fO = mk
                    lm = model_lambdas(mdl, r.HomeTeam, r.AwayTeam)
                    lmk = market_lambdas(f1, f2, fO, 2.5, lm or (1.4, 1.1))
                    mid = f"fd-{div}-{r.Date.date().isoformat()}-{r.HomeTeam}-{r.AwayTeam}"
                    store["preds"][mid] = dict(d=r.Date.date().isoformat(), k=r.Date.date().isoformat() + "T15:00:00Z", div=div,
                                               lg=FD_NAMES[div], h=r.HomeTeam, a=r.AwayTeam, fh=r.HomeTeam, fa=r.AwayTeam,
                                               pm=learn.vec(score_matrix(*lm)) if lm else None, pk=learn.vec(score_matrix(*lmk)),
                                               res=[int(r.FTHG), int(r.FTAG)], src="backtest")
            wk += pd.Timedelta(days=7)
    # probabilites "annoncees" : reglages appris chaque debut de mois sur les seuls matchs anterieurs
    recs = sorted((r for r in store["preds"].values() if r.get("src") == "backtest"), key=lambda r: r["d"])
    month, prm = None, None
    for r in recs:
        if r["d"][:7] != month:
            month = r["d"][:7]
            ref = datetime.fromisoformat(month + "-01").replace(tzinfo=timezone.utc)
            prm = learn.learn_params(store, ref, before=month + "-01")
            learn.log_params(store, ref, prm)
        r["pr"] = learn.adjust_vec(learn.blend(r.get("pm"), r["pk"], prm["w_model"]), prm["offsets"]).round(4).tolist()
    store["seeded"] = True
    print(f"amorcage : {len(recs)} matchs rejoues", file=sys.stderr)


def record_predictions(store, matches):
    for m in matches:
        lp = m.pop("_lp", None)
        if lp:
            learn.record(store, m["id"], dict(d=m["day"], k=m["kickoff"], div=m["div"], lg=m["league"], h=m["home"], a=m["away"],
                                              fh=m["fd_home"], fa=m["fd_away"]), lp["pm"], lp["pk"], lp["pr"])


def settle_predictions(store, fd):
    """Scores des matchs du journal : football-data, sinon ESPN (gratuit)."""
    late = (NOW - timedelta(hours=2, minutes=15)).isoformat()
    todo = [(mid, r) for mid, r in store["preds"].items() if not r.get("res") and not r.get("lost") and r["k"] <= late]
    if not todo:
        return 0
    legs = [dict(match_id=mid, kickoff=r["k"], div=r["div"], home=r["h"], away=r["a"]) for mid, r in todo]
    try:
        espn = espn_scores({"combos": [{"status": "en attente", "legs": legs}]})
    except Exception as e:
        print("espn journal", e, file=sys.stderr)
        espn = {}
    n = 0
    for mid, r in todo:
        sc = espn.get(mid) or find_score_fd(fd, dict(kickoff=r["k"], fd_home=r.get("fh"), fd_away=r.get("fa")))
        if sc:
            r["res"] = [int(sc[0]), int(sc[1])]
            n += 1
        elif r["k"] < (NOW - timedelta(days=10)).isoformat():
            r["res"] = None
            r["lost"] = True  # score introuvable : ignore dans les mesures
    return n


# ---------------------------------------------------------------- programme principal
ODDS_SLOTS = ((7, 30), (16, 30))  # heures de Paris ou les cotes sont actualisees (credits)


def odds_due(meta):
    if os.environ.get("FORCE") == "1":
        return True
    last = meta.get("last_odds_run")
    now_p = NOW.astimezone(PARIS)
    for i, (h, m) in enumerate(ODDS_SLOTS):
        slot = now_p.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= now_p and (not last or datetime.fromisoformat(last) < slot):
            if i > 0 and not afternoon_affordable(meta, now_p):
                print("creneau de l'apres-midi saute pour garder des credits jusqu'a la fin du mois")
                return False
            return True
    return False


RUN_COST = 14  # credits d'un passage avec cotes (environ 10 a 12 pour le foot, plus 1 a 3 le matin pour NBA et tennis)


def afternoon_affordable(meta, now_p):
    """Le passage de 16h30 n'a lieu que s'il reste de quoi faire celui de 7h30 tous les jours jusqu'a la fin du mois
    (500 credits gratuits par mois, soit un peu moins que deux passages par jour)."""
    rem = meta.get("credits_remaining")
    if rem is None:
        return True
    nxt = (now_p.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_left = (nxt.date() - now_p.date()).days - 1
    return rem - RUN_COST >= days_left * RUN_COST


def results_only(meta, history):
    """Passage gratuit : resultats ESPN seulement, on n'ecrit que si quelque chose a change."""
    before = json.dumps(history, sort_keys=True, default=str)
    meta_changed = sync_played(meta)
    sync_backup()
    meta_changed |= notify_kickoffs(meta, history)
    meta_changed |= settle_perso(meta)
    status_before = {c["id"]: c["status"] for c in history["combos"]}
    settle(history, None, {}, espn_scores(history))
    notify_settled(status_before, history, meta.get("played", {}))
    week_before = meta.get("recap_week")
    weekly_recap(meta, history)
    meta_changed |= meta.get("recap_week") != week_before
    try:
        update_logos(history, load("today.json", {}))
    except Exception as e:
        print("logos", e, file=sys.stderr)
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

    # 0. amelioration continue : reglages reappris sur les matchs passes (journal docs/data/learning.json)
    store = load("learning.json", None) or learn.new_store()
    if not store.get("seeded"):
        try:
            seed_learning(store)
        except Exception as e:
            print("amorcage impossible", e, file=sys.stderr)
    params = learn.learn_params(store, NOW)
    PARAMS.update(params)

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
    record_predictions(store, matches)
    now_p = NOW.astimezone(PARIS)
    prev = load("today.json", {}).get("matches", [])
    # NBA et tennis : un seul releve payant par jour (1 a 3 credits), les autres passages reprennent ces matchs
    paid = meta.get("other_day") != today.isoformat()
    matches += other_sports(prev, horizon, paid=paid)
    if paid:
        meta["other_day"] = today.isoformat()
    matches.sort(key=lambda m: m["kickoff"])

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
    sync_backup()
    notify_kickoffs(meta, history)
    settle_perso(meta)
    status_before = {c["id"]: c["status"] for c in history["combos"]}
    settle(history, fd, api_scores, espn)
    notify_settled(status_before, history, meta.get("played", {}))
    weekly_recap(meta, history)
    history["combos"].sort(key=lambda c: (c["day"], c["kind"]), reverse=True)
    history["bilan"] = bilan(history)
    history["updated"] = NOW.isoformat()

    # 5. journal des predictions : scores, puis mesures pour l'onglet Modele
    settle_predictions(store, fd)
    learn.prune(store, NOW)
    learn.log_params(store, NOW, params)
    save("model.json", learn.metrics(store, params, history, NOW))
    save("learning.json", store, compact=True)

    current = [c for c in history["combos"] if c["day"] >= today.isoformat() and not c.get("replaced")]
    meta.update(credits_remaining=credits["remaining"], credits_used_last_run=credits["used_run"],
                last_run=NOW.isoformat(), last_odds_run=NOW.isoformat(), frozen_days=sorted(d for d in frozen if d >= (today - timedelta(days=7)).isoformat()),
                leagues=[v[1] for v in LEAGUES.values()])
    save("today.json", dict(generated_at=NOW.isoformat(), credits_remaining=credits["remaining"],
                            combos=sorted(current, key=lambda c: (c["day"], c["kind"] == "folie", c["kind"])),
                            alts=[a for d in days for a in alts_for_day(d, matches, {c["id"] for c in current})],
                            matches=[m for m in matches if m["day"] <= (today + timedelta(days=2)).isoformat()]))
    save("history.json", history)
    try:
        update_logos(history, load("today.json", {}))
    except Exception as e:
        print("logos", e, file=sys.stderr)
    save("odds_cache.json", cache)
    save("meta.json", meta)
    print(f"{len(matches)} matchs, {len(current)} combines, credits restants {credits['remaining']} "
          f"(utilises : {credits['used_run']})")


if __name__ == "__main__":
    main()
