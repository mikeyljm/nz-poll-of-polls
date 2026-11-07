"""
Load NZ party-vote polls and election results into one tidy table.

Sources
-------
* data/nzpolls_data.yml : the NZPolls dataset (github.com/Nixinova/NZPolls),
  scraped from Wikipedia. Covers 2011 to mid-August 2026, plus official
  election results.
* data/recent_polls.csv, added_polls.csv : hand-entered 2026-cycle polls and
  gaps in the YAML.
* data/scraped_polls.csv : polls since the 2026 election, scraped daily from
  Wikipedia by pipeline/scrape_polls.py.
* data/manual_polls.csv : anything the scraper misses. Add rows here by hand;
  a manual row replaces a scraped row with the same pollster and end date.
* data/elections.csv : official election results (the anchors). Election
  rows in the YAML are ignored in favour of this file.

Output: a wide DataFrame, one row per poll or election, with columns
    date_start, date_end, date_mid, org, n, is_election, <party shares 0-1>
Missing party values are NaN (the model masks them).
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import yaml

import config as cfg


# The YAML stores unknown days as "00" (e.g. 2026-04-00), which PyYAML's
# timestamp parser rejects, so load dates as plain strings.
class _NoDateLoader(yaml.SafeLoader):
    pass


_NoDateLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _parse_date(s: str, fallback: dt.date | None = None) -> dt.date | None:
    """Parse YYYY-MM-DD, treating day 00 as unknown."""
    y, m, d = (int(x) for x in str(s).split("-"))
    if d == 0:
        return fallback
    try:
        return dt.date(y, m, d)
    except ValueError:  # source typos such as 2015-09-31
        return fallback


def load_yaml_polls(path=cfg.DATA_DIR / "nzpolls_data.yml") -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f, Loader=_NoDateLoader)

    model_parties = [p for p in cfg.PARTIES if p != "OTH"]
    rows = []
    for _cycle, entries in raw.items():
        for i, e in enumerate(entries):
            dates = e["date"]
            is_election = i == 0
            if is_election:
                continue  # elections come from data/elections.csv
            end = _parse_date(dates[-1])
            if end is None:  # both days unknown: skip
                continue
            start = _parse_date(dates[0], fallback=end - dt.timedelta(days=7))
            row = {
                "date_start": start, "date_end": end,
                "org": "ELECTION" if is_election else e.get("org"),
                "n": e.get("n"), "is_election": is_election,
                "source": "NZPolls YAML",
            }
            for k, v in e.items():
                code = cfg.YAML_PARTY_MAP.get(k, k)
                if code in model_parties:
                    row[code] = v
            rows.append(row)
    return pd.DataFrame(rows)


def load_recent_polls(paths=(cfg.DATA_DIR / "recent_polls.csv",
                             cfg.DATA_DIR / "added_polls.csv")) -> pd.DataFrame:
    """Hand-entered polls: recent ones, plus gaps filled in the YAML."""
    frames = [pd.read_csv(p, comment="#") for p in paths if p.exists()]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date_start"] = pd.to_datetime(df["date_start"]).dt.date
    df["date_end"] = pd.to_datetime(df["date_end"]).dt.date
    df["is_election"] = False
    return df


def load_current_cycle() -> pd.DataFrame:
    """Scraped polls since the last election, with manual rows taking priority."""
    scraped = load_recent_polls((cfg.DATA_DIR / "scraped_polls.csv",))
    manual = load_recent_polls((cfg.DATA_DIR / "manual_polls.csv",))
    if len(scraped) and len(manual):
        key = set(zip(manual["org"], manual["date_end"]))
        scraped = scraped[[k not in key for k in zip(scraped["org"], scraped["date_end"])]]
    df = pd.concat([x for x in (scraped, manual) if len(x)], ignore_index=True) \
        if len(scraped) or len(manual) else pd.DataFrame()
    if len(df):
        # Only polls after the 2026 election come from here; earlier ones are in
        # the YAML and recent_polls.csv.
        df = df[pd.to_datetime(df["date_end"]) > pd.Timestamp("2026-11-07")]
    return df


def load_elections() -> pd.DataFrame:
    e = cfg.load_elections()
    e["date_start"] = pd.to_datetime(e["date"]).dt.date
    e["date_end"] = e["date_start"]
    e["org"] = "ELECTION"
    e["is_election"] = True
    e["source"] = "elections.csv (" + e["status"] + ")"
    return e.drop(columns=["date", "status", "note"], errors="ignore")


def load_all(start=cfg.START_DATE, verbose=True) -> pd.DataFrame:
    df = pd.concat([load_yaml_polls(), load_recent_polls(), load_current_cycle(),
                    load_elections()], ignore_index=True)
    df["is_election"] = df["is_election"].astype(bool)
    parties = [p for p in cfg.PARTIES if p != "OTH"]

    for p in parties:
        df[p] = pd.to_numeric(df[p], errors="coerce") / 100.0

    # "Other" = remainder, only when every modelled party was reported
    df["OTH"] = 1.0 - df[parties].sum(axis=1, skipna=False)
    df["OTH"] = df["OTH"].clip(lower=0.002)  # rounding can push it negative

    df["n"] = pd.to_numeric(df["n"], errors="coerce")
    df["n_imputed"] = df["n"].isna() & ~df["is_election"]
    df.loc[df["n_imputed"], "n"] = cfg.DEFAULT_SAMPLE_SIZE

    df["date_start"] = pd.to_datetime(df["date_start"])
    df["date_end"] = pd.to_datetime(df["date_end"])
    df["date_mid"] = df["date_start"] + (df["date_end"] - df["date_start"]) / 2

    # Polls report to whole numbers or to 0.1/0.5. Flag integer-rounded polls
    # so the model can add rounding error.
    vals = df[parties].to_numpy() * 100
    df["integer_rounded"] = np.nanmax(np.abs(vals - np.round(vals)), axis=1) < 1e-9

    before = len(df)
    df = df.drop_duplicates(subset=["org", "date_start", "date_end"] + parties)
    df = df[df["date_end"] >= pd.Timestamp(start)]
    df = df.sort_values("date_mid").reset_index(drop=True)

    if verbose:
        print(f"Loaded {len(df)} polls/elections from {start} "
              f"({before - len(df)} dropped as duplicates or before start).")
        print(df.groupby("org").size().sort_values(ascending=False).to_string())
    return df


# %% Quick look (run this cell in Spyder)
if __name__ == "__main__":
    polls = load_all()
    print(polls.tail(12)[["date_end", "org", "n"] + cfg.PARTIES].round(3))
