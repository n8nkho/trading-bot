import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from utils import pnl_ledger_health as plh


class TestPnlLedgerHealth(unittest.TestCase):
    def test_audit_fires_on_classic_stale_without_fortress(self):
        with tempfile.TemporaryDirectory() as td:
            classic = Path(td) / "classic.jsonl"
            old = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
            classic.write_text(
                json.dumps({"timestamp": old, "order_id": "old-1", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(plh, "_CLASSIC_LEDGER", classic), mock.patch.object(
                plh, "_broker_closed_sells_since", return_value=[]
            ):
                audit = plh.audit_ledger_gap(stale_days=3.0)
            self.assertTrue(audit["ledger_gap_detected"])
            self.assertGreaterEqual(audit["classic_age_days"], 24.0)
            findings = plh.scan_classic_pnl_ledger_stale(stale_days=3.0)
            self.assertEqual(findings[0]["code"], "classic_pnl_ledger_stale")

    def test_audit_skips_mirrored_rows_for_last_exit(self):
        with tempfile.TemporaryDirectory() as td:
            classic = Path(td) / "classic.jsonl"
            old = (datetime.now(timezone.utc) - timedelta(days=25)).isoformat()
            new = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            classic.write_text(
                json.dumps({"timestamp": old, "order_id": "real-1", "pnl": 1.0}) + "\n"
                + json.dumps(
                    {
                        "timestamp": new,
                        "ticker": "CRWD",
                        "pnl": -0.3,
                        "mirrored_from": "fortress_ai",
                        "source": "skim_swarm",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(plh, "_CLASSIC_LEDGER", classic), mock.patch.object(
                plh, "_broker_closed_sells_since", return_value=[]
            ):
                audit = plh.audit_ledger_gap(stale_days=3.0)
            self.assertTrue(audit["ledger_gap_detected"])
            self.assertGreaterEqual(audit["classic_age_days"], 24.0)

    def test_audit_fires_when_broker_missing_classic_sells(self):
        with tempfile.TemporaryDirectory() as td:
            classic = Path(td) / "classic.jsonl"
            recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            classic.write_text(
                json.dumps({"timestamp": recent, "order_id": "known-1", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(plh, "_CLASSIC_LEDGER", classic), mock.patch.object(
                plh,
                "_broker_closed_sells_since",
                return_value=[{"order_id": "missing-1", "symbol": "EMR"}],
            ):
                audit = plh.audit_ledger_gap(stale_days=3.0)
            self.assertTrue(audit["ledger_gap_detected"])
            self.assertEqual(audit["broker_sells_missing_from_classic"], 1)


if __name__ == "__main__":
    unittest.main()
