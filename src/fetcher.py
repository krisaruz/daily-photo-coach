"""Unsplash 图片抓取模块 -- 按风格主题每日抓取高质量摄影作品。"""

import hashlib
import json
import logging
import os
import random
from datetime import date
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

UNSPLASH_RANDOM_URL = "https://api.unsplash.com/photos/random"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"
MIN_LONG_EDGE = 1600
MIN_LIKES = 40
SPAM_DESCRIPTION_MARKERS = (
    "credit me by linking",
    "tag me on instagram",
    "follow me on instagram",
    "linking back to my website",
)


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


def _as_topic_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _as_query_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _style_fit_score(photo: dict[str, Any], style_label: str = "") -> float:
    """Reward frames that match the teaching style; penalize awkward crops."""
    width = int(photo.get("width") or 0)
    height = int(photo.get("height") or 0)
    if width <= 0 or height <= 0:
        return 0
    ratio = width / height
    label = style_label or str(photo.get("style_label") or "")
    square = 0.9 <= ratio <= 1.11
    if "风光" in label or "建筑" in label or "夜景" in label:
        if ratio >= 1.25:
            return 12
        if square:
            return -18
        return -6
    if "人像" in label:
        if ratio <= 0.85:
            return 12
        if square:
            return -12
        return -4
    if square:
        return -8
    return 0


def photo_quality_score(photo: dict[str, Any], style_label: str = "") -> float:
    """Score a candidate for photography teaching. Negative means reject."""
    if photo.get("sponsored"):
        return -100
    width = int(photo.get("width") or 0)
    height = int(photo.get("height") or 0)
    long_edge = max(width, height)
    if long_edge < MIN_LONG_EDGE:
        return -50
    likes = int(photo.get("likes") or 0)
    if likes < MIN_LIKES:
        return -30

    description = str(photo.get("description") or "").lower()
    if any(marker in description for marker in SPAM_DESCRIPTION_MARKERS):
        return -40

    score = min(likes, 2000) / 20
    score += min(long_edge, 6000) / 1000
    exif = photo.get("exif") or {}
    if exif.get("model"):
        score += 15
    if exif.get("aperture") and exif.get("exposure_time"):
        score += 10
    if description and "http" not in description:
        score += 5
    score += _style_fit_score(photo, style_label)
    return score


def select_best_photos(
    candidates: list[dict[str, Any]],
    limit: int,
    style_label: str = "",
) -> list[dict[str, Any]]:
    """Keep the highest-scoring unique photos that pass the quality floor."""
    ranked = []
    seen: set[str] = set()
    for photo in candidates:
        pid = str(photo.get("id") or "")
        if not pid or pid in seen:
            continue
        score = photo_quality_score(photo, style_label=style_label)
        if score < 0:
            continue
        seen.add(pid)
        ranked.append((score, photo))
    ranked.sort(key=lambda item: item[0], reverse=True)

    picked: list[dict[str, Any]] = []
    picked_ids: set[str] = set()
    used_photographers: set[str] = set()

    def photographer_key(photo: dict[str, Any]) -> str:
        return str(photo.get("photographer") or "").strip().lower()

    for _, photo in ranked:
        photog = photographer_key(photo)
        if photog and photog in used_photographers:
            continue
        picked.append(photo)
        picked_ids.add(str(photo["id"]))
        if photog:
            used_photographers.add(photog)
        if len(picked) >= limit:
            return picked

    for _, photo in ranked:
        pid = str(photo["id"])
        if pid in picked_ids:
            continue
        picked.append(photo)
        picked_ids.add(pid)
        if len(picked) >= limit:
            break
    return picked


def _normalise_unsplash_photo(data: dict[str, Any]) -> dict[str, Any]:
    exif = data.get("exif") or {}
    description = data.get("description") or data.get("alt_description") or ""
    urls = data.get("urls") or {}
    user = data.get("user") or {}
    links = data.get("links") or {}
    return {
        "id": data["id"],
        "url_regular": urls.get("regular") or "",
        "url_full": urls.get("full") or "",
        "url_small": urls.get("small") or "",
        "width": data.get("width"),
        "height": data.get("height"),
        "likes": int(data.get("likes") or 0),
        "sponsored": bool(data.get("sponsorship")),
        "description": description,
        "photographer": user.get("name", "Unknown"),
        "photographer_url": (user.get("links") or {}).get("html", ""),
        "unsplash_url": links.get("html", ""),
        "download_location": links.get("download_location", ""),
        "exif": {
            "make": exif.get("make"),
            "model": exif.get("model"),
            "aperture": exif.get("aperture"),
            "exposure_time": exif.get("exposure_time"),
            "focal_length": exif.get("focal_length"),
            "iso": exif.get("iso"),
        },
    }


def fetch_photo(access_key: str, query: str = None, topics: str = None, orientation: str = "landscape", featured: bool = False) -> dict[str, Any] | None:
    """从 Unsplash 抓取一张符合主题的随机照片，遇限流自动等待。"""
    photos = _request_unsplash_random(
        access_key,
        query=query,
        topics=topics,
        orientation=orientation,
        featured=featured,
        count=1,
    )
    return photos[0] if photos else None


def _request_unsplash_random(
    access_key: str,
    *,
    query: str | None,
    topics: str | None,
    orientation: str | None,
    featured: bool,
    count: int,
) -> list[dict[str, Any]]:
    import time

    params: dict[str, Any] = {
        "content_filter": "high",
        "count": min(max(count, 1), 30),
    }
    if orientation:
        params["orientation"] = orientation
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
            remaining = resp.headers.get("X-Ratelimit-Remaining", "")
            if resp.status_code == 403:
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    logger.error("Unsplash API 限流（剩余: %s），运行在 CI 环境中，立即终止抓取以避免挂起。", remaining)
                    return []
                wait = 3660
                logger.warning("Unsplash API 限流（剩余: %s），等待 %d 分钟后继续...", remaining, wait // 60)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            time.sleep(1.2)
            items = payload if isinstance(payload, list) else [payload]
            photos = []
            for item in items:
                if isinstance(item, dict) and item.get("id") and item.get("urls"):
                    photos.append(_normalise_unsplash_photo(item))
            return photos
        except requests.RequestException as exc:
            if attempt < 9:
                logger.warning("Unsplash API 请求失败 [query=%s, topics=%s]: %s，等待 10s 重试...", query, topics, exc)
                time.sleep(10)
                continue
            logger.error("Unsplash API 请求最终失败 [query=%s, topics=%s]: %s", query, topics, exc)
            return []
    return []


def _request_unsplash_search(
    access_key: str,
    *,
    query: str,
    orientation: str | None,
    page: int,
    per_page: int,
) -> list[dict[str, Any]]:
    """Search Unsplash for a larger, relevance-ranked candidate pool."""
    import time

    params: dict[str, Any] = {
        "query": query,
        "page": max(page, 1),
        "per_page": min(max(per_page, 1), 30),
        "order_by": "relevant",
        "content_filter": "high",
    }
    if orientation:
        params["orientation"] = orientation

    headers = {
        "Authorization": f"Client-ID {access_key}",
        "Accept-Version": "v1",
    }

    for attempt in range(10):
        try:
            resp = requests.get(UNSPLASH_SEARCH_URL, params=params, headers=headers, timeout=30)
            remaining = resp.headers.get("X-Ratelimit-Remaining", "")
            if resp.status_code == 403:
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    logger.error("Unsplash Search 限流（剩余: %s），运行在 CI 环境中，立即终止抓取以避免挂起。", remaining)
                    return []
                wait = 3660
                logger.warning("Unsplash Search 限流（剩余: %s），等待 %d 分钟后继续...", remaining, wait // 60)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            time.sleep(1.2)
            items = payload.get("results") if isinstance(payload, dict) else payload
            if not isinstance(items, list):
                return []
            photos = []
            for item in items:
                if isinstance(item, dict) and item.get("id") and item.get("urls"):
                    photos.append(_normalise_unsplash_photo(item))
            return photos
        except requests.RequestException as exc:
            if attempt < 9:
                logger.warning("Unsplash Search 请求失败 [query=%s]: %s，等待 10s 重试...", query, exc)
                time.sleep(10)
                continue
            logger.error("Unsplash Search 请求最终失败 [query=%s]: %s", query, exc)
            return []
    return []


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

    queries = _as_query_list(style.get("query", ""))
    topics = _as_topic_list(style.get("topics", ""))
    orientations = ["landscape", "portrait"]
    candidates: list[dict[str, Any]] = []
    local_seen: set[str] = set()
    style_label = style["label"]
    page = 1 + (
        int(hashlib.sha256(f"{date.today().isoformat()}:{style_label}".encode("utf-8")).hexdigest()[:8], 16) % 4
    )

    def accept(photo: dict[str, Any], via: str) -> None:
        pid = photo.get("id")
        if not pid or pid in local_seen or (global_seen and pid in global_seen):
            return
        if photo_quality_score(photo, style_label=style_label) < 0:
            logger.debug("  [%s] 低质量照片 %s，跳过", style_label, pid)
            return
        photo["style_query"] = via
        photo["style_label"] = style_label
        photo["style_color"] = style.get("color", "#6b7280")
        photo["style_icon"] = style.get("icon", "📷")
        candidates.append(photo)
        local_seen.add(pid)

    for index, orientation in enumerate(orientations):
        query = queries[index % len(queries)] if queries else None
        search_query = query or "photography"
        for photo in _request_unsplash_search(
            access_key,
            query=search_query,
            orientation=orientation,
            page=page,
            per_page=30,
        ):
            accept(photo, search_query)

    if len(select_best_photos(candidates, count, style_label=style_label)) < count:
        logger.info("  [%s] Search 候选不足，补充 Unsplash random", style_label)
        candidate_count = min(max(count * 3, 6), 12)
        for index, orientation in enumerate(orientations):
            topic = topics[index % len(topics)] if topics else None
            query = queries[index % len(queries)] if queries else None
            for photo in _request_unsplash_random(
                access_key,
                query=query,
                topics=topic,
                orientation=orientation,
                featured=featured,
                count=candidate_count,
            ):
                accept(photo, topic or query or "")

    selected = select_best_photos(candidates, count, style_label=style_label)
    if global_seen is not None:
        for photo in selected:
            global_seen.add(photo["id"])

    for photo in selected:
        logger.info(
            "  [Unsplash %s] %s by %s (likes=%s score=%.1f)",
            style_label,
            photo["id"],
            photo["photographer"],
            photo.get("likes"),
            photo_quality_score(photo, style_label=style_label),
        )

    if len(selected) < count:
        logger.warning("  [%s] Unsplash 只筛选到 %d/%d 张高质量照片", style_label, len(selected), count)
    return selected


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

