"""End-to-end build: master data -> prices -> targets -> holdings -> policy -> engine -> lifecycle -> anomalies -> ground truth."""
from . import anomalies as A
from . import engine as E
from . import generator as G
from .schema import ISSUE_TYPES


def build(p):
    inv = G.gen_investors(p)
    ports = G.gen_portfolios(p, inv)
    ins = G.gen_instruments(p)
    prices, series, days, px, stale_ids, missing = G.gen_prices(p, ins)
    targets = G.gen_targets(p, ports, inv)
    holdings = G.gen_holdings(p, ports, ins, targets, days, series, px)
    fees = G.gen_fee_schedule(p)
    cons, bridge = G.gen_constraints(p, ports, inv, ins)
    T = {"investor_profile": inv, "portfolio": ports, "instrument": ins, "market_price": prices,
         "holding": holdings, "target_allocation": targets, "fee_schedule": fees, "constraint": cons,
         "portfolio_constraint": bridge}
    ctx = E.Ctx(p, T, series, days, px)

    # candidates for the target-weight defect: ACTIVE portfolios that breach under the valid targets
    hold_by, tgt_by = {}, {}
    for h in holdings:
        hold_by.setdefault(h["portfolio_id"], []).append(h)
    for t in targets:
        if t["status"] == "ACTIVE":
            tgt_by.setdefault(t["portfolio_id"], {})[t["asset_class"]] = t
    cands = [x["portfolio_id"] for x in ports if x["status"] == "ACTIVE"
             and E.compute_drift(ctx, x["portfolio_id"], hold_by[x["portfolio_id"]], tgt_by[x["portfolio_id"]])[2]]
    bad_targets = A.inject_target_defects(p, T, cands)
    bad_pids = {b["portfolio_id"] for b in bad_targets}

    proposals, trades, posts, drifts = E.run_engine(ctx, T)
    events = E.build_events(p, proposals, trades, ports, inv)
    gt_trade, posts = A.inject_trade_anomalies(ctx, T, proposals, trades, posts)

    T.update({"rebalance_proposal": proposals, "trade": trades, "proposal_event": events,
              "drift_snapshot": drifts, "post_trade_allocation": posts})

    # ------------------------------------------------------------------ ground truth (kept out of inputs)
    gt = []

    def add(cat, etype, eid, issue, decision, pid="", prop="", detail=""):
        gt.append({"gt_id": f"GT-{len(gt) + 1:06d}", "label_category": cat, "entity_type": etype, "entity_id": eid,
                   "portfolio_id": pid, "proposal_id": prop, "issue_type": issue, "expected_decision": decision,
                   "detail": detail})
    prop_of = {pr["portfolio_id"]: pr["proposal_id"] for pr in proposals}
    for b in bad_targets:
        add("INJECTED_ANOMALY", "Portfolio", b["portfolio_id"], "TARGET_WEIGHTS_NOT_100", "BLOCK_INVALID_TARGET",
            b["portfolio_id"], prop_of.get(b["portfolio_id"], ""), f"{b['asset_class']} target shifted {b['delta']:+.1f} pts")
    for g in gt_trade:
        add("INJECTED_ANOMALY", g["entity_type"], g["entity_id"], g["issue_type"], "REJECT_PROPOSAL",
            g["portfolio_id"], g["proposal_id"], g["detail"])
    breach = {}
    for d in drifts:
        breach[d["portfolio_id"]] = breach.get(d["portfolio_id"], False) or d["breach_flag"]
    for x in ports:
        pid = x["portfolio_id"]
        if pid in bad_pids:
            dec = "BLOCK_INVALID_TARGET"
        elif not breach[pid]:
            dec = "NO_ACTION"
        else:
            dec = "BLOCK_FROZEN" if x["status"] != "ACTIVE" else "REBALANCE"
        add("EXPECTED_DECISION", "Portfolio", pid, "NONE", dec, pid, prop_of.get(pid, ""),
            "decision from documented rules")
        if x["status"] == "FROZEN":
            add("EXPECTED_EXCEPTION", "Portfolio", pid, "PORTFOLIO_FROZEN_KYC_EXPIRED", "BLOCK_FROZEN", pid,
                prop_of.get(pid, ""), "KYC expired")
    for iid in stale_ids:
        add("EXPECTED_EXCEPTION", "Instrument", iid, "STALE_PRICE_INSTRUMENT", "FLAG_AND_ESCALATE", detail=f"{px[iid][2]} trading days stale")
    for iid, d in missing:
        add("EXPECTED_EXCEPTION", "MarketPrice", f"PX-{iid}-{d.replace('-', '')}", "MISSING_PRICE", "CARRY_FORWARD_AND_AGE", detail="no close")
    for t in trades:
        if t["liquidity_cap_applied"]:
            add("EXPECTED_EXCEPTION", "Trade", t["trade_id"], "LIQUIDITY_CAP_APPLIED", "REDUCE_TO_ADV_CAP",
                t["portfolio_id"], t["proposal_id"], "trade quantity capped at % of ADV")
        if t["stale_price_flag"]:
            add("EXPECTED_EXCEPTION", "Trade", t["trade_id"], "STALE_PRICE_FLAGGED", "FLAG_AND_ESCALATE",
                t["portfolio_id"], t["proposal_id"], "stale price correctly flagged")
    meta = {"stale_instruments": stale_ids, "issue_types": ISSUE_TYPES}
    return T, gt, meta
