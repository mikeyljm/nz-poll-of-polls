"""
Daily update: scrape new polls, refit the poll-of-polls if anything changed,
and regenerate the website's data.

    python pipeline/run_update.py             # normal daily run
    python pipeline/run_update.py --force     # refit even if no inputs changed
    python pipeline/run_update.py --no-scrape --quick   # local test (short sampling)

Decides whether to refit by hashing every model input (poll files, elections,
config and model code). The hash of the last published fit is kept in
site/data/meta.json, which is committed with the site.
If running under GitHub Actions, writes updated=true|false to $GITHUB_OUTPUT.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "polls"))
sys.path.insert(0, str(ROOT / "pipeline"))

META = ROOT / "site" / "data" / "meta.json"
INPUTS = [
    *sorted((ROOT / "data" / "polls").glob("*.csv")),
    ROOT / "data" / "polls" / "nzpolls_data.yml",
    *sorted((ROOT / "pipeline" / "polls").glob("*.py")),
    *sorted((ROOT / "pipeline" / "booths").glob("*.py")),
    ROOT / "pipeline" / "export_polls.py",
    ROOT / "pipeline" / "export_booths.py",
    *sorted((ROOT / "data" / "booths" / "nz_data").glob("z_*")),
]


def input_hash() -> str:
    h = hashlib.sha256()
    for p in INPUTS:
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.is_file():
                h.update(str(f.relative_to(ROOT)).encode())
                h.update(f.read_bytes())
    return h.hexdigest()[:16]


def gh_output(**kv):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def week_start(d: dt.date) -> str:
    return d.isoformat()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-scrape", action="store_true")
    ap.add_argument("--quick", action="store_true", help="short sampling for local tests")
    a = ap.parse_args(argv)

    if not a.no_scrape:
        subprocess.run([sys.executable, str(ROOT / "pipeline" / "scrape_polls.py")], check=True)

    h = input_hash()
    old = json.loads(META.read_text()) if META.exists() else {}
    # Also refit when a new week starts, so the "today" estimate keeps moving forward
    # (uncertainty widens between polls) even with no new polls. Weekly is plenty.
    this_week = dt.date.today().isocalendar()[:2]
    same_week = tuple(old.get("iso_week", ())) == tuple(this_week)
    if not a.force and old.get("input_hash") == h and same_week:
        print("No new polls or input changes this week; site data unchanged.")
        gh_output(updated="false")
        return 0

    import arviz as az
    import load_data
    import model as M
    import export_polls as EP

    polls = load_data.load_all()
    d = M.prepare(polls)
    print(f"{d['n_weeks']} weeks, {len(d['y'])} poll-party cells, cycles {d['cycles']}")
    try:
        import nutpie  # noqa: F401
        sampler = "nutpie"
    except ImportError:
        sampler = "pymc"
    mdl = M.build_model(d)
    kw = dict(draws=300, tune=400, chains=2) if a.quick else dict(draws=1250, tune=1500, chains=4)   # 5,000 posterior draws
    idata = M.fit(mdl, nuts_sampler=sampler, progressbar=False, **kw)

    summ = az.summary(idata, var_names=["sigma_rw", "tau_house", "tau_drift", "tau_industry",
                                        "sigma_extra"])
    diag = {"max_rhat": round(float(summ["r_hat"].max()), 3),
            "min_ess_bulk": int(summ["ess_bulk"].min()),
            "draws": int(idata.posterior.sizes["draw"] * idata.posterior.sizes["chain"]),
            "sampler": sampler}
    print("Diagnostics:", diag)
    if diag["max_rhat"] > 1.05:
        print("WARNING: r-hat above 1.05; check convergence before trusting this run.")

    meta = EP.export(idata, d, polls, diag)
    subprocess.run([sys.executable, str(ROOT / "pipeline" / "booths" / "nz_parse.py"),
                    str(ROOT / "data" / "booths" / "nz_data"), str(ROOT / "build" / "booths" / "parsed")],
                   check=True, cwd=ROOT / "pipeline" / "booths")
    subprocess.run([sys.executable, str(ROOT / "pipeline" / "export_booths.py")], check=True)
    EP.export_seats(meta)

    META.write_text(json.dumps({**meta, "input_hash": h, "iso_week": list(this_week)},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    gh_output(updated="true")
    print("Site data updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
