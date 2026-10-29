"""Evaluation: (1) rule-based detector vs ground truth, (2) business/outcome metrics of the rebalancing output."""
import csv
import os
import statistics as st

from .schema import ISSUE_TYPES


def _prf(tp, fp, fn):
    pr = tp / (tp + fp) if tp + fp else 1.0
    rc = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(pr, 4), "recall": round(rc, 4), "f1": round(f1, 4)}


def load_gt(data_dir):
    with open(os.path.join(data_dir, "ground_truth", "ground_truth.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _avg(xs):
    return round(sum(xs) / len(xs), 4) if xs else None


def pct(xs, q):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4) if xs else None


def evaluate(data_dir, T, findings):
    gt = load_gt(data_dir)
    inj = {(g["issue_type"], g["entity_id"]) for g in gt if g["label_category"] == "INJECTED_ANOMALY"}
    found = {(f["issue_type"], f["entity_id"]) for f in findings if f["issue_type"] in ISSUE_TYPES}
    det = {t: _prf(len({x for x in inj if x[0] == t} & {x for x in found if x[0] == t}),
                   len({x for x in found if x[0] == t} - inj),
                   len({x for x in inj if x[0] == t} - found)) for t in ISSUE_TYPES}
    tp, fp, fn = len(inj & found), len(found - inj), len(inj - found)
    other = {}
    inj_props = {g["proposal_id"] for g in gt if g["label_category"] == "INJECTED_ANOMALY" and g["proposal_id"]}
    unexplained = 0
    for f in findings:
        if f["issue_type"] not in ISSUE_TYPES:
            other[f["issue_type"]] = other.get(f["issue_type"], 0) + 1
            if f["proposal_id"] not in inj_props:
                unexplained += 1
    # decision agreement: expected decision (ground truth) vs the decision the data actually shows
    props = {p["portfolio_id"]: p for p in T["rebalance_proposal"]}
    agree = tot = 0
    mism = {}
    for g in gt:
        if g["label_category"] != "EXPECTED_DECISION":
            continue
        pr = props.get(g["portfolio_id"])
        actual = "NO_ACTION" if pr is None else ("BLOCK_FROZEN" if pr["status"] == "BLOCKED" else "REBALANCE")
        tot += 1
        if actual == g["expected_decision"]:
            agree += 1
        else:
            k = f"{g['expected_decision']} -> {actual}"
            mism[k] = mism.get(k, 0) + 1
    # outcome metrics
    P = T["rebalance_proposal"]
    live = [p for p in P if p["trigger_reason"] == "DRIFT_BREACH"]
    status = {}
    for p in P:
        status[p["status"]] = status.get(p["status"], 0) + 1
    reasons = {}
    for p in P:
        for r in (p["review_reasons"] or "").split("|"):
            if r:
                reasons[r] = reasons.get(r, 0) + 1
    drift_breach_portfolios = len({d["portfolio_id"] for d in T["drift_snapshot"] if d["breach_flag"]})
    resolved = [p for p in live if p["num_trades"] > 0]
    fee_bps = [p["total_estimated_fees"] / (p["total_buy_value"] + p["total_sell_value"]) * 1e4
               for p in resolved if p["total_buy_value"] + p["total_sell_value"] > 0]
    clean_ids = {g["proposal_id"] for g in gt if g["label_category"] == "INJECTED_ANOMALY" and g["proposal_id"]}
    clean = [p for p in resolved if p["proposal_id"] not in clean_ids]
    remain = 0
    tol = {}
    for t in T["target_allocation"]:
        if t["status"] == "ACTIVE":
            tol[t["portfolio_id"]] = max(tol.get(t["portfolio_id"], 0), t["tolerance_band_pct"])
    metrics = {
        "detector_vs_ground_truth": {"per_issue_type": det, "overall": _prf(tp, fp, fn),
                                     "other_findings_not_labelled_as_primary_anomaly": dict(sorted(other.items())),
                                     "other_findings_on_clean_proposals": unexplained,
                                     "note": "Other findings (e.g. turnover cap) only occur on proposals that carry an injected anomaly; clean proposals must have 0."},
        "decision_agreement": {"portfolios": tot, "agreement_rate": round(agree / tot, 4),
                               "mismatches": dict(sorted(mism.items())),
                               "note": "Mismatches are the injected invalid-target portfolios that were rebalanced instead of blocked."},
        "outcomes": {
            "portfolios": len(T["portfolio"]), "breaching_portfolios": drift_breach_portfolios,
            "breach_rate": round(drift_breach_portfolios / len(T["portfolio"]), 4),
            "proposals": len(P), "proposal_status_counts": dict(sorted(status.items())),
            "compliance_escalation_rate": round(sum(p["requires_compliance_review"] for p in live) / max(1, len(live)), 4),
            "escalation_reason_counts": dict(sorted(reasons.items())),
            "trades": len(T["trade"]),
            "trades_stale_flagged": sum(t["stale_price_flag"] for t in T["trade"]),
            "trades_liquidity_capped": sum(t["liquidity_cap_applied"] for t in T["trade"]),
            "mean_pre_max_drift_pct": _avg([p["pre_max_abs_drift_pct"] for p in resolved]),
            "mean_post_max_drift_pct": _avg([p["post_max_abs_drift_pct"] for p in resolved]),
            "mean_drift_reduction_pct": _avg([p["drift_reduction_pct"] for p in clean]),
            "median_turnover_pct": round(st.median([p["turnover_pct"] for p in resolved]), 4) if resolved else None,
            "p95_turnover_pct": pct([p["turnover_pct"] for p in resolved], 0.95),
            "mean_fee_bps_of_notional": _avg(fee_bps),
            "total_estimated_fees_usd": round(sum(p["total_estimated_fees"] for p in P), 2),
            "suppressed_trades_below_min": sum(p["suppressed_trade_count"] for p in P),
            "drift_snapshot_breach_by_class": {c: sum(1 for d in T["drift_snapshot"] if d["asset_class"] == c and d["breach_flag"])
                                               for c in ("EQUITY", "FIXED_INCOME", "REAL_ASSETS", "CASH")},
        },
    }
    return metrics
