"""
Predict every general electorate (2026 boundaries) from booth history.

Generalised from predict_2026_nz.py for the website: the national scenario is
passed in (the poll-of-polls median), and the base year is the latest election
in the data, so adding the 2026 voting-place results moves the model onto them.

Inputs
  nz_out/*.csv                        (from nz_parse.py)
  <boundaries zip>                   general_electorates_2025.geojson + suburbs_localities.geojson
  overrides.csv (optional)           seat,party,relative_personal_vote,note
                                     e.g.  Kāpiti,Labour,0,"Handford: new candidate, typical"
National scenario: NAT_2026 below.

Steps
  1. Each 2023 election-day locality is placed at its LINZ locality centroid and assigned to
     the 2026 electorate containing it. Names used in more than one place are resolved to
     the copy nearest the rest of that locality's 2023 electorate.
  2. Weights: locality share of its 2023 electorate's election-day votes x that electorate's
     2023 total valid votes (so advance and special votes follow their home electorate).
  3. Party vote per seat (nz_model.seat_party_shares) for 'recent' (central), 'mean', 'trend'.
  4. Candidates: for each seat the main predecessor = the 2023 electorate supplying most of
     its votes. Each party's 2023 candidate there is assumed to stand again, carrying their
     relative personal vote, unless overrides.csv says otherwise.
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

from nz_model import *

NAT_2026 = {"National": 27.5, "Labour": 28.0, "Green": 13.6, "NZ First": 10.4, "ACT": 10.0,
            "TOP": 6.8, "Māori": 1.6}   # median projection from Michael's poll of polls
NAT_2026["Other"] = 100 - sum(NAT_2026.values())
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("NZ_OUT", ROOT / "build" / "booths" / "predict")); OUT.mkdir(parents=True, exist_ok=True)
GEO = ROOT / "data" / "booths" / "geo"
SHP = os.environ.get("NZ_SHP", str(GEO / "general-electorates-2025"))   # Stats NZ GED2025 shapefile (no extension)

# (2023 electorate, locality) -> 2026 seat, for localities the LINZ file doesn't name
MANUAL_SEAT = {
    ("otaki", "ihakara"): "Rangitīkei",          # rural Horowhenua, between Foxton and Levin
    ("otaki", "waitarere beach"): "Rangitīkei",  # Horowhenua coast, west of Levin
    ("mana", "linden"): "Kenepuru",              # Tawa suburb
}   # Stats NZ shapefile (NZTM)


def load_geo(zpath):
    """Electorates from the Stats NZ shapefile (NZTM); localities from a GeoJSON (WGS84)
    inside zpath, reprojected to NZTM."""
    import shapefile
    from pyproj import Transformer
    from shapely.ops import transform
    r = shapefile.Reader(SHP)
    seats = [(rec[1], shape(sh.__geo_interface__)) for rec, sh in zip(r.records(), r.shapes())]
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        loc = json.loads(z.read(next(n for n in names if "localit" in n.lower())))
    tf = Transformer.from_crs(4326, 2193, always_xy=True).transform
    locs = []
    for f in loc["features"]:
        if not f["geometry"]:
            continue
        g = transform(tf, shape(f["geometry"]))
        pr = f["properties"]
        pt = g.representative_point()
        for nm in {pr.get("name"), pr.get("name_ascii")}:
            if nm:
                locs.append({"loc": loc_canon(nm), "x": pt.x, "y": pt.y, "ta": pr.get("territorial_authority")})
    return seats, pd.DataFrame(locs).drop_duplicates()


def place_localities(W23, seats, locs):
    """W23: electorate, loc, w (2023). Adds x, y, seat."""
    cand = W23.merge(locs, on="loc", how="left")
    # resolve duplicate names: keep the copy nearest the electorate's median of unique matches
    nmatch = cand.groupby(["electorate", "loc"]).x.transform("count")
    uniq = cand[nmatch == 1].groupby("electorate")[["x", "y"]].median()
    cand = cand.join(uniq, on="electorate", rsuffix="_e")
    cand["d"] = np.hypot(cand.x - cand.x_e, cand.y - cand.y_e)
    cand = cand.sort_values("d").drop_duplicates(["electorate", "loc"])
    tree = STRtree([g for _, g in seats])
    names = [n for n, _ in seats]

    def which(x, y):
        if np.isnan(x):
            return None
        p = Point(x, y)
        hits = tree.query(p, predicate="intersects")
        if len(hits):
            return names[hits[0]]
        return names[tree.nearest(p)]
    cand["seat"] = [which(x, y) for x, y in zip(cand.x, cand.y)]
    # unmatched names -> the seat that receives most of their 2023 electorate's votes
    main = cand.dropna(subset=["seat"]).groupby(["electorate", "seat"]).w.sum().reset_index()
    main = main.sort_values("w").groupby("electorate").tail(1).set_index("electorate").seat
    cand["placed_by"] = np.where(cand.seat.isna(), "electorate fallback", "locality centroid")
    cand["seat"] = cand.seat.fillna(cand.electorate.map(main))
    # hand-checked placements for localities missing from the LINZ download
    for (elec, loc), seat in MANUAL_SEAT.items():
        m = (cand.electorate == elec) & (cand["loc"] == loc)
        cand.loc[m, "seat"] = seat
        cand.loc[m, "placed_by"] = "manual"
    return cand


def main(zpath=GEO / "nz_localities.zip", overrides=ROOT / "data" / "booths" / "overrides.csv",
         nat=None, methods=("recent", "mean", "trend"), geo=None):
    """nat: national party-vote scenario {party: %}, defaults to NAT_2026.
    geo: (seats, locs) from load_geo, to avoid reloading."""
    nat = dict(nat or NAT_2026)
    nat.setdefault("Other", 100 - sum(v for k, v in nat.items() if k != "Other"))
    P, C, CT = load()
    CT["nk"] = CT.candidate.map(name_key)
    seats, locs = geo or load_geo(zpath)
    base = int(P.year.max())
    target = base + 3

    ed = P[(P.year == base) & (P.type == "Election day")].groupby(["electorate", "loc"]).total_valid.sum().reset_index()
    tot = P[P.year == base].groupby("electorate").total_valid.sum()
    ed["w"] = ed.total_valid / ed.groupby("electorate").total_valid.transform("sum") * ed.electorate.map(tot)
    placed = place_localities(ed, seats, locs)
    placed.to_csv(OUT / "locality_placement.csv", index=False)
    W = placed[["seat", "loc", "w"]]

    # predecessor of each seat
    flows = placed.groupby(["seat", "electorate"]).w.sum().reset_index()
    flows["share_of_seat"] = flows.w / flows.groupby("seat").w.transform("sum")
    flows.sort_values(["seat", "share_of_seat"], ascending=[True, False]).round(3).to_csv(OUT / "seat_flows_2023_to_2026.csv", index=False)
    pred = flows.sort_values("share_of_seat").groupby("seat").tail(1).set_index("seat")

    years = sorted(int(y) for y in P.year.unique())
    L = locality_leans(P, years)
    A = electorate_adjust(P, years[-3:])
    adj = project_adj(A, years[-3:])

    D = candidate_data(P, C, years)
    models = fit_candidate_models(D, CT)

    # assumed candidates: 2023 candidates of the main predecessor
    pers = pd.DataFrame(index=pred.index, columns=PARTIES, dtype=float)
    who = pd.DataFrame(index=pred.index, columns=PARTIES, dtype=object)
    for seat, r in pred.iterrows():
        for p, (coef, pv) in models.items():
            c = CT[(CT.year == base) & (CT.electorate == r.electorate) & (CT.party == p)]
            if len(c):
                # personal vote only counts in the part of the new seat they already represented
                pers.loc[seat, p] = lookup_personal(pv, c.nk.iloc[0], r.electorate, base + 1) * r.share_of_seat
                who.loc[seat, p] = c.candidate.iloc[0]
    if overrides and Path(overrides).exists() and base == 2023:   # overrides were written for 2026
        ov = pd.read_csv(overrides)
        for _, o in ov.iterrows():
            pers.loc[o.seat, o.party] = o.relative_personal_vote
            who.loc[o.seat, o.party] = o.get("note", "override")

    summary, all_rows = [], []
    for method in methods:
        lean = project_lean(L, target, method)
        S = seat_party_shares(W, lean, adj, nat)
        CS = seat_candidate_shares(S, models, pers)
        win = CS[PARTIES].idxmax(axis=1)
        top2 = np.sort(CS[PARTIES].values, axis=1)
        margin = top2[:, -1] - top2[:, -2]
        df = pd.DataFrame({"method": method, "predecessor": pred.electorate,
                           "predecessor_share": pred.share_of_seat.round(2),
                           "share_votes_no_history": S.share_no_history.round(3)})
        for p in PARTIES:
            df[f"{p}_party"] = S[p].round(1)
        for p in PARTIES:
            df[f"{p}_cand"] = CS[p].round(1)
        df["winner"] = win
        df["margin_pp"] = margin.round(1)
        for p in ["National", "Labour", "Green", "ACT"]:
            df[f"assumed_{p}_candidate"] = who[p]
        all_rows.append(df.reset_index().rename(columns={"index": "seat"}))
        counts = win.value_counts().to_dict()
        summary.append({"method": method, **{p: counts.get(p, 0) for p in PARTIES},
                        "National_within_3pp": int(((win == "National") & (margin < 3)).sum()),
                        "nonNational_within_3pp": int(((win != "National") & (margin < 3)).sum())})
    R = pd.concat(all_rows)
    R.to_csv(OUT / "seat_predictions.csv", index=False)
    Sm = pd.DataFrame(summary)
    Sm.to_csv(OUT / "seat_counts.csv", index=False)
    print(Sm.to_string(index=False))
    print(placed.placed_by.value_counts())
    return R, Sm, placed, base


if __name__ == "__main__":
    main()
