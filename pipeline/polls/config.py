"""
Configuration for the NZ poll-of-polls.

Everything you are likely to want to tweak lives here: which parties are
modelled, the time window, MMP rules, the electorate-seat assumptions and
the coalitions to report.

Election results that anchor the model live in data/polls/elections.csv, so a
new result can be added without touching code.
"""
import datetime as dt
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]          # repo root
DATA_DIR = ROOT / "data" / "polls"
OUT_DIR = ROOT / "build" / "polls"                   # intermediate outputs (not published)
SITE_DATA = ROOT / "site" / "data"                   # JSON read by the website

# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------
# Modelled parties. "OTH" is everything else (computed as 100 - sum of the
# rest) and is needed so shares live on a proper simplex.
PARTIES = ["NAT", "LAB", "GRN", "ACT", "NZF", "TPM", "OPP", "OTH"]

PARTY_NAMES = {
    "NAT": "National", "LAB": "Labour", "GRN": "Green", "ACT": "ACT",
    "NZF": "NZ First", "TPM": "Te Pāti Māori", "OPP": "Opportunity",
    "OTH": "Other", "TTT": "Te Tai Tokerau Party", "IND": "Independent",
}

PARTY_COLOURS = {
    "NAT": "#00529F", "LAB": "#D82A20", "GRN": "#098137", "ACT": "#FDE401",
    "NZF": "#3F3F3F", "TPM": "#B2001A", "OPP": "#4E8F9E", "OTH": "#A0A0A0",
    "TTT": "#7A3B69", "IND": "#C08A2D",
}

# Codes in the NZPolls YAML that map onto our codes
YAML_PARTY_MAP = {"MRI": "TPM", "TOP": "OPP"}

# --------------------------------------------------------------------------
# Pollsters
# --------------------------------------------------------------------------
POLLSTER_NAMES = {
    "COL": "1News–Verian",
    "CUR": "Taxpayers' Union–Curia",
    "REI": "RNZ–Reid Research",
    "ROY": "Roy Morgan",
    "TBM": "Talbot Mills",
    "FWS": "The Post–Freshwater Strategy",
    "ANA": "Anacta",
    "BAU": "Bauer Media", "DYN": "Dynata", "ESS": "Essential",
    "GUA": "Guardian Essential", "HOR": "Horizon", "YGV": "YouGov",
    "IPS": "Ipsos", "DGI": "DigiPoll",
}

# --------------------------------------------------------------------------
# Time window
# --------------------------------------------------------------------------
# The model starts at the 2020 election, so pollster bias is judged from the
# 2020-23 and 2023-26 cycles and their results.
START_DATE = "2020-10-17"

# The model runs to the current week ("if an election were held today").
# MODEL_END can be set in the environment to re-run as at a past date.
# Once the next election date is announced, set NEXT_ELECTION_DATE and the
# site also shows an election-day projection.
MODEL_END = os.environ.get("MODEL_END", dt.date.today().isoformat())
NEXT_ELECTION_DATE = None          # e.g. "2029-11-03" once announced

DEFAULT_SAMPLE_SIZE = 1000            # used when a poll doesn't report n


def load_elections(path=DATA_DIR / "elections.csv") -> pd.DataFrame:
    e = pd.read_csv(path, comment="#", dtype={"date": str})
    e = e[pd.to_datetime(e["date"]) >= pd.Timestamp(START_DATE)]
    return e.sort_values("date").reset_index(drop=True)


ELECTIONS = load_elections()["date"].tolist()     # anchors, oldest first

# Final election in the data, and the date the current cycle's polls start
LAST_ELECTION = ELECTIONS[-1]

# --------------------------------------------------------------------------
# MMP rules
# --------------------------------------------------------------------------
TOTAL_SEATS = 120
THRESHOLD = 0.05            # party-vote threshold
ELECTORATE_EXEMPTION = 1    # electorates needed to bypass the threshold

# --------------------------------------------------------------------------
# Electorate assumptions
# --------------------------------------------------------------------------
# Only electorates that could matter for MMP (threshold exemptions and
# overhang) need listing. Every other electorate is won by National or Labour,
# whose electorate wins never exceed their list entitlement, so they don't
# change seat totals.
#
# Each entry: probabilities of each party winning the seat when that party's
# national vote is at its median. "swing_beta" links the chance to the party's
# simulated national vote: p = invlogit(logit(p0) + beta * relative_deviation),
# so electorate results move with the national swing. Set beta = 0 for
# independent draws.
#
# THESE ARE PLACEHOLDERS carried over from the 2026 campaign. Update them once
# the 2026 electorate results are known (who holds each seat now).
ELECTORATES = {
    # Threshold-exemption seats for ACT
    "Epsom":            {"ACT": 0.85, "NAT": 0.15},
    "Tāmaki":           {"ACT": 0.55, "NAT": 0.45},
    # Green-held / competitive inner-city seats
    "Auckland Central": {"GRN": 0.70, "LAB": 0.15, "NAT": 0.15},
    "Wellington Central": {"GRN": 0.70, "LAB": 0.30},
    "Rongotai":         {"GRN": 0.50, "LAB": 0.50},
    # Seats where minor parties have a (long-shot) chance
    "Northland":        {"NAT": 0.75, "NZF": 0.15, "LAB": 0.10},
    "Ilam":             {"NAT": 0.70, "OPP": 0.15, "LAB": 0.15},
    # Māori electorates: fixed to the standard poll-projection assumption
    # (TPM holds four; Labour wins Te Tai Tokerau, Te Tai Tonga, Ikaroa-Rāwhiti)
    "Te Tai Tokerau":   {"LAB": 1.0},
    "Tāmaki Makaurau":  {"TPM": 1.0},
    "Hauraki-Waikato":  {"TPM": 1.0},
    "Waiariki":         {"TPM": 1.0},
    "Te Tai Hauāuru":   {"TPM": 1.0},
    "Te Tai Tonga":     {"LAB": 1.0},
    "Ikaroa-Rāwhiti":   {"LAB": 1.0},
}
SWING_BETA = 2.0

# Parties or candidates that can win electorates but aren't in the vote model.
SMALL_PARTY_SHARES = {}   # e.g. {"TTT": 0.003}
INDEPENDENTS = ["IND"]

# --------------------------------------------------------------------------
# Coalitions to report
# --------------------------------------------------------------------------
COALITIONS = {
    "National + ACT + NZ First":                 ["NAT", "ACT", "NZF"],
    "National + ACT + NZ First + Opportunity":   ["NAT", "ACT", "NZF", "OPP"],
    "Labour + Green":                            ["LAB", "GRN"],
    "Labour + Green + Te Pāti Māori":            ["LAB", "GRN", "TPM"],
    "Labour + Green + Te Pāti Māori + Opportunity": ["LAB", "GRN", "TPM", "OPP"],
    "National + Labour":                         ["NAT", "LAB"],
}
# For the headline "who forms government" summary
RIGHT_BLOC = ["NAT", "ACT", "NZF"]
LEFT_BLOC = ["LAB", "GRN", "TPM"]
KINGMAKER = "OPP"
