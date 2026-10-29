"""Modele Dixon-Coles (Poisson pondere dans le temps) + probabilites de marches."""
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAXG = 10


def fit_poisson(home_idx, away_idx, hg, ag, weights, n_teams, reg=0.01):
    """Poisson pondere : log(lambda_h) = mu + home + att_h - def_a ; log(lambda_a) = mu + att_a - def_h."""
    def unpack(x):
        mu, home = x[0], x[1]
        att = x[2:2 + n_teams]
        de = x[2 + n_teams:]
        return mu, home, att, de

    def nll(x):
        mu, home, att, de = unpack(x)
        lh = mu + home + att[home_idx] - de[away_idx]
        la = mu + att[away_idx] - de[home_idx]
        eh, ea = np.exp(lh), np.exp(la)
        f = -np.sum(weights * (hg * lh - eh + ag * la - ea))
        f += reg * (np.sum(att ** 2) + np.sum(de ** 2))
        # gradient
        rh = weights * (hg - eh)
        ra = weights * (ag - ea)
        g = np.zeros_like(x)
        g[0] = -(rh.sum() + ra.sum())
        g[1] = -rh.sum()
        gatt = np.zeros(n_teams)
        gde = np.zeros(n_teams)
        np.add.at(gatt, home_idx, -rh)
        np.add.at(gatt, away_idx, -ra)
        np.add.at(gde, away_idx, rh)
        np.add.at(gde, home_idx, ra)
        g[2:2 + n_teams] = gatt + 2 * reg * att
        g[2 + n_teams:] = gde + 2 * reg * de
        return f, g

    x0 = np.zeros(2 + 2 * n_teams)
    x0[0] = np.log(max(np.average(np.r_[hg, ag], weights=np.r_[weights, weights]), 0.1))
    res = minimize(nll, x0, jac=True, method="L-BFGS-B")
    return unpack(res.x)


def dc_tau_matrix(lh, la, rho):
    t = np.ones((2, 2))
    t[0, 0] = 1 - lh * la * rho
    t[0, 1] = 1 + lh * rho
    t[1, 0] = 1 + la * rho
    t[1, 1] = 1 - rho
    return t


def score_matrix(lh, la, rho=-0.06):
    g = np.arange(MAXG + 1)
    m = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    m[:2, :2] *= dc_tau_matrix(lh, la, rho)
    return m / m.sum()


def ah_prob(m, line, side):
    """Probabilite 'effective' d'un handicap asiatique (gain, demi-gain, rembourse).
    Retourne (p_win, p_half_win, p_push, p_half_loss, p_loss) pour le cote home (side='H') avec handicap line applique au home.
    Les lignes en quart (.25/.75) sont decomposees en deux demi-mises."""
    g = np.arange(MAXG + 1)
    diff = g[:, None] - g[None, :]  # home - away
    if side == "A":
        diff = -diff
        line = -line

    def single(l):
        v = diff + l
        win = m[v > 0.01].sum()
        push = m[np.abs(v) < 0.01].sum()
        loss = m[v < -0.01].sum()
        return win, push, loss

    frac = round((line * 4) % 2)
    if frac == 1:  # quart de ligne
        a = single(line - 0.25)
        b = single(line + 0.25)
        return a, b
    s = single(line)
    return s, s


def ah_ev(m, line, side, odds):
    a, b = ah_prob(m, line, side)
    ev = 0
    for (w, p, l) in (a, b):
        ev += 0.5 * (w * (odds - 1) + p * 0 - l)
    return ev


def ah_settle(hg, ag, line, side, odds):
    """Retourne le gain net pour une mise de 1."""
    diff = hg - ag
    if side == "A":
        diff, line = -diff, -line

    def single(l):
        v = diff + l
        if v > 0.01:
            return odds - 1
        if abs(v) < 0.01:
            return 0.0
        return -1.0

    frac = round((line * 4) % 2)
    if frac == 1:
        return 0.5 * single(line - 0.25) + 0.5 * single(line + 0.25)
    return single(line)
