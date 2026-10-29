"""Master data, prices, targets, holdings and policy tables. Valid baseline records only (no anomalies here)."""
import bisect
import datetime as dt
import math
import random

from .schema import ASSET_CLASSES, NON_CASH, RISK_PROFILES, COUNTRIES

PROFILE_TARGETS = {
    "CONSERVATIVE": {"EQUITY": 20.0, "FIXED_INCOME": 60.0, "REAL_ASSETS": 5.0, "CASH": 15.0},
    "MODERATE": {"EQUITY": 35.0, "FIXED_INCOME": 45.0, "REAL_ASSETS": 10.0, "CASH": 10.0},
    "BALANCED": {"EQUITY": 50.0, "FIXED_INCOME": 33.0, "REAL_ASSETS": 10.0, "CASH": 7.0},
    "GROWTH": {"EQUITY": 65.0, "FIXED_INCOME": 20.0, "REAL_ASSETS": 10.0, "CASH": 5.0},
    "AGGRESSIVE": {"EQUITY": 78.0, "FIXED_INCOME": 8.0, "REAL_ASSETS": 11.0, "CASH": 3.0},
}
PROFILE_MIN_CASH = {"CONSERVATIVE": 5.0, "MODERATE": 3.0, "BALANCED": 2.0, "GROWTH": 1.0, "AGGRESSIVE": 1.0}
PROFILE_BAND = {"CONSERVATIVE": 4.0, "MODERATE": 5.0, "BALANCED": 5.0, "GROWTH": 6.0, "AGGRESSIVE": 6.0}
BASE_SCORE = {"CONSERVATIVE": 20, "MODERATE": 38, "BALANCED": 55, "GROWTH": 72, "AGGRESSIVE": 88}
# annual drift, annual vol, initial price range
CLASS_PARAMS = {"EQUITY": (0.08, 0.22, (20, 250)), "FIXED_INCOME": (0.035, 0.06, (80, 115)),
                "REAL_ASSETS": (0.05, 0.18, (15, 150)), "CASH": (0.0, 0.0, (1, 1))}
SUBCLASSES = {"EQUITY": ["US_LARGE", "US_SMALL", "INTL_DEVELOPED", "EMERGING"],
              "FIXED_INCOME": ["GOVERNMENT", "CORPORATE_IG", "HIGH_YIELD", "SHORT_TERM"],
              "REAL_ASSETS": ["REIT", "COMMODITY", "INFRASTRUCTURE"], "CASH": ["MONEY_MARKET"]}
LIQ_WEIGHTS = {"EQUITY": [0.55, 0.33, 0.12], "FIXED_INCOME": [0.45, 0.40, 0.15], "REAL_ASSETS": [0.20, 0.45, 0.35]}
ADV_RANGE = {"HIGH": (200_000, 2_000_000), "MEDIUM": (20_000, 200_000), "LOW": (2_000, 20_000)}
LOT = {"EQUITY": 1, "FIXED_INCOME": 10, "REAL_ASSETS": 1, "CASH": 0.01}
PREFIX = {"EQUITY": "EQ", "FIXED_INCOME": "FI", "REAL_ASSETS": "RA", "CASH": "CS"}
LABEL = {"EQUITY": "Equity Fund", "FIXED_INCOME": "Bond Fund", "REAL_ASSETS": "Real Asset Fund", "CASH": "Money Market"}
LIQUIDITY = ["HIGH", "MEDIUM", "LOW"]
ADMIN_ID = "USR-ADM-001"


def rng(p, stage):
    return random.Random(f"{p.seed}:{stage}")


def D(s):
    return dt.date.fromisoformat(s)


def band_for(profile, asset_class):
    return {"REAL_ASSETS": 3.0, "CASH": 2.0}.get(asset_class, PROFILE_BAND[profile])


def trading_days(as_of, n):
    d = D(as_of)
    if d.weekday() >= 5:
        raise ValueError("as_of_date must be a weekday")
    days = []
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= dt.timedelta(days=1)
    return days[::-1]


# ----------------------------------------------------------------------------- investors / portfolios
def gen_investors(p):
    r = rng(p, "investors")
    n_two = round(0.10 * p.n_portfolios)
    n_inv = p.n_portfolios - n_two
    as_of = D(p.as_of_date)
    rows = []
    for i in range(1, n_inv + 1):
        age = int(min(80, max(21, r.gauss(46, 12))))
        horizon = int(min(40, max(1, (67 - age) * r.uniform(0.6, 1.1) if age < 62 else r.uniform(1, 8))))
        if age < 35:
            w = [0.03, 0.10, 0.25, 0.37, 0.25]
        elif age < 50:
            w = [0.07, 0.18, 0.35, 0.28, 0.12]
        elif age < 62:
            w = [0.15, 0.30, 0.35, 0.15, 0.05]
        else:
            w = [0.35, 0.35, 0.20, 0.08, 0.02]
        profile = r.choices(RISK_PROFILES, weights=w)[0]
        score = BASE_SCORE[profile] + round((50 - age) / 5) + round(min(horizon, 30) / 6)
        score = max(1, min(100, score))
        kyc = r.choices(["VERIFIED", "PENDING", "EXPIRED"], weights=[0.90, 0.06, 0.04])[0]
        if kyc == "EXPIRED":
            expiry = as_of - dt.timedelta(days=r.randint(5, 300))
        else:
            expiry = as_of + dt.timedelta(days=r.randint(30, 700))
        rows.append({"investor_id": f"INV-{i:06d}", "risk_profile": profile, "risk_score": score, "age": age,
                     "investment_horizon_years": horizon,
                     "annual_income_band": r.choices(["LOW", "MIDDLE", "UPPER", "HIGH"], weights=[0.15, 0.45, 0.28, 0.12])[0],
                     "country": r.choice(COUNTRIES), "base_currency": "USD", "kyc_status": kyc,
                     "kyc_expiry_date": expiry.isoformat(),
                     "created_date": (as_of - dt.timedelta(days=r.randint(400, 3500))).isoformat(),
                     "status": "ACTIVE"})
    return rows


def gen_portfolios(p, investors):
    r = rng(p, "portfolios")
    as_of = D(p.as_of_date)
    ids = [i["investor_id"] for i in investors]
    two = set(r.sample(ids, round(0.10 * p.n_portfolios)))
    names = ["Core Account", "Retirement Account", "Goal Account", "Growth Account"]
    rows = []
    for inv in investors:
        created = D(inv["created_date"])
        for s in ([1, 2] if inv["investor_id"] in two else [1]):
            latest = as_of - dt.timedelta(days=180)
            incep = created + dt.timedelta(days=r.randint(1, max(1, (latest - created).days)))
            frozen = inv["kyc_status"] == "EXPIRED"
            rows.append({"portfolio_id": f"PORT-{inv['investor_id']}-{s:02d}", "investor_id": inv["investor_id"],
                         "portfolio_seq": s, "portfolio_name": r.choice(names), "base_currency": "USD",
                         "inception_date": incep.isoformat(), "status": "FROZEN" if frozen else "ACTIVE",
                         "status_reason": "KYC_EXPIRED" if frozen else None})
    return rows


# ----------------------------------------------------------------------------- instruments / prices
def gen_instruments(p):
    r = rng(p, "instruments")
    n = p.n_instruments
    n_cash = max(3, round(0.04 * n))
    n_eq = round(0.45 * n)
    n_fi = round(0.35 * n)
    counts = {"EQUITY": n_eq, "FIXED_INCOME": n_fi, "REAL_ASSETS": n - n_cash - n_eq - n_fi, "CASH": n_cash}
    as_of = D(p.as_of_date)
    rows, k = [], 0
    for c in ASSET_CLASSES:
        for j in range(1, counts[c] + 1):
            k += 1
            tier = "HIGH" if c == "CASH" else r.choices(LIQUIDITY, weights=LIQ_WEIGHTS[c])[0]
            lo, hi = ADV_RANGE[tier] if c != "CASH" else (1_000_000_000, 1_000_000_000)
            adv = int(math.exp(r.uniform(math.log(lo), math.log(hi))))
            rows.append({"instrument_id": f"INS-{k:06d}", "ticker": f"{PREFIX[c]}{j:04d}",
                         "instrument_name": f"Synthetic {LABEL[c]} {j:03d}", "asset_class": c,
                         "sub_class": r.choice(SUBCLASSES[c]), "currency": "USD", "liquidity_tier": tier,
                         "avg_daily_volume_units": adv, "lot_size": LOT[c], "is_excluded": False,
                         "exclusion_reason": None,
                         "listing_date": (as_of - dt.timedelta(days=r.randint(500, 6000))).isoformat(),
                         "status": "ACTIVE"})
    # exclusions: at least one per non-cash class, about 3% of non-cash overall
    noncash = [x for x in rows if x["asset_class"] != "CASH"]
    n_excl = max(3, round(0.03 * len(noncash)))
    chosen = []
    for c in NON_CASH:
        chosen.append(r.choice([x for x in rows if x["asset_class"] == c])["instrument_id"])
    rest = [x["instrument_id"] for x in noncash if x["instrument_id"] not in chosen]
    chosen += r.sample(rest, max(0, n_excl - len(chosen)))
    for x in rows:
        if x["instrument_id"] in chosen:
            x["is_excluded"] = True
            x["exclusion_reason"] = r.choice(["RESTRICTED_LIST", "SANCTIONS_SCREEN", "INTERNAL_POLICY"])
    return rows


def gen_prices(p, instruments):
    """Returns (price_rows, series, days, px_asof, stale_ids, missing_cells)."""
    r = rng(p, "prices")
    days = trading_days(p.as_of_date, p.n_days)
    n = len(days)
    mkt = {}
    for c in NON_CASH:
        mu, sig, _ = CLASS_PARAMS[c]
        mu_d, sd_d = mu / 252, sig / math.sqrt(252)
        mkt[c] = [r.gauss(mu_d, 0.7 * sd_d) for _ in range(n)]
    noncash = sorted(x["instrument_id"] for x in instruments if x["asset_class"] != "CASH")
    n_stale = max(2, round(p.stale_instrument_rate * len(noncash)))
    stale_ids = sorted(r.sample(noncash, n_stale))
    gaps = {iid: r.randint(4, 12) for iid in stale_ids}
    series, missing_cells = {}, []
    for ins in instruments:
        iid, c = ins["instrument_id"], ins["asset_class"]
        if c == "CASH":
            series[iid] = [1.0] * n
            continue
        mu, sig, (lo, hi) = CLASS_PARAMS[c]
        sd_d = sig / math.sqrt(252)
        px, beta, vals = r.uniform(lo, hi), r.uniform(0.7, 1.3), []
        for t in range(n):
            if t > 0:
                px = max(0.01, px * math.exp(beta * mkt[c][t] + r.gauss(0, 0.714 * sd_d)))
            vals.append(round(px, 4))
        for t in range(1, n):
            if r.random() < p.missing_price_rate:
                vals[t] = None
        for t in range(n - gaps.get(iid, 0), n):
            vals[t] = None
        series[iid] = vals
    rows = []
    for ins in instruments:
        iid = ins["instrument_id"]
        for t, d in enumerate(days):
            v = series[iid][t]
            if v is None:
                missing_cells.append((iid, d.isoformat()))
            rows.append({"price_id": f"PX-{iid}-{d.strftime('%Y%m%d')}", "instrument_id": iid, "price_date": d.isoformat(),
                         "close_price": v, "price_status": "OBSERVED" if v is not None else "MISSING",
                         "source": "SYNTHETIC_GBM"})
    px_asof = {}
    for iid, vals in series.items():
        idx = max(t for t in range(n) if vals[t] is not None)
        px_asof[iid] = (vals[idx], days[idx].isoformat(), n - 1 - idx)
    return rows, series, days, px_asof, stale_ids, missing_cells


# ----------------------------------------------------------------------------- targets
def make_target(r, profile):
    base, mc = PROFILE_TARGETS[profile], PROFILE_MIN_CASH[profile]
    eq = base["EQUITY"] + 0.5 * r.randint(-4, 4)
    ra = base["REAL_ASSETS"] + 0.5 * r.randint(-2, 2)
    cash = max(mc + 1, base["CASH"] + 0.5 * r.randint(-2, 2))
    fi = 100.0 - eq - ra - cash
    if fi < 3.0:
        eq -= 3.0 - fi
        fi = 3.0
    return {"EQUITY": eq, "FIXED_INCOME": fi, "REAL_ASSETS": ra, "CASH": cash}


def gen_targets(p, portfolios, investors):
    r = rng(p, "targets")
    prof = {i["investor_id"]: i["risk_profile"] for i in investors}
    as_of = D(p.as_of_date)
    rows = []

    def emit(pid, profile, version, tg, eff_from, eff_to, status):
        for c in ASSET_CLASSES:
            rows.append({"target_id": f"TGT-{pid}-{c}-V{version}", "portfolio_id": pid, "asset_class": c,
                         "target_weight_pct": tg[c], "tolerance_band_pct": band_for(profile, c), "version": version,
                         "effective_from": eff_from.isoformat(), "effective_to": eff_to.isoformat() if eff_to else None,
                         "status": status})
    for port in portfolios:
        profile = prof[port["investor_id"]]
        incep = D(port["inception_date"])
        if r.random() < 0.10:
            span = (as_of - incep).days
            cut = incep + dt.timedelta(days=r.randint(30, max(31, span - 90)))
            emit(port["portfolio_id"], profile, 1, make_target(r, profile), incep, cut, "SUPERSEDED")
            emit(port["portfolio_id"], profile, 2, make_target(r, profile), cut + dt.timedelta(days=1), None, "ACTIVE")
        else:
            emit(port["portfolio_id"], profile, 1, make_target(r, profile), incep, None, "ACTIVE")
    return rows


# ----------------------------------------------------------------------------- holdings
def gen_holdings(p, portfolios, instruments, targets, days, series, px_asof):
    r = rng(p, "holdings")
    thr = p.stale_days_threshold
    inst = {x["instrument_id"]: x for x in instruments}
    by_class = {c: sorted(x["instrument_id"] for x in instruments if x["asset_class"] == c) for c in ASSET_CLASSES}
    cur = {}
    for t in targets:
        if t["status"] == "ACTIVE":
            cur.setdefault(t["portfolio_id"], {})[t["asset_class"]] = t["target_weight_pct"]
    extras = p.n_holdings - 4 * len(portfolios)
    extra_cnt = {}
    for idx in r.choices(range(len(portfolios)), k=extras):
        extra_cnt[idx] = extra_cnt.get(idx, 0) + 1
    as_of = D(p.as_of_date)
    rows = []
    for idx, port in enumerate(portfolios):
        pid = port["portfolio_id"]
        k = {c: 1 for c in ASSET_CLASSES}
        for _ in range(extra_cnt.get(idx, 0)):
            for _try in range(20):
                c = r.choices(NON_CASH, weights=[0.45, 0.35, 0.20])[0]
                if k[c] < len(by_class[c]):
                    k[c] += 1
                    break
        u = r.random()
        sd = 1.2 if u < 0.55 else (3.5 if u < 0.85 else 7.5)
        tg = cur[pid]
        w = {}
        for c in ASSET_CLASSES:
            w[c] = max(0.3 if c == "CASH" else 0.5, tg[c] + r.gauss(0, sd * (0.5 if c == "CASH" else 1.0)))
        tot = sum(w.values())
        w = {c: v * 100.0 / tot for c, v in w.items()}
        v0 = min(5_000_000.0, max(10_000.0, math.exp(r.gauss(math.log(150_000), 1.0))))
        incep = D(port["inception_date"])
        prow = []
        for c in ASSET_CLASSES:
            picks = r.sample(by_class[c], k[c])
            splits = [r.gammavariate(1.5, 1.0) for _ in picks]
            ssum = sum(splits)
            for iid, sp in zip(picks, splits):
                value = v0 * w[c] / 100.0 * sp / ssum
                price, pdate, age = px_asof[iid]
                lot = inst[iid]["lot_size"]
                if c == "CASH":
                    qty, acq, cost = round(value, 2), incep, 1.0
                else:
                    qty = int(max(lot, round(value / price / lot) * lot))
                    acq = incep + dt.timedelta(days=r.randint(0, (as_of - incep).days))
                    pos = bisect.bisect_right([d for d in days], acq) - 1
                    if pos < 0:
                        first = next(v for v in series[iid] if v is not None)
                        cost = round(first * r.uniform(0.9, 1.1), 4)
                    else:
                        j = pos
                        while series[iid][j] is None:
                            j -= 1
                        cost = series[iid][j]
                prow.append({"holding_id": f"HOLD-{pid}-{iid}", "portfolio_id": pid, "instrument_id": iid,
                             "as_of_date": p.as_of_date, "quantity": qty, "avg_cost_per_unit": cost,
                             "acquired_date": acq.isoformat(), "price_used": price, "price_date_used": pdate,
                             "price_age_days": age, "stale_price_flag": age > thr,
                             "market_value": round(qty * price, 2), "current_weight_pct": 0.0, "status": "ACTIVE"})
        total = sum(h["market_value"] for h in prow)
        for h in prow:
            h["current_weight_pct"] = round(h["market_value"] / total * 100.0, 6)
        rows += prow
    return rows


# ----------------------------------------------------------------------------- policy tables
def gen_fee_schedule(p):
    rates = {"EQUITY": (12, 8, 5, 1.0, 1.0), "FIXED_INCOME": (20, 12, 8, 2.0, 2.5),
             "REAL_ASSETS": (25, 15, 10, 3.0, 3.0), "CASH": (0, 0, 0, 0.0, 0.0)}
    tiers = [("TIER_1", 0.0, 10_000.0), ("TIER_2", 10_000.0, 100_000.0), ("TIER_3", 100_000.0, 1e12)]
    rows, n = [], 0
    for ver, (eff_from, eff_to, mult, status) in enumerate(
            [("2024-01-01", "2026-03-31", 1.10, "SUPERSEDED"), ("2026-04-01", None, 1.0, "ACTIVE")], start=1):
        for c in ASSET_CLASSES:
            b1, b2, b3, flat, minf = rates[c]
            for (tier, lo, hi), bps in zip(tiers, (b1, b2, b3)):
                n += 1
                rows.append({"fee_schedule_id": f"FEE-{n:06d}", "asset_class": c, "tier": tier, "min_notional": lo,
                             "max_notional": hi, "commission_bps": round(bps * mult, 4), "flat_fee": flat,
                             "min_fee": minf, "fee_version": ver, "effective_from": eff_from, "effective_to": eff_to,
                             "status": status, "created_by": ADMIN_ID})
    return rows


def gen_constraints(p, portfolios, investors, instruments):
    r = rng(p, "constraints")
    prof = {i["investor_id"]: i["risk_profile"] for i in investors}
    rows, bridge = [], []

    def add(ctype, stype, sid, applies, value, unit, desc):
        cid = f"CON-{len(rows) + 1:06d}"
        rows.append({"constraint_id": cid, "constraint_type": ctype, "scope_type": stype, "scope_id": sid,
                     "applies_to": applies, "value": value, "unit": unit, "severity": "HARD", "description": desc,
                     "effective_from": "2025-01-01", "effective_to": None, "status": "ACTIVE", "created_by": ADMIN_ID})
        return cid
    for c, v in (("EQUITY", 250.0), ("FIXED_INCOME", 500.0), ("REAL_ASSETS", 500.0)):
        add("MIN_TRADE_VALUE", "ASSET_CLASS", c, "ALL_PORTFOLIOS", v, "USD", f"Minimum trade value for {c}")
    add("MAX_TURNOVER_PCT", "GLOBAL", None, "ALL_PORTFOLIOS", p.max_turnover_pct, "PCT_OF_PORTFOLIO",
        "Max one-way turnover per proposal")
    for t, v in (("HIGH", 10.0), ("MEDIUM", 5.0), ("LOW", 2.0)):
        add("MAX_PCT_ADV", "LIQUIDITY_TIER", t, "ALL_PORTFOLIOS", v, "PCT_OF_ADV", f"Max trade as % of ADV, {t} liquidity")
    firm = sorted(x["instrument_id"] for x in instruments if x["is_excluded"])
    for iid in firm:
        add("EXCLUDED_INSTRUMENT", "INSTRUMENT", iid, "ALL_PORTFOLIOS", None, "NONE", "Firm-wide exclusion: no BUY")
    candidates = sorted(x["instrument_id"] for x in instruments if x["asset_class"] != "CASH" and not x["is_excluded"])
    for iid in r.sample(candidates, min(6, len(candidates))):
        cid = add("EXCLUDED_INSTRUMENT", "INSTRUMENT", iid, "LISTED_PORTFOLIOS", None, "NONE", "Client ESG exclusion: no BUY")
        for port in r.sample(portfolios, max(1, round(0.12 * len(portfolios)))):
            bridge.append((port["portfolio_id"], cid))
    cash_cons = {}
    for pr in RISK_PROFILES:
        cash_cons[pr] = add("MIN_CASH_PCT", "RISK_PROFILE", pr, "LISTED_PORTFOLIOS", PROFILE_MIN_CASH[pr],
                            "PCT_OF_PORTFOLIO", f"Minimum cash after trades, {pr}")
    for port in portfolios:
        bridge.append((port["portfolio_id"], cash_cons[prof[port["investor_id"]]]))
    pinc = {x["portfolio_id"]: x["inception_date"] for x in portfolios}
    bridge_rows = []
    for i, (pid, cid) in enumerate(sorted(bridge), start=1):
        bridge_rows.append({"portfolio_constraint_id": f"PC-{i:06d}", "portfolio_id": pid, "constraint_id": cid,
                            "effective_from": max("2025-01-01", pinc[pid]), "effective_to": None})
    return rows, bridge_rows
