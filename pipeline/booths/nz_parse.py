"""
Parse every general-electorate party-vote and candidate-vote file (one folder per election)
into two nationwide booth-level tables.

  booth_party.csv : year, electorate, type, key, suburb, address, total_valid, <party votes...>
  booth_cand.csv  : year, electorate, type, key, cand_total, <party>|cand votes ...
  candidates.csv  : year, electorate, candidate, party (canonical where known), votes

Booth key = canonical suburb + "|" + canonical venue (so "St Mary's Church" in two towns
stays two booths). Special-vote rows are keyed per electorate.

Usage: python nz_parse.py <dir containing one folder per election zip> <out_dir>
"""
import csv
import re
import sys
from pathlib import Path

import pandas as pd

from booth_lean import (BAD_ROWS, PARTY_ALIASES, YEAR_MARKERS, canon, deaccent, norm,
                        special_key, to_int, venue_key)

SPECIAL_RE = re.compile(r"special votes|party only|ordinary votes|hospital|rest homes|care homes|"
                        r"mobile & advance|mobile team|pop.?up voting services|prisons team|"
                        r"less than 6", re.I)


def read_rows(path):
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252")
    return list(csv.reader(text.splitlines()))


def canon_party(p):
    return PARTY_ALIASES.get(deaccent(p.strip().lower()))


def iter_rows(rows, ncols, stop_prefix):
    """Yield (type, suburb, label, numbers) for each data row."""
    section, suburb = "Election day", ""
    for r in rows[3:]:
        if not r or not any(c.strip() for c in r):
            continue
        first = r[0].strip()
        if first == "Advance Voting Places":
            section = "Advance"; continue
        if first in ("Voting Places",):
            section = "Election day"; continue
        if first.startswith(stop_prefix) or "Total" in "".join(r[:2]):
            break
        if len(r) < 2 + ncols:
            continue
        label = r[1].strip()
        nums = [to_int(c) for c in r[2:2 + ncols + 1]]
        if any(v is None for v in nums[:ncols]):
            continue
        if first:
            suburb = first
        yield section, suburb, label, nums


def booth_key(electorate, section, suburb, label):
    if SPECIAL_RE.search(label) or (not suburb and section == "Election day"):
        return "Special / other", f"{electorate}|{special_key(label, electorate)}"
    return section, f"{canon(suburb)}|{venue_key(suburb, label)}"


def electorate_of(rows):
    return deaccent(norm(re.sub(r"\s*\d+$", "", rows[1][0])))


def parse_party(path):
    rows = read_rows(path)
    elec = electorate_of(rows)
    header = [h.strip() for h in rows[2][2:] if h.strip()]
    lower = {deaccent(p.lower()) for p in header}
    year = next((y for y, m in YEAR_MARKERS if m in lower), None)
    parties = header[:header.index("Total Valid Party Votes")]
    out, bad = [], 0
    for section, suburb, label, nums in iter_rows(rows, len(parties), "Electorate Party"):
        votes = nums[:len(parties)]
        if nums[len(parties)] is not None and sum(votes) != nums[len(parties)]:
            bad += 1; continue
        if "less than 6" in label.lower():
            continue
        if any(e == elec and y == year and b in label.lower() for e, y, b in BAD_ROWS):
            bad += 1; continue
        t, key = booth_key(elec, section, suburb, label)
        rec = {"year": year, "electorate": elec, "type": t, "key": key,
               "suburb": suburb if t != "Special / other" else "", "address": label,
               "total_valid": sum(votes)}
        for p, v in zip(parties, votes):
            cp = canon_party(p) or "Other"
            rec[cp] = rec.get(cp, 0) + v
        out.append(rec)
    return year, elec, out, bad


def parse_cand(path, year):
    rows = read_rows(path)
    elec = electorate_of(rows)
    header = [h.strip() for h in rows[2][2:] if h.strip()]
    cands = header[:header.index("Total Valid Candidate Votes")]
    i_foot = next(i for i, r in enumerate(rows) if r and r[0].startswith("Electorate Candidate Valid"))
    cparty = {r[0].strip(): r[1].strip() for r in rows[i_foot + 1:] if len(r) >= 2 and r[0].strip()}
    out = []
    for section, suburb, label, nums in iter_rows(rows[:i_foot], len(cands), "Electorate Candidate"):
        if "less than 6" in label.lower():
            continue
        votes = nums[:len(cands)]
        t, key = booth_key(elec, section, suburb, label)
        rec = {"year": year, "electorate": elec, "type": t, "key": key, "cand_total": sum(votes)}
        for c, v in zip(cands, votes):
            cp = canon_party(cparty.get(c, "")) or "Other"
            rec[f"{cp}|cand"] = rec.get(f"{cp}|cand", 0) + v
        out.append(rec)
    ctab = []
    totals = {c: 0 for c in cands}
    for r in out:
        pass
    for section, suburb, label, nums in iter_rows(rows[:i_foot], len(cands), "Electorate Candidate"):
        for c, v in zip(cands, nums[:len(cands)]):
            totals[c] += v
    for c in cands:
        ctab.append({"year": year, "electorate": elec, "candidate": c,
                     "party_raw": cparty.get(c, ""), "party": canon_party(cparty.get(c, "")) or "Other",
                     "votes": totals[c]})
    return out, ctab


def main(root, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    P, C, CT, report = [], [], [], []
    for d in sorted(Path(root).glob("z_*")):
        base = d / "General electorates"
        # The folder name (z_2026) sets the year. The parties on the ballot are only a check,
        # since a party can stand in more than one election (e.g. NZ Loyal).
        fy = int(re.search(r"(\d{4})", d.name).group(1))
        party_files = sorted((base / "Party votes").glob("*.csv"))
        for f in party_files:
            y, e, recs, bad = parse_party(f)
            if y is not None and y != fy:
                print(f"  note: {f.name} looks like {y} from its party list; using folder year {fy}")
            for r in recs:
                r["year"] = fy
            P += recs
            if bad:
                report.append((fy, e, f"{bad} party rows skipped (row sum != total)"))
        year = fy
        for f in sorted((base / "Candidate votes").glob("*.csv")):
            recs, ct = parse_cand(f, year)
            C += recs; CT += ct
        print(f"{d.name}: {year}, {len(party_files)} electorates")
    P = pd.DataFrame(P).fillna(0)
    C = pd.DataFrame(C).fillna(0)
    P.to_csv(out / "booth_party.csv", index=False)
    C.to_csv(out / "booth_cand.csv", index=False)
    pd.DataFrame(CT).to_csv(out / "candidates.csv", index=False)
    pd.DataFrame(report, columns=["year", "electorate", "note"]).to_csv(out / "parse_report.csv", index=False)
    print(P.groupby("year").agg(rows=("key", "size"), votes=("total_valid", "sum")))
    print(report)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
