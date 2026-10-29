"""Command line interface:  python -m rebalance_sim <generate|validate|repro|docs|all> ..."""
import argparse
import csv
import json
import os
import shutil
import tempfile

from . import exporter as X
from .evaluate import evaluate
from .params import Params, make_params
from .pipeline import build
from .schema import ENTITIES, render_data_dictionary_md
from .validate import validate


def command_string(scale, p):
    extra = ""
    d = make_params(scale)
    for k in ("n_portfolios", "n_instruments", "n_holdings", "n_days"):
        if getattr(p, k) != getattr(d, k):
            extra += f" --{k.replace('n_', '').replace('_', '-')} {getattr(p, k)}"
    return f"python -m rebalance_sim generate --scale {scale} --seed {p.seed}{extra} --out <OUT_DIR>"


def write_validation(out, summary, findings, metrics):
    v = os.path.join(out, "validation")
    os.makedirs(v, exist_ok=True)
    with open(os.path.join(v, "validation_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    with open(os.path.join(v, "evaluation_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")
    cols = ["issue_type", "entity_type", "entity_id", "portfolio_id", "proposal_id", "detail"]
    X.write_csv(os.path.join(v, "findings.csv"), cols, findings)
    md = ["# Validation summary", "", f"**Overall structural status: {summary['overall_status']}** "
          f"({summary['checks_passed']}/{summary['checks_total']} checks passed)", "",
          "## Row counts", "", "| Table | Rows |", "|---|---|"]
    md += [f"| {k} | {n} |" for k, n in summary["row_counts"].items()]
    md += ["", "## Structural and reconciliation checks", "", "| Check | Category | Description | Rows | Violations | Status |", "|---|---|---|---|---|---|"]
    md += [f"| {c['check_id']} | {c['category']} | {c['description']} | {c['rows_checked']} | {c['violations']} | {c['status']} |" for c in summary["checks"]]
    md += ["", "## Business-rule findings (include injected anomalies)", "", "| Issue type | Count |", "|---|---|"]
    md += [f"| {k} | {n} |" for k, n in summary["business_rule_findings_by_type"].items()]
    det = metrics["detector_vs_ground_truth"]
    md += ["", "## Rule-based detector vs ground truth", "", "| Issue type | TP | FP | FN | Precision | Recall |", "|---|---|---|---|---|---|"]
    md += [f"| {k} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']} | {m['recall']} |" for k, m in det["per_issue_type"].items()]
    md += ["", f"Decision agreement with expected decisions: {metrics['decision_agreement']['agreement_rate']}", ""]
    with open(os.path.join(v, "validation_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def generate(scale, p, out):
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    cmd = command_string(scale, p)
    T, gt, _ = build(p)
    X.export_all(out, T, gt, p, cmd)
    summary, findings, T2 = validate(out, p)
    metrics = evaluate(out, T2, findings)
    write_validation(out, summary, findings, metrics)
    manifest = X.write_manifest(out, T, gt, p, cmd)
    return summary, metrics, manifest


def tree_checksums(out):
    res = {}
    for root, _, names in os.walk(out):
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            if rel != "reproducibility_report.json":
                res[rel] = X.sha256(full)
    return res


def repro(scale, p, out):
    """Step 10: regenerate twice with the same seed and compare row counts and checksums with the main output."""
    generate(scale, p, out)
    runs = {"original": tree_checksums(out)}
    tmp = tempfile.mkdtemp(prefix="rebalance_repro_")
    try:
        for name in ("regen_1", "regen_2"):
            d = os.path.join(tmp, name)
            generate(scale, p, d)
            runs[name] = tree_checksums(d)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    base = runs["original"]
    rows = {}
    for e in ENTITIES:
        with open(os.path.join(out, "csv", e.file), encoding="utf-8") as f:
            rows[e.table] = sum(1 for _ in f) - 1
    mism = {n: sorted(k for k in set(base) | set(r) if base.get(k) != r.get(k)) for n, r in runs.items() if n != "original"}
    report = {"seed": p.seed, "scale": scale, "runs_compared": list(runs), "files_compared": len(base),
              "row_counts": rows, "identical": all(not m for m in mism.values()), "mismatching_files": mism,
              "checksums_original": base}
    with open(os.path.join(out, "reproducibility_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rebalance_sim", description="Synthetic portfolio rebalancing dataset generator (educational, not financial advice)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("generate", "repro", "all"):
        s = sub.add_parser(name)
        s.add_argument("--scale", choices=["starter", "full"], default="full")
        s.add_argument("--seed", type=int, default=20261022)
        s.add_argument("--out", default=None)
        s.add_argument("--portfolios", type=int)
        s.add_argument("--instruments", type=int)
        s.add_argument("--holdings", type=int)
        s.add_argument("--days", type=int)
    v = sub.add_parser("validate")
    v.add_argument("--data", required=True)
    sub.add_parser("docs")
    a = ap.parse_args(argv)

    if a.cmd == "docs":
        os.makedirs("docs", exist_ok=True)
        with open("docs/data_dictionary.md", "w", encoding="utf-8") as f:
            f.write(render_data_dictionary_md())
        print("wrote docs/data_dictionary.md")
        return 0
    if a.cmd == "validate":
        with open(os.path.join(a.data, "manifest", "source_manifest.json"), encoding="utf-8") as f:
            p = Params(**json.load(f)["parameters"])
        summary, findings, T = validate(a.data, p)
        metrics = evaluate(a.data, T, findings)
        print(json.dumps({k: summary[k] for k in ("overall_status", "checks_passed", "checks_failed", "business_rule_findings_by_type")}, indent=2))
        return 0 if summary["overall_status"] == "PASS" else 1
    p = make_params(a.scale, seed=a.seed, n_portfolios=a.portfolios, n_instruments=a.instruments,
                    n_holdings=a.holdings, n_days=a.days)
    out = a.out or os.path.join("data", a.scale)
    if a.cmd == "generate":
        summary, metrics, manifest = generate(a.scale, p, out)
        print(f"{a.scale}: {summary['checks_passed']}/{summary['checks_total']} checks passed -> {summary['overall_status']}; out={out}")
        print(json.dumps(summary["business_rule_findings_by_type"]))
        return 0 if summary["overall_status"] == "PASS" else 1
    rep = repro(a.scale, p, out)
    print(f"{a.scale}: reproducible={rep['identical']} files={rep['files_compared']}")
    return 0 if rep["identical"] else 1
