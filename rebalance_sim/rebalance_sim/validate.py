"""Independent validation. Reads only the exported CSVs (never the generator's in-memory objects or the ground truth).

Two result kinds:
  * checks   - structural / reconciliation checks. Any FAIL means a generator or export bug.
  * findings - business-rule violations found in the data (these include the deliberately injected anomalies).
"""
import csv
import datetime as dt
import json
import os
import re

from .schema import (ENTITIES, ID_PATTERNS, ASSET_CLASSES, TRANSITIONS, TRADE_STATUS_FROM_PROPOSAL)

TOL_MONEY, TOL_W = 0.011, 1e-4


def _parse(t, v):
    if v == "":
        return None
    if t == "INTEGER":
        return int(v)
    if t == "REAL":
        return float(v)
    if t == "BOOLEAN":
        return v == "true"
    return v


def load_tables(data_dir):
    T, header_bad = {}, []
    for e in ENTITIES:
        with open(os.path.join(data_dir, "csv", e.file), newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            if rd.fieldnames != [x.name for x in e.fields]:
                header_bad.append(e.table)
            T[e.table] = [{x.name: _parse(x.type, r[x.name]) for x in e.fields} for r in rd]
    return T, header_bad


def validate(data_dir, p):
    T, header_bad = load_tables(data_dir)
    checks, findings = [], []
    as_of = p.as_of_date
    thr = p.stale_days_threshold

    def chk(cid, cat, desc, bad, total, examples=()):
        checks.append({"check_id": cid, "category": cat, "description": desc, "rows_checked": total,
                       "violations": bad, "status": "PASS" if bad == 0 else "FAIL", "examples": list(examples)[:5]})

    def find(issue, etype, eid, pid, prop, detail):
        findings.append({"issue_type": issue, "entity_type": etype, "entity_id": eid, "portfolio_id": pid,
                         "proposal_id": prop, "detail": detail})

    chk("SCH-001", "schema", "CSV headers match the data dictionary", len(header_bad), len(ENTITIES), header_bad)

    # ---- primary keys, natural keys
    for e in ENTITIES:
        keys = [tuple(r[k] for k in e.pk) for r in T[e.table]]
        chk(f"PK-{e.table}", "primary_key", f"{e.table}: primary key unique and non-null", len(keys) - len(set(keys)) + sum(None in k for k in keys), len(keys))
        for uk in e.unique_keys:
            vals = [tuple(r[c] for c in uk) for r in T[e.table]]
            chk(f"DUP-{e.table}-{'_'.join(uk)}", "duplicates", f"{e.table}: no duplicate ({', '.join(uk)})", len(vals) - len(set(vals)), len(vals))
    # ---- id formats
    for tb, cols in ID_PATTERNS.items():
        for col, pat in cols.items():
            rx = re.compile(pat + r"$")
            bad = [r[col] for r in T[tb] if not rx.match(r[col] or "")]
            chk(f"ID-{tb}-{col}", "id_format", f"{tb}.{col} matches {pat}", len(bad), len(T[tb]), bad)
    pid_ok = [x for x in T["portfolio"] if x["portfolio_id"] != f"PORT-{x['investor_id']}-{x['portfolio_seq']:02d}"]
    chk("ID-portfolio-composition", "id_format", "portfolio_id = PORT-<investor_id>-<seq>", len(pid_ok), len(T["portfolio"]))
    hid = [h for h in T["holding"] if h["holding_id"] != f"HOLD-{h['portfolio_id']}-{h['instrument_id']}"]
    chk("ID-holding-composition", "id_format", "holding_id = HOLD-<portfolio_id>-<instrument_id>", len(hid), len(T["holding"]))
    # ---- foreign keys
    for e in ENTITIES:
        for col, pt, pc in e.fks:
            parents = {r[pc] for r in T[pt]}
            bad = [r[e.pk[0]] for r in T[e.table] if r[col] is not None and r[col] not in parents]
            chk(f"FK-{e.table}-{col}", "foreign_key", f"{e.table}.{col} -> {pt}.{pc}", len(bad), len(T[e.table]), bad)
    # Orphan rows are reported above; exclude them from later checks so one broken join does not crash the run.
    orig_counts = {e.table: len(T[e.table]) for e in ENTITIES}
    for e in ENTITIES:
        for col, pt, pc in e.fks:
            parents = {r[pc] for r in T[pt]}
            T[e.table] = [r for r in T[e.table] if r[col] is None or r[col] in parents]
    # ---- enums and required
    for e in ENTITIES:
        bad_req = bad_enum = 0
        ex = []
        for r in T[e.table]:
            for f in e.fields:
                v = r[f.name]
                if f.required and v is None:
                    bad_req += 1
                    ex.append(f"{e.table}.{f.name}")
                if v is not None and isinstance(f.allowed, list) and v not in f.allowed:
                    bad_enum += 1
                    ex.append(f"{e.table}.{f.name}={v}")
        chk(f"REQ-{e.table}", "required", f"{e.table}: required fields populated", bad_req, len(T[e.table]), ex)
        chk(f"ENUM-{e.table}", "enum", f"{e.table}: values within allowed enums", bad_enum, len(T[e.table]), ex)

    inv = {r["investor_id"]: r for r in T["investor_profile"]}
    port = {r["portfolio_id"]: r for r in T["portfolio"]}
    inst = {r["instrument_id"]: r for r in T["instrument"]}
    prop = {r["proposal_id"]: r for r in T["rebalance_proposal"]}
    hold = {(h["portfolio_id"], h["instrument_id"]): h for h in T["holding"]}
    hold_by = {}
    for h in T["holding"]:
        hold_by.setdefault(h["portfolio_id"], []).append(h)
    tgt_cur = {}
    for t in T["target_allocation"]:
        if t["status"] == "ACTIVE":
            tgt_cur.setdefault(t["portfolio_id"], {})[t["asset_class"]] = t

    # ---- date ordering
    d1 = [x["portfolio_id"] for x in T["portfolio"] if not (inv[x["investor_id"]]["created_date"] < x["inception_date"] <= as_of)]
    chk("DATE-001", "date_order", "investor created_date < portfolio inception_date <= as_of", len(d1), len(T["portfolio"]), d1)
    d2 = [h["holding_id"] for h in T["holding"] if not (port[h["portfolio_id"]]["inception_date"] <= h["acquired_date"] <= as_of)]
    chk("DATE-002", "date_order", "inception_date <= holding acquired_date <= as_of", len(d2), len(T["holding"]), d2)
    d3 = [t["target_id"] for t in T["target_allocation"] if t["effective_to"] is not None and t["effective_to"] < t["effective_from"]]
    byv = {}
    for t in T["target_allocation"]:
        byv.setdefault((t["portfolio_id"], t["asset_class"]), []).append(t)
    for v in byv.values():
        v.sort(key=lambda r: r["version"])
        for a, b in zip(v, v[1:]):
            if a["effective_to"] is None or a["effective_to"] >= b["effective_from"] or a["status"] != "SUPERSEDED":
                d3.append(a["target_id"])
        if v[-1]["status"] != "ACTIVE" or v[-1]["effective_to"] is not None:
            d3.append(v[-1]["target_id"])
    chk("DATE-003", "date_order", "target effective ranges ordered; one ACTIVE version, earlier versions SUPERSEDED", len(d3), len(T["target_allocation"]), d3)
    first_px = min(r["price_date"] for r in T["market_price"])
    d4 = [i["instrument_id"] for i in T["instrument"] if i["listing_date"] >= first_px]
    chk("DATE-004", "date_order", "instrument listing_date before first price_date", len(d4), len(T["instrument"]), d4)
    d5 = [i["investor_id"] for i in T["investor_profile"] if (i["kyc_status"] == "EXPIRED") != (i["kyc_expiry_date"] < as_of)]
    chk("DATE-005", "date_order", "kyc_expiry_date < as_of iff kyc_status = EXPIRED", len(d5), len(T["investor_profile"]), d5)
    d6 = [x["portfolio_id"] for x in T["portfolio"] if (x["status"] == "FROZEN") != (inv[x["investor_id"]]["kyc_status"] == "EXPIRED")]
    chk("DEP-001", "dependency", "portfolio FROZEN iff investor KYC EXPIRED", len(d6), len(T["portfolio"]), d6)
    wk = [r["price_id"] for r in T["market_price"] if dt.date.fromisoformat(r["price_date"]).weekday() >= 5]
    chk("DATE-006", "date_order", "all price dates are weekdays", len(wk), len(T["market_price"]), wk)

    # ---- market price consistency
    days = sorted({r["price_date"] for r in T["market_price"]})
    didx = {d: i for i, d in enumerate(days)}
    last_obs = {}
    bad_px = []
    for r in T["market_price"]:
        if (r["close_price"] is None) != (r["price_status"] == "MISSING"):
            bad_px.append(r["price_id"])
        if r["price_status"] == "OBSERVED" and r["price_date"] <= as_of:
            if r["instrument_id"] not in last_obs or r["price_date"] > last_obs[r["instrument_id"]][0]:
                last_obs[r["instrument_id"]] = (r["price_date"], r["close_price"])
    chk("PX-001", "arithmetic", "close_price null iff MISSING", len(bad_px), len(T["market_price"]), bad_px)
    per_inst = {}
    for r in T["market_price"]:
        per_inst[r["instrument_id"]] = per_inst.get(r["instrument_id"], 0) + 1
    chk("PX-002", "coverage", f"every instrument has {p.n_days} daily price rows",
        sum(1 for i in inst if per_inst.get(i) != p.n_days), len(inst))
    aidx = didx[as_of]

    def age_of(d):
        return aidx - didx[d]

    # ---- holdings reconciliation
    bad_mv, bad_price, bad_w, bad_flag = [], [], [], []
    tot = {}
    for h in T["holding"]:
        lo = last_obs[h["instrument_id"]]
        if abs(h["price_used"] - lo[1]) > 1e-9 or h["price_date_used"] != lo[0] or h["price_age_days"] != age_of(lo[0]):
            bad_price.append(h["holding_id"])
        if h["stale_price_flag"] != (h["price_age_days"] > thr):
            bad_flag.append(h["holding_id"])
        if abs(h["market_value"] - round(h["quantity"] * h["price_used"], 2)) > TOL_MONEY:
            bad_mv.append(h["holding_id"])
        tot[h["portfolio_id"]] = tot.get(h["portfolio_id"], 0.0) + h["market_value"]
    for h in T["holding"]:
        if abs(h["current_weight_pct"] - h["market_value"] / tot[h["portfolio_id"]] * 100) > TOL_W:
            bad_w.append(h["holding_id"])
    chk("HLD-001", "arithmetic", "holding price_used/date/age equals last observed MarketPrice", len(bad_price), len(T["holding"]), bad_price)
    chk("HLD-002", "arithmetic", "holding stale flag = age > threshold", len(bad_flag), len(T["holding"]), bad_flag)
    chk("HLD-003", "arithmetic", "market_value = quantity x price_used", len(bad_mv), len(T["holding"]), bad_mv)
    chk("HLD-004", "arithmetic", "current_weight_pct = market_value / portfolio total", len(bad_w), len(T["holding"]), bad_w)
    wsum = [pid for pid in port if abs(sum(h["current_weight_pct"] for h in hold_by[pid]) - 100) > 1e-3]
    chk("HLD-005", "arithmetic", "current holding weights sum to 100% per portfolio", len(wsum), len(port), wsum)
    miss = [pid for pid in port if {inst[h["instrument_id"]]["asset_class"] for h in hold_by.get(pid, [])} != set(ASSET_CLASSES)]
    chk("HLD-006", "coverage", "every portfolio holds all four asset classes", len(miss), len(port), miss)

    # ---- drift snapshot recompute
    cv = {}
    for h in T["holding"]:
        k = (h["portfolio_id"], inst[h["instrument_id"]]["asset_class"])
        cv[k] = cv.get(k, 0.0) + h["market_value"]
    bad_d = []
    for s in T["drift_snapshot"]:
        V = tot[s["portfolio_id"]]
        w = cv[(s["portfolio_id"], s["asset_class"])] / V * 100
        t = tgt_cur[s["portfolio_id"]][s["asset_class"]]
        if (abs(s["current_weight_pct"] - w) > TOL_W or abs(s["drift_pct"] - (w - t["target_weight_pct"])) > TOL_W
                or s["breach_flag"] != (abs(w - t["target_weight_pct"]) > t["tolerance_band_pct"] + 1e-9)):
            bad_d.append(s["snapshot_id"])
    chk("DRF-001", "arithmetic", "drift snapshot recomputed from holdings and targets", len(bad_d), len(T["drift_snapshot"]), bad_d)
    breach = {}
    for s in T["drift_snapshot"]:
        breach[s["portfolio_id"]] = breach.get(s["portfolio_id"], False) or s["breach_flag"]
    nopr = [pid for pid, b in breach.items() if b and pid not in {r["portfolio_id"] for r in T["rebalance_proposal"]}]
    chk("DRF-002", "dependency", "every breaching portfolio has a proposal", len(nopr), len(breach), nopr)

    # ---- trades / proposals reconciliation
    tby = {}
    for t in T["trade"]:
        tby.setdefault(t["proposal_id"], []).append(t)
    fee_active = {}
    for f in T["fee_schedule"]:
        if f["status"] == "ACTIVE" and f["effective_from"] <= as_of and (f["effective_to"] is None or f["effective_to"] >= as_of):
            fee_active.setdefault(f["asset_class"], []).append(f)
    fee_by_id = {f["fee_schedule_id"]: f for f in T["fee_schedule"]}
    cons = T["constraint"]
    min_trade = {c["scope_id"]: c["value"] for c in cons if c["constraint_type"] == "MIN_TRADE_VALUE"}
    adv_pct = {c["scope_id"]: c["value"] for c in cons if c["constraint_type"] == "MAX_PCT_ADV"}
    max_turn = next(c["value"] for c in cons if c["constraint_type"] == "MAX_TURNOVER_PCT")
    listed = {}
    for b in T["portfolio_constraint"]:
        listed.setdefault(b["constraint_id"], set()).add(b["portfolio_id"])
    firm_excl, client_excl, min_cash = set(), {}, {}
    for c in cons:
        if c["constraint_type"] == "EXCLUDED_INSTRUMENT":
            if c["applies_to"] == "ALL_PORTFOLIOS":
                firm_excl.add(c["scope_id"])
            else:
                for pid in listed.get(c["constraint_id"], ()):
                    client_excl.setdefault(pid, set()).add(c["scope_id"])
        if c["constraint_type"] == "MIN_CASH_PCT":
            for pid in listed.get(c["constraint_id"], ()):
                min_cash[pid] = c["value"]
    chk("CON-001", "dependency", "is_excluded flag matches firm-wide EXCLUDED_INSTRUMENT constraints",
        len({i for i, x in inst.items() if x["is_excluded"]} ^ firm_excl), len(inst))

    bad_not, bad_hq, bad_pid, bad_cnt, bad_sum, bad_pta, bad_lot = [], [], [], [], [], [], []
    ptab = {}
    for r in T["post_trade_allocation"]:
        ptab.setdefault(r["proposal_id"], {})[r["asset_class"]] = r
    for t in T["trade"]:
        if abs(t["notional"] - round(t["quantity"] * t["price_used"], 2)) > TOL_MONEY:
            bad_not.append(t["trade_id"])
        if abs(t["holding_quantity_before"] - (hold[(t["portfolio_id"], t["instrument_id"])]["quantity"] if (t["portfolio_id"], t["instrument_id"]) in hold else 0)) > 1e-9:
            bad_hq.append(t["trade_id"])
        if prop[t["proposal_id"]]["portfolio_id"] != t["portfolio_id"]:
            bad_pid.append(t["trade_id"])
        lot = inst[t["instrument_id"]]["lot_size"]
        if abs(t["quantity"] / lot - round(t["quantity"] / lot)) > 1e-9:
            bad_lot.append(t["trade_id"])
    chk("TRD-001", "arithmetic", "notional = quantity x price_used", len(bad_not), len(T["trade"]), bad_not)
    chk("TRD-002", "arithmetic", "holding_quantity_before equals Holding table", len(bad_hq), len(T["trade"]), bad_hq)
    chk("TRD-003", "dependency", "trade portfolio equals proposal portfolio", len(bad_pid), len(T["trade"]), bad_pid)
    chk("TRD-004", "arithmetic", "trade quantity is a multiple of lot size", len(bad_lot), len(T["trade"]), bad_lot)

    other_secondary = 0
    for pr in T["rebalance_proposal"]:
        pid, prid = pr["portfolio_id"], pr["proposal_id"]
        trs = tby.get(prid, [])
        hrows = hold_by[pid]
        buys = sum(t["notional"] for t in trs if t["side"] == "BUY")
        sells = sum(t["notional"] for t in trs if t["side"] == "SELL")
        fees = sum(t["estimated_fee"] or 0.0 for t in trs)
        V = sum(h["market_value"] for h in hrows)
        if (len(trs) != pr["num_trades"] or abs(buys - pr["total_buy_value"]) > TOL_MONEY or abs(sells - pr["total_sell_value"]) > TOL_MONEY
                or abs(fees - pr["total_estimated_fees"]) > TOL_MONEY or abs(V - pr["portfolio_value"]) > TOL_MONEY
                or abs((buys + sells) / 2 / V * 100 - pr["turnover_pct"]) > TOL_W
                or pr["price_stale_count"] != sum(t["stale_price_flag"] for t in trs)
                or pr["liquidity_capped_count"] != sum(t["liquidity_cap_applied"] for t in trs)):
            bad_sum.append(prid)
        # independent post-trade recompute
        qty = {h["instrument_id"]: h["quantity"] for h in hrows}
        price = {h["instrument_id"]: h["price_used"] for h in hrows}
        for t in trs:
            sg = 1 if t["side"] == "BUY" else -1
            qty[t["instrument_id"]] = qty.get(t["instrument_id"], 0) + sg * t["quantity"]
            price.setdefault(t["instrument_id"], t["price_used"])
        cash0 = sorted(h["instrument_id"] for h in hrows if inst[h["instrument_id"]]["asset_class"] == "CASH")[0]
        qty[cash0] = round(qty[cash0] + round(sells - buys - fees, 2), 2)
        post = {c: 0.0 for c in ASSET_CLASSES}
        for i, q in qty.items():
            post[inst[i]["asset_class"]] += q * price[i]
        Vp = sum(post.values())
        rows = ptab.get(prid, {})
        ok = len(rows) == 4 and abs(Vp - pr["post_trade_value"]) <= TOL_MONEY and abs(post["CASH"] - pr["cash_after"]) <= TOL_MONEY
        for c in ASSET_CLASSES:
            if c not in rows or abs(rows[c]["post_weight_pct"] - post[c] / Vp * 100) > TOL_W or abs(rows[c]["post_value"] - post[c]) > TOL_MONEY:
                ok = False
        if ok and abs(sum(rows[c]["post_weight_pct"] for c in ASSET_CLASSES) - 100) > 1e-3:
            ok = False
        if ok:
            mx = max(abs(post[c] / Vp * 100 - tgt_cur[pid][c]["target_weight_pct"]) for c in ASSET_CLASSES)
            ok = abs(mx - pr["post_max_abs_drift_pct"]) <= TOL_W
        if not ok:
            bad_pta.append(prid)
        # ---- business-rule findings per proposal
        tsum = sum(tgt_cur[pid][c]["target_weight_pct"] for c in ASSET_CLASSES)
        if abs(tsum - 100) > 1e-6:
            find("TARGET_WEIGHTS_NOT_100", "Portfolio", pid, pid, prid, f"target weights sum to {tsum:g}")
        if trs and pr["turnover_pct"] > max_turn + 1e-6:
            find("TURNOVER_CAP_BREACH", "RebalanceProposal", prid, pid, prid, f"turnover {pr['turnover_pct']:.2f}% > {max_turn}%")
        if trs and pr["cash_after"] < pr["min_cash_required"] - TOL_MONEY and pr["cash_after"] < sum(h["market_value"] for h in hrows if inst[h["instrument_id"]]["asset_class"] == "CASH"):
            find("MIN_CASH_BREACH", "RebalanceProposal", prid, pid, prid, "cash after trades below policy minimum")
        for t in trs:
            iid, cls = t["instrument_id"], inst[t["instrument_id"]]["asset_class"]
            held = hold[(pid, iid)]["quantity"] if (pid, iid) in hold else 0
            if t["side"] == "SELL" and t["quantity"] > held + 1e-9:
                find("TRADE_EXCEEDS_HOLDING", "Trade", t["trade_id"], pid, prid, f"SELL {t['quantity']:g} > holding {held:g}")
            if t["side"] == "BUY" and (inst[iid]["is_excluded"] or iid in firm_excl or iid in client_excl.get(pid, set())):
                find("EXCLUDED_INSTRUMENT_RECOMMENDED", "Trade", t["trade_id"], pid, prid, f"BUY {iid} is excluded")
            if t["estimated_fee"] is None:
                find("FEE_OMITTED", "Trade", t["trade_id"], pid, prid, "estimated_fee missing")
            else:
                fr = next((f for f in fee_active[cls] if f["min_notional"] <= t["notional"] < f["max_notional"]), None)
                exp = round(max(fr["min_fee"], fr["flat_fee"] + t["notional"] * fr["commission_bps"] / 10000.0), 2)
                if abs(exp - t["estimated_fee"]) > 0.005 or t["fee_schedule_id"] != fr["fee_schedule_id"]:
                    find("FEE_MISMATCH", "Trade", t["trade_id"], pid, prid, f"fee {t['estimated_fee']} vs expected {exp}")
            age = age_of(t["price_date_used"])
            if age > thr and not t["stale_price_flag"]:
                find("STALE_PRICE_UNFLAGGED", "Trade", t["trade_id"], pid, prid, f"price {age} trading days old, not flagged")
            if t["stale_price_flag"] != (t["price_age_days"] > thr) and age <= thr:
                find("STALE_FLAG_INCONSISTENT", "Trade", t["trade_id"], pid, prid, "flag inconsistent with age")
            if t["notional"] < min_trade.get(cls, 0) - TOL_MONEY:
                find("BELOW_MIN_TRADE_VALUE", "Trade", t["trade_id"], pid, prid, f"notional {t['notional']} < minimum")
            ins = inst[iid]
            if t["quantity"] > ins["avg_daily_volume_units"] * adv_pct[ins["liquidity_tier"]] / 100.0 + 1e-6:
                find("LIQUIDITY_CAP_BREACH", "Trade", t["trade_id"], pid, prid, "quantity above % of ADV cap")
    chk("PRP-001", "arithmetic", "proposal totals reconcile to trades and holdings", len(bad_sum), len(prop), bad_sum)
    chk("PRP-002", "arithmetic", "post-trade allocation recomputed from holdings, trades and prices", len(bad_pta), len(prop), bad_pta)
    chk("PRP-003", "coverage", "BLOCKED proposals have no trades; frozen portfolios are blocked",
        sum(1 for r in T["rebalance_proposal"] if (r["status"] == "BLOCKED") != (port[r["portfolio_id"]]["status"] == "FROZEN")
            or (r["status"] == "BLOCKED" and r["num_trades"] != 0)), len(prop))

    # ---- lifecycle
    ev_by = {}
    for e in T["proposal_event"]:
        ev_by.setdefault(e["proposal_id"], []).append(e)
    bad_life, bad_ts, bad_final, bad_ts_map = [], [], [], []
    for prid, pr in prop.items():
        evs = ev_by.get(prid, [])
        prev, last_ts = None, ""
        for e in evs:
            if e["from_status"] != prev or e["to_status"] not in TRANSITIONS.get(prev, set()):
                bad_life.append(e["event_id"])
            if e["event_ts"] < last_ts:
                bad_ts.append(e["event_id"])
            prev, last_ts = e["to_status"], e["event_ts"]
        if not evs or prev != pr["status"]:
            bad_final.append(prid)
        want = TRADE_STATUS_FROM_PROPOSAL.get(pr["status"], "PROPOSED")
        bad_ts_map += [t["trade_id"] for t in tby.get(prid, []) if t["trade_status"] != want]
    chk("LIF-001", "lifecycle", "event chain: first event DRAFT, from_status continuity, allowed transitions", len(bad_life), len(T["proposal_event"]), bad_life)
    chk("LIF-002", "lifecycle", "event timestamps non-decreasing per proposal", len(bad_ts), len(T["proposal_event"]), bad_ts)
    chk("LIF-003", "lifecycle", "proposal.status equals latest event to_status", len(bad_final), len(prop), bad_final)
    chk("LIF-004", "lifecycle", "trade_status mapped from proposal status", len(bad_ts_map), len(T["trade"]), bad_ts_map)
    chk("LIF-005", "lifecycle", "event timestamps not before proposal generated_at",
        sum(1 for e in T["proposal_event"] if e["event_ts"] < prop[e["proposal_id"]]["generated_at"]), len(T["proposal_event"]))

    status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    counts = {}
    for f in findings:
        counts[f["issue_type"]] = counts.get(f["issue_type"], 0) + 1
    summary = {"overall_status": status, "checks_total": len(checks), "checks_passed": sum(c["status"] == "PASS" for c in checks),
               "checks_failed": sum(c["status"] == "FAIL" for c in checks),
               "row_counts": orig_counts,
               "business_rule_findings_by_type": dict(sorted(counts.items())),
               "note": "Findings include the deliberately injected anomalies (see ground_truth/). Structural checks must all PASS.",
               "checks": checks}
    return summary, findings, T
