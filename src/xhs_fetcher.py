"""Xiaohongshu public share-page fetcher.

This module only reads publicly reachable share/note pages. It does not log in,
solve challenges, or bypass access controls.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_STYLE = {
    "label": "小红书精选",
    "color": "#be185d",
    "icon": "📕",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

IMAGE_HEADERS = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
    "Referer": "https://www.xiaohongshu.com/",
}


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v for k, v in attrs if v is not None}
        if tag.lower() == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content")
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag.lower() == "a" and attr.get("href"):
            self.links.append(attr["href"])


def _clean_text(value: Any, keep_lines: bool = False) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("[话题]", "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if keep_lines:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return re.sub(r"\s+", " ", text).strip()


def _normalise_url(url: str | None, base_url: str = "") -> str:
    if not url:
        return ""
    value = html.unescape(str(url)).strip().replace("\\u002F", "/")
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(base_url, value)
    if value.startswith("http://sns-") or value.startswith("http://ci.xiaohongshu.com"):
        value = "https://" + value[len("http://") :]
    return value


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _safe_asset_name(value: Any, fallback: str) -> str:
    raw = str(value or fallback)
    safe = re.sub(r"[^0-9A-Za-z._-]+", "-", raw).strip("-._")
    return safe or fallback


def _image_extension(resp: requests.Response, url: str) -> str:
    content_type = resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    if content_type == "image/gif":
        return ".gif"

    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ext in path:
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def _existing_asset(stem: Path) -> Path | None:
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = stem.with_suffix(ext)
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _make_session(cookie: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def _fetch_html(session: requests.Session, url: str, timeout: int = 30) -> tuple[str, str]:
    logger.info("读取小红书公开页面: %s", url)
    resp = session.get(url, allow_redirects=True, timeout=timeout)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    time.sleep(0.8)
    return resp.text, resp.url


def _parse_meta(page_html: str) -> tuple[dict[str, list[str]], list[str]]:
    parser = _MetaParser()
    parser.feed(page_html)
    return parser.meta, parser.links


def _parse_initial_state(page_html: str) -> dict[str, Any]:
    match = re.search(r"window\.__INITIAL_STATE__=(\{.*?\})</script>", page_html, re.S)
    if not match:
        return {}

    raw = match.group(1)
    raw = re.sub(r"(?<=[:\[,])undefined(?=[,\]}])", "null", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("小红书页面状态解析失败，改用 meta fallback: %s", exc)
        return {}


def _walk_note_dicts(obj: Any, seen: set[str]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        note = obj.get("note") if isinstance(obj.get("note"), dict) else obj
        note_id = str(note.get("noteId") or note.get("id") or "")
        if isinstance(note.get("imageList"), list) and (note.get("desc") or note.get("title")):
            key = note_id or hashlib.sha1(json.dumps(note, sort_keys=True, default=str).encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                notes.append(note)
        for value in obj.values():
            notes.extend(_walk_note_dicts(value, seen))
    elif isinstance(obj, list):
        for value in obj:
            notes.extend(_walk_note_dicts(value, seen))
    return notes


def _extract_note_dicts(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not state:
        return []

    notes: list[dict[str, Any]] = []
    seen: set[str] = set()
    detail_map = state.get("note", {}).get("noteDetailMap", {})
    if isinstance(detail_map, dict):
        for item in detail_map.values():
            note = item.get("note") if isinstance(item, dict) else None
            if not isinstance(note, dict):
                continue
            note_id = str(note.get("noteId") or "")
            if note_id and note_id not in seen:
                seen.add(note_id)
                notes.append(note)

    notes.extend(_walk_note_dicts(state, seen))
    return notes


def _extract_note_links(page_html: str, links: list[str], base_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    candidates = list(links)
    candidates.extend(
        match.group(0)
        for match in re.finditer(
            r"(?:https?:)?//www\.xiaohongshu\.com/(?:discovery/item|explore)/[0-9a-fA-F]{24}[^\"'<\s]*",
            page_html,
        )
    )
    candidates.extend(
        match.group(0)
        for match in re.finditer(r"/(?:discovery/item|explore)/[0-9a-fA-F]{24}[^\"'<\s]*", page_html)
    )

    for raw in candidates:
        url = _normalise_url(raw, base_url)
        if not _is_http_url(url):
            continue
        if "/discovery/item/" not in url and "/explore/" not in url:
            continue
        clean = url.split("#", 1)[0]
        if clean not in seen:
            found.append(clean)
            seen.add(clean)

    return found


def _image_urls(image: dict[str, Any], base_url: str) -> tuple[str, str]:
    full = _normalise_url(image.get("urlDefault") or image.get("url"), base_url)
    preview = _normalise_url(image.get("urlPre"), base_url)

    info_list = image.get("infoList") if isinstance(image.get("infoList"), list) else []
    dft_urls = [
        _normalise_url(info.get("url"), base_url)
        for info in info_list
        if isinstance(info, dict) and "DFT" in str(info.get("imageScene", "")).upper()
    ]
    prv_urls = [
        _normalise_url(info.get("url"), base_url)
        for info in info_list
        if isinstance(info, dict) and "PRV" in str(info.get("imageScene", "")).upper()
    ]

    full = full or next((url for url in dft_urls if url), "")
    preview = preview or next((url for url in prv_urls if url), "")
    return full or preview, preview or full


def _profile_url(user: dict[str, Any]) -> str:
    user_id = user.get("userId") or user.get("id")
    if not user_id:
        return ""
    return f"https://www.xiaohongshu.com/user/profile/{user_id}"


def _note_to_photos(
    note: dict[str, Any],
    page_url: str,
    source_name: str,
    style: dict[str, str],
    max_images: int,
) -> list[dict[str, Any]]:
    note_id = str(note.get("noteId") or note.get("id") or hashlib.sha1(page_url.encode()).hexdigest()[:24])
    title = _clean_text(note.get("title"))
    caption = _clean_text(note.get("desc"), keep_lines=True)
    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    photographer = _clean_text(user.get("nickname")) or source_name or "小红书博主"
    photographer_url = _profile_url(user)
    note_url = page_url.split("#", 1)[0]

    images = note.get("imageList") if isinstance(note.get("imageList"), list) else []
    image_count = len(images)
    photos: list[dict[str, Any]] = []
    for idx, image in enumerate(images[:max_images], 1):
        if not isinstance(image, dict):
            continue
        url_full, url_small = _image_urls(image, note_url)
        if not url_full:
            continue
        description = title or _clean_text(caption[:120]) or "小红书摄影作品"
        photos.append(
            {
                "id": f"xhs-{note_id}-{idx}",
                "url_regular": url_full,
                "url_full": url_full,
                "url_small": url_small or url_full,
                "width": image.get("width"),
                "height": image.get("height"),
                "description": description,
                "photographer": photographer,
                "photographer_url": photographer_url,
                "source_name": "小红书",
                "source_platform": "xhs",
                "source_url": note_url,
                "xhs_url": note_url,
                "note_id": note_id,
                "note_title": title,
                "note_image_index": idx,
                "note_image_count": image_count,
                "caption": caption,
                "style_query": source_name or "xiaohongshu photography",
                "style_label": style["label"],
                "style_color": style.get("color", DEFAULT_STYLE["color"]),
                "style_icon": style.get("icon", DEFAULT_STYLE["icon"]),
                "exif": {},
            }
        )

    return photos


def cache_photo_assets(
    photos: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    asset_prefix: str = "assets/xhs",
    cookie: str = "",
) -> list[dict[str, Any]]:
    """Download Xiaohongshu CDN images into the static site output directory.

    The public CDN URLs exposed by Xiaohongshu frequently fail as hotlinks on
    GitHub Pages. Keep the original `url_*` values for attribution/analysis and
    add `local_url_*` values for rendering stable static pages.
    """
    output_root = Path(output_dir)
    asset_root = output_root / asset_prefix
    session = _make_session(cookie)
    session.headers.update(IMAGE_HEADERS)
    downloaded: dict[str, str] = {}

    for photo in photos:
        if photo.get("source_platform") != "xhs":
            continue

        note_id = _safe_asset_name(photo.get("note_id"), "note")
        photo_id = _safe_asset_name(photo.get("id"), hashlib.sha1(str(photo).encode()).hexdigest()[:12])
        photo_dir = asset_root / note_id

        for source_key, local_key, suffix in (
            ("url_small", "local_url_small", "small"),
            ("url_regular", "local_url_regular", "regular"),
            ("url_full", "local_url_full", "full"),
        ):
            url = str(photo.get(source_key) or "")
            if not _is_http_url(url):
                continue
            if url in downloaded:
                photo[local_key] = downloaded[url]
                continue

            stem = photo_dir / f"{photo_id}-{suffix}"
            existing = _existing_asset(stem)
            if existing:
                rel_path = existing.relative_to(output_root).as_posix()
                photo[local_key] = rel_path
                downloaded[url] = rel_path
                continue

            try:
                resp = session.get(url, timeout=45)
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.lower().startswith("image/"):
                    logger.warning("Xiaohongshu image response is not an image: %s (%s)", url, content_type)
                    continue

                path = stem.with_suffix(_image_extension(resp, url))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)
                rel_path = path.relative_to(output_root).as_posix()
                photo[local_key] = rel_path
                downloaded[url] = rel_path
                logger.info("Xiaohongshu image cached: %s", rel_path)
            except requests.RequestException as exc:
                logger.warning("Xiaohongshu image cache failed %s: %s", url, exc)

    return photos


def _meta_to_photos(
    meta: dict[str, list[str]],
    page_url: str,
    source_name: str,
    style: dict[str, str],
    max_images: int,
) -> list[dict[str, Any]]:
    title = _clean_text((meta.get("og:title") or [""])[0]).removesuffix(" - 小红书")
    caption = _clean_text((meta.get("description") or meta.get("og:description") or [""])[0], keep_lines=True)
    image_urls = [_normalise_url(url, page_url) for url in meta.get("og:image", [])]
    image_urls = [url for url in image_urls if _is_http_url(url)]

    note_id_match = re.search(r"/(?:discovery/item|explore)/([0-9a-fA-F]{24})", page_url)
    note_id = note_id_match.group(1) if note_id_match else hashlib.sha1(page_url.encode()).hexdigest()[:24]
    photographer = source_name or "小红书博主"

    photos = []
    for idx, url in enumerate(image_urls[:max_images], 1):
        photos.append(
            {
                "id": f"xhs-{note_id}-{idx}",
                "url_regular": url,
                "url_full": url,
                "url_small": url,
                "width": None,
                "height": None,
                "description": title or _clean_text(caption[:120]) or "小红书摄影作品",
                "photographer": photographer,
                "photographer_url": "",
                "source_name": "小红书",
                "source_platform": "xhs",
                "source_url": page_url,
                "xhs_url": page_url,
                "note_id": note_id,
                "note_title": title,
                "note_image_index": idx,
                "note_image_count": len(image_urls),
                "caption": caption,
                "style_query": source_name or "xiaohongshu photography",
                "style_label": style["label"],
                "style_color": style.get("color", DEFAULT_STYLE["color"]),
                "style_icon": style.get("icon", DEFAULT_STYLE["icon"]),
                "exif": {},
            }
        )
    return photos


def fetch_source(
    url: str,
    *,
    source_name: str = "",
    style_label: str = DEFAULT_STYLE["label"],
    style_color: str = DEFAULT_STYLE["color"],
    style_icon: str = DEFAULT_STYLE["icon"],
    max_notes: int = 3,
    max_images_per_note: int = 6,
    cookie: str = "",
) -> list[dict[str, Any]]:
    """Fetch photos from one public Xiaohongshu share/profile page."""
    session = _make_session(cookie)
    style = {"label": style_label, "color": style_color, "icon": style_icon}

    page_html, final_url = _fetch_html(session, url)
    meta, links = _parse_meta(page_html)
    state = _parse_initial_state(page_html)
    notes = _extract_note_dicts(state)

    if notes:
        logger.info("从公开页面状态中解析到 %d 条笔记", len(notes))
        photos: list[dict[str, Any]] = []
        for note in notes[:max_notes]:
            photos.extend(_note_to_photos(note, final_url, source_name, style, max_images_per_note))
        return photos

    note_links = _extract_note_links(page_html, links, final_url)
    if note_links:
        logger.info("发现 %d 个公开笔记链接，开始抓取前 %d 个", len(note_links), max_notes)
        photos = []
        seen_ids: set[str] = set()
        for note_url in note_links[:max_notes]:
            try:
                note_html, resolved_note_url = _fetch_html(session, note_url)
            except requests.RequestException as exc:
                logger.warning("笔记抓取失败 %s: %s", note_url, exc)
                continue
            note_meta, _ = _parse_meta(note_html)
            note_state = _parse_initial_state(note_html)
            note_dicts = _extract_note_dicts(note_state)
            if note_dicts:
                for note in note_dicts[:1]:
                    for photo in _note_to_photos(note, resolved_note_url, source_name, style, max_images_per_note):
                        if photo["id"] not in seen_ids:
                            photos.append(photo)
                            seen_ids.add(photo["id"])
            else:
                for photo in _meta_to_photos(note_meta, resolved_note_url, source_name, style, max_images_per_note):
                    if photo["id"] not in seen_ids:
                        photos.append(photo)
                        seen_ids.add(photo["id"])
        return photos

    logger.info("未发现笔记状态，改用 OpenGraph 图片 fallback")
    return _meta_to_photos(meta, final_url, source_name, style, max_images_per_note)


def fetch_sources(
    sources: list[dict[str, Any]],
    *,
    default_style_label: str = DEFAULT_STYLE["label"],
    default_style_color: str = DEFAULT_STYLE["color"],
    default_style_icon: str = DEFAULT_STYLE["icon"],
    default_max_notes: int = 3,
    default_max_images_per_note: int = 6,
    cookie: str = "",
) -> list[dict[str, Any]]:
    """Fetch and de-duplicate photos from multiple Xiaohongshu sources."""
    photos: list[dict[str, Any]] = []
    seen: set[str] = set()

    for source in sources:
        source_url = source.get("url")
        if not source_url:
            continue
        try:
            fetched = fetch_source(
                str(source_url),
                source_name=str(source.get("name") or ""),
                style_label=str(source.get("style_label") or source.get("label") or default_style_label),
                style_color=str(source.get("style_color") or source.get("color") or default_style_color),
                style_icon=str(source.get("style_icon") or source.get("icon") or default_style_icon),
                max_notes=int(source.get("max_notes") or default_max_notes),
                max_images_per_note=int(source.get("max_images_per_note") or default_max_images_per_note),
                cookie=str(source.get("cookie") or cookie or ""),
            )
        except requests.RequestException as exc:
            logger.warning("小红书来源抓取失败，已跳过 %s: %s", source_url, exc)
            continue
        for photo in fetched:
            key = photo.get("id") or photo.get("url_full")
            if key and key not in seen:
                photos.append(photo)
                seen.add(key)

    logger.info("小红书来源合计获取 %d 张照片", len(photos))
    return photos
