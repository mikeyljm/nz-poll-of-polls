"""
Electorate simulation: carry the poll-of-polls uncertainty through to every seat.

For each posterior draw of the national party vote:
  1. seat party vote   = national draw + the seat's offset (voting-place leans + the
                         advance/special-vote adjustment), clipped and renormalised;
  2. candidate vote    = the electorate model's candidate equation (personal vote plus
                         vote-splitting from other parties' voters);
  3. local error       = a year effect shared by all seats + a seat effect, drawn from
                         the errors the model made in the 2014-2023 backtests
                         (local_error.py), then renormalised.
The winner in each draw is the candidate with the most votes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import nz_model as NM

ALL = NM.PARTIES + ["Other"]


def simulate_method(O, models, pers, nat_draws: pd.DataFrame, calib: dict | None, seed=2026):
    """O: seat x ALL offsets (pp). nat_draws: draws x ALL national shares (%).
    Returns (party shares [D,S,P], candidate shares [D,S,P]) over NM.PARTIES, and seat index."""
    rng = np.random.default_rng(seed)
    seats = O.index
    nat = nat_draws[ALL].to_numpy(float)                       # D x K
    off = O[ALL].to_numpy(float)                                # S x K
    S = np.clip(nat[:, None, :] + off[None, :, :], 0, None)     # D x S x K
    S = S / S.sum(axis=2, keepdims=True) * 100

    K = len(NM.PARTIES)
    C = np.zeros_like(S)
    for i, p in enumerate(NM.PARTIES):
        if p not in models:
            continue
        coef, pv = models[p]
        typical = pv.groupby("year").personal.median().mean()
        pr = pers[p].reindex(seats).fillna(0).to_numpy(float) if p in pers else np.zeros(len(seats))
        transfer = sum(coef[f"s_{k}"] * S[:, :, j] for j, k in enumerate(NM.PARTIES))
        C[:, :, i] = np.clip(S[:, :, i] + typical + pr[None, :] + transfer, 0, None)
    C[:, :, K] = np.clip(S[:, :, K] * 0.4, 0, None)
    C = C / C.sum(axis=2, keepdims=True) * 100

    if calib:
        idx = [NM.PARTIES.index(p) for p in calib["parties"]]
        D, Sn = C.shape[:2]
        ye = rng.multivariate_normal(np.zeros(len(idx)), np.array(calib["year_cov"]), size=D, method="eigh")        # D x E
        se = rng.multivariate_normal(np.zeros(len(idx)), np.array(calib["seat_cov"]), size=(D, Sn), method="eigh")   # D x S x E
        stood = C[:, :, idx] > 0.05          # no error for a party with no real candidate there
        C[:, :, idx] = np.where(stood, C[:, :, idx] + ye[:, None, :] + se, C[:, :, idx])
        C = np.clip(C, 0, None)
        C = C / C.sum(axis=2, keepdims=True) * 100
    return S[:, :, :K], C[:, :, :K], seats


def summarise(S, C, seats):
    """Per-seat win probabilities and quantiles, and the distribution of seats won."""
    K = len(NM.PARTIES)
    win = C.argmax(axis=2)                                       # D x S
    D = win.shape[0]
    q = lambda X: np.percentile(X, [5, 50, 95], axis=0)          # 3 x S x K
    cq, pq = q(C), q(S)
    rows = []
    for j, seat in enumerate(seats):
        pw = np.bincount(win[:, j], minlength=K) / D
        rows.append({
            "seat": seat,
            "p_win": {p: float(pw[i]) for i, p in enumerate(NM.PARTIES) if pw[i] >= 0.0005},
            "cand": {p: [float(cq[0, j, i]), float(cq[1, j, i]), float(cq[2, j, i])] for i, p in enumerate(NM.PARTIES)},
            "party": {p: [float(pq[0, j, i]), float(pq[1, j, i]), float(pq[2, j, i])] for i, p in enumerate(NM.PARTIES)},
        })
    counts = np.stack([(win == i).sum(axis=1) for i in range(K)], axis=1)   # D x K
    dist = {}
    for i, p in enumerate(NM.PARTIES):
        c = counts[:, i]
        if c.max() == 0:
            continue
        vc = pd.Series(c).value_counts(normalize=True).sort_index()
        dist[p] = {"median": int(np.median(c)), "lo": int(np.percentile(c, 5)), "hi": int(np.percentile(c, 95)),
                   "mean": float(c.mean()), "dist": {int(k): float(v) for k, v in vc.items() if v >= 0.0005}}
    return rows, dist, counts, win
