"""Generation parameters. One generator serves every scale (starter / full)."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Params:
    seed: int = 20261022
    n_portfolios: int = 1000
    n_instruments: int = 300          # instrument universe (priced for every trading day)
    n_holdings: int = 5000            # holding rows across all portfolios (>= 4 x portfolios)
    n_days: int = 250                 # trading days of prices (weekdays, no holiday calendar)
    as_of_date: str = "2026-10-16"    # valuation date == last price date (must be a weekday)
    stale_days_threshold: int = 3     # price older than this many trading days is STALE
    missing_price_rate: float = 0.008
    stale_instrument_rate: float = 0.04   # share of non-cash instruments with a trailing price gap
    high_notional_usd: float = 250000.0   # compliance escalation: buys+sells above this
    high_turnover_pct: float = 20.0       # compliance escalation threshold
    max_turnover_pct: float = 25.0        # hard cap, also published as a Constraint row
    # injected anomaly rates, as a fraction of portfolios (minimum 2 of each)
    rate_weights_not_100: float = 0.02
    rate_trade_exceeds_holding: float = 0.015
    rate_excluded_recommended: float = 0.015
    rate_fees_omitted: float = 0.02
    rate_stale_unflagged: float = 0.015

    def to_dict(self):
        return asdict(self)

    def anomaly_count(self, rate):
        return max(2, round(rate * self.n_portfolios))


PRESETS = {
    "starter": dict(n_portfolios=100, n_instruments=60, n_holdings=500),
    "full": dict(),
}


def make_params(scale="full", **overrides):
    kw = dict(PRESETS[scale])
    kw.update({k: v for k, v in overrides.items() if v is not None})
    p = Params(**kw)
    if p.n_holdings < 4 * p.n_portfolios:
        raise ValueError("n_holdings must be >= 4 * n_portfolios (one holding per asset class)")
    return p
