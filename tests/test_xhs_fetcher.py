"""Xiaohongshu fetcher should not treat blocked notes or platform logos as photos."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import xhs_fetcher

PLACEHOLDER_LOGO = (
    "https://picasso-static.xiaohongshu.com/fe-platform/"
    "e6214e4fbfae2cf14d634d4296916e8a5eaefdf4.png"
)
BLOCKED_URL = (
    "https://www.xiaohongshu.com/404?source=/404/sec_TDAZgkzw"
    "?redirectPath=https%3A%2F%2Fwww.xiaohongshu.com%2Fexplore%2F643a5d6900000000130363ba"
    "&error_code=300031&error_msg=%E5%BD%93%E5%89%8D%E7%AC%94%E8%AE%B0%E6%9A%82%E6%97%B6%E6%97%A0%E6%B3%95%E6%B5%8F%E8%A7%88"
)
BLOCKED_HTML = f"""
<html><head>
<meta property="og:title" content="小红书">
<meta property="og:image" content="{PLACEHOLDER_LOGO}">
<meta name="description" content="当前笔记暂时无法浏览">
</head><body>当前笔记暂时无法浏览</body></html>
"""


class PlaceholderDetectionTests(unittest.TestCase):
    def test_picasso_static_logo_is_placeholder(self):
        self.assertTrue(xhs_fetcher.is_placeholder_image_url(PLACEHOLDER_LOGO))

    def test_real_cdn_image_is_not_placeholder(self):
        url = (
            "https://sns-webpic-qc.xhscdn.com/202606140357/"
            "af3b761d4c0b618cece31fa0919b39ce/"
            "1000g0082b2evo12h40005o7pibl0bnims7m4nro!nd_dft_wlteh_jpg_3"
        )
        self.assertFalse(xhs_fetcher.is_placeholder_image_url(url))

    def test_error_300031_page_is_blocked(self):
        self.assertTrue(xhs_fetcher.is_blocked_note_page(BLOCKED_URL, BLOCKED_HTML))

    def test_explore_note_page_is_not_blocked(self):
        url = "https://www.xiaohongshu.com/explore/643631310000000011011932"
        self.assertFalse(xhs_fetcher.is_blocked_note_page(url, "<html>横店拍摄一日游</html>"))


class MetaFallbackTests(unittest.TestCase):
    def test_meta_fallback_skips_platform_logo(self):
        meta = {
            "og:title": ["小红书"],
            "og:image": [PLACEHOLDER_LOGO],
            "description": ["当前笔记暂时无法浏览"],
        }
        photos = xhs_fetcher._meta_to_photos(
            meta,
            BLOCKED_URL,
            "Yeeton",
            xhs_fetcher.DEFAULT_STYLE,
            6,
        )
        self.assertEqual(photos, [])


class FetchSourceTests(unittest.TestCase):
    def test_blocked_note_page_returns_no_photos(self):
        with mock.patch.object(
            xhs_fetcher,
            "_fetch_html",
            return_value=(BLOCKED_HTML, BLOCKED_URL),
        ):
            photos = xhs_fetcher.fetch_source(
                "https://www.xiaohongshu.com/explore/643a5d6900000000130363ba"
            )
        self.assertEqual(photos, [])


class UsablePhotoTests(unittest.TestCase):
    def test_logo_archive_entry_is_not_usable(self):
        photo = {
            "source_platform": "xhs",
            "source_name": "小红书",
            "description": "小红书摄影作品",
            "note_title": "",
            "url_small": PLACEHOLDER_LOGO,
            "url_regular": PLACEHOLDER_LOGO,
            "url_full": PLACEHOLDER_LOGO,
            "source_url": BLOCKED_URL,
        }
        self.assertFalse(xhs_fetcher.is_usable_xhs_photo(photo))

    def test_real_note_archive_entry_is_usable(self):
        photo = {
            "source_platform": "xhs",
            "source_name": "小红书",
            "description": "横店拍摄一日游！",
            "note_title": "横店拍摄一日游！",
            "url_small": "https://sns-webpic-qc.xhscdn.com/example.jpg",
            "source_url": "https://www.xiaohongshu.com/explore/643631310000000011011932",
            "local_url_small": "assets/xhs/643631310000000011011932/xhs-643631310000000011011932-1-small.jpg",
        }
        self.assertTrue(xhs_fetcher.is_usable_xhs_photo(photo))


if __name__ == "__main__":
    unittest.main()
