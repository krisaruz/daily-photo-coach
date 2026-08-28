"""Render Daily Photo Coach outputs into HTML, Markdown, and JSON archives."""

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

import xhs_fetcher

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
LOCAL_ASSET_KEYS = ("local_url_small", "local_url_regular", "local_url_full")
XHS_PUBLIC_NOTICE = "原图在小红书。本站只保留学习笔记和原帖链接，不转载、不托管照片。"
DEFAULT_SITE_URL = "https://krisaruz.github.io/daily-photo-coach"


def _site_url() -> str:
    """Public base URL of the deployed site, without trailing slash."""
    value = (os.environ.get("SITE_URL") or DEFAULT_SITE_URL).strip()
    return value.rstrip("/")


def _abs_url(path: str) -> str:
    """Join a relative path with the site URL to produce an absolute URL."""
    if not path:
        return _site_url()
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return _site_url() + path


def _markdown_to_html(md_text: str) -> str:
    """Convert lightweight Markdown into HTML without extra dependencies."""
    lines = md_text.split("\n")
    html_parts = []
    in_list = False
    list_type = None

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
                list_type = None
            html_parts.append("")
            continue

        h_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if h_match:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            level = len(h_match.group(1))
            html_parts.append(f"<h{level}>{_inline_format(h_match.group(2))}</h{level}>")
            continue

        ul_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if ul_match:
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ul>")
                in_list = True
                list_type = "ul"
            html_parts.append(f"<li>{_inline_format(ul_match.group(1))}</li>")
            continue

        ol_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if ol_match:
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ol>")
                in_list = True
                list_type = "ol"
            html_parts.append(f"<li>{_inline_format(ol_match.group(1))}</li>")
            continue

        if in_list:
            html_parts.append(f"</{list_type}>")
            in_list = False
            list_type = None
        html_parts.append(f"<p>{_inline_format(stripped)}</p>")

    if in_list:
        html_parts.append(f"</{list_type}>")

    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    """Apply inline Markdown formatting."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _is_xhs_entry(photo: dict[str, Any] | None) -> bool:
    if not isinstance(photo, dict):
        return False
    return photo.get("source_platform") == "xhs" or photo.get("source_name") == "小红书"


def _strip_local_asset_fields(photo: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(photo)
    for key in LOCAL_ASSET_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _strip_grouped_local_assets(grouped_photos: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for label, photos in grouped_photos.items():
        if not isinstance(photos, list):
            cleaned[label] = photos
            continue
        cleaned[label] = [
            _strip_local_asset_fields(photo) if isinstance(photo, dict) else photo
            for photo in photos
        ]
    return cleaned


def _styles_from_grouped(grouped_photos: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    styles: list[dict[str, str]] = []
    for label, photos in grouped_photos.items():
        if not photos or not isinstance(photos, list):
            continue
        sample = next((item for item in photos if isinstance(item, dict)), {})
        styles.append(
            {
                "label": label,
                "color": str(sample.get("style_color") or "#6b7280"),
                "icon": str(sample.get("style_icon") or "📷"),
            }
        )
    return styles


def _image_url(photo: dict[str, Any], size: str = "regular", base_prefix: str = "") -> str:
    """Return a renderable image URL. Xiaohongshu entries are never displayed."""
    if _is_xhs_entry(photo):
        return ""
    local_keys = {
        "small": ("local_url_small", "local_url_regular", "local_url_full"),
        "regular": ("local_url_regular", "local_url_full", "local_url_small"),
        "full": ("local_url_full", "local_url_regular", "local_url_small"),
    }
    remote_keys = {
        "small": ("url_small", "url_regular", "url_full"),
        "regular": ("url_regular", "url_full", "url_small"),
        "full": ("url_full", "url_regular", "url_small"),
    }

    for key in local_keys.get(size, local_keys["regular"]):
        value = photo.get(key)
        if value:
            return base_prefix + str(value).lstrip("/")
    for key in remote_keys.get(size, remote_keys["regular"]):
        value = photo.get(key)
        if value:
            return str(value)
    return ""


def _strip_trailing_whitespace(text: str) -> str:
    """Remove generated line-end whitespace without changing content."""
    return "\n".join(line.rstrip() for line in text.splitlines())


def _truncate(text: str, limit: int = 140) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rsplit(" ", 1)[0].strip()
    return (clipped or text[: limit - 1]).rstrip(" .,;:") + "…"


def _clean_description(text: str | None, limit: int = 120) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return "Untitled frame"
    return _truncate(cleaned, limit)


def _extract_excerpt(md_text: str, limit: int = 140) -> str:
    fallback = []

    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        line = _clean_text(line)
        if not line:
            continue
        fallback.append(line)
        if raw_line.lstrip().startswith(("#", "-", "*", ">")) or re.match(r"^\d+\.", raw_line.lstrip()):
            continue
        return _truncate(line, limit)

    if fallback:
        return _truncate(" ".join(fallback), limit)
    return "从优秀作品里拆解光线、构图与拍摄决策。"


def _iter_photos(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        photos = []
        for group in data.values():
            if isinstance(group, list):
                photos.extend(photo for photo in group if isinstance(photo, dict))
        return photos
    if isinstance(data, list):
        return [photo for photo in data if isinstance(photo, dict)]
    return []


def _pick_preview_images(data: Any, limit: int = 3) -> list[str]:
    previews: list[str] = []
    seen: set[str] = set()

    if isinstance(data, dict):
        for group in data.values():
            if not isinstance(group, list):
                continue
            for photo in group[:1]:
                if _is_xhs_entry(photo):
                    continue
                url = _image_url(photo, "small")
                if url and url not in seen:
                    previews.append(url)
                    seen.add(url)
                if len(previews) >= limit:
                    return previews

    for photo in _iter_photos(data):
        if _is_xhs_entry(photo):
            continue
        url = _image_url(photo, "small")
        if url and url not in seen:
            previews.append(url)
            seen.add(url)
        if len(previews) >= limit:
            break

    return previews


def _build_style_counts(data: Any) -> list[dict[str, Any]]:
    style_counts: list[dict[str, Any]] = []

    if isinstance(data, dict):
        for label, photos in data.items():
            photo_list = photos if isinstance(photos, list) else []
            sample = photo_list[0] if photo_list else {}
            style_counts.append(
                {
                    "label": label,
                    "count": len(photo_list),
                    "color": sample.get("style_color", "#7a6f66"),
                    "icon": sample.get("style_icon", "•"),
                }
            )
        return style_counts

    grouped: dict[str, dict[str, Any]] = {}
    for photo in _iter_photos(data):
        label = photo.get("style_label", "未分类")
        item = grouped.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "color": photo.get("style_color", "#7a6f66"),
                "icon": photo.get("style_icon", "•"),
            },
        )
        item["count"] += 1

    return list(grouped.values())


def _render_photo_item(photo: dict[str, Any], base_prefix: str) -> dict[str, Any]:
    item = {**photo}
    item["url_small"] = _image_url(photo, "small", base_prefix)
    item["url_regular"] = _image_url(photo, "regular", base_prefix)
    item["url_full"] = _image_url(photo, "full", base_prefix)
    item["analysis_html"] = _markdown_to_html(photo.get("analysis", ""))
    item["analysis_excerpt"] = _extract_excerpt(photo.get("analysis", ""))
    item["description_short"] = _clean_description(photo.get("description", ""))
    item["caption_short"] = _truncate(_clean_text(photo.get("caption", "")), 180)
    item["note_title_short"] = _clean_description(photo.get("note_title", ""), 80)
    if photo.get("note_image_index") and photo.get("note_image_count"):
        item["note_title_short"] = (
            f"{item['note_title_short']} · 组图 "
            f"{photo['note_image_index']}/{photo['note_image_count']}"
        )
    item["source_name"] = (
        photo.get("source_name")
        or ("Unsplash" if photo.get("unsplash_url") else "来源")
    )
    item["source_url"] = (
        photo.get("source_url")
        or photo.get("unsplash_url")
        or photo.get("xhs_url")
        or photo.get("url_full")
        or photo.get("url_regular")
        or ""
    )
    item["is_xhs"] = _is_xhs_entry(photo)
    item["source_unavailable"] = bool(
        item["is_xhs"] and xhs_fetcher.is_blocked_note_page(item["source_url"])
    )
    item["xhs_notice"] = XHS_PUBLIC_NOTICE if item["is_xhs"] else ""

    width = photo.get("width") or 0
    height = photo.get("height") or 0
    if width and height:
        if height > width:
            item["orientation"] = "portrait"
        elif width > height:
            item["orientation"] = "landscape"
        else:
            item["orientation"] = "square"
    else:
        item["orientation"] = "unknown"
    return item


def render_web(
    grouped_photos: dict[str, list[dict[str, Any]]],
    styles: list[dict[str, str]],
    date: str,
    output_dir: str,
) -> Path:
    """Render the daily HTML page."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"], default=True),
    )
    template = env.get_template("daily.html")

    # Filter out failed analysis photos
    def _is_analysis_failed(photo: dict) -> bool:
        analysis = photo.get("analysis", "")
        return analysis == "（分析失败，请稍后重试）"

    ordered_styles = list(styles)
    known_labels = {style.get("label") for style in ordered_styles}
    for label, photos in grouped_photos.items():
        if label in known_labels or not photos:
            continue
        sample = photos[0]
        ordered_styles.append(
            {
                "label": label,
                "color": sample.get("style_color", "#be185d"),
                "icon": sample.get("style_icon", "📕"),
            }
        )

    tabs = []
    for style in ordered_styles:
        label = style["label"]
        photos = grouped_photos.get(label, [])
        if not photos:
            continue

        # Filter out failed photos
        valid_photos = [p for p in photos if not _is_analysis_failed(p)]
        if not valid_photos:
            continue

        rendered = [_render_photo_item(photo, "../") for photo in valid_photos]

        tabs.append(
            {
                "label": label,
                "color": style.get("color", "#7a6f66"),
                "icon": style.get("icon", "•"),
                "slug": re.sub(r"[^\w]", "", label),
                "photos": rendered,
                "summary": rendered[0]["analysis_excerpt"],
                "cover_image": rendered[0].get("url_regular", ""),
            }
        )

    total = sum(len(tab["photos"]) for tab in tabs)
    hero_photo = tabs[0]["photos"][0] if tabs and tabs[0]["photos"] else None
    page_path = f"{date}/index.html"
    cover_url = ""
    if hero_photo:
        cover_url = hero_photo.get("url_regular") or hero_photo.get("url_full") or ""
    if cover_url and not cover_url.startswith(("http://", "https://")):
        cover_url = _abs_url(cover_url)
    og_title = f"每日摄影教练 · {date}"
    og_description = ""
    if tabs:
        first_tab = tabs[0]
        og_description = (
            first_tab.get("summary")
            or (first_tab["photos"][0].get("analysis_excerpt") if first_tab["photos"] else "")
            or f"{first_tab['label']} 等共 {total} 张摄影教学点评"
        )
    html = template.render(
        date=date,
        tabs=tabs,
        total_photos=total,
        total_styles=len(tabs),
        hero_photo=hero_photo,
        og_title=og_title,
        og_description=og_description,
        og_url=_abs_url(page_path),
        og_image=cover_url,
        site_url=_site_url(),
    )

    day_dir = Path(output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "index.html"
    out_path.write_text(_strip_trailing_whitespace(html), encoding="utf-8", newline="\n")
    logger.info("Web page rendered: %s", out_path)
    return out_path


def render_markdown(
    grouped_photos: dict[str, list[dict[str, Any]]],
    date: str,
    output_dir: str,
) -> Path:
    """Render the daily Markdown archive."""
    parts = [f"# 每日摄影教练 - {date}\n"]

    # Filter out failed analysis photos
    def _is_analysis_failed(photo: dict) -> bool:
        analysis = photo.get("analysis", "")
        return analysis == "（分析失败，请稍后重试）"

    photo_idx = 0
    for label, photos in grouped_photos.items():
        # Filter out failed photos
        valid_photos = [p for p in photos if not _is_analysis_failed(p)]
        if not valid_photos:
            continue

        parts.append(f"\n---\n\n# {label}\n")

        for photo in valid_photos:
            photo_idx += 1
            source_name = photo.get("source_name") or ("Unsplash" if photo.get("unsplash_url") else "来源")
            source_url = photo.get("source_url") or photo.get("unsplash_url") or photo.get("xhs_url") or ""
            parts.append(f"\n## #{photo_idx} {label}\n")
            parts.append(f"**摄影师**: [{photo['photographer']}]({photo.get('photographer_url', '')})")
            parts.append(f" | **来源**: [{source_name}]({source_url})\n")
            image_url = _image_url(photo, "regular", "../")
            if image_url:
                parts.append(f"![{photo.get('description', '')}]({image_url})\n")
            elif _is_xhs_entry(photo):
                parts.append(f"{XHS_PUBLIC_NOTICE}\n")
                if source_url:
                    parts.append(f"[在小红书查看原图]({source_url})\n")

            exif = photo.get("exif", {})
            exif_parts = []
            if exif.get("make") or exif.get("model"):
                exif_parts.append(f"Camera {exif.get('make', '')} {exif.get('model', '')}".strip())
            if exif.get("aperture"):
                exif_parts.append(f"f/{exif['aperture']}")
            if exif.get("exposure_time"):
                exif_parts.append(f"{exif['exposure_time']}s")
            if exif.get("focal_length"):
                exif_parts.append(f"{exif['focal_length']}mm")
            if exif.get("iso"):
                exif_parts.append(f"ISO {exif['iso']}")
            if exif_parts:
                parts.append(f"> EXIF: {' | '.join(exif_parts)}\n")

            analysis = photo.get("analysis", "")
            if analysis:
                parts.append(f"\n{analysis}\n")

    day_dir = Path(output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "daily.md"
    out_path.write_text(_strip_trailing_whitespace("\n".join(parts)), encoding="utf-8", newline="\n")
    logger.info("Markdown rendered: %s", out_path)
    return out_path


def save_archive(
    grouped_photos: dict[str, list[dict[str, Any]]],
    date: str,
    output_dir: str,
) -> Path:
    """Persist the structured photo archive for the day."""
    grouped_photos = _strip_grouped_local_assets(grouped_photos)
    day_dir = Path(output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "photos.json"
    out_path.write_text(
        json.dumps(grouped_photos, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    logger.info("JSON archive saved: %s", out_path)
    return out_path


def _xhs_note_groups(photos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for photo in photos:
        if photo.get("source_platform") != "xhs" and photo.get("source_name") != "小红书":
            continue
        key = str(photo.get("note_id") or photo.get("source_url") or photo.get("id") or "")
        if not key:
            continue
        groups.setdefault(key, []).append(photo)
    return list(groups.values())


def render_xhs_site(output_dir: str) -> Path:
    """Render the standalone Xiaohongshu mini-site."""
    output_path = Path(output_dir)
    xhs_root = output_path / "xhs"
    xhs_root.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"], default=True),
    )
    index_template = env.get_template("xhs_index.html")
    detail_template = env.get_template("xhs_detail.html")
    notes: list[dict[str, Any]] = []

    def _is_analysis_failed(photo: dict) -> bool:
        analysis = photo.get("analysis", "")
        return analysis == "（分析失败，请稍后重试）"

    for day_dir in sorted(output_path.iterdir(), reverse=True):
        if not day_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        json_file = day_dir / "photos.json"
        if not json_file.exists():
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping broken archive %s: %s", json_file, exc)
            continue

        flat_photos = [photo for photo in _iter_photos(data) if not _is_analysis_failed(photo)]
        for group in _xhs_note_groups(flat_photos):
            group = [photo for photo in group if xhs_fetcher.is_usable_xhs_photo(photo)]
            if not group:
                continue
            rendered_photos = [_render_photo_item(photo, "../../") for photo in group]
            if not rendered_photos:
                continue
            cover = rendered_photos[0]
            title = _clean_description(
                cover.get("note_title") or cover.get("description") or "小红书摄影作品",
                90,
            )
            note = {
                "date": day_dir.name,
                "note_id": cover.get("note_id", ""),
                "title": title,
                "caption": _truncate(_clean_text(cover.get("caption", "")), 180),
                "photographer": cover.get("photographer", "小红书博主"),
                "source_url": cover.get("source_url") or cover.get("xhs_url") or "",
                "source_unavailable": bool(
                    xhs_fetcher.is_blocked_note_page(cover.get("source_url") or cover.get("xhs_url") or "")
                ),
                "detail_url": f"{day_dir.name}/index.html",
                "image_count": len(rendered_photos),
            }
            detail_dir = xhs_root / day_dir.name
            detail_dir.mkdir(parents=True, exist_ok=True)
            cover_image = rendered_photos[0].get("url_regular") or rendered_photos[0].get("url_full") or ""
            if cover_image and not cover_image.startswith(("http://", "https://")):
                cover_image = _abs_url(cover_image)
            og_description = note.get("caption") or note.get("title") or "小红书摄影教学点评"
            detail_html = detail_template.render(
                date=day_dir.name,
                note=note,
                photos=rendered_photos,
                xhs_notice=XHS_PUBLIC_NOTICE,
                og_title=f"{note['title']} · 小红书精选",
                og_description=og_description,
                og_url=_abs_url(f"xhs/{day_dir.name}/index.html"),
                og_image=cover_image,
                site_url=_site_url(),
            )
            (detail_dir / "index.html").write_text(
                _strip_trailing_whitespace(detail_html),
                encoding="utf-8",
                newline="\n",
            )
            notes.append(note)

    index_html = index_template.render(
        notes=notes,
        xhs_notice=XHS_PUBLIC_NOTICE,
        og_title="小红书摄影精选 · Daily Photo Coach",
        og_description="从小红书公开分享链接中精选人像写真作品，配合多模态 LLM 的摄影教学点评。",
        og_url=_abs_url("xhs/index.html"),
        og_image="",
        site_url=_site_url(),
    )
    out_path = xhs_root / "index.html"
    out_path.write_text(_strip_trailing_whitespace(index_html), encoding="utf-8", newline="\n")
    logger.info("Xiaohongshu site updated: %s (%d notes)", out_path, len(notes))
    return out_path


def update_index(output_dir: str) -> Path:
    """Update the archive index page."""
    output_path = Path(output_dir)
    days = []
    total_photos = 0
    style_totals: dict[str, dict[str, Any]] = {}
    source_totals: dict[str, int] = {}
    xhs_picks: list[dict[str, Any]] = []
    seen_xhs_notes: set[str] = set()

    # Filter out failed analysis photos
    def _is_analysis_failed(photo: dict) -> bool:
        analysis = photo.get("analysis", "")
        return analysis == "（分析失败，请稍后重试）"

    for day_dir in sorted(output_path.iterdir(), reverse=True):
        if not day_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue

        json_file = day_dir / "photos.json"
        if not json_file.exists():
            continue

        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            # Filter out failed photos
            filtered_data = {}
            for label, photos in data.items():
                if isinstance(photos, list):
                    filtered_photos = [p for p in photos if not _is_analysis_failed(p)]
                    if filtered_photos:
                        filtered_data[label] = filtered_photos

            if not filtered_data:
                continue

            flat_photos = _iter_photos(filtered_data)
            style_counts = _build_style_counts(filtered_data)
            photo_count = len(flat_photos)
            if not photo_count:
                continue

            for photo in flat_photos:
                source_name = photo.get("source_name") or ("Unsplash" if photo.get("unsplash_url") else "其他")
                source_totals[source_name] = source_totals.get(source_name, 0) + 1
                if photo.get("source_platform") == "xhs" or source_name == "小红书":
                    if not xhs_fetcher.is_usable_xhs_photo(photo):
                        continue
                    note_key = str(photo.get("note_id") or photo.get("source_url") or photo.get("id") or "")
                    if note_key and note_key in seen_xhs_notes:
                        continue
                    if note_key:
                        seen_xhs_notes.add(note_key)
                    xhs_title = _clean_description(
                        photo.get("note_title") or photo.get("description") or "小红书摄影作品",
                        64,
                    )
                    xhs_picks.append(
                        {
                            "date": day_dir.name,
                            "title": xhs_title,
                            "caption": _truncate(_clean_text(photo.get("caption", "")), 120),
                            "photographer": photo.get("photographer", "小红书博主"),
                            "source_url": photo.get("source_url") or photo.get("xhs_url") or "",
                            "source_unavailable": bool(
                                xhs_fetcher.is_blocked_note_page(
                                    photo.get("source_url") or photo.get("xhs_url") or ""
                                )
                            ),
                            "detail_url": f"xhs/{day_dir.name}/index.html",
                            "image_count": int(photo.get("note_image_count") or 1),
                        }
                    )

            for item in style_counts:
                stat = style_totals.setdefault(
                    item["label"],
                    {
                        "label": item["label"],
                        "count": 0,
                        "color": item["color"],
                        "icon": item["icon"],
                    },
                )
                stat["count"] += item["count"]

            primary_style = max(style_counts, key=lambda item: item["count"]) if style_counts else None
            lead_photo = flat_photos[0] if flat_photos else {}

            days.append(
                {
                    "date": day_dir.name,
                    "photo_count": photo_count,
                    "style_labels": [item["label"] for item in style_counts],
                    "style_counts": style_counts,
                    "primary_style": primary_style,
                    "preview_images": _pick_preview_images(filtered_data),
                    "summary": _extract_excerpt(lead_photo.get("analysis", ""), 150),
                    "lead_description": _clean_description(lead_photo.get("description", ""), 90),
                    "lead_photographer": lead_photo.get("photographer", "Unknown"),
                }
            )
            total_photos += photo_count
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Skipping broken archive %s: %s", json_file, exc)

    featured_day = days[0] if days else None
    archive_days = days[1:] if len(days) > 1 else []
    style_totals_list = sorted(style_totals.values(), key=lambda item: item["count"], reverse=True)
    source_totals_list = [
        {"label": label, "count": count}
        for label, count in sorted(source_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"], default=True),
    )
    template = env.get_template("index.html")
    home_cover = ""
    if featured_day and featured_day.get("preview_images"):
        home_cover = featured_day["preview_images"][0]
    if home_cover and not home_cover.startswith(("http://", "https://")):
        home_cover = _abs_url(home_cover)
    home_description = "每日摄影教练：多风格摄影作品抓取 + 多模态 LLM 教学点评，生成可浏览的静态日报。"
    if featured_day:
        home_description = (
            featured_day.get("summary")
            or f"{featured_day['date']} · 共 {featured_day['photo_count']} 张摄影教学点评"
        )
    html = template.render(
        days=days,
        featured_day=featured_day,
        archive_days=archive_days,
        style_totals=style_totals_list,
        source_totals=source_totals_list,
        xhs_picks=xhs_picks[:10],
        xhs_index_url="xhs/index.html",
        xhs_notice=XHS_PUBLIC_NOTICE,
        total_photos=total_photos,
        og_title="Daily Photo Coach · 摄影学习档案",
        og_description=home_description,
        og_url=_abs_url("index.html"),
        og_image=home_cover,
        site_url=_site_url(),
    )

    render_xhs_site(output_dir)

    out_path = output_path / "index.html"
    out_path.write_text(_strip_trailing_whitespace(html), encoding="utf-8", newline="\n")
    logger.info("Archive index updated: %s (%d days, %d photos)", out_path, len(days), total_photos)
    return out_path


def rebuild_public_pages(output_dir: str) -> None:
    """Re-render every daily page, markdown, and index from existing archives."""
    output_path = Path(output_dir)
    if not output_path.exists():
        raise FileNotFoundError(output_dir)

    for day_dir in sorted(output_path.iterdir()):
        if not day_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        json_file = day_dir / "photos.json"
        if not json_file.exists():
            continue
        try:
            grouped = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping broken archive %s: %s", json_file, exc)
            continue
        if not isinstance(grouped, dict):
            continue
        grouped = _strip_grouped_local_assets(grouped)
        save_archive(grouped, day_dir.name, str(output_path))
        styles = _styles_from_grouped(grouped)
        render_web(grouped, styles, day_dir.name, str(output_path))
        render_markdown(grouped, day_dir.name, str(output_path))
        logger.info("Rebuilt public pages for %s", day_dir.name)

    update_index(str(output_path))
