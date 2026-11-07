"""Scraper regression tests. Run: python tests/test_scraper.py"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import scrape_polls as SP  # noqa: E402

P = ["NAT", "LAB", "GRN", "ACT", "NZF", "TPM", "OPP"]


def test_real_2026_page():
    """Saved copy of the real 2026 polling page (7 Nov 2026)."""
    html = (ROOT / "tests/fixtures/wikipedia_2026_page.html").read_text(encoding="utf-8")
    s = SP.parse_html(html, "test")
    # every nationwide poll of the 2023-26 term, and nothing from the electorate,
    # regional or demographic tables
    assert len(s) == 134, len(s)
    assert set(s.org) <= {"CUR", "ROY", "COL", "TBM", "FWS", "REI", "ANA"}, set(s.org)
    hand = pd.read_csv(ROOT / "data/polls/recent_polls.csv", comment="#")
    hand["date_end"] = pd.to_datetime(hand["date_end"]).dt.date
    m = s.merge(hand, on=["org", "date_end"], suffixes=("", "_h"))
    assert len(m) == len(hand), (len(m), len(hand))
    assert np.nanmax(np.abs(m[P].values - m[[p + "_h" for p in P]].values)) < 0.051


def test_mock_page():
    html = (ROOT / "tests/fixture_wikipedia.html").read_text(encoding="utf-8")
    s = SP.parse_html(html, "test")
    assert len(s) == 4 and "Tāmaki" not in s.to_string()


if __name__ == "__main__":
    test_real_2026_page()
    test_mock_page()
    print("scraper tests passed")
