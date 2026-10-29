"""CSV / JSON / SQL export, checksums and source manifest. Ground truth is written to its own folder."""
import csv
import hashlib
import json
import os
import sqlite3

from .schema import ENTITIES, render_ddl, render_data_dictionary_md, dictionary_rows

GT_FIELDS = ["gt_id", "label_category", "entity_type", "entity_id", "portfolio_id", "proposal_id", "issue_type",
             "expected_decision", "detail"]
GENERATOR_VERSION = "1.0.0"


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fieldnames)
        for r in rows:
            w.writerow([_cell(r.get(k)) for k in fieldnames])


def write_json(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps({k: r.get(k) for k in fieldnames}, separators=(",", ":")) for r in rows))
        f.write("\n]\n")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_all(out, T, gt, params, command):
    for sub in ("csv", "json", "sql", "ground_truth", "docs", "validation", "manifest"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)
    for e in ENTITIES:
        names = [f.name for f in e.fields]
        write_csv(os.path.join(out, "csv", e.file), names, T[e.table])
        write_json(os.path.join(out, "json", f"{e.table}.json"), names, T[e.table])
    write_csv(os.path.join(out, "ground_truth", "ground_truth.csv"), GT_FIELDS, gt)
    write_json(os.path.join(out, "ground_truth", "ground_truth.json"), GT_FIELDS, gt)
    # SQL: schema + seed (loaded into SQLite to enforce PKs, FKs and CHECKs, then dumped)
    ddl = render_ddl()
    with open(os.path.join(out, "sql", "schema.sql"), "w", encoding="utf-8") as f:
        f.write(ddl)
    con = sqlite3.connect(":memory:")
    con.executescript(ddl)
    for e in ENTITIES:
        names = [f.name for f in e.fields]
        con.executemany(f"INSERT INTO {_q(e.table)} ({','.join(names)}) VALUES ({','.join('?' * len(names))})",
                        [[r.get(k) for k in names] for r in T[e.table]])
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    if bad:
        raise RuntimeError(f"foreign_key_check failed: {bad[:5]}")
    con.commit()
    with open(os.path.join(out, "sql", "seed.sql"), "w", encoding="utf-8") as f:
        f.write("\n".join(con.iterdump()) + "\n")
    con.close()
    # docs
    with open(os.path.join(out, "docs", "data_dictionary.md"), "w", encoding="utf-8") as f:
        f.write(render_data_dictionary_md())
    rows = dictionary_rows()
    write_csv(os.path.join(out, "docs", "data_dictionary.csv"), list(rows[0].keys()), rows)
    with open(os.path.join(out, "docs", "generator_command.txt"), "w", encoding="utf-8") as f:
        f.write(command + "\n")


def _q(name):
    return f'"{name}"' if name in ("constraint", "trade", "holding", "portfolio") else name


def write_manifest(out, T, gt, params, command):
    """Checksums + source manifest. Call last (after validation files exist)."""
    files = {}
    for root, _, names in os.walk(out):
        for n in sorted(names):
            full = os.path.join(root, n)
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            if rel.startswith("manifest/") or rel == "reproducibility_report.json":
                continue
            files[rel] = full
    entries = []
    for rel in sorted(files):
        entry = {"path": rel, "sha256": sha256(files[rel])}
        if rel.startswith("csv/"):
            entry["rows"] = len(T[rel[4:-4]])
        if rel == "ground_truth/ground_truth.csv":
            entry["rows"] = len(gt)
        entries.append(entry)
    manifest = {
        "dataset": "Portfolio rebalancing simulation (educational, synthetic)",
        "generator_version": GENERATOR_VERSION, "generator_command": command, "seed": params.seed,
        "parameters": params.to_dict(),
        "external_data_used": False,
        "sources": [],
        "provenance": "All records are produced by rebalance_sim from the seeded generator. No external datasets, "
                      "scraped data, real tickers, names or personal data were used. Public financial-data "
                      "conventions (asset-class buckets, tiered commissions, ADV liquidity caps) informed only the schema design.",
        "license": "Synthetic data released for educational use; no restrictions, no warranty.",
        "disclaimer": "Educational simulation. Not financial advice.",
        "files": entries,
    }
    with open(os.path.join(out, "manifest", "source_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    with open(os.path.join(out, "manifest", "checksums.sha256"), "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f"{e['sha256']}  {e['path']}\n")
    return manifest
