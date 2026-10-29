"""Labelled edge-case injection. Valid baseline data is generated first; each defect touches exactly the rows it labels."""
import math

from .engine import calc_fee, fee_row, finalize, _floor_lot
from .generator import rng
from .schema import NON_CASH


def inject_target_defects(p, tables, candidates):
    """Portfolio weights fail to sum to 100%: shift one ACTIVE class target by +/-3 points. Returns list of dicts."""
    r = rng(p, "anomalies-targets")
    k = p.anomaly_count(p.rate_weights_not_100)
    chosen = sorted(r.sample(sorted(candidates), min(k, len(candidates))))
    cur = {}
    for t in tables["target_allocation"]:
        if t["status"] == "ACTIVE":
            cur[(t["portfolio_id"], t["asset_class"])] = t
    out = []
    for pid in chosen:
        cls = r.choice(NON_CASH)
        delta = r.choice([-3.0, 3.0])
        row = cur[(pid, cls)]
        row["target_weight_pct"] = round(row["target_weight_pct"] + delta, 6)
        out.append({"portfolio_id": pid, "asset_class": cls, "delta": delta,
                    "target_id": row["target_id"]})
    return out


def inject_trade_anomalies(ctx, tables, proposals, trades, posts):
    """Mutates trades/proposals in place; returns (ground_truth_rows, new_posts)."""
    p = ctx.p
    r = rng(p, "anomalies-trades")
    thr = p.stale_days_threshold
    hold_by, tgt_by = {}, {}
    for h in tables["holding"]:
        hold_by.setdefault(h["portfolio_id"], []).append(h)
    for t in tables["target_allocation"]:
        if t["status"] == "ACTIVE":
            tgt_by.setdefault(t["portfolio_id"], {})[t["asset_class"]] = t
    prop_by = {pr["proposal_id"]: pr for pr in proposals}
    tby = {}
    for t in trades:
        tby.setdefault(t["proposal_id"], []).append(t)
    used, touched, gt = set(), set(), []

    def pick(pred, k):
        elig = sorted(pid for pid, ts in tby.items() if pid not in used and pred(ts))
        chosen = r.sample(elig, min(k, len(elig)))
        used.update(chosen)
        return chosen

    def label(t, issue, detail):
        gt.append({"entity_type": "Trade", "entity_id": t["trade_id"], "portfolio_id": t["portfolio_id"],
                   "proposal_id": t["proposal_id"], "issue_type": issue, "detail": detail})

    def reprice(t, price, pdate, age):
        t["price_used"], t["price_date_used"], t["price_age_days"] = price, pdate, age
        t["notional"] = round(t["quantity"] * price, 2)
        fr = fee_row(ctx, ctx.aclass(t["instrument_id"]), t["notional"])
        t["fee_schedule_id"], t["estimated_fee"] = fr["fee_schedule_id"], calc_fee(fr, t["notional"])

    # 1. trade exceeds holding
    for pid in pick(lambda ts: any(t["side"] == "SELL" for t in ts), p.anomaly_count(p.rate_trade_exceeds_holding)):
        t = r.choice([x for x in tby[pid] if x["side"] == "SELL"])
        lot = ctx.inst[t["instrument_id"]]["lot_size"]
        hq = t["holding_quantity_before"]
        q = int(math.ceil(hq * r.uniform(1.1, 1.6) / lot) * lot)
        if q <= hq:
            q = int(hq + lot)
        t["quantity"] = q
        reprice(t, t["price_used"], t["price_date_used"], t["price_age_days"])
        touched.add(pid)
        label(t, "TRADE_EXCEEDS_HOLDING", f"SELL {q} vs holding {hq}")

    # 2. excluded instrument recommended
    firm = sorted(ctx.firm_excl)
    for pid in pick(lambda ts: any(t["side"] == "BUY" for t in ts), p.anomaly_count(p.rate_excluded_recommended)):
        t = r.choice([x for x in tby[pid] if x["side"] == "BUY"])
        in_prop = {x["instrument_id"] for x in tby[pid]}
        cls = ctx.aclass(t["instrument_id"])
        pool = [i for i in firm if ctx.aclass(i) == cls and i not in in_prop] or [i for i in firm if i not in in_prop]
        iid = r.choice(pool)
        price, pdate, age = ctx.px[iid]
        ins = ctx.inst[iid]
        lot = ins["lot_size"]
        cap = _floor_lot(ins["avg_daily_volume_units"] * ctx.adv_pct[ins["liquidity_tier"]] / 100.0, lot)
        q = max(lot, min(cap, _floor_lot(t["notional"] / price, lot)))
        held = {h["instrument_id"]: h["quantity"] for h in hold_by[prop_by[pid]["portfolio_id"]]}
        t["instrument_id"], t["quantity"] = iid, int(q)
        t["holding_quantity_before"] = held.get(iid, 0)
        t["stale_price_flag"] = age > thr
        t["liquidity_cap_applied"] = False
        reprice(t, price, pdate, age)
        touched.add(pid)
        label(t, "EXCLUDED_INSTRUMENT_RECOMMENDED", f"BUY of excluded instrument {iid}")

    # 3. fees omitted (fee step skipped for the whole proposal)
    for pid in pick(lambda ts: len(ts) > 0, p.anomaly_count(p.rate_fees_omitted)):
        for t in tby[pid]:
            t["estimated_fee"], t["fee_schedule_id"] = None, None
            label(t, "FEE_OMITTED", "fee not computed")
        touched.add(pid)

    # 4. stale price used without flag
    n = len(ctx.days)
    for pid in pick(lambda ts: any(not t["stale_price_flag"] for t in ts), p.anomaly_count(p.rate_stale_unflagged)):
        t = r.choice([x for x in tby[pid] if not x["stale_price_flag"]])
        iid = t["instrument_id"]
        j = (n - 1 - ctx.px[iid][2]) - r.randint(5, 9)
        while j >= 0 and ctx.series[iid][j] is None:
            j -= 1
        if j < 0:
            used.discard(pid)
            continue
        reprice(t, ctx.series[iid][j], ctx.days[j].isoformat(), n - 1 - j)
        t["stale_price_flag"] = False
        touched.add(pid)
        label(t, "STALE_PRICE_UNFLAGGED", f"price {n - 1 - j} trading days old, flag=false")

    keep = [x for x in posts if x["proposal_id"] not in touched]
    for pid in sorted(touched):
        pr = prop_by[pid]
        _, newp = finalize(ctx, pr, tby[pid], hold_by[pr["portfolio_id"]], tgt_by[pr["portfolio_id"]])
        keep += newp
    keep.sort(key=lambda x: x["post_alloc_id"])
    return gt, keep
