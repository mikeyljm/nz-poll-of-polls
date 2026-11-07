# New Zealand poll of polls

A public, automatically updating New Zealand poll aggregator from
[Kōrero and Complexity](https://mikeyljmiller.substack.com):

* a Bayesian poll of polls (PyMC) with pollster house effects anchored to election results,
* MMP seat and coalition probabilities,
* how every voting place has leaned since 2002, on a map, and
* projected winners in all 64 general electorates.

The site is static (`site/`), served by GitHub Pages. A GitHub Action runs twice a day:
it scrapes Wikipedia for new polls, refits the model if anything changed (or a new week
has started), regenerates `site/data/*.json`, commits it and redeploys.

## Layout

| Path | What it is |
|---|---|
| `pipeline/run_update.py` | The daily job: scrape, decide whether to refit, fit, export |
| `pipeline/scrape_polls.py` | Wikipedia polling-page scraper |
| `pipeline/polls/` | Poll-of-polls model: `config.py`, `load_data.py`, `model.py`, `seats.py` |
| `pipeline/booths/` | Voting-place lean and electorate model (`nz_parse.py`, `nz_model.py`, `predict_nz.py`) |
| `pipeline/export_polls.py`, `export_booths.py` | Write the JSON the site reads |
| `data/polls/elections.csv` | **Election results that anchor the model.** Add new results here |
| `data/polls/manual_polls.csv` | Polls the scraper misses (optional; create it with the same columns as `scraped_polls.csv`) |
| `data/polls/scraped_polls.csv` | Written by the scraper; don't edit |
| `data/polls/nzpolls_data.yml`, `recent_polls.csv`, `added_polls.csv` | Polls 2020–2026 |
| `data/booths/nz_data/z_YYYY/` | Electoral Commission results by voting place, one folder per election |
| `data/archive/final_2026_projection_draws.csv` | The final pre-election projection (polls to 5 Nov 2026), for the post-election check |
| `site/` | The website |

## Running locally (Spyder or a terminal)

```
uv pip install -r requirements.txt
python pipeline/run_update.py --no-scrape --quick     # short sampling, a few minutes
python pipeline/run_update.py --force                 # full fit, as the Action runs it
python -m http.server -d site 8000                    # then open http://localhost:8000
```

## Checklist after the 2026 election

1. **Election night (7 Nov).** Add the preliminary party vote to `data/polls/elections.csv`
   with `status` = `preliminary`. Push; the site refits and shows the 2026 result as the
   starting point, plus how the final projection did.
2. **Official results (27 Nov).** Replace that row with the official figures (`official`).
3. **Voting-place results (27 Nov).** Download the 2026 "results by voting place" CSVs for
   the general electorates and put them in
   `data/booths/nz_data/z_2026/General electorates/Party votes/` and `.../Candidate votes/`,
   named as for earlier years. Push. The electorate model then uses 2026 as its base year,
   with 2026's candidates.
4. **Electorate assumptions.** Update `ELECTORATES` in `pipeline/polls/config.py` to reflect
   who now holds Epsom, Tāmaki, the Māori electorates and the Green seats.
5. Once the 2029 election date is announced, set `NEXT_ELECTION_DATE` in `config.py`.

## Settings on GitHub (once)

* **Settings → Pages → Source: GitHub Actions.**
* **Settings → Actions → General → Workflow permissions: Read and write.**
* Optional: a custom domain under Settings → Pages.

## Notes

* Polls the scraper can't parse are listed in the Action log. Add them to
  `data/polls/manual_polls.csv`; a manual row replaces a scraped row with the same pollster
  and end date.
* Unknown pollsters get a three-letter code from their name. Add a pattern to `ORG_PATTERNS`
  in `scrape_polls.py` and a display name to `POLLSTER_NAMES` in `config.py`.
* Electorate projections assume a uniform swing from the poll-of-polls median and the last
  election's candidates; Māori electorates are not modelled there.
