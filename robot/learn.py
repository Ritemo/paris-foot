"""Amelioration continue du robot : journal des predictions, reapprentissage et metriques (onglet Modele).

Principe : chaque match des championnats suivis est enregistre avec trois jeux de probabilites
  - pm : le modele maison seul (Poisson pondere), quand il connait les deux equipes
  - pk : le marche (cotes des bookmakers, marge retiree)
  - pr : ce que le robot a vraiment annonce (melange + corrections de calibration en vigueur ce jour-la)
Une fois le score connu, on mesure qui a vu juste, et on reapprend deux reglages :
  - le poids du modele maison dans le melange (0 a 0,6, ramene vers 0,2 tant que l'echantillon est petit)
  - une correction par type de pari si le robot surestime ou sous-estime durablement ce type (bornee, prudente)
On apprend sur TOUS les matchs (des centaines), jamais sur les seuls tickets joues (trop peu nombreux : du bruit).
"""
import math
from datetime import datetime, timedelta, timezone

import numpy as np

KEYS = ("p1", "pN", "p2", "o15", "o25", "o35", "btts", "h1", "h2")
FAMILIES = {  # cle -> (nom affiche, indices du vecteur)
    "dom": ("Victoire à domicile", (0,)),
    "nul": ("Match nul", (1,)),
    "ext": ("Victoire à l'extérieur", (2,)),
    "buts": ("Nombre de buts", (3, 4, 5)),
    "btts": ("Les deux équipes marquent", (6,)),
    "hcp": ("Victoire par 2 buts ou +", (7, 8)),
}
W_PRIOR, W_N0, W_MAX = 0.2, 300, 0.6    # poids du modele : valeur du backtest, prudence, plafond
CAL_N0, CAL_MAX, CAL_MIN_N = 400, 0.25, 150  # corrections : prudence, plafond (en logit), echantillon minimal
CAL_Z = 2.0                              # on ne corrige que si l'ecart sort nettement de la marge du hasard
HALF_LIFE = 240                          # jours : les matchs recents comptent plus
KEEP_DAYS = 730
MIN_MATCHES_VERDICT = 300                # en dessous, l'onglet dit que c'est trop tot pour conclure


# ---------------------------------------------------------------- vecteurs de probabilites
def vec(mat):
    """Probabilites des marches suivis, a partir d'une matrice de scores."""
    g = np.arange(mat.shape[0])
    diff = g[:, None] - g[None, :]
    tot = g[:, None] + g[None, :]
    return [round(float(x), 4) for x in (mat[diff > 0].sum(), mat[diff == 0].sum(), mat[diff < 0].sum(),
                                         mat[tot > 1.5].sum(), mat[tot > 2.5].sum(), mat[tot > 3.5].sum(),
                                         mat[1:, 1:].sum(), mat[diff >= 2].sum(), mat[diff <= -2].sum())]


def outcomes(hg, ag):
    d, t = hg - ag, hg + ag
    return [int(d > 0), int(d == 0), int(d < 0), int(t > 1.5), int(t > 2.5), int(t > 3.5),
            int(hg > 0 and ag > 0), int(d >= 2), int(d <= -2)]


def _logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + np.exp(-x))


def adjust_vec(v, offsets):
    """Applique les corrections par type de pari (decalage en logit), en gardant 1N2 coherent."""
    v = np.array(v, dtype=float)
    if not offsets or not any(offsets.values()):
        return v
    out = v.copy()
    for key, (_name, idx) in FAMILIES.items():
        b = offsets.get(key, 0.0)
        if b:
            out[list(idx)] = _sig(_logit(v[list(idx)]) + b)
    out[:3] = out[:3] / out[:3].sum()
    out[7] = min(out[7], out[0])
    out[8] = min(out[8], out[2])
    return out


def adjust_probs(p, offsets):
    """Meme correction, sur le dictionnaire de probabilites du robot (run.probs)."""
    if not offsets or not any(offsets.values()):
        return p
    ov = p["over"]
    v = [p["p1"], p["pN"], p["p2"], ov.get(1.5), ov.get(2.5), ov.get(3.5), p["btts"], p["h1"], p["h2"]]
    a = adjust_vec(v, offsets)
    q = dict(p)
    q.update(p1=a[0], pN=a[1], p2=a[2], btts=a[6], h1=a[7], h2=a[8], over={1.5: a[3], 2.5: a[4], 3.5: a[5]})
    b = offsets.get("buts", 0.0)
    q["pO"] = float(_sig(_logit(np.array(p["pO"])) + b)) if b else p["pO"]
    for ln, idx in ((1.5, 3), (2.5, 4), (3.5, 5)):
        if abs(p["pO"] - ov.get(ln, -1)) < 1e-9:
            q["pO"] = a[idx]
    return q


def blend(pm, pk, w):
    return np.array(pk, dtype=float) if pm is None else w * np.array(pm, dtype=float) + (1 - w) * np.array(pk, dtype=float)


# ---------------------------------------------------------------- journal
def new_store():
    return {"preds": {}, "params_log": [], "seeded": False}


def record(store, mid, info, pm, pk, pr):
    """Enregistre (ou rafraichit jusqu'au coup d'envoi) la prediction d'un match a venir."""
    r = store["preds"].get(mid)
    if r and r.get("res"):
        return
    store["preds"][mid] = dict(info, pm=pm, pk=[round(float(x), 4) for x in pk], pr=[round(float(x), 4) for x in pr], src="live")


def prune(store, now):
    lim = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    store["preds"] = {k: v for k, v in store["preds"].items() if v["d"] >= lim}


def _settled(store, before=None, after=None):
    rs = [r for r in store["preds"].values() if r.get("res")]
    if before:
        rs = [r for r in rs if r["d"] < before]
    if after:
        rs = [r for r in rs if r["d"] >= after]
    return rs


def _arrays(rs):
    n = len(rs)
    PK = np.array([r["pk"] for r in rs], dtype=float).reshape(n, 9)
    PM = np.array([r["pm"] if r.get("pm") else [np.nan] * 9 for r in rs], dtype=float).reshape(n, 9)
    PR = np.array([r.get("pr") or r["pk"] for r in rs], dtype=float).reshape(n, 9)
    Y = np.array([outcomes(*r["res"]) for r in rs], dtype=float).reshape(n, 9)
    return PK, PM, PR, Y


def _ages(rs, now):
    d0 = now.date() if hasattr(now, "date") else now
    return np.array([(d0 - datetime.fromisoformat(r["d"]).date()).days for r in rs], dtype=float)


def _ll3(P, Y):
    return -np.log(np.clip((P[:, :3] * Y[:, :3]).sum(1), 1e-6, 1))


def _llb(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ---------------------------------------------------------------- reapprentissage
def learn_params(store, now, before=None):
    """Poids du modele et corrections, appris sur les matchs termines (avant la date `before` si donnee)."""
    rs = _settled(store, before=before)
    out = dict(w_model=W_PRIOR, w_opt=None, n_w=0, offsets={k: 0.0 for k in FAMILIES}, n=len(rs))
    if not rs:
        return out
    PK, PM, _PR, Y = _arrays(rs)
    t = 0.5 ** (_ages(rs, now) / HALF_LIFE)
    has = ~np.isnan(PM[:, 0])
    n_w = int(has.sum())
    w = W_PRIOR
    if n_w >= 30:
        grid = np.round(np.arange(0, W_MAX + 1e-9, 0.05), 2)
        losses = []
        for g in grid:
            B = g * PM[has] + (1 - g) * PK[has]
            losses.append(float((t[has] * (_ll3(B, Y[has]) + _llb(B[:, 4], Y[has, 4]))).sum()))
        w_opt = float(grid[int(np.argmin(losses))])
        w = (n_w * w_opt + W_N0 * W_PRIOR) / (n_w + W_N0)
        out["w_opt"] = w_opt
    out["w_model"] = round(float(min(max(w, 0.0), W_MAX)), 3)
    out["n_w"] = n_w
    # corrections par type de pari, mesurees sur le melange avec le poids qu'on vient d'apprendre
    B = np.where(has[:, None], out["w_model"] * np.nan_to_num(PM) + (1 - out["w_model"]) * PK, PK)
    for key, (_name, idx) in FAMILIES.items():
        p = B[:, list(idx)].ravel()
        y = Y[:, list(idx)].ravel()
        tw = np.repeat(t, len(idx))
        n = len(rs)
        if n < CAL_MIN_N:
            continue
        # ecart annonce / reel en nombre d'ecarts-types (variance gonflee : les seuils d'un meme match sont lies)
        zf = (y.sum() - p.sum()) / math.sqrt(max((p * (1 - p)).sum() * len(idx), 1e-9))
        out.setdefault("z", {})[key] = round(float(zf), 2)
        if abs(zf) < CAL_Z:
            continue
        z, b = _logit(p), 0.0
        for _ in range(25):  # Newton sur la log-vraisemblance ponderee
            q = _sig(z + b)
            g = (tw * (q - y)).sum()
            h = (tw * q * (1 - q)).sum() + 1e-9
            b -= g / h
        b = b * n / (n + CAL_N0)
        out["offsets"][key] = round(float(np.clip(b, -CAL_MAX, CAL_MAX)), 3)
    return out


def log_params(store, now, params):
    day = now.date().isoformat()
    log = [x for x in store.get("params_log", []) if x["d"] != day]
    log.append(dict(d=day, w=params["w_model"], w_opt=params.get("w_opt"), n=params["n"], off=params["offsets"]))
    store["params_log"] = sorted(log, key=lambda x: x["d"])[-400:]


# ---------------------------------------------------------------- metriques pour l'appli
def _brier3(P, Y):
    return ((P[:, :3] - Y[:, :3]) ** 2).sum(1)


def _z(obs, exp, var):
    return round(float((obs - exp) / math.sqrt(var)), 2) if var > 0 else 0.0


def ticket_check(history):
    """Annonce contre realite sur les tickets proposes par le robot (hors folies), et sur leurs selections."""
    cs = [c for c in history.get("combos", []) if c.get("status") in ("gagne", "perdu") and not c.get("replaced") and c["kind"] != "folie"]
    legs = [l for c in cs for l in c["legs"] if "won" in l]
    out = {}
    for name, items, pf, wf in (("tickets", cs, lambda c: c["p"], lambda c: c["status"] == "gagne"),
                                ("selections", legs, lambda l: l["p"], lambda l: bool(l["won"]))):
        if not items:
            continue
        ps = np.array([pf(x) for x in items])
        obs = sum(wf(x) for x in items)
        out[name] = dict(n=len(items), annonce=round(float(ps.mean()), 3), reel=round(obs / len(items), 3),
                         attendus=round(float(ps.sum()), 1), observes=int(obs), z=_z(obs, ps.sum(), (ps * (1 - ps)).sum()),
                         marge=round(2 * math.sqrt(float((ps * (1 - ps)).sum())), 1))  # +/- 2 ecarts-types : la marge du hasard
    return out


def verdict(z):
    a = abs(z)
    return "hasard" if a < 2 else "net" if a >= 3 else "probable"


def metrics(store, params, history, now):
    """Tout ce que l'onglet Modele affiche : docs/data/model.json (petit fichier)."""
    rs_all = _settled(store)
    y365 = (now - timedelta(days=365)).date().isoformat()
    rs = [r for r in rs_all if r["d"] >= y365]
    live = [r for r in rs_all if r.get("src") == "live"]
    pending = sum(1 for r in store["preds"].values() if not r.get("res"))
    out = dict(updated=now.isoformat(), params=dict(w_model=params["w_model"], w_prior=W_PRIOR, w_opt=params.get("w_opt"),
                                                    n_w=params["n_w"], offsets=params["offsets"]),
               counts=dict(settled=len(rs_all), last_year=len(rs), live=len(live), pending=pending,
                           backtest=len(rs_all) - len(live), since=min((r["d"] for r in rs_all), default=None),
                           live_since=min((r["d"] for r in live), default=None)),
               min_verdict=MIN_MATCHES_VERDICT)
    out["tickets"] = ticket_check(history)
    out["log"] = [dict(d=x["d"], w=x["w"], off=x["off"]) for x in store.get("params_log", [])][-120:]
    if not rs:
        out["lessons"] = ["Le robot n'a encore aucun match terminé dans son journal : les mesures apparaîtront après les premiers résultats."]
        return out
    PK, PM, PR, Y = _arrays(rs)
    has = ~np.isnan(PM[:, 0])

    def sc(P, Yy):
        return dict(brier=round(float(_brier3(P, Yy).mean()), 4), logloss=round(float(_ll3(P, Yy).mean()), 4),
                    acc=round(float((P[:, :3].argmax(1) == Yy[:, :3].argmax(1)).mean()), 3))

    out["scores"] = dict(n=len(rs), robot=sc(PR, Y), marche=sc(PK, Y))
    if has.sum():
        out["scores"]["modele"] = sc(PM[has], Y[has])
        out["scores"]["n_modele"] = int(has.sum())
        out["scores"]["marche_sur_modele"] = sc(PK[has], Y[has])
    d = _brier3(PK, Y) - _brier3(PR, Y)                # > 0 : le robot fait mieux que les bookmakers
    out["scores"]["gain_vs_marche"] = round(float(d.mean() / _brier3(PK, Y).mean()), 4)
    out["scores"]["z_vs_marche"] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2) if len(d) > 2 and d.std() > 0 else 0.0
    if has.sum() > 2:
        dm = _brier3(PK[has], Y[has]) - _brier3(PM[has], Y[has])
        out["scores"]["z_modele_vs_marche"] = round(float(dm.mean() / (dm.std(ddof=1) / math.sqrt(len(dm)))), 2) if dm.std() > 0 else 0.0

    # calibration : probabilites annoncees (1, N, 2, plus de 2,5 buts) regroupees par tranches de 10 %
    p = PR[:, [0, 1, 2, 4]].ravel()
    y = Y[:, [0, 1, 2, 4]].ravel()
    bins = []
    for lo in np.arange(0, 1, 0.1):
        m = (p >= lo) & (p < lo + 0.1)
        if m.sum() >= 15:
            bins.append(dict(lo=round(float(lo), 1), p=round(float(p[m].mean()), 3), f=round(float(y[m].mean()), 3), n=int(m.sum())))
    out["calibration"] = bins

    fams = []
    for key, (name, idx) in FAMILIES.items():
        pp = PR[:, list(idx)].ravel()
        yy = Y[:, list(idx)].ravel()
        fams.append(dict(key=key, name=name, n=int(len(rs)), annonce=round(float(pp.mean()), 3), reel=round(float(yy.mean()), 3),
                         z=_z(yy.sum(), pp.sum(), (pp * (1 - pp)).sum() * len(idx)), offset=params["offsets"].get(key, 0.0)))
    out["families"] = fams

    months = {}
    for i, r in enumerate(rs):
        months.setdefault(r["d"][:7], []).append(i)
    out["months"] = [dict(m=m, n=len(ix), robot=round(float(_brier3(PR[ix], Y[ix]).mean()), 4),
                          marche=round(float(_brier3(PK[ix], Y[ix]).mean()), 4)) for m, ix in sorted(months.items()) if len(ix) >= 20]

    leagues = {}
    for i, r in enumerate(rs):
        leagues.setdefault(r.get("lg", "?"), []).append(i)
    out["leagues"] = sorted([dict(name=k, n=len(ix), robot=round(float(_brier3(PR[ix], Y[ix]).mean()), 4),
                                  marche=round(float(_brier3(PK[ix], Y[ix]).mean()), 4)) for k, ix in leagues.items() if len(ix) >= 20],
                            key=lambda x: -x["n"])
    out["lessons"] = lessons(out)
    return out


def _fr(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def lessons(m):
    """Ce que le robot a appris, en phrases simples (affichees en tete de l'onglet)."""
    L = []
    sc, prm = m.get("scores", {}), m["params"]
    n = m["counts"]["last_year"]
    if n < MIN_MATCHES_VERDICT:
        L.append(f"Seulement {n} matchs terminés dans le journal : les mesures sont encore fragiles, il en faut au moins {MIN_MATCHES_VERDICT}.")
    z = sc.get("z_vs_marche", 0)
    if verdict(z) == "hasard":
        L.append("Le robot et les bookmakers voient juste à peu près aussi souvent : l'écart entre eux reste dans la marge du hasard. "
                 "C'est normal, les cotes intègrent déjà presque toute l'information.")
    elif z > 0:
        L.append("Sur l'année, les probabilités du robot sont un peu plus justes que celles des bookmakers. L'avance reste petite et ne couvre pas leur marge.")
    else:
        L.append("Sur l'année, les bookmakers voient plus juste que le robot : le poids du modèle maison est réduit en conséquence.")
    zm = sc.get("z_modele_vs_marche")
    if zm is not None and zm <= -2:
        L.append("Seul, le modèle maison prévoit nettement moins bien que les bookmakers sur ces matchs.")
    w, wp = prm["w_model"], prm["w_prior"]
    if abs(w - wp) < 0.02:
        L.append(f"Le modèle maison garde son poids de départ ({round(w * 100)} % du mélange, le reste vient des cotes).")
    else:
        L.append(f"Le poids du modèle maison est passé de {round(wp * 100)} % à {round(w * 100)} % du mélange, "
                 f"{'car il apporte' if w > wp else 'car il apporte moins que prévu'} sur les matchs récents.")
    for f in m.get("families", []):
        if f["offset"] and abs(f["offset"]) >= 0.03:
            sens = "surestimait" if f["offset"] < 0 else "sous-estimait"
            L.append(f"{f['name']} : le robot {sens} ce type de pari ({round(f['annonce'] * 100)} % annoncés pour {round(f['reel'] * 100)} % réels), "
                     f"il le corrige désormais.")
    if not any(abs(f["offset"]) >= 0.03 for f in m.get("families", [])):
        L.append("Aucun type de pari n'est durablement mal estimé : pas de correction appliquée.")
    t = m.get("tickets", {}).get("tickets")
    if t:
        msg = f"Tickets proposés : {t['observes']} gagnés sur {t['n']} pour {_fr(t['attendus'])} attendus. "
        v = verdict(t["z"])
        msg += ("Écart compatible avec le hasard, rien à corriger à ce stade." if v == "hasard"
                else "Écart à surveiller." if v == "probable" else "Écart net : les tickets réussissent moins que prévu." if t["z"] < 0 else "Écart net en faveur des tickets, probablement de la chance.")
        L.append(msg)
    return L
