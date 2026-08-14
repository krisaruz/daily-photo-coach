"""Public pages must not display Xiaohongshu photos."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import renderer

XHS_PHOTO = {
    "id": "xhs-643631310000000011011932-1",
    "source_platform": "xhs",
    "source_name": "小红书",
    "description": "横店拍摄一日游！",
    "note_title": "横店拍摄一日游！",
    "note_id": "643631310000000011011932",
    "note_image_index": 1,
    "note_image_count": 2,
    "photographer": "黄小人",
    "caption": "妆造细致",
    "url_small": "https://sns-webpic-qc.xhscdn.com/example-small.jpg",
    "url_regular": "https://sns-webpic-qc.xhscdn.com/example.jpg",
    "url_full": "https://sns-webpic-qc.xhscdn.com/example-full.jpg",
    "local_url_small": "assets/xhs/643631310000000011011932/xhs-1-small.jpg",
    "local_url_regular": "assets/xhs/643631310000000011011932/xhs-1-regular.jpg",
    "source_url": "https://www.xiaohongshu.com/explore/643631310000000011011932",
    "style_label": "小红书｜人像写真",
    "style_color": "#be185d",
    "style_icon": "📕",
    "analysis": "## 直觉\n汉服的轻盈白纱和古城墙形成反差。",
}

UNSPLASH_PHOTO = {
    "id": "unsplash-1",
    "description": "mountain ridge",
    "photographer": "Ada",
    "url_small": "https://images.unsplash.com/photo-small.jpg",
    "url_regular": "https://images.unsplash.com/photo.jpg",
    "url_full": "https://images.unsplash.com/photo-full.jpg",
    "unsplash_url": "https://unsplash.com/photos/abc",
    "style_label": "风光/自然",
    "style_color": "#16a34a",
    "style_icon": "🏔️",
    "analysis": "## 直觉\n山脊的光。",
}


class ImageUrlTests(unittest.TestCase):
    def test_xhs_photo_never_returns_local_or_cdn_url(self):
        self.assertEqual(renderer._image_url(XHS_PHOTO, "small"), "")
        self.assertEqual(renderer._image_url(XHS_PHOTO, "regular"), "")
        self.assertEqual(renderer._image_url(XHS_PHOTO, "full"), "")

    def test_unsplash_photo_still_returns_remote_url(self):
        self.assertEqual(
            renderer._image_url(UNSPLASH_PHOTO, "regular"),
            "https://images.unsplash.com/photo.jpg",
        )

    def test_preview_picker_skips_xhs_and_keeps_unsplash(self):
        data = {
            "小红书｜人像写真": [XHS_PHOTO],
            "风光/自然": [UNSPLASH_PHOTO],
        }
        self.assertEqual(
            renderer._pick_preview_images(data, limit=3),
            ["https://images.unsplash.com/photo-small.jpg"],
        )


class ArchiveAndRenderTests(unittest.TestCase):
    def test_save_archive_strips_local_xhs_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer.save_archive(
                {"小红书｜人像写真": [dict(XHS_PHOTO)]},
                "2026-08-14",
                tmp,
            )
            saved = json.loads((Path(tmp) / "2026-08-14" / "photos.json").read_text(encoding="utf-8"))
            photo = saved["小红书｜人像写真"][0]
            self.assertNotIn("local_url_small", photo)
            self.assertNotIn("local_url_regular", photo)
            self.assertEqual(photo["url_regular"], XHS_PHOTO["url_regular"])

    def test_markdown_does_not_embed_xhs_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            renderer.render_markdown(
                {"小红书｜人像写真": [XHS_PHOTO]},
                "2026-08-14",
                tmp,
            )
            text = (Path(tmp) / "2026-08-14" / "daily.md").read_text(encoding="utf-8")
            self.assertNotIn("![", text)
        self.assertNotIn("assets/xhs", text)
        self.assertNotIn("xhscdn", text)
        self.assertIn("xiaohongshu.com/explore/643631310000000011011932", text)
        self.assertIn("汉服的轻盈白纱", text)

    def test_xhs_site_has_analysis_and_source_link_but_no_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = Path(tmp) / "2026-08-13"
            day.mkdir()
            (day / "photos.json").write_text(
                json.dumps({"小红书｜人像写真": [XHS_PHOTO]}, ensure_ascii=False),
                encoding="utf-8",
            )
            renderer.render_xhs_site(tmp)
            index_html = (Path(tmp) / "xhs" / "index.html").read_text(encoding="utf-8")
            detail_html = (Path(tmp) / "xhs" / "2026-08-13" / "index.html").read_text(encoding="utf-8")

        for html in (index_html, detail_html):
            self.assertNotIn("assets/xhs", html)
            self.assertNotIn("xhscdn", html)
            self.assertNotIn("picasso-static", html)
            self.assertNotIn("<img", html.lower())
        self.assertIn("横店拍摄一日游", index_html)
        self.assertIn("xiaohongshu.com/explore/643631310000000011011932", detail_html)
        self.assertIn("汉服的轻盈白纱", detail_html)
        self.assertIn("不转载", detail_html)
        self.assertIn("不托管", detail_html)
