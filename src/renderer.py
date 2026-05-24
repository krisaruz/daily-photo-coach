"""Render Daily Photo Coach outputs into HTML, Markdown, and JSON archives."""

import html
import json
import logging
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"


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


def _image_url(photo: dict[str, Any], size: str = "regular", base_prefix: str = "") -> str:
    """Return a renderable image URL, preferring cached static assets."""
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
                url = _image_url(photo, "small")
                if url and url not in seen:
                    previews.append(url)
                    seen.add(url)
                if len(previews) >= limit:
                    return previews

    for photo in _iter_photos(data):
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

        rendered = []
        for photo in valid_photos:
            item = {**photo}
            item["url_small"] = _image_url(photo, "small", "../")
            item["url_regular"] = _image_url(photo, "regular", "../")
            item["url_full"] = _image_url(photo, "full", "../")
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

            rendered.append(item)

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
    html = template.render(
        date=date,
        tabs=tabs,
        total_photos=total,
        total_styles=len(tabs),
        hero_photo=hero_photo,
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
            parts.append(f"![{photo.get('description', '')}]({_image_url(photo, 'regular', '../')})\n")

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
                    note_key = str(photo.get("note_id") or photo.get("source_url") or photo.get("id") or "")
                    if note_key and note_key in seen_xhs_notes:
                        continue
                    if note_key:
                        seen_xhs_notes.add(note_key)
                    xhs_title = _clean_description(
                        photo.get("note_title") or photo.get("description") or "小红书摄影作品",
                        64,
                    )
                    if photo.get("note_image_index") and photo.get("note_image_count"):
                        xhs_title = (
                            f"{xhs_title} · 组图 "
                            f"{photo['note_image_index']}/{photo['note_image_count']}"
                        )
                    xhs_picks.append(
                        {
                            "date": day_dir.name,
                            "image": _image_url(photo, "small"),
                            "title": xhs_title,
                            "caption": _truncate(_clean_text(photo.get("caption", "")), 120),
                            "photographer": photo.get("photographer", "小红书博主"),
                            "source_url": photo.get("source_url") or photo.get("xhs_url") or "",
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
    html = template.render(
        days=days,
        featured_day=featured_day,
        archive_days=archive_days,
        style_totals=style_totals_list,
        source_totals=source_totals_list,
        xhs_picks=xhs_picks[:10],
        total_photos=total_photos,
    )

    out_path = output_path / "index.html"
    out_path.write_text(_strip_trailing_whitespace(html), encoding="utf-8", newline="\n")
    logger.info("Archive index updated: %s (%d days, %d photos)", out_path, len(days), total_photos)
    return out_path
