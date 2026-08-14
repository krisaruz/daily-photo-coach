"""Unsplash candidates should be ranked and filtered for teaching value."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import fetcher


def _photo(**overrides):
    photo = {
        "id": "abc",
        "likes": 120,
        "width": 4000,
        "height": 3000,
        "sponsored": False,
        "description": "mountain ridge at sunrise",
        "exif": {"model": "Canon EOS R5", "aperture": "8", "exposure_time": "1/250"},
    }
    photo.update(overrides)
    return photo


class PhotoQualityTests(unittest.TestCase):
    def test_sponsored_photos_are_rejected(self):
        self.assertLess(fetcher.photo_quality_score(_photo(sponsored=True)), 0)

    def test_low_resolution_photos_are_rejected(self):
        self.assertLess(fetcher.photo_quality_score(_photo(width=800, height=600)), 0)

    def test_credit_spam_description_is_rejected(self):
        spam = "if you want, credit me by linking back to my website www.example.com"
        self.assertLess(fetcher.photo_quality_score(_photo(description=spam)), 0)

    def test_popular_exif_photo_outranks_unknown_snapshot(self):
        strong = _photo(id="strong", likes=800, exif={"model": "LEICA Q3", "aperture": "1.7"})
        weak = _photo(id="weak", likes=25, exif={}, description="")
        self.assertGreater(fetcher.photo_quality_score(strong), fetcher.photo_quality_score(weak))

    def test_select_best_photos_keeps_top_scored(self):
        candidates = [
            _photo(id="weak", likes=30, exif={}),
            _photo(id="best", likes=900, width=6000, height=4000),
            _photo(id="mid", likes=120),
            _photo(id="spam", description="tag me on instagram @foo"),
        ]
        selected = fetcher.select_best_photos(candidates, limit=2)
        self.assertEqual([photo["id"] for photo in selected], ["best", "mid"])

    def test_split_topic_ids(self):
        self.assertEqual(
            fetcher._as_topic_list("6sMVjTLSkeQ,Fzo3zuOHN6w,bo8jQKTaE0Y"),
            ["6sMVjTLSkeQ", "Fzo3zuOHN6w", "bo8jQKTaE0Y"],
        )


if __name__ == "__main__":
    unittest.main()
