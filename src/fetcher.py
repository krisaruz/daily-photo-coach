"""Unsplash 图片抓取模块 -- 按风格主题每日抓取高质量摄影作品。"""

import logging
import random
from typing import Any

import requests

logger = logging.getLogger(__name__)

UNSPLASH_RANDOM_URL = "https://api.unsplash.com/photos/random"


def fetch_photo(access_key: str, query: str, orientation: str = "landscape") -> dict[str, Any] | None:
    """从 Unsplash 抓取一张符合主题的随机照片。"""
    params = {
        "query": query,
        "orientation": orientation,
        "content_filter": "high",
    }
    headers = {
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    }

    try:
        resp = requests.get(UNSPLASH_RANDOM_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error("Unsplash API 请求失败 [query=%s]: %s", query, e)
        return None

    exif = data.get("exif") or {}

    return {
        "id": data["id"],
        "url_regular": data["urls"]["regular"],
        "url_full": data["urls"]["full"],
        "url_small": data["urls"]["small"],
        "width": data.get("width"),
        "height": data.get("height"),
        "description": data.get("description") or data.get("alt_description") or "",
        "photographer": data.get("user", {}).get("name", "Unknown"),
        "photographer_url": data.get("user", {}).get("links", {}).get("html", ""),
        "unsplash_url": data.get("links", {}).get("html", ""),
        "download_location": data.get("links", {}).get("download_location", ""),
        "exif": {
            "make": exif.get("make"),
            "model": exif.get("model"),
            "aperture": exif.get("aperture"),
            "exposure_time": exif.get("exposure_time"),
            "focal_length": exif.get("focal_length"),
            "iso": exif.get("iso"),
        },
    }


def fetch_photos_for_style(
    access_key: str, style: dict[str, str], count: int = 3
) -> list[dict[str, Any]]:
    """为一种风格抓取多张照片。"""
    orientations = ["landscape", "portrait", "squarish"]
    photos = []
    seen_ids: set[str] = set()

    for i in range(count):
        orientation = orientations[i % len(orientations)]
        photo = fetch_photo(access_key, query=style["query"], orientation=orientation)
        if photo and photo["id"] not in seen_ids:
            photo["style_query"] = style["query"]
            photo["style_label"] = style["label"]
            photo["style_color"] = style.get("color", "#6b7280")
            photo["style_icon"] = style.get("icon", "📷")
            photos.append(photo)
            seen_ids.add(photo["id"])
            logger.info(
                "  [%s %d/%d] %s by %s",
                style["label"], i + 1, count, photo["id"], photo["photographer"],
            )
        else:
            logger.warning("  [%s %d/%d] 抓取失败或重复，跳过", style["label"], i + 1, count)

    return photos


def fetch_daily(
    access_key: str, styles: list[dict[str, str]], photos_per_style: int = 3
) -> dict[str, list[dict[str, Any]]]:
    """按风格分类抓取今日全部照片，返回 {style_label: [photos]} 字典。"""
    result: dict[str, list[dict[str, Any]]] = {}

    for style in styles:
        logger.info("抓取 [%s] ...", style["label"])
        photos = fetch_photos_for_style(access_key, style, count=photos_per_style)
        if photos:
            result[style["label"]] = photos

    return result
