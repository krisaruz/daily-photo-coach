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

import os
import re

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


def _expand_env(obj: object) -> object:
    if isinstance(obj, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def load_config(config_path: Path) -> dict:
    """加载配置：优先读 config.yaml 并展开 ${ENV_VAR}；不存在时从环境变量构建。"""
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return _expand_env(raw)

    return _config_from_env()


def _config_from_env() -> dict:
    """从环境变量构建完整配置（用于 CI/GitHub Actions）。"""
    import os

    access_key = os.environ.get("UNSPLASH_ACCESS_KEY") or ""
    unsplash_featured = (os.environ.get("UNSPLASH_FEATURED") or "true").lower() in ("true", "1", "yes")
    flickr_api_key = os.environ.get("FLICKR_API_KEY") or ""
    daily_source = os.environ.get("DAILY_SOURCE") or "unsplash"

    llm_url = os.environ.get("LLM_URL") or "http://ai-gateway.wps.cn/api/v3/chat/completions"
    llm_model = os.environ.get("LLM_MODEL") or "azure/gpt-5.5"
    llm_auth = os.environ.get("LLM_AUTH", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")

    headers: dict[str, str] = {}
    if llm_auth:
        headers["Authorization"] = (
            llm_auth if llm_auth.lower().startswith(("bearer ", "token ")) else f"Bearer {llm_auth}"
        )
    elif openai_api_key:
        headers["Authorization"] = f"Bearer {openai_api_key}"
    gateway_uid = os.environ.get("LLM_GATEWAY_UID", "")
    gateway_product = os.environ.get("LLM_GATEWAY_PRODUCT", "")
    gateway_intention = os.environ.get("LLM_GATEWAY_INTENTION", "")
    if gateway_uid:
        headers["AI-Gateway-Uid"] = gateway_uid
    if gateway_product:
        headers["AI-Gateway-Product-Name"] = gateway_product
    if gateway_intention:
        headers["AI-Gateway-Intention-Code"] = gateway_intention

    photos_per_style = int(os.environ.get("PHOTOS_PER_STYLE", "3"))

    styles = [
        {"query": "landscape nature mountain", "topics": "6sMVjTLSkeQ,Fzo3zuOHN6w,bo8jQKTaE0Y", "label": "风光/自然", "color": "#16a34a", "icon": "🏔️"},
        {"query": ["street portrait photography", "lifestyle portrait candid", "cinematic portrait"], "topics": "towJZFskpGg,S4MKLAsBB74", "label": "人像/质感", "color": "#dc2626", "icon": "👤"},
        {"query": "street photography documentary", "topics": "xHxYTMHLgOc", "label": "街头/人文", "color": "#ea580c", "icon": "🚶"},
    ]

    logger.info("从环境变量加载配置（CI 模式）")
    return {
        "unsplash": {"access_key": access_key, "featured": unsplash_featured},
        "flickr": {"api_key": flickr_api_key},
        "llm": {
            "url": llm_url,
            "model": llm_model,
            "headers": headers,
            "timeout": int(os.environ.get("LLM_TIMEOUT", "300")),
            "max_retries": int(os.environ.get("LLM_MAX_RETRIES", "3")),
        },
        "daily": {"source": daily_source, "photos_per_style": photos_per_style, "styles": styles},
        "xhs": {
            "model": os.environ.get("XHS_LLM_MODEL", "gpt-5.5"),
            "cookie": os.environ.get("XHS_COOKIE", ""),
            "max_notes_per_source": int(os.environ.get("XHS_MAX_NOTES", "3")),
            "max_images_per_note": int(os.environ.get("XHS_MAX_IMAGES_PER_NOTE", "18")),
        },
        "output": {"dir": os.environ.get("OUTPUT_DIR", "output")},
    }


def daily_run(
    config: dict,
    target_date: str,
    skip_fetch: bool = False,
    skip_analysis: bool = False,
    force_analysis: bool = False,
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
        source = config.get("daily", {}).get("source", "unsplash")
        if source == "flickr":
            flickr_key = config.get("flickr", {}).get("api_key", "")
            if not flickr_key or flickr_key == "YOUR_FLICKR_API_KEY":
                logger.error("请先在 config.yaml 中设置 Flickr API Key！")
                sys.exit(1)
        else:
            access_key = config.get("unsplash", {}).get("access_key", "")
            if not access_key or access_key == "YOUR_UNSPLASH_ACCESS_KEY":
                logger.error(
                    "请先在 config.yaml 中设置 Unsplash Access Key！\n"
                    "  注册地址: https://unsplash.com/developers"
                )
                sys.exit(1)

        logger.info("=== Phase 1: 抓取照片 ===")
        global_seen = fetcher.load_historical_ids(output_dir)
        grouped_photos = fetcher.fetch_daily(config, styles, photos_per_style, global_seen=global_seen)
        actual = sum(len(v) for v in grouped_photos.values())
        logger.info("成功抓取 %d 张照片（%d 种风格）", actual, len(grouped_photos))

    # --- Phase 2: LLM 分析 ---
    if skip_analysis:
        logger.info("=== Phase 2: 跳过 LLM 分析（--skip-analysis）===")
    else:
        logger.info("=== Phase 2: 摄影教学分析 ===")
        total = sum(len(v) for v in grouped_photos.values())
        done = 0
        for label, photos in grouped_photos.items():
            for photo in photos:
                done += 1
                if photo.get("analysis") and skip_fetch and not force_analysis:
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
    parser.add_argument("--skip-analysis", action="store_true", help="跳过 LLM 分析（仅抓图+渲染）")
    parser.add_argument("--force-analysis", action="store_true", help="强制重新分析（忽略已有结果）")
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
        skip_analysis=args.skip_analysis,
        force_analysis=args.force_analysis,
        per_style=args.per_style,
        style_filter=args.styles,
    )


if __name__ == "__main__":
    main()
