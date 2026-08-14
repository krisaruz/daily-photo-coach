"""Daily Xiaohongshu picker should fall back to archived real notes."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import xhs_daily

GOOD_NOTE = {
    "id": "xhs-643631310000000011011932-1",
    "source_platform": "xhs",
    "source_name": "小红书",
    "description": "横店拍摄一日游！",
    "note_title": "横店拍摄一日游！",
    "note_id": "643631310000000011011932",
    "photographer": "黄小人",
    "url_small": "https://sns-webpic-qc.xhscdn.com/example.jpg",
    "url_regular": "https://sns-webpic-qc.xhscdn.com/example.jpg",
    "url_full": "https://sns-webpic-qc.xhscdn.com/example.jpg",
    "source_url": "https://www.xiaohongshu.com/explore/643631310000000011011932",
    "local_url_small": "assets/xhs/643631310000000011011932/xhs-643631310000000011011932-1-small.jpg",
    "style_label": "小红书｜人像写真",
    "analysis": "## 直觉\n汉服写真",
}

PLACEHOLDER_NOTE = {
    "id": "xhs-8dcf271643a2052dde0f5577-1",
    "source_platform": "xhs",
    "source_name": "小红书",
    "description": "小红书摄影作品",
    "note_title": "",
    "note_id": "8dcf271643a2052dde0f5577",
    "photographer": "Yeeton",
    "url_small": "https://picasso-static.xiaohongshu.com/fe-platform/logo.png",
    "url_regular": "https://picasso-static.xiaohongshu.com/fe-platform/logo.png",
    "url_full": "https://picasso-static.xiaohongshu.com/fe-platform/logo.png",
    "source_url": "https://www.xiaohongshu.com/404?error_code=300031",
    "style_label": "小红书｜人像写真",
    "analysis": "这张图本身更像小红书平台占位封面",
}


class ArchiveFallbackTests(unittest.TestCase):
    def test_load_archived_pool_skips_placeholder_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good_dir = Path(tmp) / "2026-07-21"
            bad_dir = Path(tmp) / "2026-08-12"
            good_dir.mkdir()
            bad_dir.mkdir()
            (good_dir / "photos.json").write_text(
                json.dumps({"小红书｜人像写真": [GOOD_NOTE]}, ensure_ascii=False),
                encoding="utf-8",
            )
            (bad_dir / "photos.json").write_text(
                json.dumps({"小红书｜人像写真": [PLACEHOLDER_NOTE]}, ensure_ascii=False),
                encoding="utf-8",
            )
            pool = xhs_daily._load_archived_xhs_pool(tmp)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["note_id"], "643631310000000011011932")

    def test_fetch_pool_uses_archive_when_live_returns_placeholders(self):
        args = SimpleNamespace(
            url=None,
            source_name="",
            style=None,
            style_color=None,
            style_icon=None,
            max_notes=None,
            max_images_per_note=None,
            cookie="",
            from_archive_only=False,
        )
        config = {
            "output": {"dir": "output"},
            "xhs": {"sources": [{"url": "https://www.xiaohongshu.com/explore/abc"}]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            day_dir = Path(tmp) / "2026-07-21"
            day_dir.mkdir()
            (day_dir / "photos.json").write_text(
                json.dumps({"小红书｜人像写真": [GOOD_NOTE]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(xhs_daily, "PROJECT_ROOT", Path(tmp)):
                with mock.patch.object(
                    xhs_daily.xhs_fetcher,
                    "fetch_sources",
                    return_value=[PLACEHOLDER_NOTE],
                ):
                    with mock.patch.object(xhs_daily.xhs_fetcher, "cache_photo_assets", side_effect=lambda photos, *a, **k: photos):
                        config["output"]["dir"] = "."
                        # PROJECT_ROOT / output dir -> tmp if output.dir is "."
                        # Wait: output_dir = PROJECT_ROOT / config["output"]["dir"]
                        # If PROJECT_ROOT is tmp and dir is ".", that's tmp which has 2026-07-21
                        pool = xhs_daily.fetch_pool(config, args)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["note_id"], "643631310000000011011932")


PORTRAIT_NOTE = {
    **GOOD_NOTE,
    "id": "xhs-643631310000000011011932-1",
    "note_id": "643631310000000011011932",
    "note_title": "横店拍摄一日游！",
    "description": "横店拍摄一日游！",
    "caption": "妆造也特别细致特别棒，很适合写真出片",
    "note_image_count": 7,
}

TRAVEL_NOTE = {
    **GOOD_NOTE,
    "id": "xhs-64ba91e5000000000800f849-1",
    "note_id": "64ba91e5000000000800f849",
    "note_title": "西江千户苗寨一日游攻略",
    "description": "西江千户苗寨一日游攻略",
    "caption": "门票、交通和住宿分享，适合周末出行",
    "note_image_count": 1,
    "source_url": "https://www.xiaohongshu.com/explore/64ba91e5000000000800f849",
}

FLOWER_NOTE = {
    **GOOD_NOTE,
    "id": "xhs-6433d257000000000800e88f-1",
    "note_id": "6433d257000000000800e88f",
    "note_title": "电影般的春天｜漫游属于西安的那片紫色花海",
    "description": "电影般的春天｜漫游属于西安的那片紫色花海",
    "caption": "拍照小tips：下午三点后光线更柔和",
    "note_image_count": 13,
    "source_url": "https://www.xiaohongshu.com/explore/6433d257000000000800e88f",
}


class NoteSelectionTests(unittest.TestCase):
    def test_travel_guide_without_photo_terms_is_dropped(self):
        self.assertFalse(xhs_daily._is_reasonable_note([TRAVEL_NOTE], xhs_daily._xhs_config({})))

    def test_portrait_note_is_kept(self):
        self.assertTrue(xhs_daily._is_reasonable_note([PORTRAIT_NOTE], xhs_daily._xhs_config({})))

    def test_prefers_unseen_portrait_over_recently_used_flower_set(self):
        selected = xhs_daily._select_for_date(
            [FLOWER_NOTE, PORTRAIT_NOTE],
            "2026-08-14",
            mode="note",
            count=1,
            recent_note_ids={"6433d257000000000800e88f"},
        )
        self.assertEqual(selected[0]["note_id"], "643631310000000011011932")


if __name__ == "__main__":
    unittest.main()
