"""Recycle Daily Photo Coach -- 每日循环模式。

LLM 分析 API 不再可用后，每日内容改为从历史归档中挑选"已有分析"的图片：
不抓取新图、不调用 LLM，按日期做确定性轮换，对访客保持每天正常更新的观感。

选图规则:
    python src/recycle_daily.py                       # 当天
    python src/recycle_daily.py --date 2026-09-04     # 指定日期
    python src/recycle_daily.py --per-style 6         # 每种风格张数
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import renderer
from analysis_schedule import shanghai_now
from main import DEFAULT_CONFIG, PROJECT_ROOT, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 旧版式风格 → 现行风格。旧风格的图片并入现行池，避免 148 张已分析的人像图被浪费。
STYLE_MERGES: dict[str, str] = {
    "人像/肖像": "人像/质感",
}

# 与现行每日页版式一致的默认风格顺序（3 风格 × 8 张）。
CURRENT_STYLE_ORDER = ["风光/自然", "人像/质感", "街头/人文"]

# 目标日期之前多少天内用过的图片不再选用，避免短期重复被察觉。
RECENT_WINDOW_DAYS = 14


def _has_good_analysis(photo: dict[str, Any]) -> bool:
    analysis = str(photo.get("analysis") or "").strip()
    return bool(analysis) and "分析失败" not in analysis


def _is_xhs_photo(photo: dict[str, Any]) -> bool:
    return photo.get("source_platform") == "xhs" or photo.get("source_name") == "小红书"


def _load_day_archive(output_dir: str | Path, day: str) -> dict[str, list[dict[str, Any]]] | None:
    path = Path(output_dir) / day / "photos.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def build_pools(
    output_dir: str | Path,
    style_labels: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """扫描全部历史归档，为每种现行风格收集"有分析"的去重图片池。

    同一图片 ID 只保留分析内容最完整的一份（晚出现的天数不覆盖早的，
    但若早的记录缺分析则允许更晚的补上）。池内顺序按首次出现的日期稳定排列。
    """
    output_path = Path(output_dir)
    pools: dict[str, list[dict[str, Any]]] = {}
    seen_ids: dict[str, dict[str, Any]] = {}

    for json_file in sorted(output_path.glob("????-??-??/photos.json")):
        try:
            grouped = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(grouped, dict):
            continue
        for label, photos in grouped.items():
            if not isinstance(photos, list):
                continue
            for photo in photos:
                if not isinstance(photo, dict) or _is_xhs_photo(photo):
                    continue
                if not _has_good_analysis(photo):
                    continue
                pid = str(photo.get("id") or "")
                if not pid:
                    continue
                if pid in seen_ids:
                    continue
                target_label = STYLE_MERGES.get(label, label)
                if style_labels is not None and target_label not in style_labels:
                    continue
                entry = copy.deepcopy(photo)
                entry["style_label"] = target_label
                entry["style_color"] = _style_color(target_label, photo)
                entry["style_icon"] = _style_icon(target_label, photo)
                seen_ids[pid] = entry
                pools.setdefault(target_label, []).append(entry)

    return pools


def _style_color(label: str, photo: dict[str, Any]) -> str:
    """沿用现行风格的色值，保证页面上 Tab 颜色与历史版式一致。"""
    palette = {
        "风光/自然": "#16a34a",
        "人像/质感": "#dc2626",
        "街头/人文": "#ea580c",
    }
    return palette.get(label, str(photo.get("style_color") or "#6b7280"))


def _style_icon(label: str, photo: dict[str, Any]) -> str:
    icons = {
        "风光/自然": "🏔️",
        "人像/质感": "👤",
        "街头/人文": "🚶",
    }
    return icons.get(label, str(photo.get("style_icon") or "📷"))


def recent_used_ids(
    output_dir: str | Path,
    target_date: str,
    window_days: int = RECENT_WINDOW_DAYS,
) -> set[str]:
    """收集目标日期之前 window_days 天内（不含目标日）已被选用的非小红书图片 ID。"""
    output_path = Path(output_dir)
    target = date.fromisoformat(target_date)
    used: set[str] = set()
    for offset in range(1, window_days + 1):
        grouped = _load_day_archive(output_path, (target - timedelta(days=offset)).isoformat())
        if not grouped:
            continue
        for photos in grouped.values():
            if not isinstance(photos, list):
                continue
            for photo in photos:
                if not isinstance(photo, dict) or _is_xhs_photo(photo):
                    continue
                pid = str(photo.get("id") or "")
                if pid:
                    used.add(pid)
    return used


def _stable_shuffle(items: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    """对图片池做确定性洗牌：同一池 + 同一种子 → 同一顺序。"""
    def key(photo: dict[str, Any]) -> str:
        return hashlib.sha256(
            f"{seed}:{photo.get('id')}".encode("utf-8")
        ).hexdigest()

    return sorted(items, key=key)


def _epoch_ordinal(target_date: str) -> int:
    """目标日期距纪元基准（2026-09-04，循环模式首日）的天数。"""
    base = date(2026, 9, 4)
    return (date.fromisoformat(target_date) - base).days


def _day_cycle_blocks(pool_size: int, per_style: int) -> int:
    """池子能切成多少个互不重叠的日块。"""
    if pool_size <= 0 or per_style <= 0:
        return 0
    return max(1, pool_size // per_style)


def select_for_date(
    pools: dict[str, list[dict[str, Any]]],
    target_date: str,
    per_style: int,
    *,
    style_order: list[str] | None = None,
    used_ids: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按日期从各风格池中确定性挑选 per_style 张图片。

    采用"日期分块轮换"：每个风格池按 per_style 切成若干连续块，每天按
    (天数偏移 % 块数) 取一块。同一个轮次周期内每天的块互不重叠（结构性
    保证，不靠随机）；周期走完后从头开始下一轮。每轮开始前按日期种子对
    池做一次确定性洗牌，让每个周期的分块组合都不同，避免"每 60 天内容
    完全一样"。

    used_ids（近 RECENT_WINDOW_DAYS 天已用图）在块内做替换：块里撞上近期
    用过的图时，从该池的剩余图片中按稳定顺序补位。池子足够时当天选出的
    图不会出现在近期窗口内。
    """
    # 复制一份，避免把调用方传入的集合污染掉（函数内部会往里 add 当天选中项）
    used = set(used_ids) if used_ids is not None else set()
    order = style_order or list(pools.keys())
    day_index = _epoch_ordinal(target_date)
    selected: dict[str, list[dict[str, Any]]] = {}

    for label in order:
        pool = pools.get(label) or []
        if not pool:
            continue

        # 每个轮次周期用不同洗牌；周期内所有天共用同一顺序，保证分块不重叠。
        cycle_length = _day_cycle_blocks(len(pool), per_style)
        cycle_index = day_index // cycle_length
        shuffled = _stable_shuffle(pool, f"cycle-{cycle_index}")

        block = day_index % cycle_length
        start = block * per_style
        chunk = shuffled[start : start + per_style]
        # 池尾块不满 per_style 时从头部补齐（按 ID 去重，避免同一天重复出图）
        if len(chunk) < per_style:
            picked = {str(p.get("id")) for p in chunk}
            extra = [
                photo for photo in shuffled if str(photo.get("id")) not in picked
            ][: per_style - len(chunk)]
            chunk.extend(extra)

        picked_ids = {str(p.get("id")) for p in chunk}
        if used:
            clash = [photo for photo in chunk if str(photo.get("id")) in used]
            if clash:
                # 从池中未选、近期未用的图里按稳定顺序补位
                fallback = [
                    photo
                    for photo in shuffled
                    if str(photo.get("id")) not in picked_ids and str(photo.get("id")) not in used
                ]
                for photo in clash:
                    if not fallback:
                        break
                    replacement = fallback.pop(0)
                    chunk = [replacement if p is photo else p for p in chunk]
                    picked_ids.add(str(replacement.get("id")))

        if not chunk:
            continue
        selected[label] = [copy.deepcopy(photo) for photo in chunk]
        for photo in selected[label]:
            used.add(str(photo.get("id")))

    return selected


def recycle_run(
    config: dict[str, Any],
    target_date: str,
    per_style: int,
    *,
    style_labels: list[str] | None = None,
    style_order: list[str] | None = None,
    output_dir_override: str | None = None,
) -> Path:
    """为 target_date 生成一份循环版每日归档并渲染页面。"""
    output_dir = output_dir_override or str(PROJECT_ROOT / config["output"]["dir"])
    archive_path = Path(output_dir) / target_date / "photos.json"

    pools = build_pools(output_dir, style_labels=style_labels)
    if not pools:
        logger.error("历史归档中没有可循环的已分析图片")
        sys.exit(1)

    for label in (style_order or style_labels or CURRENT_STYLE_ORDER):
        if label not in pools:
            logger.warning("风格 %s 在历史归档中无可用图片，跳过", label)

    used = recent_used_ids(output_dir, target_date)
    logger.info("近 %d 天已用图片: %d 张，将优先避开", RECENT_WINDOW_DAYS, len(used))

    grouped_photos = select_for_date(
        pools,
        target_date,
        per_style,
        style_order=style_order,
        used_ids=used,
    )
    if not grouped_photos:
        logger.error("没有选出任何图片")
        sys.exit(1)

    total = sum(len(photos) for photos in grouped_photos.values())
    logger.info(
        "循环选图完成: %s 共 %d 张（%s）",
        target_date,
        total,
        "，".join(f"{label}×{len(photos)}" for label, photos in grouped_photos.items()),
    )

    styles = [
        {
            "label": label,
            "color": photos[0].get("style_color", "#7a6f66"),
            "icon": photos[0].get("style_icon", "📷"),
        }
        for label, photos in grouped_photos.items()
    ]

    renderer.save_archive(grouped_photos, target_date, output_dir)
    web_path = renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    logger.info("循环版日报已生成: %s", web_path)
    return web_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Photo Coach -- 每日循环模式（不抓图、不调 LLM）")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--date", type=str, default=None, help="指定日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--per-style",
        type=int,
        default=None,
        help="每种风格张数（默认读配置 daily.photos_per_style，无配置时 8）",
    )
    parser.add_argument(
        "--styles",
        nargs="+",
        default=None,
        help="只循环指定风格（默认现行三风格：风光/人像/街头）",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    per_style = args.per_style
    if per_style is None:
        # 抓取模式的 CI 默认是 3（省 API 配额）；循环模式必须对齐现行版式 3×8=24 张。
        # CI 环境变量模式（无 config.yaml）不采用该兜底值，直接用 8。
        if Path(args.config).exists():
            configured = (config.get("daily") or {}).get("photos_per_style")
            per_style = int(configured) if configured else 8
        else:
            per_style = 8

    style_labels = args.styles or CURRENT_STYLE_ORDER
    target_date = args.date or shanghai_now().date().isoformat()

    logger.info("Daily Photo Coach 循环模式启动")
    logger.info("  日期: %s", target_date)
    logger.info("  风格: %s × %d 张", "，".join(style_labels), per_style)

    recycle_run(config, target_date, per_style, style_labels=style_labels)


if __name__ == "__main__":
    main()
