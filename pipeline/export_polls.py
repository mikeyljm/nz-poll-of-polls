"""
Turn a fitted poll-of-polls into the JSON files the website reads.

  site/data/polls.json      trend, current estimate, every poll, house effects
  site/data/seats.json      seat distribution, coalition and "who governs" probabilities
  site/data/final_check.json  the final 2026 projection against the result (once entered)
  build/polls/current_median.json   national scenario for the electorate model
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "polls"))
import config as cfg      # noqa: E402
import model as M         # noqa: E402
import seats as S         # noqa: E402

VOTE_PARTIES = [p for p in cfg.PARTIES]


def r(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _dump(obj, name):
    cfg.SITE_DATA.mkdir(parents=True, exist_ok=True)
    (cfg.SITE_DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                                      encoding="utf-8")


def current_week_index(d) -> int:
    """Index of the week containing MODEL_END (the 'today' estimate)."""
    end = pd.Timestamp(cfg.MODEL_END)
    idx = int((end - pd.Timestamp(cfg.START_DATE)).days // 7)
    return min(max(idx, 0), d["n_weeks"] - 1)


def share_draws(idata, week: int) -> pd.DataFrame:
    s = idata.posterior["share"].isel(week=week).stack(sample=("chain", "draw"))
    return pd.DataFrame(s.T.values, columns=list(s["party"].values))


def export(idata, d, polls: pd.DataFrame, diagnostics: dict) -> dict:
    wk = current_week_index(d)
    weeks = d["weeks"][: wk + 1]
    post = idata.posterior["share"].isel(week=slice(0, wk + 1))
    q = post.quantile([0.05, 0.25, 0.5, 0.75, 0.95], dim=("chain", "draw")).values  # q x week x party
    trend = {p: {f"q{int(qq * 100):02d}": [r(v * 100, 2) for v in q[i, :, k]]
                 for i, qq in enumerate([0.05, 0.25, 0.5, 0.75, 0.95])}
             for k, p in enumerate(cfg.PARTIES)}

    ed = share_draws(idata, wk)
    current = {p: {"median": r(ed[p].median() * 100), "lo": r(ed[p].quantile(.05) * 100),
                   "hi": r(ed[p].quantile(.95) * 100), "p_threshold": r((ed[p] >= cfg.THRESHOLD).mean(), 3)}
               for p in cfg.PARTIES}
    # change since the last election (in percentage points)
    last_e = d["elections"].iloc[-1]
    for p in cfg.PARTIES:
        if p in last_e and not pd.isna(last_e[p]):
            current[p]["since_election"] = r(current[p]["median"] - last_e[p] * 100)

    # polls (all, for the chart and table)
    cyc_start = pd.Timestamp(cfg.ELECTIONS[-1])
    pl = []
    for _, x in polls[~polls["is_election"]].iterrows():
        pl.append({"start": x.date_start.date().isoformat(), "end": x.date_end.date().isoformat(),
                   "org": x.org, "n": None if x.get("n_imputed") else int(x.n),
                   **{p: r(x[p] * 100) for p in cfg.PARTIES if not pd.isna(x[p])},
                   "cycle_current": bool(x.date_end > cyc_start)})
    el = [{"date": x.date_end.date().isoformat(),
           **{p: r(x[p] * 100, 2) for p in cfg.PARTIES if not pd.isna(x[p])}}
          for _, x in d["elections"].iterrows()]

    he = M.house_effects(idata, d)
    # house_effects() uses the last modelled week; that's fine (it's a difference)
    n_cur = d["polls"][d["polls"]["cycle"] == d["cycles"][-1]].groupby("org").size()
    n_all = d["polls"].groupby("org").size()
    prev_e = pd.Timestamp(cfg.ELECTIONS[-2]) if len(cfg.ELECTIONS) > 1 else pd.Timestamp(cfg.START_DATE)
    n_recent = d["polls"][d["polls"]["date_end"] > prev_e].groupby("org").size()
    house = []
    for org, g in he.groupby("pollster"):
        if n_all.get(org, 0) < 3:
            continue
        house.append({"org": org, "name": cfg.POLLSTER_NAMES.get(org, org),
                      "n_current": int(n_cur.get(org, 0)), "n_total": int(n_all.get(org, 0)),
                      "n_recent": int(n_recent.get(org, 0)),
                      "effects": {row.party: {"mean": r(row["mean"]), "lo": r(row["lo"]), "hi": r(row["hi"])}
                                  for _, row in g.iterrows()}})

    n_cycle = int((polls[~polls["is_election"]].date_end > cyc_start).sum())
    last_poll = polls[~polls["is_election"]].date_end.max()
    meta = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "as_of_week": weeks[-1].date().isoformat(),
        "model_end": cfg.MODEL_END,
        "last_poll": last_poll.date().isoformat(),
        "last_election": cfg.ELECTIONS[-1],
        "previous_election": cfg.ELECTIONS[-2] if len(cfg.ELECTIONS) > 1 else cfg.START_DATE,
        "last_election_status": cfg.load_elections()["status"].iloc[-1],
        "polls_this_cycle": n_cycle,
        "parties": {p: {"name": cfg.PARTY_NAMES[p], "colour": cfg.PARTY_COLOURS[p]} for p in cfg.PARTIES},
        "pollsters": {k: v for k, v in cfg.POLLSTER_NAMES.items()},
        "diagnostics": diagnostics,
    }
    _dump({"meta": meta, "weeks": [w.date().isoformat() for w in weeks], "trend": trend,
           "current": current, "polls": pl, "elections": el, "house": house}, "polls.json")

    # scenario for the electorate model
    med = {p: round(ed[p].median() * 100, 2) for p in cfg.PARTIES}
    cfg.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (cfg.OUT_DIR / "current_median.json").write_text(json.dumps(med))
    ed.to_csv(cfg.OUT_DIR / "current_draws.csv", index=False)
    export_final_check()
    return meta


def export_seats(meta: dict):
    """MMP seats and coalitions, run after the electorate model so each draw's general
    electorate winners come from that draw's national vote."""
    ed = pd.read_csv(cfg.OUT_DIR / "current_draws.csv")
    gw_file = ROOT / "build" / "booths" / "general_winner_draws.csv"
    gw = pd.read_csv(gw_file) if gw_file.exists() else None
    if gw is not None and len(gw) != len(ed):
        print("Electorate draws don't match vote draws; using fallback electorate assumptions.")
        gw = None
    seat_draws, winners = S.simulate(ed, general_winners=gw)
    total = seat_draws["TOTAL"]
    seats = {}
    for p in [c for c in seat_draws.columns if c != "TOTAL"]:
        v = seat_draws[p]
        hist = v.value_counts(normalize=True).sort_index()
        seats[p] = {"median": int(v.median()), "lo": int(v.quantile(.05)), "hi": int(v.quantile(.95)),
                    "mean": r(v.mean()), "dist": {int(k): r(x, 4) for k, x in hist.items() if x >= 0.0005}}
    cp = S.coalition_probs(seat_draws)
    coal = [{"name": x.coalition, "parties": cfg.COALITIONS[x.coalition], "p_majority": r(x.p_majority, 3),
             "median": int(x.median_seats), "lo": int(x.lo), "hi": int(x.hi)} for _, x in cp.iterrows()]
    head = {k: r(v, 3) for k, v in S.headline(seat_draws).items()}
    maori = {name: {p: r(v, 3) for p, v in winners[name].value_counts(normalize=True).items()}
             for name in cfg.MAORI_ELECTORATES}
    # key general seats for the method page: chance each party wins them in the simulation
    key = {}
    if gw is not None:
        for name in gw.columns:
            vc = gw[name].value_counts(normalize=True)
            # seats a party other than National or Labour has a real chance of winning
            if vc.drop(["NAT", "LAB"], errors="ignore").max() >= 0.05 if len(vc.drop(["NAT", "LAB"], errors="ignore")) else False:
                key[name] = {p: r(v, 3) for p, v in vc.items() if v >= 0.005}
    overhang = (total - cfg.TOTAL_SEATS)
    _dump({"meta": {"as_of_week": meta["as_of_week"], "updated": meta["updated"],
                    "total_seats": {"median": int(total.median()), "max": int(total.max()),
                                    "p_overhang": r((overhang > 0).mean(), 3),
                                    "overhang_median": int(overhang.median())},
                    "electorates_from_model": gw is not None,
                    "blocs": {"right": cfg.RIGHT_BLOC, "left": cfg.LEFT_BLOC, "kingmaker": cfg.KINGMAKER}},
           "seats": seats, "coalitions": coal, "headline": head,
           "electorate_assumptions": {"maori": cfg.MAORI_ELECTORATES, "maori_simulated": maori,
                                      "general_key_seats": key, "swing_beta": cfg.SWING_BETA}}, "seats.json")
    print("Seats (median, 90%):", {p: (v["median"], v["lo"], v["hi"]) for p, v in seats.items() if v["hi"] > 0},
          "| overhang P =", r((overhang > 0).mean(), 3))


def export_final_check():
    """Final pre-election projection (polls to 5 Nov 2026) against the 2026 result."""
    f = ROOT / "data" / "archive" / "final_2026_projection_draws.csv"
    if not f.exists():
        return
    draws = pd.read_csv(f)
    e = cfg.load_elections()
    res = e[e["date"] == "2026-11-07"]
    rows = []
    for p in [c for c in cfg.PARTIES if c in draws]:
        x = draws[p] * 100
        row = {"party": p, "median": r(x.median()), "lo": r(x.quantile(.05)), "hi": r(x.quantile(.95))}
        if len(res) and p in res and not pd.isna(res[p].iloc[0]):
            row["result"] = r(res[p].iloc[0], 2)
            row["inside_90"] = bool(row["lo"] <= row["result"] <= row["hi"])
        rows.append(row)
    _dump({"projection_date": "2026-11-05",
           "result_status": None if res.empty else res["status"].iloc[0],
           "parties": rows}, "final_check.json")
