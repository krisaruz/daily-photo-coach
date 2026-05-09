"""Daily Photo Coach -- 每日摄影教练主入口。

用法:
    python src/main.py                       # 正常运行（全部风格）
    python src/main.py --date 2026-05-09     # 指定日期
    python src/main.py --skip-fetch          # 跳过抓取，重新分析已有照片
    python src/main.py --per-style 2         # 每种风格只抓 2 张
    python src/main.py --styles 风光 人像     # 只跑指定风格
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
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def daily_run(
    config: dict,
    target_date: str,
    skip_fetch: bool = False,
    per_style: int | None = None,
    style_filter: list[str] | None = None,
):
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    llm_config = config["llm"]
    photos_per_style = per_style or config["daily"]["photos_per_style"]
    styles = config["daily"]["styles"]

    if style_filter:
        styles = [s for s in styles if any(f in s["label"] for f in style_filter)]
        if not styles:
            logger.error("没有匹配的风格: %s", style_filter)
            sys.exit(1)
        logger.info("已筛选风格: %s", [s["label"] for s in styles])

    total_expected = len(styles) * photos_per_style
    logger.info("计划: %d 种风格 x %d 张 = %d 张照片", len(styles), photos_per_style, total_expected)

    # --- Phase 1: 抓取照片 ---
    archive_path = Path(output_dir) / target_date / "photos.json"

    if skip_fetch and archive_path.exists():
        logger.info("跳过抓取，加载已有归档: %s", archive_path)
        grouped_photos: dict[str, list[dict[str, Any]]] = json.loads(
            archive_path.read_text(encoding="utf-8")
        )
    else:
        access_key = config["unsplash"]["access_key"]
        if access_key == "YOUR_UNSPLASH_ACCESS_KEY":
            logger.error(
                "请先在 config.yaml 中设置 Unsplash Access Key！\n"
                "  注册地址: https://unsplash.com/developers"
            )
            sys.exit(1)

        logger.info("=== Phase 1: 抓取照片 ===")
        grouped_photos = fetcher.fetch_daily(access_key, styles, photos_per_style)
        actual = sum(len(v) for v in grouped_photos.values())
        logger.info("成功抓取 %d 张照片（%d 种风格）", actual, len(grouped_photos))

    # --- Phase 2: LLM 分析 ---
    logger.info("=== Phase 2: 摄影教学分析 ===")
    total = sum(len(v) for v in grouped_photos.values())
    done = 0
    for label, photos in grouped_photos.items():
        for photo in photos:
            done += 1
            if photo.get("analysis") and skip_fetch:
                logger.info("[%d/%d] 已有分析，跳过: %s", done, total, photo["id"])
                continue
            logger.info("[%d/%d] [%s] 分析中: %s", done, total, label, photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)

    # --- Phase 3: 生成输出 ---
    logger.info("=== Phase 3: 生成输出 ===")
    renderer.save_archive(grouped_photos, target_date, output_dir)
    web_path = renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    renderer.update_index(output_dir)

    logger.info("=" * 50)
    logger.info("今日摄影教练已就绪！")
    logger.info("  Web 页面: %s", web_path)
    logger.info("  Markdown: %s", Path(output_dir) / target_date / "daily.md")
    logger.info("  总索引:   %s", Path(output_dir) / "index.html")


def main():
    parser = argparse.ArgumentParser(description="Daily Photo Coach -- 每日摄影教练")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--skip-fetch", action="store_true", help="跳过抓取，使用已有照片")
    parser.add_argument("--per-style", type=int, default=None, help="每种风格的照片数")
    parser.add_argument("--styles", nargs="+", default=None, help="只跑指定风格（关键词匹配）")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    target_date = args.date or date.today().isoformat()

    logger.info("Daily Photo Coach 启动")
    logger.info("  日期: %s", target_date)

    daily_run(
        config,
        target_date,
        skip_fetch=args.skip_fetch,
        per_style=args.per_style,
        style_filter=args.styles,
    )


if __name__ == "__main__":
    main()
