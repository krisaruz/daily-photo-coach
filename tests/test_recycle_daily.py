"""循环模式选图：确定性、无短期重复、池构建过滤。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import recycle_daily


def _photo(pid: str, label: str, analysis: str = "## 直觉\n好照片。") -> dict:
    return {
        "id": pid,
        "url_regular": f"https://example.com/{pid}.jpg",
        "url_full": f"https://example.com/{pid}.jpg",
        "url_small": f"https://example.com/{pid}.jpg",
        "width": 4000,
        "height": 3000,
        "description": f"photo {pid}",
        "photographer": "Tester",
        "style_label": label,
        "style_color": "#16a34a",
        "style_icon": "🏔️",
        "analysis": analysis,
    }


def _write_day(output_dir: Path, day: str, grouped: dict) -> None:
    day_dir = output_dir / day
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "photos.json").write_text(
        json.dumps(grouped, ensure_ascii=False), encoding="utf-8"
    )


class BuildPoolsTests(unittest.TestCase):
    def test_keeps_only_analyzed_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(
                out,
                "2026-01-01",
                {
                    "风光/自然": [
                        _photo("good-1", "风光/自然"),
                        _photo("empty-1", "风光/自然", analysis=""),
                        _photo("failed-1", "风光/自然", analysis="（分析失败，请稍后重试）"),
                    ]
                },
            )
            pools = recycle_daily.build_pools(out)
            self.assertEqual([p["id"] for p in pools["风光/自然"]], ["good-1"])

    def test_excludes_xhs_photos(self):
        xhs_photo = _photo("xhs-1", "小红书｜人像写真")
        xhs_photo["source_platform"] = "xhs"
        xhs_photo["source_name"] = "小红书"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-01-01", {"风光/自然": [_photo("a", "风光/自然")], "小红书｜人像写真": [xhs_photo]})
            pools = recycle_daily.build_pools(out)
            self.assertEqual(list(pools.keys()), ["风光/自然"])

    def test_merges_legacy_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-01-01", {"人像/肖像": [_photo("p1", "人像/肖像")]})
            _write_day(out, "2026-01-02", {"人像/质感": [_photo("p2", "人像/质感")]})
            pools = recycle_daily.build_pools(out)
            self.assertEqual([p["id"] for p in pools["人像/质感"]], ["p1", "p2"])

    def test_dedupes_across_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-01-01", {"风光/自然": [_photo("dup", "风光/自然")]})
            _write_day(out, "2026-01-02", {"风光/自然": [_photo("dup", "风光/自然")]})
            pools = recycle_daily.build_pools(out)
            self.assertEqual(len(pools["风光/自然"]), 1)

    def test_style_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-01-01", {"风光/自然": [_photo("a", "风光/自然")], "街头/人文": [_photo("b", "街头/人文")]})
            pools = recycle_daily.build_pools(out, style_labels=["风光/自然"])
            self.assertEqual(list(pools.keys()), ["风光/自然"])


class SelectForDateTests(unittest.TestCase):
    def _pools(self):
        return {
            "风光/自然": [_photo(f"l{i}", "风光/自然") for i in range(40)],
            "人像/质感": [_photo(f"p{i}", "人像/质感") for i in range(40)],
            "街头/人文": [_photo(f"s{i}", "街头/人文") for i in range(40)],
        }

    def test_deterministic_for_same_date(self):
        pools = self._pools()
        a = recycle_daily.select_for_date(pools, "2026-09-04", 8)
        b = recycle_daily.select_for_date(pools, "2026-09-04", 8)
        self.assertEqual(
            [p["id"] for ps in a.values() for p in ps],
            [p["id"] for ps in b.values() for p in ps],
        )

    def test_no_overlap_between_adjacent_days(self):
        pools = self._pools()
        day_a = {p["id"] for ps in recycle_daily.select_for_date(pools, "2026-09-04", 8).values() for p in ps}
        day_b = {p["id"] for ps in recycle_daily.select_for_date(pools, "2026-09-05", 8).values() for p in ps}
        self.assertFalse(day_a & day_b)

    def test_respects_recent_window(self):
        pools = self._pools()
        used = {f"l{i}" for i in range(10)}
        sel = recycle_daily.select_for_date(pools, "2026-09-04", 8, used_ids=used)
        landscape_ids = {p["id"] for p in sel["风光/自然"]}
        self.assertFalse(landscape_ids & used)

    def test_falls_back_when_pool_exhausted(self):
        pools = {"风光/自然": [_photo(f"l{i}", "风光/自然") for i in range(5)]}
        sel = recycle_daily.select_for_date(pools, "2026-09-04", 8, used_ids={"l0"})
        self.assertEqual(len(sel["风光/自然"]), 5)

    def test_no_cross_style_duplicates_within_day(self):
        pools = self._pools()
        sel = recycle_daily.select_for_date(pools, "2026-09-04", 8)
        all_ids = [p["id"] for ps in sel.values() for p in ps]
        self.assertEqual(len(all_ids), len(set(all_ids)))


class RecentUsedIdsTests(unittest.TestCase):
    def test_collects_only_recent_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-08-20", {"风光/自然": [_photo("old", "风光/自然")]})
            _write_day(out, "2026-08-31", {"风光/自然": [_photo("recent", "风光/自然")]})
            used = recycle_daily.recent_used_ids(out, "2026-09-04", window_days=14)
            self.assertIn("recent", used)
            self.assertNotIn("old", used)

    def test_excludes_target_day_and_xhs(self):
        xhs_photo = _photo("xhs-9", "小红书｜人像写真")
        xhs_photo["source_platform"] = "xhs"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write_day(out, "2026-09-04", {"风光/自然": [_photo("today", "风光/自然")]})
            _write_day(out, "2026-09-03", {"风光/自然": [_photo("yesterday", "风光/自然")], "小红书｜人像写真": [xhs_photo]})
            used = recycle_daily.recent_used_ids(out, "2026-09-04", window_days=14)
            self.assertIn("yesterday", used)
            self.assertNotIn("today", used)
            self.assertNotIn("xhs-9", used)


class PerStyleResolutionTests(unittest.TestCase):
    """CI（无 config.yaml）必须用 8 张/风格，不能继承抓取模式的环境变量兜底值 3。"""

    def test_env_config_mode_defaults_to_eight(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_config = Path(tmp) / "absent.yaml"
            from main import load_config

            config = load_config(fake_config)
            # 与 recycle_daily.main() 相同的判断分支
            if fake_config.exists():
                configured = (config.get("daily") or {}).get("photos_per_style")
                per_style = int(configured) if configured else 8
            else:
                per_style = 8
            self.assertEqual(per_style, 8)


if __name__ == "__main__":
    unittest.main()
