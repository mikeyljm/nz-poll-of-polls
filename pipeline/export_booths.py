"""
Export the voting-place lean analysis and electorate projections for the website.

Writes to site/data/:
  localities.json      every election-day locality (voting places grouped by suburb, as in
                       the electorate model): name, coordinates, 2026 seat, lean by party and
                       election, and the recent/trend projected lean
  electorates.geojson  simplified 2026 general electorate boundaries
  electorates.json     projected party vote and electorate winner for each seat, using the
                       poll-of-polls current median as the national scenario

Usage: python pipeline/export_booths.py [--scenario build/polls/current_median.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "booths"))
import nz_model as NM          # noqa: E402
import predict_nz as PR        # noqa: E402

SITE = ROOT / "site" / "data"
CODE = {"National": "NAT", "Labour": "LAB", "Green": "GRN", "ACT": "ACT",
        "NZ First": "NZF", "TOP": "OPP", "Māori": "TPM", "Other": "OTH"}
FROM_CODE = {v: k for k, v in CODE.items()}


def r1(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 1)


def to_wgs84():
    from pyproj import Transformer
    return Transformer.from_crs(2193, 4326, always_xy=True).transform


def export_boundaries(seats, tol=120.0):
    from shapely.geometry import mapping
    from shapely.ops import transform
    tf = to_wgs84()
    feats = []
    for name, g in seats:
        g2 = transform(tf, g.simplify(tol, preserve_topology=True))
        geom = mapping(g2)

        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 4), round(c[1], 4)]
        geom = {"type": geom["type"], "coordinates": rnd(geom["coordinates"])}
        feats.append({"type": "Feature", "properties": {"seat": name}, "geometry": geom})
    (SITE / "electorates.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False,
                   separators=(",", ":")), encoding="utf-8")


def export_localities(P, seats, locs, base):
    years = sorted(int(y) for y in P.year.unique())
    ed = P[P.type == "Election day"]
    L = NM.locality_leans(P, years)
    proj = {m: NM.project_lean(L, base + 3, m) for m in ("recent", "trend")}

    # Place every locality ever used (not just the latest year's) at its LINZ centroid.
    last = ed.sort_values("year").groupby("loc").tail(1)[["loc", "electorate", "year"]]
    votes = ed.groupby(["loc", "year"]).total_valid.sum()
    W = last.assign(w=[votes.get((l, y), 0) for l, y in zip(last["loc"], last["year"])])
    placed = PR.place_localities(W[["electorate", "loc", "w"]], seats, locs)
    tf = to_wgs84()

    names = (ed.sort_values("year").groupby("loc").tail(1).set_index("loc").suburb)
    booths = (ed.sort_values("year").groupby("loc")
              .apply(lambda d: sorted(d[d.year == d.year.max()].address.unique().tolist()),
                     include_groups=False))
    parties = NM.PARTIES
    out = []
    for _, r in placed.iterrows():
        loc = r["loc"]
        if not loc or pd.isna(r.x):
            continue
        g = L[L["loc"] == loc].sort_values("year")
        lon, lat = tf(r.x, r.y)
        out.append({
            "id": loc,
            "name": str(names.get(loc, loc)),
            "seat": r.seat,
            "approx": r.placed_by != "locality centroid",
            "lat": round(lat, 4), "lon": round(lon, 4),
            "years": g.year.astype(int).tolist(),
            "votes": g.total_valid.astype(int).tolist(),
            "lean": {CODE[p]: [r1(v) for v in g[f"lean_{p}"]] for p in parties},
            "share": {CODE[p]: [r1(100 * a / b) for a, b in zip(g[p], g.total_valid)] for p in parties},
            "recent": {CODE[p]: r1(proj["recent"].loc[loc, p]) for p in parties if loc in proj["recent"].index},
            "trend": {CODE[p]: r1(proj["trend"].loc[loc, p]) for p in parties if loc in proj["trend"].index},
            "booths": booths.get(loc, [])[:12],
        })
    meta = {"elections": years, "base_year": base,
            "national": {str(y): {CODE[p]: r1(v) for p, v in NM.national_share(y).items()} for y in years}}
    (SITE / "localities.json").write_text(
        json.dumps({"meta": meta, "localities": out}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")
    return len(out)


def export_projection(R, Sm, base, nat):
    seats = []
    for seat, g in R.groupby("seat"):
        row = {"seat": seat}
        for _, x in g.iterrows():
            m = x["method"]
            row[m] = {
                "party": {CODE[p]: r1(x[f"{p}_party"]) for p in NM.PARTIES},
                "candidate": {CODE[p]: r1(x[f"{p}_cand"]) for p in NM.PARTIES},
                "winner": CODE[x["winner"]], "margin": r1(x["margin_pp"]),
            }
        x = g.iloc[0]
        row["predecessor"] = x["predecessor"]
        row["predecessor_share"] = r1(100 * x["predecessor_share"])
        row["assumed"] = {CODE[p]: (None if pd.isna(x[f"assumed_{p}_candidate"]) else x[f"assumed_{p}_candidate"])
                          for p in ["National", "Labour", "Green", "ACT"]}
        seats.append(row)
    counts = {r["method"]: {CODE[p]: int(r[p]) for p in NM.PARTIES} for _, r in Sm.iterrows()}
    out = {"base_year": base, "scenario": {CODE[k]: r1(v) for k, v in nat.items()},
           "counts": counts, "seats": seats}
    (SITE / "electorates.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                                           encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default=str(ROOT / "build" / "polls" / "current_median.json"),
                    help="JSON of national party vote (%) by party code; default: poll-of-polls median")
    a = ap.parse_args(argv)
    SITE.mkdir(parents=True, exist_ok=True)

    if Path(a.scenario).exists():
        med = json.loads(Path(a.scenario).read_text())
        nat = {FROM_CODE[k]: float(v) for k, v in med.items() if k in FROM_CODE and k != "OTH"}
        print("Scenario from poll-of-polls:", nat)
    else:
        nat = {k: v for k, v in PR.NAT_2026.items() if k != "Other"}
        print("No poll-of-polls median found; using the 2026 campaign scenario.")

    P, C, CT = NM.load()
    seats, locs = PR.load_geo(ROOT / "data" / "booths" / "geo" / "nz_localities.zip")
    R, Sm, placed, base = PR.main(nat=nat, geo=(seats, locs))
    export_projection(R, Sm, base, {**nat, "Other": 100 - sum(nat.values())})
    n = export_localities(P, seats, locs, base)
    export_boundaries(seats)
    for f in ("localities.json", "electorates.json", "electorates.geojson"):
        print(f"  {f}: {(SITE / f).stat().st_size / 1e3:.0f} kB")
    print(f"Exported {n} localities, {len(R.seat.unique())} seats (base year {base}).")


if __name__ == "__main__":
    main()
