"""渲染模块 -- 将分析结果生成 Web HTML 和 Markdown 文件。"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"


def _markdown_to_html(md_text: str) -> str:
    """轻量级 Markdown -> HTML 转换（不依赖额外库）。"""
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
    """处理行内 Markdown 格式。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def render_web(
    grouped_photos: dict[str, list[dict[str, Any]]],
    styles: list[dict[str, str]],
    date: str,
    output_dir: str,
) -> Path:
    """生成当日 Web HTML 页面（按风格分 Tab）。"""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    template = env.get_template("daily.html")

    style_lookup = {s["label"]: s for s in styles}

    tabs = []
    for label, photos in grouped_photos.items():
        style_info = style_lookup.get(label, {})
        rendered = []
        for photo in photos:
            item = {**photo}
            item["analysis_html"] = _markdown_to_html(photo.get("analysis", ""))
            rendered.append(item)
        tabs.append({
            "label": label,
            "color": style_info.get("color", "#6b7280"),
            "icon": style_info.get("icon", ""),
            "slug": re.sub(r"[^\w]", "", label),
            "photos": rendered,
        })

    total = sum(len(t["photos"]) for t in tabs)
    html = template.render(date=date, tabs=tabs, total_photos=total)

    day_dir = Path(output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("Web 页面已生成: %s", out_path)
    return out_path


def render_markdown(
    grouped_photos: dict[str, list[dict[str, Any]]],
    date: str,
    output_dir: str,
) -> Path:
    """生成当日 Markdown 文件（按风格分节）。"""
    parts = [f"# 每日摄影教练 — {date}\n"]

    photo_idx = 0
    for label, photos in grouped_photos.items():
        parts.append(f"\n---\n\n# {label}\n")

        for photo in photos:
            photo_idx += 1
            parts.append(f"\n## #{photo_idx} {label}\n")
            parts.append(f"**摄影师**: [{photo['photographer']}]({photo.get('photographer_url', '')})")
            parts.append(f" | **来源**: [Unsplash]({photo.get('unsplash_url', '')})\n")
            parts.append(f"![{photo.get('description', '')}]({photo['url_regular']})\n")

            exif = photo.get("exif", {})
            exif_parts = []
            if exif.get("make") or exif.get("model"):
                exif_parts.append(f"📷 {exif.get('make', '')} {exif.get('model', '')}".strip())
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
    out_path.write_text("\n".join(parts), encoding="utf-8")
    logger.info("Markdown 已生成: %s", out_path)
    return out_path


def save_archive(
    grouped_photos: dict[str, list[dict[str, Any]]],
    date: str,
    output_dir: str,
) -> Path:
    """保存原始数据 + 分析结果为 JSON 归档。"""
    day_dir = Path(output_dir) / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "photos.json"
    out_path.write_text(json.dumps(grouped_photos, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("JSON 归档已保存: %s", out_path)
    return out_path


def update_index(output_dir: str) -> Path:
    """更新总索引页，扫描所有日期目录。"""
    output_path = Path(output_dir)
    days = []
    total_photos = 0

    for day_dir in sorted(output_path.iterdir(), reverse=True):
        if not day_dir.is_dir() or not re.match(r"\d{4}-\d{2}-\d{2}", day_dir.name):
            continue
        json_file = day_dir / "photos.json"
        if not json_file.exists():
            continue

        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            photo_count = sum(len(v) for v in data.values()) if isinstance(data, dict) else len(data)
            if isinstance(data, dict):
                style_labels = list(data.keys())
            else:
                style_labels = list({p.get("style_label", "") for p in data if p.get("style_label")})
            days.append({
                "date": day_dir.name,
                "photo_count": photo_count,
                "style_labels": style_labels,
            })
            total_photos += photo_count
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("跳过损坏的归档 %s: %s", json_file, e)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)
    template = env.get_template("index.html")
    html = template.render(days=days, total_photos=total_photos)

    out_path = output_path / "index.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("总索引已更新: %s (%d 天, %d 张)", out_path, len(days), total_photos)
    return out_path
