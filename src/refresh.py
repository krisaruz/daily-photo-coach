"""单风格刷新入口 -- 仅重新抓取+分析指定风格的照片，保留其他风格不变。

用法:
    python src/refresh.py --style 人像
    python src/refresh.py --style 街头 --date 2026-05-11
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

import analyzer
import fetcher
import renderer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    import os
    from main import _config_from_env
    return _config_from_env()


def refresh_style(
    config: dict,
    style_keyword: str,
    target_date: str,
    skip_analysis: bool = False,
):
    """刷新指定风格的照片：重新抓取 + 可选分析，合并到当天归档并重新渲染。"""
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    llm_config = config["llm"]
    photos_per_style = config["daily"]["photos_per_style"]
    styles = config["daily"]["styles"]

    matched = [s for s in styles if style_keyword in s["label"]]
    if not matched:
        logger.error("没有匹配的风格: '%s'", style_keyword)
        logger.info("可用风格: %s", [s["label"] for s in styles])
        sys.exit(1)

    target_style = matched[0]
    logger.info("刷新风格: %s (query=%s)", target_style["label"], target_style["query"])

    archive_path = Path(output_dir) / target_date / "photos.json"
    if archive_path.exists():
        grouped_photos: dict[str, list[dict[str, Any]]] = json.loads(
            archive_path.read_text(encoding="utf-8")
        )
        logger.info("已加载当天归档，包含 %d 种风格", len(grouped_photos))
    else:
        grouped_photos = {}
        logger.info("当天无已有归档，将创建新的")

    source = config.get("daily", {}).get("source", "unsplash")
    if source == "flickr":
        flickr_key = config.get("flickr", {}).get("api_key", "")
        if not flickr_key or flickr_key == "YOUR_FLICKR_API_KEY":
            logger.error("Flickr API Key 未配置")
            sys.exit(1)
    else:
        access_key = config.get("unsplash", {}).get("access_key", "")
        if not access_key or access_key == "YOUR_UNSPLASH_ACCESS_KEY":
            logger.error("Unsplash Access Key 未配置")
            sys.exit(1)

    logger.info("=== 抓取新照片 ===")
    global_seen = fetcher.load_historical_ids(output_dir)
    new_photos = fetcher.fetch_photos_for_style(config, target_style, count=photos_per_style, global_seen=global_seen)
    if not new_photos:
        logger.error("抓取失败，无新照片")
        sys.exit(1)
    logger.info("抓取到 %d 张新照片", len(new_photos))

    if skip_analysis:
        logger.info("=== 跳过 LLM 分析 ===")
    else:
        logger.info("=== 分析照片 ===")
        for i, photo in enumerate(new_photos, 1):
            logger.info("[%d/%d] 分析中: %s", i, len(new_photos), photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)

    grouped_photos[target_style["label"]] = new_photos

    logger.info("=== 重新渲染 ===")
    renderer.save_archive(grouped_photos, target_date, output_dir)
    renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    renderer.update_index(output_dir)

    logger.info("刷新完成！风格 [%s] 已更新为 %d 张新照片", target_style["label"], len(new_photos))


def main():
    parser = argparse.ArgumentParser(description="Daily Photo Coach -- 单风格刷新")
    parser.add_argument("--style", type=str, required=True, help="要刷新的风格关键词（如：人像、街头）")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--skip-analysis", action="store_true", default=True, help="跳过 LLM 分析")
    parser.add_argument("--run-analysis", action="store_true", help="执行 LLM 分析（默认关闭）")
    args = parser.parse_args()

    skip_analysis = args.skip_analysis
    if args.run_analysis:
        skip_analysis = False

    config = load_config(Path(args.config))
    target_date = args.date or date.today().isoformat()

    logger.info("单风格刷新模式")
    logger.info("  风格关键词: %s", args.style)
    logger.info("  日期: %s", target_date)

    refresh_style(config, args.style, target_date, skip_analysis=skip_analysis)


if __name__ == "__main__":
    main()
