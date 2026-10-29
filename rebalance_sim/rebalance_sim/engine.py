"""Rebalancing engine: valuation, drift, policy-constrained trade planning, fees, post-trade simulation, lifecycle.

Policy summary (documented rules; every outcome in the data comes from these):
  1. Value holdings with the last OBSERVED price on/before as_of (carry-forward). Price older than 3 trading days => STALE (flagged).
  2. drift = current weight - target weight per asset class. Breach when abs(drift) > tolerance band.
  3. Breach + ACTIVE portfolio  => rebalance within the asset class, pro rata to existing position values.
     Breach + FROZEN portfolio  => BLOCKED proposal, no trades (exception path).
  4. Constraints: excluded instruments may be sold but never bought; min trade value per asset class; trade <= x% of ADV by
     liquidity tier; lot size; SELL <= holding; one-way turnover <= cap; cash after trades >= min cash for the risk profile.
  5. Fee = max(min_fee, flat + notional*bps/10000) from the FeeSchedule tier that contains the notional.
  6. Cash is the residual: cash_after = cash + sells - buys - fees.
"""
import datetime as dt
import math

from .schema import ASSET_CLASSES, NON_CASH

CLASS_ORDER = {c: i for i, c in enumerate(ASSET_CLASSES)}
POLICY_VERSION = "POLICY-2026.10"


class Ctx:
    def __init__(self, p, tables, series, days, px):
        self.p, self.as_of = p, p.as_of_date
        self.series, self.days, self.px = series, days, px
        self.inst = {r["instrument_id"]: r for r in tables["instrument"]}
        fees = {}
        for r in tables["fee_schedule"]:
            if (r["status"] == "ACTIVE" and r["effective_from"] <= self.as_of
                    and (r["effective_to"] is None or r["effective_to"] >= self.as_of)):
                fees.setdefault(r["asset_class"], []).append(r)
        for v in fees.values():
            v.sort(key=lambda r: r["min_notional"])
        self.fees = fees
        listed = {}
        for b in tables["portfolio_constraint"]:
            listed.setdefault(b["constraint_id"], set()).add(b["portfolio_id"])
        self.min_trade, self.adv_pct = {}, {}
        self.max_turnover = p.max_turnover_pct
        self.firm_excl, self.client_excl, self.min_cash = set(), {}, {}
        for c in tables["constraint"]:
            if c["status"] != "ACTIVE":
                continue
            t = c["constraint_type"]
            if t == "MIN_TRADE_VALUE":
                self.min_trade[c["scope_id"]] = c["value"]
            elif t == "MAX_TURNOVER_PCT":
                self.max_turnover = c["value"]
            elif t == "MAX_PCT_ADV":
                self.adv_pct[c["scope_id"]] = c["value"]
            elif t == "EXCLUDED_INSTRUMENT":
                if c["applies_to"] == "ALL_PORTFOLIOS":
                    self.firm_excl.add(c["scope_id"])
                else:
                    for pid in listed.get(c["constraint_id"], ()):
                        self.client_excl.setdefault(pid, set()).add(c["scope_id"])
            elif t == "MIN_CASH_PCT":
                for pid in listed.get(c["constraint_id"], ()):
                    self.min_cash[pid] = c["value"]

    def aclass(self, iid):
        return self.inst[iid]["asset_class"]


def fee_row(ctx, asset_class, notional):
    rows = ctx.fees[asset_class]
    for r in rows:
        if r["min_notional"] <= notional < r["max_notional"]:
            return r
    return rows[-1]


def calc_fee(row, notional):
    return round(max(row["min_fee"], row["flat_fee"] + notional * row["commission_bps"] / 10000.0), 2)


def class_values(ctx, hrows):
    d = {c: 0.0 for c in ASSET_CLASSES}
    for h in hrows:
        d[ctx.aclass(h["instrument_id"])] += h["market_value"]
    return d


def compute_drift(ctx, pid, hrows, tg):
    """tg: asset_class -> target row. Returns (snapshot rows, max abs drift, breach, total value)."""
    cv = class_values(ctx, hrows)
    V = sum(cv.values())
    rows, mx, breach = [], 0.0, False
    for c in ASSET_CLASSES:
        w = cv[c] / V * 100.0
        drift = w - tg[c]["target_weight_pct"]
        band = tg[c]["tolerance_band_pct"]
        b = abs(drift) > band + 1e-9
        breach = breach or b
        mx = max(mx, abs(drift))
        rows.append({"snapshot_id": f"SNAP-{pid}-{c}", "portfolio_id": pid, "as_of_date": ctx.as_of, "asset_class": c,
                     "current_value": round(cv[c], 2), "current_weight_pct": round(w, 6),
                     "target_weight_pct": tg[c]["target_weight_pct"], "drift_pct": round(drift, 6),
                     "tolerance_band_pct": band, "breach_flag": b})
    return rows, mx, breach, V


def _floor_lot(x, lot):
    return int(math.floor(x / lot + 1e-9) * lot)


def plan_trades(ctx, pid, hrows, tg, V, cv, min_cash_pct):
    """Returns (drafts, suppressed_count, no_eligible_flag)."""
    thr = ctx.p.stale_days_threshold
    drafts, suppressed, no_elig = [], 0, False
    excluded = ctx.firm_excl | ctx.client_excl.get(pid, set())

    def make(h, side, qty, c):
        iid = h["instrument_id"]
        return {"iid": iid, "side": side, "qty": qty, "price": h["price_used"], "pdate": h["price_date_used"],
                "age": h["price_age_days"], "stale": h["price_age_days"] > thr, "capped": False, "cls": c}

    def cap_qty(h, qty):
        ins = ctx.inst[h["instrument_id"]]
        cap_units = ins["avg_daily_volume_units"] * ctx.adv_pct[ins["liquidity_tier"]] / 100.0
        capq = _floor_lot(cap_units, ins["lot_size"])
        return (capq, True) if qty > capq else (qty, False)

    for c in NON_CASH:
        D_ = tg[c]["target_weight_pct"] / 100.0 * V - cv[c]
        held = [h for h in hrows if ctx.aclass(h["instrument_id"]) == c]
        if abs(D_) < 1e-9 or not held or cv[c] <= 0:
            continue
        if D_ < 0:
            cands, need, side = held, -D_, "SELL"
        else:
            cands = [h for h in held if h["instrument_id"] not in excluded and ctx.inst[h["instrument_id"]]["status"] == "ACTIVE"]
            need, side = D_, "BUY"
            if not cands:
                no_elig = True
                continue
        base = sum(h["market_value"] for h in cands)
        for h in cands:
            lot = ctx.inst[h["instrument_id"]]["lot_size"]
            share = need * h["market_value"] / base
            qty = _floor_lot(share / h["price_used"], lot)
            if side == "SELL":
                qty = min(qty, _floor_lot(h["quantity"], lot))
            qty, capped = cap_qty(h, qty)
            if qty < lot:
                continue
            if qty * h["price_used"] < ctx.min_trade[c]:
                suppressed += 1
                continue
            d = make(h, side, qty, c)
            d["capped"] = capped
            drafts.append(d)

    def notional(d):
        return d["qty"] * d["price"]

    def rescale(ds, side, f):
        out = []
        for d in ds:
            if d["side"] != side:
                out.append(d)
                continue
            lot = ctx.inst[d["iid"]]["lot_size"]
            q = _floor_lot(d["qty"] * f, lot)
            if q < lot or q * d["price"] < ctx.min_trade[d["cls"]]:
                continue
            d = dict(d)
            d["qty"] = q
            out.append(d)
        return out

    # turnover cap
    b = sum(notional(d) for d in drafts if d["side"] == "BUY")
    s = sum(notional(d) for d in drafts if d["side"] == "SELL")
    turnover = (b + s) / (2 * V) * 100.0
    if turnover > ctx.max_turnover:
        f = ctx.max_turnover / turnover * 0.999
        drafts = rescale(rescale(drafts, "BUY", f), "SELL", f)

    # minimum cash: scale buys down until cash after trades >= floor
    cash_before = cv["CASH"]
    floor = min_cash_pct / 100.0 * V

    def totals(ds):
        bb = ss = ff = fb = 0.0
        for d in ds:
            n = d["qty"] * d["price"]
            fee = calc_fee(fee_row(ctx, d["cls"], round(n, 2)), round(n, 2))
            ff += fee
            if d["side"] == "BUY":
                bb += n
                fb += fee
            else:
                ss += n
        return bb, ss, ff, fb

    for _ in range(12):
        bb, ss, ff, fb = totals(drafts)
        if bb == 0 or cash_before + ss - bb - ff >= floor - 1e-6:
            break
        avail = cash_before + ss - (ff - fb) - floor
        if avail <= 0:
            drafts = [d for d in drafts if d["side"] == "SELL"]
            break
        drafts = rescale(drafts, "BUY", min(0.98, 0.98 * avail / (bb + fb)))
    else:
        drafts = [d for d in drafts if d["side"] == "SELL"]
    return drafts, suppressed, no_elig


def finalize(ctx, prop, trades, hrows, tg):
    """Recompute every derived field of a proposal from holdings, trades and prices. Returns (proposal, post rows)."""
    V = sum(h["market_value"] for h in hrows)
    qty = {h["instrument_id"]: h["quantity"] for h in hrows}
    price = {h["instrument_id"]: h["price_used"] for h in hrows}
    cash_ids = sorted(h["instrument_id"] for h in hrows if ctx.aclass(h["instrument_id"]) == "CASH")
    buys = sells = fees = 0.0
    for t in trades:
        sign = 1 if t["side"] == "BUY" else -1
        qty[t["instrument_id"]] = qty.get(t["instrument_id"], 0) + sign * t["quantity"]
        price.setdefault(t["instrument_id"], t["price_used"])
        if t["side"] == "BUY":
            buys += t["notional"]
        else:
            sells += t["notional"]
        fees += t["estimated_fee"] or 0.0
    qty[cash_ids[0]] = round(qty[cash_ids[0]] + round(sells - buys - fees, 2), 2)
    pre = {c: 0.0 for c in ASSET_CLASSES}
    post = {c: 0.0 for c in ASSET_CLASSES}
    for h in hrows:
        pre[ctx.aclass(h["instrument_id"])] += h["market_value"]
    for iid, q in qty.items():
        post[ctx.aclass(iid)] += q * price[iid]
    Vp = sum(post.values())
    posts, pre_mx, post_mx = [], 0.0, 0.0
    for c in ASSET_CLASSES:
        t = tg[c]["target_weight_pct"]
        w0, w1 = pre[c] / V * 100.0, post[c] / Vp * 100.0
        pre_mx, post_mx = max(pre_mx, abs(w0 - t)), max(post_mx, abs(w1 - t))
        posts.append({"post_alloc_id": f"PTA-{prop['proposal_id']}-{c}", "proposal_id": prop["proposal_id"],
                      "asset_class": c, "pre_weight_pct": round(w0, 6), "post_weight_pct": round(w1, 6),
                      "target_weight_pct": t, "pre_drift_pct": round(w0 - t, 6), "post_drift_pct": round(w1 - t, 6),
                      "post_value": round(post[c], 2)})
    prop.update({
        "target_weight_sum_pct": round(sum(tg[c]["target_weight_pct"] for c in ASSET_CLASSES), 6),
        "portfolio_value": round(V, 2), "post_trade_value": round(Vp, 2),
        "pre_max_abs_drift_pct": round(pre_mx, 6), "post_max_abs_drift_pct": round(post_mx, 6),
        "drift_reduction_pct": round((pre_mx - post_mx) / pre_mx * 100.0, 6) if pre_mx > 0 else 0.0,
        "num_trades": len(trades), "total_buy_value": round(buys, 2), "total_sell_value": round(sells, 2),
        "total_estimated_fees": round(fees, 2), "turnover_pct": round((buys + sells) / 2 / V * 100.0, 6),
        "cash_after": round(post["CASH"], 2),
        "price_stale_count": sum(1 for t in trades if t["stale_price_flag"]),
        "liquidity_capped_count": sum(1 for t in trades if t["liquidity_cap_applied"]),
    })
    return prop, posts


def run_engine(ctx, tables):
    p, year = ctx.p, ctx.p.as_of_date[:4]
    hold_by, tgt_by = {}, {}
    for h in tables["holding"]:
        hold_by.setdefault(h["portfolio_id"], []).append(h)
    for t in tables["target_allocation"]:
        if t["status"] == "ACTIVE":
            tgt_by.setdefault(t["portfolio_id"], {})[t["asset_class"]] = t
    proposals, trades, posts, drifts = [], [], [], []
    seq = 0
    for port in sorted(tables["portfolio"], key=lambda r: r["portfolio_id"]):
        pid = port["portfolio_id"]
        hrows = sorted(hold_by[pid], key=lambda h: h["instrument_id"])
        tg = tgt_by[pid]
        drows, _, breach, V = compute_drift(ctx, pid, hrows, tg)
        drifts += drows
        if not breach:
            continue
        seq += 1
        prop_id = f"RB-{year}-{seq:06d}"
        frozen = port["status"] != "ACTIVE"
        min_cash_pct = ctx.min_cash[pid]
        drafts, suppressed, no_elig = ([], 0, False) if frozen else plan_trades(
            ctx, pid, hrows, tg, V, class_values(ctx, hrows), min_cash_pct)
        drafts.sort(key=lambda d: (CLASS_ORDER[d["cls"]], d["iid"]))
        held_qty = {h["instrument_id"]: h["quantity"] for h in hrows}
        trs = []
        for n, d in enumerate(drafts, start=1):
            notional = round(d["qty"] * d["price"], 2)
            fr = fee_row(ctx, d["cls"], notional)
            trs.append({"trade_id": f"TRD-{prop_id}-{n:02d}", "proposal_id": prop_id, "portfolio_id": pid,
                        "instrument_id": d["iid"], "side": d["side"], "quantity": d["qty"],
                        "holding_quantity_before": held_qty.get(d["iid"], 0), "price_used": d["price"],
                        "price_date_used": d["pdate"], "price_age_days": d["age"], "stale_price_flag": d["stale"],
                        "notional": notional, "fee_schedule_id": fr["fee_schedule_id"],
                        "estimated_fee": calc_fee(fr, notional), "liquidity_cap_applied": d["capped"],
                        "trade_status": "PROPOSED"})
        prop = {"proposal_id": prop_id, "portfolio_id": pid, "as_of_date": p.as_of_date,
                "generated_at": f"{p.as_of_date}T18:00:00Z",
                "trigger_reason": "PORTFOLIO_FROZEN" if frozen else "DRIFT_BREACH", "status": "DRAFT",
                "policy_version": POLICY_VERSION, "min_cash_required": round(min_cash_pct / 100.0 * V, 2),
                "suppressed_trade_count": suppressed}
        prop, prows = finalize(ctx, prop, trs, hrows, tg)
        reasons = []
        if not frozen:
            if prop["price_stale_count"]:
                reasons.append("STALE_PRICE")
            if prop["liquidity_capped_count"]:
                reasons.append("LIQUIDITY_CAP")
            if prop["total_buy_value"] + prop["total_sell_value"] > p.high_notional_usd:
                reasons.append("HIGH_NOTIONAL")
            if prop["turnover_pct"] > p.high_turnover_pct:
                reasons.append("HIGH_TURNOVER")
            if no_elig:
                reasons.append("NO_ELIGIBLE_BUY_INSTRUMENT")
        prop["requires_compliance_review"] = bool(reasons)
        prop["review_reasons"] = "|".join(reasons) if reasons else None
        proposals.append(prop)
        trades += trs
        posts += prows
    return proposals, trades, posts, drifts


def build_events(p, proposals, trades, portfolios, investors):
    """Lifecycle event log. Decisions follow documented rules (see README 'Lifecycle rules')."""
    inv = {i["investor_id"]: i for i in investors}
    port_inv = {x["portfolio_id"]: x["investor_id"] for x in portfolios}
    tby = {}
    for t in trades:
        tby.setdefault(t["proposal_id"], []).append(t)
    base = dt.datetime.fromisoformat(p.as_of_date + "T18:00:00")
    ops = [f"USR-OPS-{k:03d}" for k in range(1, 6)]
    cmp_ = [f"USR-CMP-{k:03d}" for k in range(1, 4)]
    events = []

    def ev(pr, frm, to, role, actor, delta, code):
        events.append({"event_id": f"EVT-{len(events) + 1:06d}", "proposal_id": pr["proposal_id"],
                       "event_ts": (base + delta).strftime("%Y-%m-%dT%H:%M:%SZ"), "from_status": frm,
                       "to_status": to, "actor_role": role, "actor_id": actor, "reason_code": code})
        pr["status"] = to

    H = lambda x: dt.timedelta(hours=x)
    for i, pr in enumerate(proposals):
        ev(pr, None, "DRAFT", "SYSTEM", "SYSTEM", H(0), "PROPOSAL_GENERATED")
        if pr["trigger_reason"] == "PORTFOLIO_FROZEN":
            ev(pr, "DRAFT", "BLOCKED", "SYSTEM", "SYSTEM", dt.timedelta(minutes=5), "PORTFOLIO_FROZEN_KYC_EXPIRED")
            continue
        ev(pr, "DRAFT", "PENDING_OPS_REVIEW", "SYSTEM", "SYSTEM", dt.timedelta(minutes=5), "SUBMITTED_FOR_OPS_REVIEW")
        analyst, comp = ops[i % len(ops)], cmp_[i % len(cmp_)]
        trs = tby.get(pr["proposal_id"], [])
        approved_at = None
        if pr["num_trades"] == 0:
            ev(pr, "PENDING_OPS_REVIEW", "REJECTED", "OPS_ANALYST", analyst, H(2), "NO_EXECUTABLE_TRADES")
        elif pr["drift_reduction_pct"] < 25.0:
            ev(pr, "PENDING_OPS_REVIEW", "REJECTED", "OPS_ANALYST", analyst, H(2), "INSUFFICIENT_DRIFT_REDUCTION")
        elif pr["requires_compliance_review"]:
            ev(pr, "PENDING_OPS_REVIEW", "PENDING_COMPLIANCE_REVIEW", "OPS_ANALYST", analyst, H(2),
               "ESCALATED_" + pr["review_reasons"].replace("|", "_"))
            if pr["portfolio_value"] > 1_000_000:
                continue                       # large-portfolio committee backlog: stays pending
            notional = sum(t["notional"] for t in trs) or 1.0
            stale_share = sum(t["notional"] for t in trs if t["stale_price_flag"]) / notional
            if stale_share > 0.25:
                ev(pr, "PENDING_COMPLIANCE_REVIEW", "REJECTED", "RISK_COMPLIANCE", comp, H(26), "STALE_PRICE_CONCENTRATION")
            else:
                ev(pr, "PENDING_COMPLIANCE_REVIEW", "APPROVED", "RISK_COMPLIANCE", comp, H(26), "COMPLIANCE_APPROVED")
                approved_at = 26
        else:
            ev(pr, "PENDING_OPS_REVIEW", "APPROVED", "OPS_ANALYST", analyst, H(2), "OPS_APPROVED")
            approved_at = 2
        if approved_at is None or pr["status"] != "APPROVED":
            continue
        investor = inv[port_inv[pr["portfolio_id"]]]
        if investor["kyc_status"] == "PENDING":
            continue                           # customer cannot accept until KYC is refreshed
        fee_ratio = pr["total_estimated_fees"] / pr["portfolio_value"] * 100.0
        if fee_ratio <= 0.25 and pr["turnover_pct"] <= 15.0:
            ev(pr, "APPROVED", "CUSTOMER_ACCEPTED", "CUSTOMER", investor["investor_id"], H(approved_at + 20), "CUSTOMER_ACCEPTED_LOW_COST")
            ev(pr, "CUSTOMER_ACCEPTED", "EXECUTED_SIMULATED", "SYSTEM", "SYSTEM", H(approved_at + 44), "SIMULATED_EXECUTION")
        else:
            ev(pr, "APPROVED", "EXPIRED", "SYSTEM", "SYSTEM", H(approved_at + 120), "CUSTOMER_NO_RESPONSE_EXPIRED")
    final = {pr["proposal_id"]: pr["status"] for pr in proposals}
    from .schema import TRADE_STATUS_FROM_PROPOSAL
    for t in trades:
        t["trade_status"] = TRADE_STATUS_FROM_PROPOSAL.get(final[t["proposal_id"]], "PROPOSED")
    return events
