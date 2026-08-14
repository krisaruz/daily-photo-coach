"""Import Xiaohongshu public share photos into the daily archive.

Usage:
    python src/xhs_import.py --url "http://xhslink.com/o/..." --style 小红书精选
    python src/xhs_import.py --skip-analysis
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import analyzer
import renderer
import xhs_fetcher
from main import DEFAULT_CONFIG, PROJECT_ROOT, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _xhs_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "model": None,
        "style_label": "小红书精选",
        "style_color": "#be185d",
        "style_icon": "📕",
        "max_notes_per_source": 3,
        "max_images_per_note": 6,
        "sources": [],
        "cookie": "",
    }
    return {**defaults, **(config.get("xhs") or {})}


def _build_sources(args: argparse.Namespace, xhs_config: dict[str, Any]) -> list[dict[str, Any]]:
    if args.url:
        return [
            {
                "url": args.url,
                "name": args.source_name or "",
                "style_label": args.style,
                "style_color": args.style_color,
                "style_icon": args.style_icon,
                "max_notes": args.max_notes,
                "max_images_per_note": args.max_images_per_note,
            }
        ]

    sources = xhs_config.get("sources") or []
    if not isinstance(sources, list) or not sources:
        logger.error("没有可导入的小红书来源。请传 --url，或在 config.yaml 的 xhs.sources 中配置。")
        sys.exit(1)
    return sources


def _llm_for_xhs(config: dict[str, Any], xhs_config: dict[str, Any], model_override: str | None) -> dict[str, Any]:
    llm_config = copy.deepcopy(config.get("llm") or {})
    llm_config["model"] = model_override or xhs_config.get("model") or llm_config.get("model") or "gpt-5.5"
    if not llm_config.get("url"):
        llm_config["url"] = "https://api.openai.com/v1/chat/completions"
    llm_config.setdefault("headers", {})
    llm_config.setdefault("timeout", 300)
    llm_config.setdefault("max_retries", 3)
    return llm_config


def _group_by_style(photos: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for photo in photos:
        grouped[photo.get("style_label", "小红书精选")].append(photo)
    return dict(grouped)


def _dedupe_photos(photos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for photo in photos:
        key = photo.get("id") or photo.get("url_full") or photo.get("url_regular")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(photo)
    return result


def _styles_for_render(config: dict[str, Any], grouped_photos: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    styles = list((config.get("daily") or {}).get("styles") or [])
    labels = {style.get("label") for style in styles}
    for label, photos in grouped_photos.items():
        if label in labels or not photos:
            continue
        sample = photos[0]
        styles.append(
            {
                "label": label,
                "color": sample.get("style_color", "#be185d"),
                "icon": sample.get("style_icon", "📕"),
            }
        )
        labels.add(label)
    return styles


def import_xhs(
    config: dict[str, Any],
    target_date: str,
    args: argparse.Namespace,
) -> Path:
    xhs_config = _xhs_config(config)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    archive_path = Path(output_dir) / target_date / "photos.json"

    sources = _build_sources(args, xhs_config)
    logger.info("=== Phase 1: 导入小红书公开照片 ===")
    photos = xhs_fetcher.fetch_sources(
        sources,
        default_style_label=args.style or xhs_config["style_label"],
        default_style_color=args.style_color or xhs_config["style_color"],
        default_style_icon=args.style_icon or xhs_config["style_icon"],
        default_max_notes=args.max_notes or int(xhs_config["max_notes_per_source"]),
        default_max_images_per_note=args.max_images_per_note or int(xhs_config["max_images_per_note"]),
        cookie=args.cookie or xhs_config.get("cookie", ""),
    )
    photos = _dedupe_photos(photos)[: args.limit]
    photos = [photo for photo in photos if xhs_fetcher.is_usable_xhs_photo(photo)]
    if not photos:
        logger.error("没有解析到可用照片。公开页面可能已过期、需要登录，或页面结构发生变化。")
        sys.exit(1)
    logger.info("导入 %d 张小红书照片", len(photos))

    logger.info("=== Phase 2: 摄影教学分析 ===")
    llm_config = _llm_for_xhs(config, xhs_config, args.model)
    if args.skip_analysis:
        logger.info("跳过 LLM 分析（--skip-analysis）")
    else:
        if not llm_config.get("headers"):
            logger.error("LLM headers 未配置。请设置 config.yaml，或在 Actions 中配置 OPENAI_API_KEY/LLM_AUTH。")
            sys.exit(1)
        for idx, photo in enumerate(photos, 1):
            if photo.get("analysis") and not args.force_analysis:
                logger.info("[%d/%d] 已有分析，跳过: %s", idx, len(photos), photo["id"])
                continue
            logger.info("[%d/%d] [%s] 分析中: %s", idx, len(photos), llm_config["model"], photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)

    if archive_path.exists():
        grouped_photos: dict[str, list[dict[str, Any]]] = json.loads(archive_path.read_text(encoding="utf-8"))
        logger.info("已加载当天归档: %s", archive_path)
    else:
        grouped_photos = {}
        logger.info("当天无已有归档，将创建新的")

    for label, group in _group_by_style(photos).items():
        if args.append and label in grouped_photos:
            grouped_photos[label] = _dedupe_photos([*grouped_photos[label], *group])
        else:
            grouped_photos[label] = group

    logger.info("=== Phase 3: 生成输出 ===")
    styles = _styles_for_render(config, grouped_photos)
    renderer.save_archive(grouped_photos, target_date, output_dir)
    web_path = renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    renderer.update_index(output_dir)
    logger.info("小红书导入完成: %s", web_path)
    return web_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Photo Coach -- 小红书公开照片导入")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--url", type=str, default=None, help="小红书分享链接、公开笔记链接或公开主页链接")
    parser.add_argument("--source-name", type=str, default="", help="来源/博主备注名")
    parser.add_argument("--style", type=str, default=None, help="归入的栏目名称")
    parser.add_argument("--style-color", type=str, default=None, help="栏目颜色")
    parser.add_argument("--style-icon", type=str, default=None, help="栏目图标")
    parser.add_argument("--limit", type=int, default=6, help="本次最多导入多少张照片")
    parser.add_argument("--max-notes", type=int, default=3, help="主页/列表页最多抓取多少条笔记")
    parser.add_argument("--max-images-per-note", type=int, default=6, help="每条笔记最多取多少张图")
    parser.add_argument("--model", type=str, default=None, help="小红书分析使用的模型，默认读取 xhs.model")
    parser.add_argument("--cookie", type=str, default="", help="可选 Cookie；仅用于你有权访问的公开页面")
    parser.add_argument("--append", action="store_true", help="追加到同名栏目，而不是替换该栏目")
    parser.add_argument("--skip-analysis", action="store_true", help="跳过 LLM 分析，仅导入和渲染")
    parser.add_argument("--force-analysis", action="store_true", help="强制重新分析已有结果")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    target_date = args.date or date.today().isoformat()
    logger.info("小红书导入模式")
    logger.info("  日期: %s", target_date)
    import_xhs(config, target_date, args)


if __name__ == "__main__":
    main()
