"""
Nationwide general-electorate model.

PARTY VOTE (locality level)
  * Election-day booths are grouped by locality (the Electoral Commission's suburb label,
    with renamed centres folded together, e.g. "Porirua City Centre" -> "porirua").
  * lean[locality, year, party] = locality party share - national party share.
  * Advance, special and other votes are cast far from home, so they are not placed by
    location. Instead each electorate's "non-election-day" adjustment
      adj[E, year, party] = (all-vote share - election-day share) in electorate E
    is attached to every locality in E that year and averaged over years per locality.
  * A seat's predicted share = national share + vote-weighted mean over its localities of
    (projected lean + adj). Weights = each locality's share of its electorate's election-day
    votes x that electorate's total valid votes (latest year).
  * Projected lean: 'mean' (all years), 'recent' (last 3 elections) or 'trend' (straight
    line, needs >= 3 elections; otherwise recent mean).

CANDIDATE VOTE (booth level, every electorate and year)
  For each party with a candidate, weighted least squares:
      cand share - party share = personal[candidate-year] + g * own party share
                                 + sum_k b_k * share of other party k
  Projection: incumbent / returning candidate -> their latest personal vote;
              otherwise the party's typical personal vote. Seven parties' candidates are
              projected; their shares are clipped at 0 and scaled to sum with "Other" to 100.

Usage (as a module): see backtest_2023.py and predict_2026_nz.py
"""
import re
import numpy as np
import pandas as pd

from booth_lean import NATIONAL, deaccent

PARTIES = ["National", "Labour", "Green", "ACT", "NZ First", "TOP", "Māori"]
import os
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[2]
DATA = os.environ.get("NZ_DATA", str(_ROOT / "build" / "booths" / "parsed"))   # folder written by nz_parse.py

# National results for elections not yet typed into booth_lean.NATIONAL (e.g. 2026) are
# read from data/polls/elections.csv, the same file that anchors the poll-of-polls.
_CODES = {"NAT": "National", "LAB": "Labour", "GRN": "Green", "ACT": "ACT",
          "NZF": "NZ First", "TPM": "Māori", "OPP": "TOP"}
try:
    _e = pd.read_csv(_ROOT / "data" / "polls" / "elections.csv", comment="#")
    for _, _r in _e.iterrows():
        _y = int(str(_r["date"])[:4])
        if _y not in NATIONAL:
            NATIONAL[_y] = {name: float(_r[c]) for c, name in _CODES.items()}
except FileNotFoundError:
    pass

LOC_ALIASES = {}  # extra manual folds: {"old name": "new name"}


def loc_canon(s):
    s = deaccent(str(s)).lower().replace("'", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\bmt\b", "mount", s)
    s = re.sub(r"\bst\b", "saint", s)
    s = re.sub(r"\b(central city|city centre|city central|central|city|cbd)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return LOC_ALIASES.get(s, s)


def national_share(year):
    n = dict(NATIONAL[year])
    n["Other"] = 100 - sum(n.get(p, 0) for p in PARTIES)
    return {p: n.get(p, 0.0) for p in PARTIES + ["Other"]}


def load():
    P = pd.read_csv(f"{DATA}/booth_party.csv")
    for p in PARTIES:
        if p not in P:
            P[p] = 0
    P["Other"] = P.total_valid - P[PARTIES].sum(axis=1)
    P["loc"] = np.where(P.type == "Special / other", "", P.key.str.split("|").str[0].map(loc_canon))
    C = pd.read_csv(f"{DATA}/booth_cand.csv")
    CT = pd.read_csv(f"{DATA}/candidates.csv")
    return P, C, CT


# ------------------------------------------------------------------ party-vote pieces
def locality_leans(P, years):
    ed = P[(P.type == "Election day") & P.year.isin(years)]
    g = ed.groupby(["loc", "year"])[PARTIES + ["Other", "total_valid"]].sum().reset_index()
    for p in PARTIES + ["Other"]:
        g[f"lean_{p}"] = 100 * g[p] / g.total_valid - g.year.map(lambda y: national_share(y)[p])
    return g


def electorate_adjust(P, years):
    """adj[E,year,p] = all-vote share - election-day share, then attached to localities."""
    sub = P[P.year.isin(years)]
    allv = sub.groupby(["electorate", "year"])[PARTIES + ["Other", "total_valid"]].sum()
    edv = sub[sub.type == "Election day"].groupby(["electorate", "year"])[PARTIES + ["Other", "total_valid"]].sum()
    adj = pd.DataFrame(index=allv.index)
    for p in PARTIES + ["Other"]:
        adj[p] = 100 * allv[p] / allv.total_valid - 100 * edv[p] / edv.total_valid
    adj = adj.reset_index()
    # attach to localities by where their election-day votes were cast
    ed = sub[sub.type == "Election day"].groupby(["loc", "electorate", "year"]).total_valid.sum().reset_index()
    m = ed.merge(adj, on=["electorate", "year"])
    out = m.groupby(["loc", "year"]).apply(
        lambda d: pd.Series({p: np.average(d[p], weights=d.total_valid) for p in PARTIES + ["Other"]}),
        include_groups=False).reset_index()
    return out


def project_lean(L, target_year, method):
    rows = []
    for loc, g in L.groupby("loc"):
        g = g.sort_values("year")
        r = {"loc": loc, "n_years": len(g)}
        for p in PARTIES + ["Other"]:
            y, v = g.year.values.astype(float), g[f"lean_{p}"].values
            if method == "mean":
                r[p] = v.mean()
            elif method == "recent":
                r[p] = v[-3:].mean()
            elif method == "trend":
                if len(g) >= 3:
                    s, a = np.polyfit(y, v, 1)
                    r[p] = a + s * target_year
                else:
                    r[p] = v[-3:].mean()
        rows.append(r)
    return pd.DataFrame(rows).set_index("loc")


def project_adj(A, recent_years):
    a = A[A.year.isin(recent_years)].groupby("loc")[PARTIES + ["Other"]].mean()
    return a


def seat_party_shares(weights, lean, adj, nat):
    """weights: DataFrame [seat, loc, w]. Returns DataFrame seat x party shares."""
    w = weights.merge(lean, left_on="loc", right_index=True, how="left", suffixes=("", "_lean"))
    missing = w[PARTIES[0]].isna()
    # localities with no history: fall back to the seat's average lean (computed below)
    out = []
    for seat, g in w.groupby("seat"):
        known = g[~g[PARTIES[0]].isna()]
        row = {"seat": seat, "votes": g.w.sum(), "share_no_history": g.loc[g[PARTIES[0]].isna(), "w"].sum() / g.w.sum()}
        a = adj.reindex(g["loc"]).fillna(adj.reindex(known["loc"]).mean() if len(known) else 0)
        for p in PARTIES + ["Other"]:
            base = np.average(known[p], weights=known.w) if len(known) else 0.0
            lv = g[p].fillna(base).values
            av = a[p].fillna(0).values
            row[p] = nat[p] + np.average(lv + av, weights=g.w)
        out.append(row)
    S = pd.DataFrame(out).set_index("seat")
    sh = S[PARTIES + ["Other"]].clip(lower=0)
    S[PARTIES + ["Other"]] = sh.div(sh.sum(axis=1), axis=0) * 100
    return S


# ------------------------------------------------------------------ candidate model
def name_key(n):
    n = deaccent(str(n)).upper().replace("(NEE", "(")
    sur, _, given = n.partition(",")
    sur = re.sub(r"[^A-Z\- ]", "", sur).strip()
    first = re.sub(r"[^A-Z ]", " ", given).split()
    return f"{sur}, {first[0] if first else ''}"


def candidate_data(P, C, years):
    key = ["year", "electorate", "type", "key"]
    pa = P[P.year.isin(years)].groupby(key)[PARTIES + ["Other", "total_valid"]].sum().reset_index()
    ca = C[C.year.isin(years)].groupby(key).sum(numeric_only=True).reset_index()
    m = pa.merge(ca, on=key)
    for p in PARTIES + ["Other"]:
        m[f"s_{p}"] = 100 * m[p] / m.total_valid
    return m


def fit_candidate_models(D, CT, min_votes=30):
    """Returns {party: (coef Series over s_* , personal-vote DataFrame)}."""
    CT = CT.copy()
    CT["nk"] = CT.candidate.map(name_key)
    models = {}
    for p in PARTIES:
        col = f"{p}|cand"
        if col not in D:
            continue
        d = D[(D.groupby(["year", "electorate"])[col].transform("sum") > 0) & (D.cand_total >= min_votes)].copy()
        if d.empty:
            continue
        d["ey"] = d.year.astype(str) + "|" + d.electorate
        d["gap"] = 100 * d[col] / d.cand_total - d[f"s_{p}"]
        X = pd.concat([pd.get_dummies(d.ey, dtype=float),
                       d[[f"s_{k}" for k in PARTIES]]], axis=1)
        w = np.sqrt(d.cand_total.values)
        beta, *_ = np.linalg.lstsq(X.values * w[:, None], d.gap.values * w, rcond=None)
        coef = pd.Series(beta, index=X.columns)
        pv = coef[[c for c in X.columns if "|" in c]].rename("personal").reset_index()
        pv[["year", "electorate"]] = pv["index"].str.split("|", expand=True)
        pv["year"] = pv.year.astype(int)
        names = CT[CT.party == p][["year", "electorate", "candidate", "nk"]]
        pv = pv.merge(names, on=["year", "electorate"], how="left").drop(columns="index")
        # personal vote relative to the party's median candidate that year
        pv["rel"] = pv.personal - pv.groupby("year").personal.transform("median")
        models[p] = (coef[[f"s_{k}" for k in PARTIES]], pv)
    return models


def seat_candidate_shares(S, models, personal):
    """S: seat x party shares. personal: seat x party personal vote RELATIVE to a typical
    candidate of that party (NaN or 0 = typical)."""
    out = pd.DataFrame(index=S.index)
    for p in PARTIES:
        if p not in models:
            continue
        coef, pv = models[p]
        typical = pv.groupby("year").personal.median().mean()
        pers = typical + (personal[p].fillna(0) if p in personal else 0)
        transfer = sum(coef[f"s_{k}"] * S[k] for k in PARTIES)
        out[p] = (S[p] + pers + transfer).clip(lower=0)
    out["Other"] = (S["Other"] * 0.4).clip(lower=0)
    return out.div(out.sum(axis=1), axis=0) * 100


def lookup_personal(pv, nk, electorate, before_year, prev_electorates=()):
    """Latest personal vote for candidate nk before `before_year`, preferring the same
    electorate (or listed predecessor electorates); else their latest anywhere."""
    c = pv[(pv.nk == nk) & (pv.year < before_year)]
    if c.empty:
        return np.nan
    same = c[c.electorate.isin((electorate,) + tuple(prev_electorates))]
    c = same if len(same) else c
    return c.sort_values("year").rel.iloc[-1]
