"""
Bayesian state-space poll-of-polls in PyMC.

Model
-----
Latent vote intention (weekly, from the 2020 election to the current week):

    eta[t, k]  for k = 1..K-1 (additive log-ratio scale, "Other" = reference)
    eta[0]     ~ Normal(0, 2)
    eta[t]     = eta[t-1] + sigma_k * z[t],   z ~ Normal(0, 1)
    share[t]   = softmax([eta[t], 0])

Each poll i by pollster p, in electoral cycle c, at week t:

    mu_i       = softmax([eta[t] + house[p] + drift[p, c] + industry[c], 0])
    y_ik       ~ Normal(mu_ik, sqrt(deff * mu_ik (1 - mu_ik) / n_i
                                    + sigma_extra_p^2 + rounding_i^2))

* house[p]       : persistent pollster lean (partially pooled)
* drift[p, c]    : how that lean changes from one cycle to the next
* industry[c]    : error shared by *all* polls in a cycle (2017 style misses)
* Elections enter as polls with no house/drift/industry error and a tiny sd,
  which is what anchors the house effects to reality.

For the current cycle ("next") there is no election yet, so industry[next] is
drawn from its prior (scale learnt from past cycles). This is where most of
the honest uncertainty about true vote intention comes from.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pymc as pm
import pytensor.tensor as pt

import config as cfg

ELECTION_SD = 0.0005          # sd for official results (essentially exact)
DEFF = 1.5                    # design effect applied to every poll


def _week_index(dates: pd.Series, start: pd.Timestamp) -> np.ndarray:
    return ((pd.to_datetime(dates) - start).dt.days // 7).to_numpy()


def prepare(df: pd.DataFrame) -> dict:
    """Turn the tidy poll table into index arrays for the model."""
    start = pd.Timestamp(cfg.START_DATE)
    last_e = pd.Timestamp(cfg.ELECTIONS[-1])
    end = max(pd.Timestamp(cfg.MODEL_END), df["date_end"].max(),
              last_e + pd.Timedelta(days=7))
    if cfg.NEXT_ELECTION_DATE:
        end = max(end, pd.Timestamp(cfg.NEXT_ELECTION_DATE))
    n_weeks = (end - start).days // 7 + 1
    weeks = pd.date_range(start, periods=n_weeks, freq="7D")

    df = df.copy()
    df["t"] = _week_index(df["date_mid"], start)
    df.loc[df["is_election"], "t"] = _week_index(df.loc[df["is_election"], "date_end"], start)

    # Electoral cycle = the election a poll precedes
    # Labels: the year of each past election, then "next" for polls since the
    # most recent election in data/elections.csv.
    cuts = [pd.Timestamp(d) for d in cfg.ELECTIONS] + [end]
    cycle_labels = [str(c.year) for c in cuts[1:-1]] + ["next"]
    df["cycle"] = pd.cut(df["date_end"], bins=cuts, labels=cycle_labels,
                         right=True).astype("object")

    polls = df[~df["is_election"]].reset_index(drop=True)
    elections = df[df["is_election"]].reset_index(drop=True)

    pollsters = sorted(polls["org"].unique())
    p_idx = polls["org"].map({p: i for i, p in enumerate(pollsters)}).to_numpy()
    c_idx = polls["cycle"].map({c: i for i, c in enumerate(cycle_labels)}).to_numpy()

    # Long format of observed cells (mask missing parties)
    Y = polls[cfg.PARTIES].to_numpy()
    obs_i, obs_k = np.where(~np.isnan(Y))
    y = Y[obs_i, obs_k]
    round_sd = np.where(polls["integer_rounded"].to_numpy(), 0.01 / np.sqrt(12),
                        0.001 / np.sqrt(12))

    E = elections[cfg.PARTIES].to_numpy()
    e_i, e_k = np.where(~np.isnan(E))

    return dict(
        df=df, polls=polls, elections=elections, weeks=weeks,
        n_weeks=n_weeks, pollsters=pollsters, end=end, cycles=cycle_labels,
        t=polls["t"].to_numpy(), p_idx=p_idx, c_idx=c_idx,
        n=polls["n"].to_numpy(), round_sd=round_sd,
        obs_i=obs_i, obs_k=obs_k, y=y,
        e_t=elections["t"].to_numpy(), e_i=e_i, e_k=e_k, e_y=E[e_i, e_k],
    )


def build_model(d: dict, house_effects: bool = True) -> pm.Model:
    """house_effects=False gives a plain poll average (sensitivity check)."""
    K = len(cfg.PARTIES)
    coords = {
        "week": d["weeks"], "party": cfg.PARTIES, "party_alr": cfg.PARTIES[:-1],
        "pollster": d["pollsters"], "cycle": d["cycles"],
    }
    with pm.Model(coords=coords) as model:
        # ---- latent random walk -------------------------------------------
        sigma_rw = pm.HalfNormal("sigma_rw", 0.05, dims="party_alr")
        eta0 = pm.Normal("eta0", 0, 2, dims="party_alr")
        z = pm.Normal("z", 0, 1, dims=("week", "party_alr"))
        eta = pm.Deterministic(
            "eta", eta0 + pt.cumsum(z * sigma_rw, axis=0), dims=("week", "party_alr"))

        def softmax_alr(x):
            full = pt.concatenate([x, pt.zeros((x.shape[0], 1))], axis=1)
            return pt.special.softmax(full, axis=1)

        share = pm.Deterministic("share", softmax_alr(eta), dims=("week", "party"))

        # ---- house effects ------------------------------------------------
        if house_effects:
            tau_house = pm.HalfNormal("tau_house", 0.15)
            house = pm.Normal("house", 0, tau_house, dims=("pollster", "party_alr"))
            tau_drift = pm.HalfNormal("tau_drift", 0.1)
            drift_z = pm.Normal("drift_z", 0, 1, dims=("pollster", "cycle", "party_alr"))
            drift = pm.Deterministic("drift", drift_z * tau_drift,
                                     dims=("pollster", "cycle", "party_alr"))
            pollster_bias = house[d["p_idx"]] + drift[d["p_idx"], d["c_idx"]]
        else:  # every pollster treated as unbiased (pure poll average)
            pollster_bias = 0.0
        tau_industry = pm.HalfNormal("tau_industry", 0.1)
        industry_z = pm.Normal("industry_z", 0, 1, dims=("cycle", "party_alr"))
        industry = pm.Deterministic("industry", industry_z * tau_industry,
                                    dims=("cycle", "party_alr"))

        # ---- poll likelihood ----------------------------------------------
        eta_poll = eta[d["t"]] + pollster_bias + industry[d["c_idx"]]
        mu = softmax_alr(eta_poll)
        mu_obs = mu[d["obs_i"], d["obs_k"]]

        sigma_extra = pm.HalfNormal("sigma_extra", 0.01, dims="pollster")
        sd = pt.sqrt(DEFF * mu_obs * (1 - mu_obs) / d["n"][d["obs_i"]]
                     + sigma_extra[d["p_idx"][d["obs_i"]]] ** 2
                     + d["round_sd"][d["obs_i"]] ** 2)
        pm.Normal("y_poll", mu_obs, sd, observed=d["y"])

        # ---- elections: unbiased, near-exact ---------------------------------
        mu_e = share[d["e_t"]][d["e_i"], d["e_k"]]
        pm.Normal("y_election", mu_e, ELECTION_SD, observed=d["e_y"])
    return model


def fit(model, draws=1000, tune=1500, chains=4, target_accept=0.9,
        nuts_sampler="pymc", random_seed=2026, **kw):
    """Sample. nuts_sampler="nutpie" is much faster if nutpie is installed."""
    with model:
        idata = pm.sample(draws=draws, tune=tune, chains=chains,
                          target_accept=target_accept, nuts_sampler=nuts_sampler,
                          random_seed=random_seed, **kw)
    return idata


# --------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------
def trend_summary(idata, probs=(0.05, 0.25, 0.5, 0.75, 0.95)) -> pd.DataFrame:
    """Weekly posterior quantiles of party vote share (long format)."""
    s = idata.posterior["share"].stack(sample=("chain", "draw"))
    q = s.quantile(list(probs), dim="sample")
    out = q.to_dataframe().reset_index().pivot_table(
        index=["week", "party"], columns="quantile", values="share").reset_index()
    out.columns = ["week", "party"] + [f"q{int(p * 100):02d}" for p in probs]
    return out


def election_day_shares(idata) -> pd.DataFrame:
    """Posterior draws of party vote at election day (rows = draws)."""
    s = idata.posterior["share"].isel(week=-1).stack(sample=("chain", "draw"))
    return pd.DataFrame(s.T.values, columns=list(s["party"].values))


def house_effects(idata, d) -> pd.DataFrame:
    """
    House effects on the percentage-point scale for the 2026 cycle:
    a poll's expected share minus the true share, at the latest week.
    """
    post = idata.posterior
    eta_last = post["eta"].isel(week=-1)
    true = post["share"].isel(week=-1)
    rows = []
    c26 = d["cycles"][-1]
    for p in d["pollsters"]:
        eta_p = (eta_last + post["house"].sel(pollster=p)
                 + post["drift"].sel(pollster=p, cycle=c26))
        full = np.concatenate([eta_p.values, np.zeros(eta_p.shape[:-1] + (1,))], -1)
        mu = np.exp(full) / np.exp(full).sum(-1, keepdims=True)
        diff = (mu - true.values) * 100
        flat = diff.reshape(-1, diff.shape[-1])
        for k, party in enumerate(cfg.PARTIES):
            rows.append(dict(pollster=p, party=party,
                             mean=flat[:, k].mean(),
                             lo=np.quantile(flat[:, k], 0.05),
                             hi=np.quantile(flat[:, k], 0.95)))
    return pd.DataFrame(rows)
