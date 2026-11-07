"""
Scrape New Zealand party-vote opinion polls from Wikipedia.

Reads the "Opinion polling for the 2029 New Zealand general election" page
(or its interim name) through the MediaWiki API, keeps only the nationwide
party-vote tables, and writes data/polls/scraped_polls.csv in the same format
as the hand-entered poll files:

    date_start,date_end,org,n,NAT,LAB,GRN,ACT,NZF,TPM,OPP,source

Usage
-----
    python pipeline/scrape_polls.py                 # scrape the current cycle
    python pipeline/scrape_polls.py --page "Opinion polling for the 2026 New Zealand general election" --out /tmp/check.csv
    python pipeline/scrape_polls.py --html saved_page.html   # parse a saved page (tests)

Exit code 0 even if the page doesn't exist yet (no polls is a valid state).
If running under GitHub Actions, writes new_polls=<n> to $GITHUB_OUTPUT.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "polls" / "scraped_polls.csv"

PAGES = [
    "Opinion polling for the 2029 New Zealand general election",
    "Opinion polling for the next New Zealand general election",
]
API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "nz-poll-of-polls/1.0 (automated daily poll aggregation; https://github.com)"

PARTY_COLS = ["NAT", "LAB", "GRN", "ACT", "NZF", "TPM", "OPP"]
# Header text on Wikipedia -> our code (headers are usually already abbreviations)
HEADER_MAP = {
    "NAT": "NAT", "NATIONAL": "NAT", "LAB": "LAB", "LABOUR": "LAB",
    "GRN": "GRN", "GREEN": "GRN", "GREENS": "GRN", "ACT": "ACT",
    "NZF": "NZF", "NZ FIRST": "NZF", "NEW ZEALAND FIRST": "NZF",
    "TPM": "TPM", "MRI": "TPM", "TE PĀTI MĀORI": "TPM", "MĀORI": "TPM",
    "OPP": "OPP", "TOP": "OPP", "OPPORTUNITY": "OPP",
}
# Pollster name patterns -> codes used in the model (order matters)
ORG_PATTERNS = [
    (r"1 ?news|verian|colmar|kantar", "COL"),
    (r"curia", "CUR"),
    (r"reid", "REI"),
    (r"roy morgan", "ROY"),
    (r"talbot", "TBM"),
    (r"anacta", "ANA"),
    (r"freshwater", "FWS"),
    (r"guardian essential", "GUA"),
    (r"essential", "ESS"),
    (r"horizon", "HOR"),
    (r"ipsos", "IPS"),
    (r"yougov", "YGV"),
]
# Only tables in the top-level "Party vote" section are nationwide party-vote polls.
# The page also has electorate, subnational (e.g. Auckland), demographic (men, women,
# Māori roll, Pacific voters, age groups) and leadership tables with the same columns.
KEEP_H2 = re.compile(r"party vote|nationwide|national poll", re.I)
# Within that section, sub-headings that still mark a subset of voters
SKIP_HEADINGS = re.compile(
    r"electorate|preferred|prime minister|favourab|direction|seat|leader|projection|"
    r"hypothetical|referend|issue|coalition|approval|region|subnational|demographic|"
    r"male|female|women|men\b|roll|voters|age group|pacific|māori|maori|auckland|"
    r"christchurch|wellington", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------
def fetch_page(titles=PAGES) -> tuple[str | None, str | None]:
    """Return (title, html) of the first page that exists, else (None, None)."""
    import requests
    for t in titles:
        r = requests.get(API, params={
            "action": "parse", "page": t, "prop": "text", "redirects": 1,
            "format": "json", "formatversion": 2,
        }, headers={"User-Agent": USER_AGENT}, timeout=60)
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            if j["error"].get("code") == "missingtitle":
                continue
            raise RuntimeError(j["error"])
        return j["parse"]["title"], j["parse"]["text"]
    return None, None


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def clean(s) -> str:
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    s = re.sub(r"\[[^\]]*\]", "", s)            # footnote markers [a] [12]
    return s.replace("\xa0", " ").strip()


def num(s) -> float | None:
    s = clean(s).replace(",", "")
    s = s.replace("−", "-")
    if s in ("", "-", "–", "—", "N/A", "n/a"):
        return None
    m = re.fullmatch(r"<\s*([\d.]+)", s)        # "<0.5" -> half the bound
    if m:
        return float(m.group(1)) / 2
    m = re.fullmatch(r"-?[\d.]+%?", s)
    return float(s.rstrip("%")) if m else None


def _date(d, mon, y) -> dt.date:
    return dt.date(int(y), MONTHS[mon[:3].lower()], int(d))


def parse_dates(s: str) -> tuple[dt.date | None, dt.date | None]:
    """'1–3 Sep 2026', '27 Jul – 23 Aug 2026', '28 Dec 2026 – 4 Jan 2027',
    '12 Aug 2026', 'Nov 2026' (month only: whole month)."""
    s = clean(s).replace("—", "–").replace("-", "–")
    s = re.sub(r"\s*–\s*", "–", s)
    M = r"([A-Za-z]{3,9})"
    pats = [
        (rf"^(\d{{1,2}}) {M} (\d{{4}})–(\d{{1,2}}) {M} (\d{{4}})$",
         lambda g: (_date(g[0], g[1], g[2]), _date(g[3], g[4], g[5]))),
        (rf"^(\d{{1,2}}) {M}–(\d{{1,2}}) {M} (\d{{4}})$",
         lambda g: (_date(g[0], g[1], g[4]), _date(g[2], g[3], g[4]))),
        (rf"^(\d{{1,2}})–(\d{{1,2}}) {M} (\d{{4}})$",
         lambda g: (_date(g[0], g[2], g[3]), _date(g[1], g[2], g[3]))),
        (rf"^(\d{{1,2}}) {M} (\d{{4}})$",
         lambda g: (_date(g[0], g[1], g[2]),) * 2),
        (rf"^{M} (\d{{4}})$",
         lambda g: (_date(1, g[0], g[1]),
                    (pd.Timestamp(_date(1, g[0], g[1])) + pd.offsets.MonthEnd(0)).date())),
        (rf"^{M}–{M} (\d{{4}})$",
         lambda g: (_date(1, g[0], g[2]),
                    (pd.Timestamp(_date(1, g[1], g[2])) + pd.offsets.MonthEnd(0)).date())),
    ]
    for rx, f in pats:
        m = re.match(rx, s)
        if m:
            try:
                return f(m.groups())
            except (KeyError, ValueError):
                return None, None
    return None, None


def org_code(name: str) -> str:
    n = clean(name).lower()
    for rx, code in ORG_PATTERNS:
        if re.search(rx, n):
            return code
    code = re.sub(r"[^A-Za-z]", "", clean(name)).upper()[:3] or "UNK"
    print(f"  ! unknown pollster '{clean(name)}' -> {code} (add it to ORG_PATTERNS)")
    return code


def _flat_header(col) -> str:
    """Pick the most informative level of a (possibly multi-level) header."""
    levels = [clean(c) for c in (col if isinstance(col, tuple) else (col,))]
    for lv in reversed(levels):
        if lv.upper() in HEADER_MAP or re.search(r"date|poll|sample|lead|other", lv, re.I):
            return lv
    return levels[-1]


def party_tables(html: str) -> list[pd.DataFrame]:
    """Nationwide party-vote tables, in page order, skipping other sections."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    path, out = {}, []          # heading level -> text, e.g. {2: "Electorate polling", 3: "Tāmaki"}
    for el in soup.find_all(["h2", "h3", "h4", "table"]):
        if el.name != "table":
            lvl = int(el.name[1])
            path = {k: v for k, v in path.items() if k < lvl}
            path[lvl] = el.get_text(" ", strip=True)
            continue
        if "wikitable" not in (el.get("class") or []):
            continue
        if not KEEP_H2.search(path.get(2, "")):
            continue
        if any(SKIP_HEADINGS.search(h) for lvl, h in path.items() if lvl > 2):
            continue
        try:
            df = pd.read_html(io.StringIO(str(el)))[0]
        except ValueError:
            continue
        df.columns = [_flat_header(c) for c in df.columns]
        cols = {c.upper() for c in df.columns}
        has_parties = sum(c in HEADER_MAP for c in cols) >= 4
        has_meta = any(re.search(r"poll", c, re.I) for c in df.columns) and \
            any(re.search(r"date", c, re.I) for c in df.columns)
        if has_parties and has_meta:
            out.append(df)
    return out


def table_to_polls(df: pd.DataFrame, source: str) -> pd.DataFrame:
    col = lambda rx: next((c for c in df.columns if re.search(rx, c, re.I)), None)
    c_date, c_org, c_n = col(r"date"), col(r"poll"), col(r"sample")
    pcols = {c: HEADER_MAP[c.upper()] for c in df.columns if c.upper() in HEADER_MAP}
    rows = []
    for _, r in df.iterrows():
        org = clean(r[c_org])
        if not org or re.search(r"election|result", org, re.I):
            continue
        vals = {code: num(r[c]) for c, code in pcols.items()}
        if sum(v is not None for v in vals.values()) < 4:
            continue                                   # event row spanning the table
        start, end = parse_dates(r[c_date])
        if end is None:
            print(f"  ! couldn't parse date '{clean(r[c_date])}' for {org}; skipped")
            continue
        n = num(r[c_n]) if c_n else None
        rows.append({"date_start": start, "date_end": end, "org": org_code(org),
                     "n": int(n) if n else None, **{p: vals.get(p) for p in PARTY_COLS},
                     "source": source, "org_name": org})
    return pd.DataFrame(rows)


def parse_html(html: str, source: str) -> pd.DataFrame:
    tabs = party_tables(html)
    if not tabs:
        return pd.DataFrame(columns=["date_start", "date_end", "org", "n", *PARTY_COLS, "source"])
    polls = pd.concat([table_to_polls(t, source) for t in tabs], ignore_index=True)
    if polls.empty:
        return polls
    polls = polls.drop_duplicates(subset=["org", "date_start", "date_end", *PARTY_COLS])
    return polls.sort_values(["date_end", "org"]).reset_index(drop=True)


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="Wikipedia page title (default: the 2029 cycle page)")
    ap.add_argument("--html", help="parse a saved HTML file instead of fetching")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--save-html", help="also save the fetched page HTML here (for tests)")
    a = ap.parse_args(argv)

    if a.html:
        title, html = Path(a.html).stem, Path(a.html).read_text(encoding="utf-8")
    else:
        title, html = fetch_page([a.page] if a.page else PAGES)
    if html is not None and a.save_html:
        Path(a.save_html).parent.mkdir(parents=True, exist_ok=True)
        Path(a.save_html).write_text(html, encoding="utf-8")
    if html is None:
        print("No polling page yet; nothing to scrape.")
        polls = parse_html("", "")
    else:
        polls = parse_html(html, f"Wikipedia: {title}")
        print(f"Parsed {len(polls)} polls from '{title}'.")

    out = Path(a.out)
    old = pd.read_csv(out, comment="#") if out.exists() and out.stat().st_size else pd.DataFrame()
    key = lambda d: set() if d.empty else set(
        zip(d["org"], pd.to_datetime(d["date_end"]).dt.date.astype(str)))
    new = key(polls) - key(old)

    # Never replace a good file with an empty one because of a page glitch
    if polls.empty and not old.empty:
        print("Scrape returned nothing but polls exist already; keeping the old file.")
        new = set()
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        polls = polls.drop(columns=["org_name"], errors="ignore")
        if "n" in polls:
            polls["n"] = polls["n"].astype("Int64")
        polls.to_csv(out, index=False)
    for org, d in sorted(new, key=lambda x: x[1]):
        print(f"  new poll: {org} ending {d}")
    print(f"{len(new)} new poll(s).")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"new_polls={len(new)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
