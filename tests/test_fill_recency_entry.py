"""Fill-recency entry loosen tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from utils import fill_recency_entry as fr


class TestFillRecencyEntry(unittest.TestCase):
    def test_loosen_active_when_stale_bull(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "data" / "pnl_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps({"timestamp": "2026-05-26T12:00:00", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            meta = root / "data" / "last_screening_meta.json"
            meta.write_text(
                json.dumps({"market_regime_at_screen": "TRENDING_BULL"}),
                encoding="utf-8",
            )
            ov = root / "data" / "entry_si_overrides.json"
            ov.write_text("{}", encoding="utf-8")
            pos = root / "data" / "positions.json"
            pos.write_text("[]", encoding="utf-8")
            with mock.patch.object(fr, "_LEDGER", ledger), mock.patch.object(
                fr, "_META", meta
            ), mock.patch.object(fr, "_OVERRIDES", ov), mock.patch.object(
                fr, "_POSITIONS", pos
            ), mock.patch("utils.system_time.now") as now_mock:
                from datetime import datetime
                from utils.system_time import ensure_system_tz

                ensure_system_tz()
                now_mock.return_value = datetime(2026, 6, 16, 12, 0, 0)
                ctx = fr.loosen_context()
            self.assertTrue(ctx.get("active"))
            self.assertGreaterEqual(ctx.get("days_since_last_activity") or 0, 20)
            self.assertGreaterEqual(float(ctx.get("relaxed_rsi_cap") or 0), 66.0)

    def test_loosen_inactive_when_recent_fill(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "data" / "pnl_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps({"timestamp": "2026-06-15T12:00:00", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            meta = root / "data" / "last_screening_meta.json"
            meta.write_text(json.dumps({"market_regime_at_screen": "TRENDING_BULL"}), encoding="utf-8")
            ov = root / "data" / "entry_si_overrides.json"
            ov.write_text("{}", encoding="utf-8")
            pos = root / "data" / "positions.json"
            pos.write_text("[]", encoding="utf-8")
            with mock.patch.object(fr, "_LEDGER", ledger), mock.patch.object(
                fr, "_META", meta
            ), mock.patch.object(fr, "_OVERRIDES", ov), mock.patch.object(
                fr, "_POSITIONS", pos
            ), mock.patch("utils.system_time.now") as now_mock:
                from datetime import datetime

                now_mock.return_value = datetime(2026, 6, 16, 12, 0, 0)
                ctx = fr.loosen_context()
            self.assertFalse(ctx.get("active"))

    def test_loosen_honors_persisted_override_in_volatile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "data" / "pnl_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps({"timestamp": "2026-05-26T12:00:00", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            meta = root / "data" / "last_screening_meta.json"
            meta.write_text(json.dumps({"market_regime_at_screen": "VOLATILE"}), encoding="utf-8")
            ov = root / "data" / "entry_si_overrides.json"
            ov.write_text(
                json.dumps(
                    {
                        "active": True,
                        "relaxed_rsi_cap": 70,
                        "llm_min_confidence": 0.42,
                        "position_size_mult": 0.55,
                        "relax_step": 2,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(fr, "_LEDGER", ledger), mock.patch.object(
                fr, "_META", meta
            ), mock.patch.object(fr, "_OVERRIDES", ov), mock.patch.object(
                fr, "_POSITIONS", root / "data" / "positions.json"
            ), mock.patch("utils.system_time.now") as now_mock:
                from datetime import datetime

                now_mock.return_value = datetime(2026, 6, 17, 12, 0, 0)
                ctx = fr.loosen_context()
            self.assertTrue(ctx.get("active"))
            self.assertEqual(float(ctx.get("relaxed_rsi_cap") or 0), 70.0)

    def test_open_position_within_recency_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ledger = root / "data" / "pnl_ledger.jsonl"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                json.dumps({"timestamp": "2026-05-26T12:00:00", "pnl": 1.0}) + "\n",
                encoding="utf-8",
            )
            pos = root / "data" / "positions.json"
            pos.write_text(
                json.dumps([{"ticker": "EMR", "entry_date": "2026-06-16T15:53:39"}]),
                encoding="utf-8",
            )
            meta = root / "data" / "last_screening_meta.json"
            meta.write_text(json.dumps({"market_regime_at_screen": "VOLATILE"}), encoding="utf-8")
            ov = root / "data" / "entry_si_overrides.json"
            ov.write_text("{}", encoding="utf-8")
            with mock.patch.object(fr, "_LEDGER", ledger), mock.patch.object(
                fr, "_POSITIONS", pos
            ), mock.patch.object(fr, "_META", meta), mock.patch.object(
                fr, "_OVERRIDES", ov
            ), mock.patch("utils.system_time.now") as now_mock:
                from datetime import datetime

                now_mock.return_value = datetime(2026, 6, 17, 12, 0, 0)
                self.assertEqual(fr.days_since_last_activity(), 1)
                ctx = fr.loosen_context()
            self.assertFalse(ctx.get("active"))
            self.assertEqual(ctx.get("reason"), "open_position_within_recency")


class TestClassicSiEntry(unittest.TestCase):
    def test_maybe_auto_relax_writes_overrides(self):
        from utils import classic_si_entry as cse

        with tempfile.TemporaryDirectory() as td:
            ov_path = Path(td) / "entry_si_overrides.json"
            with mock.patch.object(cse, "_OVERRIDES_PATH", ov_path), mock.patch.object(
                cse, "days_since_last_activity", return_value=21
            ), mock.patch.object(cse, "days_since_last_fill", return_value=21), mock.patch.object(
                cse, "latest_regime", return_value="TRENDING_BULL"
            ), mock.patch.object(
                cse, "load_entry_overrides", return_value={}
            ):
                out = cse.maybe_auto_relax_entry_gate()
            self.assertTrue(out.get("ok"))
            self.assertTrue(ov_path.is_file())
            doc = json.loads(ov_path.read_text(encoding="utf-8"))
            self.assertTrue(doc.get("active"))
            self.assertGreaterEqual(float(doc.get("relaxed_rsi_cap") or 0), 68)


if __name__ == "__main__":
    unittest.main()
