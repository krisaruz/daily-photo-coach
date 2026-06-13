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


def fetch_photo(access_key: str, query: str = None, topics: str = None, orientation: str = "landscape", featured: bool = False) -> dict[str, Any] | None:
    """从 Unsplash 抓取一张符合主题的随机照片，遇限流自动等待。"""
    import time

    params = {
        "orientation": orientation,
        "content_filter": "high",
    }
    if query:
        params["query"] = query
    if topics:
        params["topics"] = topics
    if featured:
        params["featured"] = "true"

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
                logger.warning("Unsplash API 请求失败 [query=%s, topics=%s]: %s，等待 10s 重试...", query, topics, e)
                time.sleep(10)
                continue
            logger.error("Unsplash API 请求最终失败 [query=%s, topics=%s]: %s", query, topics, e)
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


def fetch_unsplash_photos_for_style(
    config: dict[str, Any], style: dict[str, str], count: int = 3,
    global_seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """使用 Unsplash 抓取一种风格的多张照片，支持 topics 官方精选和 query 关键词。"""
    access_key = config.get("unsplash", {}).get("access_key", "")
    featured = config.get("unsplash", {}).get("featured", False)
    
    if not access_key or access_key == "YOUR_UNSPLASH_ACCESS_KEY":
        logger.error("Unsplash Access Key 未配置，跳过 Unsplash 抓取")
        return []

    orientations = ["landscape", "portrait", "squarish"]
    
    style_queries = style.get("query", "")
    queries = style_queries if isinstance(style_queries, list) else [style_queries] if style_queries else []
    
    style_topics = style.get("topics", "")
    topics = style_topics if isinstance(style_topics, list) else [style_topics] if style_topics else []

    photos = []
    local_seen: set[str] = set()
    max_retries = max(count * 10, 20)

    attempts = 0
    i = 0
    while len(photos) < count and attempts < max_retries:
        orientation = orientations[i % len(orientations)]
        
        query = None
        topic = None
        
        if topics:
            topic = topics[i % len(topics)]
        elif queries:
            query = queries[i % len(queries)]
            
        photo = fetch_photo(access_key, query=query, topics=topic, orientation=orientation, featured=featured)
        attempts += 1

        if not photo:
            logger.warning("  [%s] Unsplash 抓取失败，重试", style["label"])
            continue

        pid = photo["id"]
        if pid in local_seen or (global_seen and pid in global_seen):
            logger.debug("  [%s] 重复照片 %s，跳过", style["label"], pid)
            continue

        photo["style_query"] = topic or query or ""
        photo["style_label"] = style["label"]
        photo["style_color"] = style.get("color", "#6b7280")
        photo["style_icon"] = style.get("icon", "📷")
        photos.append(photo)
        local_seen.add(pid)
        if global_seen is not None:
            global_seen.add(pid)
        i += 1
        logger.info(
            "  [Unsplash %s %d/%d] %s by %s",
            style["label"], len(photos), count, pid, photo["photographer"],
        )

    if len(photos) < count:
        logger.warning("  [%s] Unsplash 只获取到 %d/%d 张（去重后）", style["label"], len(photos), count)

    return photos


FLICKR_API_URL = "https://api.flickr.com/services/rest/"


def fetch_flickr_candidates(api_key: str, query: str) -> list[dict[str, Any]]:
    """从 Flickr 搜索符合主题且最有趣的照片列表。"""
    params = {
        "method": "flickr.photos.search",
        "api_key": api_key,
        "text": query,
        "sort": "interestingness-desc",
        "content_type": 1,  # 仅限照片
        "media": "photos",
        "extras": "url_c,url_l,url_o,owner_name",
        "format": "json",
        "nojsoncallback": 1,
        "per_page": 100,
    }
    try:
        resp = requests.get(FLICKR_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "ok":
            logger.error("Flickr API 搜索失败: %s", data.get("message", "Unknown error"))
            return []
        return data.get("photos", {}).get("photo", [])
    except Exception as e:
        logger.error("Flickr API 搜索请求异常 [query=%s]: %s", query, e)
        return []


def fetch_flickr_exif(api_key: str, photo_id: str) -> dict[str, Any]:
    """获取指定 Flickr 照片的 EXIF 元数据。"""
    params = {
        "method": "flickr.photos.getExif",
        "api_key": api_key,
        "photo_id": photo_id,
        "format": "json",
        "nojsoncallback": 1,
    }
    exif_data = {
        "make": None,
        "model": None,
        "aperture": None,
        "exposure_time": None,
        "focal_length": None,
        "iso": None,
    }
    try:
        resp = requests.get(FLICKR_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("stat") != "ok":
            logger.warning("Flickr API EXIF 获取失败 [id=%s]: %s", photo_id, data.get("message", "Unknown error"))
            return exif_data
        
        exif_list = data.get("photo", {}).get("exif", [])
        for item in exif_list:
            tag = item.get("tag", "").lower()
            label = item.get("label", "").lower()
            content = item.get("raw", {}).get("_content", "")
            if not content:
                continue
            
            if tag == "make" or "manufacturer" in label:
                exif_data["make"] = content
            elif tag == "model" or "camera" in label:
                exif_data["model"] = content
            elif tag == "aperture" or tag == "fnumber" or label == "aperture":
                exif_data["aperture"] = content
            elif tag == "exposuretime" or label == "exposure":
                exif_data["exposure_time"] = content
            elif tag == "focallength" or label == "focal length":
                exif_data["focal_length"] = content
            elif tag == "iso" or label == "iso":
                exif_data["iso"] = content
                
    except Exception as e:
        logger.warning("Flickr EXIF 请求异常 [id=%s]: %s", photo_id, e)
    
    return exif_data


def matches_orientation(photo: dict[str, Any], orientation: str) -> bool:
    """检查 Flickr 照片候选是否符合指定的宽高方向。"""
    w = int(photo.get("width_l") or photo.get("width_c") or 0)
    h = int(photo.get("height_l") or photo.get("height_c") or 0)
    if w == 0 or h == 0:
        return True
    
    if orientation == "landscape":
        return w > h
    elif orientation == "portrait":
        return h > w
    elif orientation == "squarish":
        return 0.8 <= (w / h) <= 1.2
    return True


def fetch_flickr_photos_for_style(
    config: dict[str, Any], style: dict[str, str], count: int = 3,
    global_seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """使用 Flickr 抓取一种风格的多张照片。"""
    api_key = config.get("flickr", {}).get("api_key", "")
    if not api_key:
        logger.error("Flickr API Key 未配置，跳过 Flickr 抓取")
        return []

    orientations = ["landscape", "portrait", "squarish"]
    queries = style["query"] if isinstance(style["query"], list) else [style["query"]]
    photos = []
    local_seen: set[str] = set()

    # 批量拉取候选集，减少 HTTP 请求数
    candidates_by_query = {}
    for query in queries:
        candidates_by_query[query] = fetch_flickr_candidates(api_key, query)

    attempts = 0
    max_attempts = count * 5
    i = 0

    while len(photos) < count and attempts < max_attempts:
        orientation = orientations[i % len(orientations)]
        query = queries[i % len(queries)]
        candidates = candidates_by_query.get(query, [])
        
        found_photo = None
        for item in candidates:
            pid = item["id"]
            if pid in local_seen or (global_seen and pid in global_seen):
                continue
            if matches_orientation(item, orientation):
                found_photo = item
                break
                
        attempts += 1
        i += 1
        
        if not found_photo:
            continue
            
        pid = found_photo["id"]
        server = found_photo.get("server")
        secret = found_photo.get("secret")
        owner = found_photo.get("owner")
        
        # 组装图片 URL
        url_full = found_photo.get("url_o") or found_photo.get("url_l") or found_photo.get("url_c") or f"https://live.staticflickr.com/{server}/{pid}_{secret}_b.jpg"
        url_regular = found_photo.get("url_l") or found_photo.get("url_c") or f"https://live.staticflickr.com/{server}/{pid}_{secret}_c.jpg"
        url_small = found_photo.get("url_c") or f"https://live.staticflickr.com/{server}/{pid}_{secret}_z.jpg"
        
        logger.info("  [%s] 获取 Flickr EXIF ... %s", style["label"], pid)
        exif = fetch_flickr_exif(api_key, pid)
        
        photo_record = {
            "id": pid,
            "url_regular": url_regular,
            "url_full": url_full,
            "url_small": url_small,
            "width": int(found_photo.get("width_l") or found_photo.get("width_c") or 1024),
            "height": int(found_photo.get("height_l") or found_photo.get("height_c") or 768),
            "description": found_photo.get("title") or "",
            "photographer": found_photo.get("ownername") or "Flickr User",
            "photographer_url": f"https://www.flickr.com/photos/{owner}",
            "unsplash_url": f"https://www.flickr.com/photos/{owner}/{pid}",  # 保持字段名兼容 renderer/analyzer
            "flickr_url": f"https://www.flickr.com/photos/{owner}/{pid}",
            "exif": exif,
            "style_query": query,
            "style_label": style["label"],
            "style_color": style.get("color", "#6b7280"),
            "style_icon": style.get("icon", "📷"),
        }
        
        photos.append(photo_record)
        local_seen.add(pid)
        if global_seen is not None:
            global_seen.add(pid)
            
        logger.info(
            "  [Flickr %s %d/%d] %s by %s",
            style["label"], len(photos), count, pid, photo_record["photographer"],
        )

    if len(photos) < count:
        logger.warning("  [%s] Flickr 只获取到 %d/%d 张（去重后）", style["label"], len(photos), count)

    return photos


def fetch_photos_for_style(
    config_or_key: str | dict[str, Any], style: dict[str, str], count: int = 3,
    global_seen: set[str] | None = None,
) -> list[dict[str, Any]]:
    """兼容旧调用签名，并根据数据源分发抓取逻辑。"""
    if isinstance(config_or_key, dict):
        config = config_or_key
    else:
        config = {
            "unsplash": {"access_key": config_or_key, "featured": False},
            "daily": {"source": "unsplash"}
        }

    source = config.get("daily", {}).get("source", "unsplash")
    
    if source == "flickr":
        return fetch_flickr_photos_for_style(config, style, count, global_seen)
    else:
        return fetch_unsplash_photos_for_style(config, style, count, global_seen)


def fetch_daily(
    access_key_or_config: str | dict[str, Any], styles: list[dict[str, str]], photos_per_style: int = 3,
    global_seen: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按风格分类抓取今日全部照片，返回 {style_label: [photos]} 字典。"""
    result: dict[str, list[dict[str, Any]]] = {}

    for style in styles:
        logger.info("抓取 [%s] ...", style["label"])
        photos = fetch_photos_for_style(access_key_or_config, style, count=photos_per_style, global_seen=global_seen)
        if photos:
            result[style["label"]] = photos

    return result

