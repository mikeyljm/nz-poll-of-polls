"""
Voting-place partisan lean vs the national result, across NZ general elections.

For each Electoral Commission "party votes by voting place" CSV:
  1. detect which election it is (from the set of parties on the ballot),
  2. parse every voting-place row (advance + election-day), plus the special-vote rows,
  3. compute each party's share at that place and subtract the national share
     -> lean in percentage points (positive = place is more pro-party than NZ),
then, across elections, for each voting place:
  4. mean lean (simple average over the elections the place appears in),
  5. trend = OLS slope of lean on election year (pp per year, and pp per 3-yr cycle).

Usage:  python booth_lean.py data_dir out_dir
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# National party-vote results (% of valid party votes), official final results.
# Check / extend these if you add more elections or parties.
# ---------------------------------------------------------------------------
NATIONAL = {
    2002: {"Labour": 41.26, "National": 20.93, "NZ First": 10.38, "ACT": 7.14,
           "Green": 7.00, "United Future": 6.69, "Progressive": 1.70},
    2005: {"Labour": 41.10, "National": 39.10, "NZ First": 5.72, "Green": 5.30,
           "United Future": 2.67, "Māori": 2.12, "ACT": 1.51, "Progressive": 1.16},
    2008: {"National": 44.93, "Labour": 33.99, "Green": 6.72, "NZ First": 4.07,
           "ACT": 3.65, "Māori": 2.39, "Progressive": 0.91, "United Future": 0.87},
    2011: {"National": 47.31, "Labour": 27.48, "Green": 11.06, "NZ First": 6.59,
           "Conservative": 2.65, "Māori": 1.43, "Mana": 1.08, "ACT": 1.07},
    2014: {"National": 47.04, "Labour": 25.13, "Green": 10.70, "NZ First": 8.66,
           "Conservative": 3.97, "Internet MANA": 1.42, "Māori": 1.32, "ACT": 0.69},
    2017: {"National": 44.45, "Labour": 36.89, "NZ First": 7.20, "Green": 6.27,
           "TOP": 2.44, "Māori": 1.18, "ACT": 0.50},
    2020: {"Labour": 50.01, "National": 25.58, "Green": 7.86, "ACT": 7.59,
           "NZ First": 2.60, "TOP": 1.51, "New Conservative": 1.48, "Māori": 1.17,
           "Advance NZ": 0.97},
    2023: {"National": 38.06, "Labour": 26.91, "Green": 11.60, "ACT": 8.64,
           "NZ First": 6.08, "Māori": 3.08, "TOP": 2.22, "NZ Loyal": 1.20},
}

# Map raw party names in the files to short canonical names
PARTY_ALIASES = {
    "act new zealand": "ACT", "green party": "Green", "labour party": "Labour",
    "national party": "National", "new zealand first party": "NZ First",
    "māori party": "Māori", "te pāti māori": "Māori",
    "the opportunities party (top)": "TOP", "conservative": "Conservative",
    "conservative party": "Conservative", "internet mana": "Internet MANA",
    "mana": "Mana", "new conservative": "New Conservative",
    "advance nz": "Advance NZ", "new zealand loyal": "NZ Loyal",
    # older spellings (2002-2008 files)
    "act": "ACT", "nz first": "NZ First", "maori party": "Māori", "te pati maori": "Māori",
    "united future": "United Future", "united future new zealand": "United Future",
    "jim anderton's progressive": "Progressive", "progressive coalition": "Progressive",
}

# Blocs (sum of party leans)
BLOCS = {
    "Left (Lab+Grn+Māori+Mana/IM)": ["Labour", "Green", "Māori", "Mana", "Internet MANA"],
    "Right (Nat+ACT)": ["National", "ACT"],
}

# Parties whose presence identifies the election year
YEAR_MARKERS = [
    (2023, "new zealand loyal"), (2020, "advance nz"), (2017, "new zealand people's party"),
    (2014, "internet mana"), (2011, "mana"), (2008, "kiwi party"),
    (2005, "destiny new zealand"), (2002, "christian heritage"),
]

# Hand-made aliases for venues that were renamed between elections
VENUE_ALIASES = {
    "methodist church wesley hall": "pitt street methodist church",
    "methodist church hall": "pitt street methodist church",
    "level 3 atrium on elliot": "atrium on elliot",
    "auckland university students association": "ausa club space",
    "auckland university ausa club space": "ausa club space",
    "auckland university of technology": "aut wellesley campus",
    "aut university": "aut wellesley campus",
    "liston hall": "liston house",
    "kowhai intermediate school": "kōwhai intermediate school",
    "freemans bay community centre auditorium": "freemans bay community centre",
    "grey lynn community centre oval room": "grey lynn community centre",
    "grey lynn community centre main hall": "grey lynn community centre",
    "congregational christian church of samoa": "efks kingsland congregational christian church of samoa",
    "jubilee hall": "parnell community centre",
    "parnell community centre jubilee hall": "parnell community centre",
    "parnell community centre jubilee room": "parnell community centre",
    "parnell community centre parnell room": "parnell community centre",
    "parnell district school": "parnell district school hall",
    "matiatia oneroa ratepayers morra hall": "morra hall",
    "omiha memorial hall": "ōmiha memorial hall",
    "rocky bay hall": "ōmiha memorial hall",          # same building, 2 Glen Brook Rd
    "onetangi community hall": "onetangi residents association hall",
    "tryphena mulberry grove school": "mulberry grove school",
    "auckland city hospital foyer": "auckland city hospital",
    "aotea health nurses cottage": "aotea health fitzroy nurses cottage",
    "port fitzroy aotea centre nurses cottage": "aotea health fitzroy nurses cottage",
    "auckland grammar school hockey centre": "auckland grammar school",
    "auckland grammar school old boys centre": "auckland grammar school",
    "newmarket mall": "westfield newmarket",
    "baptist church hall": "church@onetwosix hall",
    "st mary's college stella maris old school hall": "st mary's college",
    "st paul's college library": "st paul's college",
    "baptist church hall": "church@onetwosix hall",
    "st stephen's presbyterian church hall": "st stephen's presbyterian church",
    "pioneer women's hall": "ellen melville centre",
    "aotea community art gallery": "aotea community art gallery (80 hector sanderson rd)",
    "aotea community art gallery schoolmaster's house": "aotea community art gallery (80 hector sanderson rd)",
    "great barrier island community health centre": "aotea community art gallery (80 hector sanderson rd)",
    "aotea health": "aotea health fitzroy nurses cottage",
    "holy trinity cathedral visitors centre": "holy trinity cathedral",
    "st mark's church hall": "st mark's church",
    "auckland university of technology north campus": "aut north campus",
    "westfield mall": "westfield albany",
    "atrium": "atrium takutai square",
    "point chevalier baptist church hall": "church@onetwosix hall",
    # ---- Ōtaki ----
    "ihakara public hall": "ihakara hall",
    "foxton beach school": "foxton beach primary school",
    "lifechangers church hall": "levin city church hall",
    "levin intermediate": "levin intermediate school",
    "manakau district association hall": "manakau district hall",
    "the meadows church": "connect church",
    "connect church formerly meadows church": "connect church",
    "kapiti senior citizens centre": "ocean road community centre",   # both 45 Ocean Rd
    "raumati school": "raumati beach school",
    "real life hall": "real life church hall",
    "te horo community hall": "te horo hall",                          # 50/54 School Rd
    # small localities where the only booth moved venue: treat as one series
    "te horo school": "te horo hall", "te horo primary school": "te horo hall",
    "poroutawhao school": "poroutawhao hall", "poroutawhao school sh 1": "poroutawhao hall",
    "opiki school": "opiki public hall",
    "st aidan's anglican church": "waitarere scout hall",
    "otaki health camp": "otaki surf lifesaving club",
    "kapiti uniting parish": "waikanae beach community hall",
    "kapakapanui school": "kapanui school",                            # renamed, 23 Rimu St
    "waikanae school": "waikanae primary school",
    "te takere": "te takeretanga o kura hau po levin public library",
    "whakarongotai marae": "waikanae marae",                           # both 2 Marae Lane
    "te wananga o raukawa": "nga purapura te wananga o raukawa",
    "victoria university hub": "victoria university",
    # ---- Mana ----
    "st peter's church hall": "st peter's village hall",
    "st peter's hall": "st peter's village hall",
    "st peters village hall": "st peter's village hall",
    "st barnabas' church": "st barnabas church hall",
    "karehana bay": "st paul's presbyterian church",
    "pauatahanui hall": "pauatahanui school",
    "stout cottage": "pauatahanui school",
    "the bradey room": "civic centre",
    "the anchor": "the anchor church",
    "raumati south returned services war memorial hall": "raumati south memorial hall",
    "kenepuru general hospital": "kenepuru hospital",
    "st mary's anglican church": "st mary's church",
}

# Rows known to be column-shifted in the source file (row sums still match, so they
# can't be caught automatically). (electorate, year, substring of label)
BAD_ROWS = [("auckland central", 2011, "votes allowed for party only")]

# Venue names in old (2002) files that omit the suburb ("School, Gray Avenue"):
# these get the suburb prefixed so they're unique and match later names.
GENERIC_VENUES = {"school", "primary school", "intermediate", "east school", "north school",
                  "baptist church", "city church", "district association", "public",
                  "boating club", "guide", "community", "college", "surf lifesaving club",
                  "presbyterian church", "school sh 1", "hall", "memorial", "intermediate school"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower().strip()
    s = s.replace("’", "'").replace("‘", "'").replace("-", " ")
    s = re.sub(r"[(),.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def deaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def canon(s: str) -> str:
    """norm + strip macrons + drop a trailing 'hall' (used inconsistently between years)."""
    k = deaccent(norm(s)).replace("'", "")
    return re.sub(r"\s+hall$", "", k)


ALIASES = {canon(k): canon(v) for k, v in VENUE_ALIASES.items()}


def venue_key(suburb: str, address: str) -> str:
    """Stable key for a voting place: the venue name (first part of the address)."""
    parts = address.split(",")
    k = canon(parts[0])
    if k in GENERIC_VENUES and suburb:
        k = canon(suburb + " " + parts[0])
    k = ALIASES.get(k, k)
    # second chance: first two comma parts joined (e.g. "Methodist Church, Wesley Hall")
    two = canon(" ".join(parts[:2]))
    if two in ALIASES:
        k = ALIASES[two]
    return k


def special_key(label: str, electorate: str) -> str:
    k = deaccent(norm(label))
    k = re.sub(r"\s*" + re.escape(electorate) + r"$", "", k).strip()
    if re.search(r"hospital|rest home|care home", k):
        return "hospital & rest home votes"
    if k.startswith("ordinary votes before polling day"):
        return "ordinary votes before polling day (pre-advance-booth era)"
    if k.startswith("overseas special votes including"):
        return "overseas special votes incl defence force"
    if k.startswith("special votes before"):
        return "special votes before polling day"
    if k.startswith("special votes on"):
        return "special votes on polling day"
    if "party only" in k and "overseas" not in k:
        return "votes allowed for party only"
    return k


def to_int(x):
    x = x.strip().replace(",", "")
    return int(x) if re.fullmatch(r"-?\d+", x) else None


def parse_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:          # pre-2011 files are Windows-1252
        text = path.read_text(encoding="cp1252")
    rows = list(csv.reader(text.splitlines()))
    electorate = deaccent(norm(re.sub(r"\s*\d+$", "", rows[1][0])))
    header = rows[2]
    parties = [h.strip() for h in header[2:] if h.strip()]
    lower = {deaccent(p.lower()) for p in parties}
    year = next((y for y, m in YEAR_MARKERS if m in lower), None)
    if year is None:
        raise ValueError(f"Can't identify election in {path.name}")
    i_total = parties.index("Total Valid Party Votes")
    party_cols = parties[:i_total]

    records, skipped = [], []
    section, suburb = "Election day", ""
    for r in rows[3:]:
        if not r or not any(c.strip() for c in r):
            continue
        first = r[0].strip()
        if first in ("Advance Voting Places",):
            section = "Advance"; continue
        if first in ("Voting Places",):
            section = "Election day"; continue
        if "Total" in "".join(r[:2]) or first.startswith("Electorate Party"):
            break
        if len(r) < 2 + len(party_cols) + 1:
            continue
        label = r[1].strip()
        nums = [to_int(c) for c in r[2:2 + len(party_cols) + 2]]
        votes = nums[:len(party_cols)]
        if any(v is None for v in votes):
            continue
        stated_total = nums[len(party_cols)]
        if stated_total is not None and sum(votes) != stated_total:
            skipped.append((year, label, "row sum != stated total (misaligned row in source)"))
            continue
        if any(e == electorate and y == year and b in label.lower() for e, y, b in BAD_ROWS):
            skipped.append((year, label, "column-shifted in source (e.g. Social Credit = 193); excluded"))
            continue
        if first:
            suburb = first
        is_place = (first != "" or section == "Advance" or "," in label or suburb) and not re.search(
            r"special votes|party only|ordinary votes|less than 6|hospital|rest homes|"
            r"care homes|mobile & advance|mobile team|pop.?up voting services", label, re.I)
        if is_place:
            kind = section
            key = venue_key(suburb, label)
        else:
            kind = "Special / other"
            key = special_key(label, electorate)
            if "less than 6" in label.lower():
                continue
        rec = {"year": year, "type": kind, "place_key": key, "suburb": suburb if is_place else "",
               "address": label, "total_valid": sum(votes)}
        for p, v in zip(party_cols, votes):
            cp = PARTY_ALIASES.get(deaccent(p.lower()))
            if cp:
                rec[cp] = rec.get(cp, 0) + v
        records.append(rec)
    return year, records, skipped


def main(data_dir, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    all_recs, all_skipped = [], []
    for f in sorted(Path(data_dir).glob("*.csv")):
        year, recs, skipped = parse_file(f)
        print(f"{f.name}: {year}, {len(recs)} rows")
        all_recs += recs; all_skipped += skipped
    df = pd.DataFrame(all_recs)

    # Same venue can appear more than once within one year & type (e.g. two booths
    # in one building, or Great Barrier mislabelled suburbs) -> sum votes.
    parties = [c for c in df.columns if c not in
               ("year", "type", "place_key", "suburb", "address", "total_valid")]
    df[parties] = df[parties].fillna(0)
    agg = (df.groupby(["year", "type", "place_key"])
             .agg(suburb=("suburb", "first"), address=("address", "first"),
                  total_valid=("total_valid", "sum"), **{p: (p, "sum") for p in parties})
             .reset_index())

    # ---- 1. lean per place per election (long) ----
    long_rows = []
    for _, r in agg.iterrows():
        nat = NATIONAL[r.year]
        for p in parties:
            if p not in nat:
                continue
            share = 100 * r[p] / r.total_valid if r.total_valid else np.nan
            long_rows.append({"year": r.year, "type": r.type, "place_key": r.place_key,
                              "suburb": r.suburb, "address": r.address,
                              "total_valid": r.total_valid, "party": p,
                              "votes": int(r[p]), "place_share_pct": share,
                              "national_share_pct": nat[p], "lean_pp": share - nat[p]})
    lean = pd.DataFrame(long_rows)
    # blocs
    bl = []
    for bname, members in BLOCS.items():
        sub = lean[lean.party.isin(members)]
        g = sub.groupby(["year", "type", "place_key", "suburb", "address", "total_valid"],
                        as_index=False)[["votes", "place_share_pct", "national_share_pct", "lean_pp"]].sum()
        g["party"] = bname
        bl.append(g)
    lean = pd.concat([lean] + bl, ignore_index=True)
    lean = lean.sort_values(["type", "place_key", "party", "year"])
    lean.round(3).to_csv(out / "lean_by_place_and_election.csv", index=False)

    # wide version: one row per place × party, one column per year
    wide = lean.pivot_table(index=["type", "place_key", "party"], columns="year",
                            values="lean_pp").round(2)
    wide.columns = [f"lean_{c}" for c in wide.columns]
    wide.reset_index().to_csv(out / "lean_wide.csv", index=False)

    # ---- 2 & 3. average and trend per place ----
    summ = []
    for (typ, key, party), g in lean.groupby(["type", "place_key", "party"]):
        g = g.dropna(subset=["lean_pp"]).sort_values("year")
        n = len(g)
        yrs, l, w = g.year.values.astype(float), g.lean_pp.values, g.total_valid.values
        row = {"type": typ, "place_key": key, "party": party, "n_elections": n,
               "years": ";".join(str(int(y)) for y in yrs),
               "mean_lean_pp": l.mean(),
               "vote_weighted_mean_lean_pp": np.average(l, weights=w),
               "sd_lean_pp": l.std(ddof=1) if n > 1 else np.nan,
               "first_lean_pp": l[0], "last_lean_pp": l[-1],
               "mean_valid_votes": w.mean()}
        if n >= 2:
            slope, intercept = np.polyfit(yrs, l, 1)
            row["trend_pp_per_year"] = slope
            row["trend_pp_per_3yr_cycle"] = slope * 3
            if n >= 3:
                pred = intercept + slope * yrs
                ss_res = ((l - pred) ** 2).sum(); ss_tot = ((l - l.mean()) ** 2).sum()
                row["trend_r2"] = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
                se = np.sqrt(ss_res / (n - 2) / ((yrs - yrs.mean()) ** 2).sum())
                row["trend_se_pp_per_year"] = se
        summ.append(row)
    summ = pd.DataFrame(summ).sort_values(["party", "type", "mean_lean_pp"],
                                           ascending=[True, True, False])
    cols = ["type", "place_key", "party", "n_elections", "years", "mean_lean_pp",
            "vote_weighted_mean_lean_pp", "sd_lean_pp", "trend_pp_per_year",
            "trend_pp_per_3yr_cycle", "trend_se_pp_per_year", "trend_r2",
            "first_lean_pp", "last_lean_pp", "mean_valid_votes"]
    summ[cols].round(3).to_csv(out / "lean_summary_mean_and_trend.csv", index=False)

    # Electorate-wide check row
    elec = (agg.groupby("year")[parties + ["total_valid"]].sum())
    chk = pd.DataFrame({p: 100 * elec[p] / elec.total_valid - pd.Series(
        {y: NATIONAL[y].get(p, np.nan) for y in elec.index}) for p in parties
        if any(p in NATIONAL[y] for y in elec.index)}).round(2)
    chk.index.name = "year"
    chk.to_csv(out / "electorate_total_lean_check.csv")

    pd.DataFrame([{"party": p, **{str(y): NATIONAL[y].get(p) for y in NATIONAL}}
                  for p in sorted({p for d in NATIONAL.values() for p in d})]
                 ).to_csv(out / "national_results_used.csv", index=False)

    if all_skipped:
        pd.DataFrame(all_skipped, columns=["year", "row", "reason"]).to_csv(
            out / "skipped_rows.csv", index=False)
    print(f"\n{agg.place_key.nunique()} distinct places; outputs in {out}")
    print("\nElectorate-wide lean (pp) by year:\n", chk)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data",
         sys.argv[2] if len(sys.argv) > 2 else "output")
