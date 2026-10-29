"""Run with:  python -m unittest discover -s tests -v   (or pytest)."""
import csv
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rebalance_sim.cli import generate, repro  # noqa: E402
from rebalance_sim.params import make_params  # noqa: E402
from rebalance_sim.validate import validate  # noqa: E402


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="rb_test_")
        cls.p = make_params("starter")
        cls.out = os.path.join(cls.tmp, "starter")
        cls.summary, cls.metrics, cls.manifest = generate("starter", cls.p, cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_structural_checks_pass(self):
        failed = [c["check_id"] for c in self.summary["checks"] if c["status"] == "FAIL"]
        self.assertEqual(failed, [])

    def test_volume_and_ids(self):
        rc = self.summary["row_counts"]
        self.assertEqual(rc["portfolio"], 100)
        self.assertEqual(rc["holding"], 500)
        self.assertEqual(rc["market_price"], 60 * 250)
        with open(os.path.join(self.out, "csv", "portfolio.csv")) as f:
            first = next(csv.DictReader(f))
        self.assertRegex(first["portfolio_id"], r"^PORT-INV-\d{6}-01$")

    def test_every_injected_anomaly_is_detected_and_nothing_else_flagged(self):
        d = self.metrics["detector_vs_ground_truth"]
        self.assertEqual(d["overall"]["fn"], 0)
        self.assertEqual(d["overall"]["fp"], 0)
        self.assertEqual(d["other_findings_on_clean_proposals"], 0)
        for t, m in d["per_issue_type"].items():
            self.assertGreaterEqual(m["tp"], 2, t)

    def test_ground_truth_not_in_input_tables(self):
        for fn in os.listdir(os.path.join(self.out, "csv")):
            with open(os.path.join(self.out, "csv", fn)) as f:
                header = next(csv.reader(f))
            self.assertFalse({"issue_type", "ground_truth", "expected_decision", "label_category"} & set(header), fn)

    def test_exception_paths_present(self):
        o = self.metrics["outcomes"]
        self.assertGreater(o["trades_stale_flagged"], 0)
        self.assertGreater(o["trades_liquidity_capped"], 0)
        self.assertGreater(o["suppressed_trades_below_min"], 0)

    def test_validator_catches_real_corruption(self):
        bad = os.path.join(self.tmp, "corrupt")
        shutil.copytree(self.out, bad)
        path = os.path.join(bad, "csv", "holding.csv")
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        h = rows[0]
        rows[1][h.index("quantity")] = str(float(rows[1][h.index("quantity")]) * 2)  # breaks market_value reconciliation
        rows[2][h.index("portfolio_id")] = "PORT-INV-999999-01"                      # breaks the FK
        with open(path, "w", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
        summary, _, _ = validate(bad, self.p)
        failed = {c["check_id"] for c in summary["checks"] if c["status"] == "FAIL"}
        self.assertEqual(summary["overall_status"], "FAIL")
        self.assertIn("HLD-003", failed)
        self.assertIn("FK-holding-portfolio_id", failed)

    def test_seed_sql_loads_with_foreign_keys(self):
        con = sqlite3.connect(":memory:")
        with open(os.path.join(self.out, "sql", "seed.sql"), encoding="utf-8") as f:
            con.executescript(f.read())
        self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM holding").fetchone()[0], 500)
        con.close()

    def test_reproducible_with_fixed_seed(self):
        rep = repro("starter", self.p, os.path.join(self.tmp, "repro"))
        self.assertTrue(rep["identical"])

    def test_different_seed_changes_data(self):
        p2 = make_params("starter", seed=1)
        generate("starter", p2, os.path.join(self.tmp, "seed1"))
        with open(os.path.join(self.out, "csv", "holding.csv")) as f:
            a = f.read()
        with open(os.path.join(self.tmp, "seed1", "csv", "holding.csv")) as f:
            b = f.read()
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
