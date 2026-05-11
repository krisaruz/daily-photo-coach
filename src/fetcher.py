"""Unsplash 图片抓取模块 -- 按风格主题每日抓取高质量摄影作品。"""

import json
import logging
import random
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

UNSPLASH_RANDOM_URL = "https://api.unsplash.com/photos/random"


def load_historical_ids(output_dir: str) -> set[str]:
    """扫描 output/ 下所有历史 photos.json，收集已用过的 photo ID。"""
    seen: set[str] = set()
    output_path = Path(output_dir)
    if not output_path.exists():
        return seen
    for json_file in output_path.glob("*/photos.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for photos in data.values():
                for photo in photos:
                    if photo.get("id"):
                        seen.add(photo["id"])
        except Exception:
            continue
    logger.info("已加载 %d 个历史 photo ID 用于去重", len(seen))
    return seen


def fetch_photo(access_key: str, query: str, orientation: str = "landscape") -> dict[str, Any] | None:
    """从 Unsplash 抓取一张符合主题的随机照片，遇限流自动等待。"""
    import time

    params = {
        "query": query,
        "orientation": orientation,
        "content_filter": "high",
    }
    headers = {
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    }

    for attempt in range(10):
        try:
            resp = requests.get(UNSPLASH_RANDOM_URL, params=params, headers=headers, timeout=30)
            if resp.status_code == 403:
                remaining = resp.headers.get("X-Ratelimit-Remaining", "0")
                if remaining == "0" or resp.status_code == 403:
                    wait = 3660  # 等 61 分钟（配额每小时重置）
                    logger.warning("Unsplash API 限流（剩余: %s），等待 %d 分钟后继续...", remaining, wait // 60)
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            data = resp.json()
            time.sleep(1.2)
            break
        except requests.RequestException as e:
            if attempt < 9:
                logger.warning("Unsplash API 请求失败 [query=%s]: %s，等待 10s 重试...", query, e)
                time.sleep(10)
                continue
            logger.error("Unsplash API 请求最终失败 [query=%s]: %s", query, e)
            return None
    else:
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
    access_key: str, style: dict[str, str], count: int = 3,
    global_seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """为一种风格抓取多张照片，支持全局去重。"""
    orientations = ["landscape", "portrait", "squarish"]
    photos = []
    local_seen: set[str] = set()
    max_retries = count * 3

    attempts = 0
    i = 0
    while len(photos) < count and attempts < max_retries:
        orientation = orientations[i % len(orientations)]
        photo = fetch_photo(access_key, query=style["query"], orientation=orientation)
        attempts += 1

        if not photo:
            logger.warning("  [%s] 抓取失败，重试", style["label"])
            continue

        pid = photo["id"]
        if pid in local_seen or (global_seen and pid in global_seen):
            logger.debug("  [%s] 重复照片 %s，跳过", style["label"], pid)
            continue

        photo["style_query"] = style["query"]
        photo["style_label"] = style["label"]
        photo["style_color"] = style.get("color", "#6b7280")
        photo["style_icon"] = style.get("icon", "📷")
        photos.append(photo)
        local_seen.add(pid)
        if global_seen is not None:
            global_seen.add(pid)
        i += 1
        logger.info(
            "  [%s %d/%d] %s by %s",
            style["label"], len(photos), count, pid, photo["photographer"],
        )

    if len(photos) < count:
        logger.warning("  [%s] 只获取到 %d/%d 张（去重后）", style["label"], len(photos), count)

    return photos


def fetch_daily(
    access_key: str, styles: list[dict[str, str]], photos_per_style: int = 3,
    global_seen: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按风格分类抓取今日全部照片，返回 {style_label: [photos]} 字典。"""
    result: dict[str, list[dict[str, Any]]] = {}

    for style in styles:
        logger.info("抓取 [%s] ...", style["label"])
        photos = fetch_photos_for_style(access_key, style, count=photos_per_style, global_seen=global_seen)
        if photos:
            result[style["label"]] = photos

    return result
