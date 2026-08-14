"""Daily analysis should run at a deterministic random hour between 09:00 and 22:00."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import analysis_schedule as schedule

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(day: str, hour: int) -> datetime:
    year, month, day_n = (int(part) for part in day.split("-"))
    return datetime(year, month, day_n, hour, 20, tzinfo=SHANGHAI)


class TargetHourTests(unittest.TestCase):
    def test_hour_stays_inside_teaching_window(self):
        hours = {schedule.target_hour(date(2026, 8, day)) for day in range(1, 29)}
        self.assertTrue(hours)
        self.assertTrue(all(9 <= hour <= 22 for hour in hours))

    def test_same_day_is_stable(self):
        day = date(2026, 8, 14)
        self.assertEqual(schedule.target_hour(day), schedule.target_hour(day))

    def test_different_days_can_vary(self):
        hours = [schedule.target_hour(date(2026, 8, day)) for day in range(1, 15)]
        self.assertGreater(len(set(hours)), 1)


class ShouldRunTests(unittest.TestCase):
    def test_force_run_ignores_hour(self):
        now = _at("2026-08-14", 3)
        self.assertTrue(schedule.should_run(now, force=True))

    def test_skips_outside_window(self):
        now = _at("2026-08-14", 2)
        self.assertFalse(schedule.should_run(now, force=False))

    def test_runs_on_target_hour(self):
        day = date(2026, 8, 14)
        target = schedule.target_hour(day)
        now = _at("2026-08-14", target)
        self.assertTrue(schedule.should_run(now, force=False))

    def test_skips_other_hours_in_window(self):
        day = date(2026, 8, 14)
        target = schedule.target_hour(day)
        other = 10 if target != 10 else 11
        now = _at("2026-08-14", other)
        if other < target:
            self.assertFalse(schedule.should_run(now, force=False))

    def test_catch_up_after_missed_target_if_incomplete(self):
        day = date(2026, 8, 14)
        target = schedule.target_hour(day)
        if target == 22:
            self.skipTest("no later hour to catch up")
        now = _at("2026-08-14", target + 1)
        self.assertTrue(schedule.should_run(now, force=False, already_complete=False))

    def test_skips_when_today_already_complete(self):
        day = date(2026, 8, 14)
        target = schedule.target_hour(day)
        now = _at("2026-08-14", target)
        self.assertFalse(schedule.should_run(now, force=False, already_complete=True))


class DayCompleteTests(unittest.TestCase):
    def test_failed_analysis_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = Path(tmp) / "2026-08-14"
            day_dir.mkdir()
            (day_dir / "photos.json").write_text(
                json.dumps(
                    {
                        "风光/自然": [
                            {"id": "u1", "analysis": "（分析失败，请稍后重试）"},
                        ],
                        "小红书｜人像写真": [
                            {
                                "id": "x1",
                                "source_platform": "xhs",
                                "source_name": "小红书",
                                "analysis": "## 直觉\n可用",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertFalse(schedule.day_is_complete(tmp, date(2026, 8, 14)))

    def test_unsplash_and_xhs_with_good_analysis_are_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = Path(tmp) / "2026-08-14"
            day_dir.mkdir()
            (day_dir / "photos.json").write_text(
                json.dumps(
                    {
                        "风光/自然": [{"id": "u1", "analysis": "## 直觉\n山脊的光"}],
                        "小红书｜人像写真": [
                            {
                                "id": "x1",
                                "source_platform": "xhs",
                                "source_name": "小红书",
                                "analysis": "## 直觉\n妆造干净",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertTrue(schedule.day_is_complete(tmp, date(2026, 8, 14)))


if __name__ == "__main__":
    unittest.main()
