"""
MMP seat allocation and coalition probabilities.

* sainte_lague()   : standard Sainte-Laguë highest-quotient allocation
* allocate_seats() : one election under NZ MMP rules (threshold, electorate
                     exemption, independents, overhang)
* simulate()       : run allocate_seats() over posterior draws of party vote,
                     with electorate outcomes drawn from config.ELECTORATES
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg


def sainte_lague(votes: dict[str, float], seats: int) -> dict[str, int]:
    """Allocate `seats` among parties in proportion to `votes`."""
    parties = list(votes)
    v = np.array([votes[p] for p in parties], dtype=float)
    divisors = 2 * np.arange(seats) + 1                  # 1, 3, 5, ...
    quotients = v[:, None] / divisors[None, :]           # party x divisor
    top = np.argsort(quotients, axis=None)[::-1][:seats]
    won = np.bincount(np.unravel_index(top, quotients.shape)[0], minlength=len(v))
    return dict(zip(parties, won.astype(int)))


def allocate_seats(shares: dict[str, float], electorates: dict[str, int],
                   total=cfg.TOTAL_SEATS, threshold=cfg.THRESHOLD,
                   exemption=cfg.ELECTORATE_EXEMPTION,
                   independents=tuple(cfg.INDEPENDENTS)) -> dict[str, int]:
    """
    shares      : party-vote share by party (any party with an electorate win
                  should appear here, even with a tiny share)
    electorates : electorate seats won, by party (or independent label)
    Returns seats by party, including overhang; independents listed too.
    """
    ind_seats = sum(electorates.get(i, 0) for i in independents)
    qualifying = {p: s for p, s in shares.items()
                  if p not in independents
                  and (s >= threshold or electorates.get(p, 0) >= exemption)}
    list_pool = total - ind_seats
    entitled = sainte_lague(qualifying, list_pool)
    seats = {p: max(entitled[p], electorates.get(p, 0)) for p in qualifying}
    # Parties below threshold with no electorate get nothing
    for p in shares:
        seats.setdefault(p, 0)
    for i in independents:
        if electorates.get(i, 0):
            seats[i] = electorates[i]
    return seats


def shift_votes(share_draws: pd.DataFrame, source: str, frac: float,
                to: dict[str, float]) -> pd.DataFrame:
    """
    Scenario: move `frac` of `source`'s vote to other parties.
    `to` gives the split, e.g. {"LAB": 0.5, "GRN": 0.5}.
    Applied draw by draw, so uncertainty in the source's vote carries through.
    """
    out = share_draws.copy()
    moved = out[source] * frac
    out[source] -= moved
    for p, w in to.items():
        out[p] += moved * w
    return out


def _draw_electorates(share_draws: pd.DataFrame, rng, beta=cfg.SWING_BETA,
                      ref_median: pd.Series | None = None, electorates=None):
    """
    Electorate winners for every draw: DataFrame (draw x electorate).
    ref_median: the national vote at which config.ELECTORATES probabilities
    apply. Pass the baseline median when running a scenario so electorates
    respond to the scenario's swing.
    """
    med = share_draws.median()
    if ref_median is not None:  # small parties added later keep their own median
        med = ref_median.reindex(med.index).fillna(med)
    out = {}
    for name, probs in (cfg.ELECTORATES if electorates is None else electorates).items():
        parties = list(probs)
        logp = np.log(np.array([probs[p] for p in parties]))[None, :]
        rel = np.column_stack([
            ((share_draws[p] - med[p]) / med[p]).to_numpy()
            if p in share_draws else np.zeros(len(share_draws))
            for p in parties])
        w = np.exp(logp + beta * rel)
        w /= w.sum(1, keepdims=True)
        u = rng.random(len(share_draws))[:, None]
        idx = (u > np.cumsum(w, 1)).sum(1)
        out[name] = np.array(parties)[idx]
    return pd.DataFrame(out)


def simulate(share_draws: pd.DataFrame, seed=2026,
             baseline: pd.DataFrame | None = None,
             general_winners: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    share_draws:     posterior draws of election-day party vote (columns = parties).
    baseline:        for scenarios, the unshifted draws (sets electorate reference).
    general_winners: winner of every general electorate in each draw (draw x seat,
                     party codes), from the electorate model, in the same draw order.
                     If given, these replace GENERAL_FALLBACK; the Māori electorates
                     still come from MAORI_ELECTORATES.
    Returns (seats, electorate_winners), one row per draw.
    """
    rng = np.random.default_rng(seed)
    shares = share_draws.copy()
    for p, s in cfg.SMALL_PARTY_SHARES.items():
        shares[p] = s
        shares["OTH"] = (shares["OTH"] - s).clip(lower=0)
    ref = None if baseline is None else baseline.median()
    if general_winners is not None:
        assert len(general_winners) == len(shares), "electorate draws must match vote draws"
        maori = _draw_electorates(shares, rng, ref_median=ref, electorates=cfg.MAORI_ELECTORATES)
        winners = pd.concat([general_winners.reset_index(drop=True), maori], axis=1)
    else:
        winners = _draw_electorates(shares, rng, ref_median=ref)

    rows = []
    vote_parties = [p for p in shares.columns if p != "OTH"]
    W = winners.to_numpy()
    for i in range(len(shares)):
        u, c = np.unique(W[i], return_counts=True)
        e_counts = dict(zip(u.tolist(), c.tolist()))
        seats = allocate_seats(shares.iloc[i][vote_parties].to_dict(), e_counts)
        rows.append(seats)
    seats = pd.DataFrame(rows).fillna(0).astype(int)
    seats["TOTAL"] = seats.sum(axis=1)
    return seats, winners


def coalition_probs(seats: pd.DataFrame, coalitions=cfg.COALITIONS) -> pd.DataFrame:
    majority = seats["TOTAL"] // 2 + 1
    rows = []
    for name, members in coalitions.items():
        s = seats[[m for m in members if m in seats]].sum(axis=1)
        rows.append(dict(coalition=name, p_majority=(s >= majority).mean(),
                         median_seats=s.median(), lo=s.quantile(0.05),
                         hi=s.quantile(0.95)))
    return pd.DataFrame(rows)


def who_governs(seats: pd.DataFrame, p_king_left: float = 0.5) -> pd.Series:
    """
    Probability each bloc forms the government.
    * A bloc with a majority on its own governs.
    * Otherwise the kingmaker picks the left with probability p_king_left.
      If the side it picks can't reach a majority even with it, it backs the
      other side instead (if that side can).
    * "No government" = neither bloc can reach a majority even with the kingmaker.
    """
    maj = seats["TOTAL"] // 2 + 1
    cols = lambda ps: [p for p in ps if p in seats]
    L = seats[cols(cfg.LEFT_BLOC)].sum(axis=1)
    R = seats[cols(cfg.RIGHT_BLOC)].sum(axis=1)
    K = seats[cfg.KINGMAKER] if cfg.KINGMAKER in seats else 0
    l_alone, r_alone = L >= maj, R >= maj
    neither = ~l_alone & ~r_alone
    l_k, r_k = neither & (L + K >= maj), neither & (R + K >= maj)
    left = (l_alone.mean() + (l_k & r_k).mean() * p_king_left
            + (l_k & ~r_k).mean())
    right = (r_alone.mean() + (l_k & r_k).mean() * (1 - p_king_left)
             + (r_k & ~l_k).mean())
    return pd.Series({"Left governs": left, "Right governs": right,
                      "No government": 1 - left - right})


def who_governs_largest(seats: pd.DataFrame, shares: pd.DataFrame,
                        left_party="LAB", right_party="NAT") -> pd.Series:
    """
    Like who_governs(), but the kingmaker backs the bloc whose main party
    (LAB or NAT) has the most party votes in that simulation, falling back to
    the other side if that bloc can't reach a majority even with it.
    """
    maj = seats["TOTAL"] // 2 + 1
    cols = lambda ps: [p for p in ps if p in seats]
    L = seats[cols(cfg.LEFT_BLOC)].sum(axis=1)
    R = seats[cols(cfg.RIGHT_BLOC)].sum(axis=1)
    K = seats[cfg.KINGMAKER] if cfg.KINGMAKER in seats else 0
    lab_first = (shares[left_party] > shares[right_party]).to_numpy()
    l_alone, r_alone = L >= maj, R >= maj
    neither = ~l_alone & ~r_alone
    l_k, r_k = neither & (L + K >= maj), neither & (R + K >= maj)
    left = l_alone | (l_k & r_k & lab_first) | (l_k & ~r_k)
    right = r_alone | (l_k & r_k & ~lab_first) | (r_k & ~l_k)
    return pd.Series({"Left governs": left.mean(), "Right governs": right.mean(),
                      "No government": 1 - left.mean() - right.mean(),
                      "P(LAB > NAT)": lab_first.mean()})


def headline(seats: pd.DataFrame) -> pd.Series:
    """Mutually exclusive outcomes for the 'who governs' question."""
    majority = seats["TOTAL"] // 2 + 1
    cols = lambda ps: [p for p in ps if p in seats]
    right = seats[cols(cfg.RIGHT_BLOC)].sum(1)
    left = seats[cols(cfg.LEFT_BLOC)].sum(1)
    king = seats[cfg.KINGMAKER] if cfg.KINGMAKER in seats else 0
    r_alone = right >= majority
    l_alone = left >= majority
    need_k = ~r_alone & ~l_alone & ((right + king >= majority) | (left + king >= majority))
    return pd.Series({
        "Right bloc majority on its own": r_alone.mean(),
        "Left bloc majority on its own": l_alone.mean(),
        f"Neither: {cfg.KINGMAKER} decides": need_k.mean(),
        f"Neither, even with {cfg.KINGMAKER}": (~r_alone & ~l_alone & ~need_k).mean(),
    })


# %% Self-test against the 2023 result (122 seats with 2 TPM overhang)
if __name__ == "__main__":
    v2023 = {"NAT": .3808, "LAB": .2692, "GRN": .1161, "ACT": .0864,
             "NZF": .0609, "TPM": .0308, "OPP": .0222}
    e2023 = {"NAT": 43, "LAB": 17, "GRN": 3, "ACT": 2, "TPM": 6}
    got = allocate_seats(v2023, e2023)
    expected = {"NAT": 48, "LAB": 34, "GRN": 15, "ACT": 11, "NZF": 8, "TPM": 6, "OPP": 0}
    print(got, "total", sum(got.values()))
    assert got == expected, "2023 check failed"
    print("2023 allocation reproduced ✓")
