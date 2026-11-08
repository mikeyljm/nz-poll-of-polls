"""
How wrong is the electorate model when the national result is known exactly?

Generalises backtest_2023.py: for each past election T, predict every general
electorate's candidate vote using only elections before T, the actual national party
vote in T, and T's electorates. The errors (actual minus predicted candidate share)
are purely *local*: candidates, campaigns, turnout and advance-vote shifts that a
uniform swing from voting-place leans can't see.

Each error is split into
  * a year effect: the average error across all seats that year, shared by every seat
    (e.g. Labour candidates as a group running behind the model in 2023), and
  * a seat effect: what's left, specific to each seat.

The electorate simulation adds both to every draw of the national vote, so seat
probabilities carry national, shared-local and seat-local uncertainty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import nz_model as NM

TEST_YEARS = (2014, 2017, 2020, 2023)
# Parties whose errors are modelled; others are too rarely competitive to estimate.
ERR_PARTIES = ["National", "Labour", "Green", "ACT", "NZ First", "TOP"]


def backtest_year(P, C, CT, T, method="recent"):
    years = sorted(int(y) for y in P.year.unique())
    train = [y for y in years if y < T]
    ed = P[(P.year == T) & (P.type == "Election day")].groupby(["electorate", "loc"]).total_valid.sum().reset_index()
    tot = P[P.year == T].groupby("electorate").total_valid.sum()
    ed["w"] = ed.total_valid / ed.groupby("electorate").total_valid.transform("sum") * ed.electorate.map(tot)
    W = ed.rename(columns={"electorate": "seat"})[["seat", "loc", "w"]]

    L = NM.locality_leans(P, train)
    A = NM.electorate_adjust(P, train[-2:])
    adj = NM.project_adj(A, train[-2:])
    nat = NM.national_share(T)
    S = NM.seat_party_shares(W, NM.project_lean(L, T, method), adj, nat)

    D = NM.candidate_data(P, C, train)
    CTn = CT.copy()
    CTn["nk"] = CTn.candidate.map(NM.name_key)
    models = NM.fit_candidate_models(D, CTn[CTn.year.isin(train)])
    pers = pd.DataFrame(index=S.index, columns=NM.PARTIES, dtype=float)
    for p, (coef, pv) in models.items():
        cT = CTn[(CTn.year == T) & (CTn.party == p)].set_index("electorate").nk
        for e, nk in cT.items():
            if e in pers.index:
                pers.loc[e, p] = NM.lookup_personal(pv, nk, e, T)
    pred = NM.seat_candidate_shares(S, models, pers)

    act = CT[CT.year == T].groupby(["electorate", "party"]).votes.sum().unstack(fill_value=0)
    act = act.div(act.sum(axis=1), axis=0) * 100
    rows = []
    for seat in pred.index:
        if seat not in act.index:
            continue
        for p in ERR_PARTIES:
            stood = p in act.columns and act.loc[seat, p] > 0 and p in pred.columns
            rows.append({"year": T, "seat": seat, "party": p,
                         "pred": pred.loc[seat, p] if p in pred.columns else np.nan, "actual": act.loc[seat, p] if stood else np.nan,
                         "err": (act.loc[seat, p] - pred.loc[seat, p]) if stood else np.nan})
    return pd.DataFrame(rows)


def _psd(m):
    """Nearest positive semi-definite matrix (clip negative eigenvalues)."""
    m = (m + m.T) / 2
    w, v = np.linalg.eigh(m)
    return (v * np.clip(w, 1e-6, None)) @ v.T


def calibrate(P, C, CT, method="recent", years=TEST_YEARS):
    """Returns dict with year-effect and seat-effect covariance matrices (pp^2) over
    ERR_PARTIES, plus summary numbers for the method page."""
    E = pd.concat([backtest_year(P, C, CT, T, method) for T in years if T in set(P.year)],
                  ignore_index=True)
    wide = E.pivot_table(index=["year", "seat"], columns="party", values="err")[ERR_PARTIES]
    year_mean = wide.groupby(level="year").mean()
    seat_dev = wide - year_mean.reindex(wide.index.get_level_values("year")).values
    # Seat effect: pairwise covariance of within-year deviations
    seat_cov = seat_dev.cov(min_periods=20).fillna(0).values
    # Year effect: variance of the yearly means, less the part that's just seat noise
    n = wide.groupby(level="year").count()
    noise = (seat_dev.var() / n.mean()).values
    yv = np.clip(year_mean.var().values - noise, 0, None) if len(year_mean) > 1 else np.zeros(len(ERR_PARTIES))
    # Few years: use variances only (a year-effect correlation from 4 points is noise)
    year_cov = np.diag(np.nan_to_num(yv))
    # winner accuracy at the true national result, for context
    acc = []
    for T, g in E.groupby("year"):
        pw = g.pivot(index="seat", columns="party", values="pred").idxmax(axis=1)
        aw = g.pivot(index="seat", columns="party", values="actual").idxmax(axis=1)
        acc.append({"year": int(T), "correct": int((pw == aw).sum()), "of": int(len(pw))})
    return {
        "method": method, "parties": ERR_PARTIES, "years": [int(y) for y in year_mean.index],
        "seat_cov": _psd(seat_cov).round(3).tolist(),
        "year_cov": year_cov.round(3).tolist(),
        "seat_sd": np.sqrt(np.diag(seat_cov)).round(2).tolist(),
        "year_sd": np.sqrt(yv).round(2).tolist(),
        "year_means": year_mean.round(2).reset_index().to_dict(orient="records"),
        "accuracy": acc,
    }


if __name__ == "__main__":
    P, C, CT = NM.load()
    for m in ("recent", "mean", "trend"):
        c = calibrate(P, C, CT, m)
        print(m, "seat sd", dict(zip(c["parties"], c["seat_sd"])))
        print("   year sd", dict(zip(c["parties"], c["year_sd"])))
        print("   accuracy", c["accuracy"])
        print(pd.DataFrame(c["year_means"]).to_string(index=False))
