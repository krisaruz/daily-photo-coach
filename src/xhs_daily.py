"""Daily Xiaohongshu picker and backfill runner.

The public web side of Xiaohongshu often exposes one share note at a time
without a searchable public feed. This runner therefore works from a configured
pool of public note/share URLs and rotates through the parsed note images by
date. Add more source URLs to `xhs.sources` for a broader daily pool.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
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

DEFAULT_STYLE = {
    "label": "小红书｜人像写真",
    "color": "#be185d",
    "icon": "📕",
}

DEFAULT_XHS_SOURCES = [
    {
        "name": "万万学姐",
        "url": "https://www.xiaohongshu.com/explore/64c52bd6000000000c0371e2?xsec_token=ABRH0_UusgNiDq6Fh2Atan5N52K1KYsHdZANmmJOa-eTY%3D&xsec_source=pc_feed",
    },
    {
        "name": "小仙女周周",
        "url": "https://www.xiaohongshu.com/explore/64ba91e5000000000800f849?xsec_token=ABbCLHT5s3qlM3EnEPlnWhUINrLLEnUQ51TY8T0KxqD2E%3D&xsec_source=pc_feed",
    },
    {
        "name": "鯊魚喬納森",
        "url": "https://www.xiaohongshu.com/explore/64bfc48e000000000a01aeb4?xsec_token=ABSnHLvO9lnVSMKpZb-K1CpsR_tawRcS33LiHfRp3otRU%3D&xsec_source=pc_feed",
    },
    {
        "name": "Yeeton",
        "url": "https://www.xiaohongshu.com/explore/643a5d6900000000130363ba?xsec_token=ABwMlOi53Bwe0jUAImDKByPTtTgJa-beEud-VpuGweXr4%3D&xsec_source=pc_feed",
    },
    {
        "name": "奶油",
        "url": "https://www.xiaohongshu.com/explore/644128a8000000001300bf69?xsec_token=ABlP6Vup-yAeNsm5GA_-MBKQjAtqezghDlgOx26677wCY%3D&xsec_source=pc_feed",
    },
    {
        "name": "周姨",
        "url": "https://www.xiaohongshu.com/explore/6433d257000000000800e88f?xsec_token=ABX1pSMvxOobor452KawVYAqkLcWN45Lm6nKpMTh88SdM%3D&xsec_source=pc_feed",
    },
    {
        "name": "黄小人",
        "url": "https://www.xiaohongshu.com/explore/643631310000000011011932?xsec_token=AB6DeaQ6zZk4H1MBOXG_8A1JuIzflslThznKSGDFMJ2rM%3D&xsec_source=pc_feed",
    },
]

for source in DEFAULT_XHS_SOURCES:
    source.setdefault("style_label", DEFAULT_STYLE["label"])
    source.setdefault("style_color", DEFAULT_STYLE["color"])
    source.setdefault("style_icon", DEFAULT_STYLE["icon"])
    source.setdefault("max_notes", 1)


DEFAULT_EXCLUDED_NOTE_IDS = {
    "64c24c2e000000001701b934",  # 文案更偏情绪随拍，不适合作为写真教学样本
    "64b60f55000000001c00fc0c",  # 旅行攻略拼图，教学信噪比低
    "64b3f0c4000000003500a86b",  # 海岛旅行信息多于人像拍法
    "64c25844000000001201f682",  # 部分图片会被模型安全系统拒绝，不适合作为默认多图样本
}


def _xhs_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "model": None,
        "style_label": DEFAULT_STYLE["label"],
        "style_color": DEFAULT_STYLE["color"],
        "style_icon": DEFAULT_STYLE["icon"],
        "max_notes_per_source": 1,
        "max_images_per_note": 18,
        "cookie": "",
        "exclude_note_ids": sorted(DEFAULT_EXCLUDED_NOTE_IDS),
        "quality_blocklist": ["老娘", "黑不黑", "PUA", "美甲"],
        "sources": copy.deepcopy(DEFAULT_XHS_SOURCES),
    }
    return {**defaults, **(config.get("xhs") or {})}


def _sources_from_env() -> list[dict[str, Any]]:
    raw = os.environ.get("XHS_SEED_URLS", "").strip()
    if not raw:
        return []
    sources = []
    for idx, url in enumerate(raw.replace("\n", ",").split(","), 1):
        url = url.strip()
        if url:
            sources.append({"name": f"小红书来源 {idx}", "url": url})
    return sources


def _merge_sources(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*primary, *fallback]:
        url = str(source.get("url") or "")
        if not url or url in seen:
            continue
        merged.append(source)
        seen.add(url)
    return merged


def _build_sources(xhs_config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.url:
        return [{"name": args.source_name or "小红书来源", "url": args.url}]
    env_sources = _sources_from_env()
    sources = xhs_config.get("sources") or []
    if env_sources:
        fallback = sources if isinstance(sources, list) and sources else copy.deepcopy(DEFAULT_XHS_SOURCES)
        return _merge_sources(env_sources, fallback)
    if isinstance(sources, list) and sources:
        return sources
    return copy.deepcopy(DEFAULT_XHS_SOURCES)


def _llm_for_xhs(config: dict[str, Any], xhs_config: dict[str, Any], model_override: str | None) -> dict[str, Any]:
    llm_config = copy.deepcopy(config.get("llm") or {})
    llm_config["model"] = model_override or xhs_config.get("model") or llm_config.get("model") or "gpt-5.5"
    if not llm_config.get("url"):
        llm_config["url"] = "https://api.openai.com/v1/chat/completions"
    llm_config.setdefault("headers", {})
    llm_config.setdefault("timeout", 300)
    llm_config.setdefault("max_retries", 3)
    return llm_config


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
                "color": sample.get("style_color", DEFAULT_STYLE["color"]),
                "icon": sample.get("style_icon", DEFAULT_STYLE["icon"]),
            }
        )
        labels.add(label)
    return styles


def _dedupe(photos: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _group_note_photos(photos: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for photo in photos:
        groups[str(photo.get("note_id") or photo.get("id"))].append(photo)
    return list(groups.values())


def _select_for_date(
    photos: list[dict[str, Any]],
    target_date: str,
    *,
    mode: str,
    count: int,
) -> list[dict[str, Any]]:
    if not photos:
        return []
    day_ordinal = date.fromisoformat(target_date).toordinal()

    if mode == "note":
        note_groups = _group_note_photos(photos)
        start = day_ordinal % len(note_groups)
        selected_groups = [
            note_groups[(start + offset) % len(note_groups)]
            for offset in range(min(count, len(note_groups)))
        ]
        return [copy.deepcopy(photo) for group in selected_groups for photo in group]

    ordered = _dedupe(photos)
    start = day_ordinal % len(ordered)
    selected = [ordered[(start + offset) % len(ordered)] for offset in range(min(count, len(ordered)))]
    return [copy.deepcopy(photo) for photo in selected]


def _group_by_style(photos: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for photo in photos:
        grouped[photo.get("style_label") or DEFAULT_STYLE["label"]].append(photo)
    return dict(grouped)


def _is_reasonable_note(group: list[dict[str, Any]], xhs_config: dict[str, Any]) -> bool:
    if not group:
        return False
    sample = group[0]
    note_id = str(sample.get("note_id") or "")
    if note_id in set(str(item) for item in xhs_config.get("exclude_note_ids", [])):
        return False

    title = str(sample.get("note_title") or sample.get("description") or "")
    caption = str(sample.get("caption") or "")
    text = f"{title}\n{caption}"
    if any(str(term) and str(term) in text for term in xhs_config.get("quality_blocklist", [])):
        return False

    photo_terms = ("拍照", "写真", "摄影", "出片", "机位", "构图", "调色", "光线", "拍摄")
    if "攻略" in title and not any(term in text for term in photo_terms):
        return False
    return True


def _filter_reasonable_notes(photos: list[dict[str, Any]], xhs_config: dict[str, Any]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for group in _group_note_photos(photos):
        if _is_reasonable_note(group, xhs_config):
            kept.extend(group)
        else:
            sample = group[0] if group else {}
            dropped.append(f"{sample.get('note_id')}:{sample.get('note_title') or sample.get('description')}")
    if dropped:
        logger.info("已过滤 %d 条不适合写真教学的小红书笔记: %s", len(dropped), "；".join(dropped))
    return kept


def _date_range(end_date: str, backfill_days: int) -> list[str]:
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=backfill_days - 1)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(backfill_days)]


def _load_archive(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _without_previous_daily_xhs(grouped_photos: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for label, photos in grouped_photos.items():
        kept = [photo for photo in photos if photo.get("daily_source") != "xhs_daily"]
        if kept:
            cleaned[label] = kept
    return cleaned


def _has_good_analysis(photo: dict[str, Any]) -> bool:
    analysis = photo.get("analysis") or ""
    return bool(analysis.strip()) and "分析失败" not in analysis


def _load_existing_analysis_cache(output_dir: str) -> dict[str, str]:
    cache: dict[str, str] = {}
    output_path = Path(output_dir)
    if not output_path.exists():
        return cache
    for json_file in output_path.glob("????-??-??/photos.json"):
        try:
            grouped_photos = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(grouped_photos, dict):
            continue
        for photos in grouped_photos.values():
            if not isinstance(photos, list):
                continue
            for photo in photos:
                if not isinstance(photo, dict) or not photo.get("id") or not _has_good_analysis(photo):
                    continue
                cache[str(photo["id"])] = str(photo["analysis"])
    return cache


def run_for_date(
    config: dict[str, Any],
    xhs_pool: list[dict[str, Any]],
    target_date: str,
    args: argparse.Namespace,
    analysis_cache: dict[str, str] | None = None,
) -> Path:
    xhs_config = _xhs_config(config)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    archive_path = Path(output_dir) / target_date / "photos.json"
    style_label = args.style or xhs_config["style_label"]
    grouped_photos = _load_archive(archive_path)
    existing_by_id = {
        photo.get("id"): photo
        for photos in grouped_photos.values()
        for photo in photos
        if isinstance(photo, dict) and photo.get("id")
    }
    if not args.append:
        grouped_photos = _without_previous_daily_xhs(grouped_photos)

    selected = _select_for_date(
        xhs_pool,
        target_date,
        mode=args.mode,
        count=args.count,
    )
    if not selected:
        logger.error("没有可用的小红书公开照片")
        sys.exit(1)

    for photo in selected:
        photo["style_label"] = style_label
        photo["style_color"] = args.style_color or xhs_config["style_color"]
        photo["style_icon"] = args.style_icon or xhs_config["style_icon"]
        photo["daily_source"] = "xhs_daily"
        photo["picked_for_date"] = target_date
        existing = existing_by_id.get(photo.get("id"))
        cached_analysis = ""
        if existing and _has_good_analysis(existing):
            cached_analysis = str(existing["analysis"])
        elif analysis_cache:
            cached_analysis = analysis_cache.get(str(photo.get("id"))) or ""
        if cached_analysis and not args.force_analysis:
            photo["analysis"] = cached_analysis

    llm_config = _llm_for_xhs(config, xhs_config, args.model)
    if args.skip_analysis:
        logger.info("[%s] 跳过小红书分析", target_date)
    else:
        if not llm_config.get("headers"):
            logger.error("LLM headers 未配置，无法分析小红书内容")
            sys.exit(1)
        for idx, photo in enumerate(selected, 1):
            if _has_good_analysis(photo) and not args.force_analysis:
                continue
            logger.info("[%s] 小红书分析 %d/%d: %s", target_date, idx, len(selected), photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)
            if analysis_cache is not None and _has_good_analysis(photo):
                analysis_cache[str(photo["id"])] = str(photo["analysis"])

    new_groups = _group_by_style(selected)
    for label, photos in new_groups.items():
        if args.append and label in grouped_photos:
            grouped_photos[label] = _dedupe([*grouped_photos[label], *photos])
        else:
            grouped_photos[label] = photos

    styles = _styles_for_render(config, grouped_photos)
    renderer.save_archive(grouped_photos, target_date, output_dir)
    web_path = renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    logger.info("[%s] 小红书栏目已写入: %s", target_date, web_path)
    return web_path


def fetch_pool(config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    xhs_config = _xhs_config(config)
    sources = _build_sources(xhs_config, args)
    logger.info("读取 %d 个小红书公开来源", len(sources))
    pool = xhs_fetcher.fetch_sources(
        sources,
        default_style_label=args.style or xhs_config["style_label"],
        default_style_color=args.style_color or xhs_config["style_color"],
        default_style_icon=args.style_icon or xhs_config["style_icon"],
        default_max_notes=args.max_notes or int(xhs_config["max_notes_per_source"]),
        default_max_images_per_note=args.max_images_per_note or int(xhs_config["max_images_per_note"]),
        cookie=args.cookie or xhs_config.get("cookie", ""),
    )
    pool = _dedupe(pool)
    pool = _filter_reasonable_notes(pool, xhs_config)
    output_dir = PROJECT_ROOT / config["output"]["dir"]
    xhs_fetcher.cache_photo_assets(
        pool,
        output_dir,
        cookie=args.cookie or xhs_config.get("cookie", ""),
    )
    if not pool:
        logger.error("没有解析到小红书公开照片")
        sys.exit(1)
    logger.info("小红书候选池: %d 张图片，%d 条笔记", len(pool), len(_group_note_photos(pool)))
    return pool


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Photo Coach -- 每日小红书精选")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--date", type=str, default=None, help="结束日期/目标日期 (YYYY-MM-DD)")
    parser.add_argument("--backfill-days", type=int, default=1, help="从目标日期往前补多少天")
    parser.add_argument("--url", type=str, default=None, help="临时指定一个小红书公开链接")
    parser.add_argument("--source-name", type=str, default="", help="临时来源名")
    parser.add_argument("--style", type=str, default=None, help="栏目名称")
    parser.add_argument("--style-color", type=str, default=None, help="栏目颜色")
    parser.add_argument("--style-icon", type=str, default=None, help="栏目图标")
    parser.add_argument("--mode", choices=["photo", "note"], default="photo", help="按图片还是按整条笔记轮换")
    parser.add_argument("--count", type=int, default=1, help="note 模式下表示每天选几条小红书帖子")
    parser.add_argument("--max-notes", type=int, default=None, help="每个来源最多解析多少条笔记")
    parser.add_argument("--max-images-per-note", type=int, default=None, help="每条笔记最多解析多少张图")
    parser.add_argument("--model", type=str, default=None, help="分析模型")
    parser.add_argument("--cookie", type=str, default="", help="可选 Cookie；仅用于你有权访问的公开页面")
    parser.add_argument("--append", action="store_true", help="追加到小红书栏目，而不是替换")
    parser.add_argument("--skip-analysis", action="store_true", default=True, help="跳过分析")
    parser.add_argument("--run-analysis", action="store_true", help="运行分析（默认关闭）")
    parser.add_argument("--force-analysis", action="store_true", help="强制重新分析")
    args = parser.parse_args()

    if args.run_analysis:
        args.skip_analysis = False

    config = load_config(Path(args.config))
    target_date = args.date or datetime.now().date().isoformat()
    if args.backfill_days < 1:
        parser.error("--backfill-days must be >= 1")

    pool = fetch_pool(config, args)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    analysis_cache = _load_existing_analysis_cache(output_dir)
    for day in _date_range(target_date, args.backfill_days):
        run_for_date(config, pool, day, args, analysis_cache)
    renderer.update_index(output_dir)
    logger.info("每日小红书流程完成：%d 天", args.backfill_days)


if __name__ == "__main__":
    main()
