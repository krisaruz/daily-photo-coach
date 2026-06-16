"""批量回填历史日期的照片+分析。

用法:
    python backfill.py --start 2025-09-05 --end 2026-03-04
    python backfill.py --start 2025-09-05 --end 2026-03-04 --skip-existing
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import fetcher  # noqa: E402
import analyzer  # noqa: E402
import renderer  # noqa: E402
from main import load_config, PROJECT_ROOT, DEFAULT_CONFIG  # noqa: E402

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def daterange(start: date, end: date):
    """生成从 start 到 end（含）的日期序列。"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="批量回填历史照片")
    parser.add_argument("--start", type=str, required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=str, required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已有 photos.json 的日期")
    parser.add_argument("--skip-analysis", action="store_true", help="只抓图不分析")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_days = (end - start).days + 1

    config = load_config(DEFAULT_CONFIG)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    llm_config = config["llm"]
    access_key = config["unsplash"]["access_key"]
    photos_per_style = config["daily"]["photos_per_style"]
    styles = config["daily"]["styles"]

    logger.info("=" * 60)
    logger.info("批量回填: %s → %s (%d 天)", start, end, total_days)
    logger.info("=" * 60)

    # 一次性加载所有历史 ID，在整个回填过程中持续维护
    global_seen = fetcher.load_historical_ids(output_dir)
    logger.info("全局去重池: %d 张已有照片", len(global_seen))

    done = 0
    skipped = 0
    failed = 0

    for d in daterange(start, end):
        target_date = d.isoformat()
        archive_path = Path(output_dir) / target_date / "photos.json"

        if args.skip_existing and archive_path.exists():
            logger.info("[%d/%d] 跳过已有: %s", done + skipped + 1, total_days, target_date)
            skipped += 1
            continue

        progress = done + skipped + failed + 1
        logger.info("=" * 40)
        logger.info("[%d/%d] 开始处理: %s (去重池: %d)", progress, total_days, target_date, len(global_seen))
        logger.info("=" * 40)

        try:
            # Phase 1: 抓取
            grouped_photos = fetcher.fetch_daily(access_key, styles, photos_per_style, global_seen=global_seen)
            actual = sum(len(v) for v in grouped_photos.values())
            logger.info("抓取完成: %d 张", actual)

            # Phase 2: 分析
            if not args.skip_analysis:
                total = sum(len(v) for v in grouped_photos.values())
                cnt = 0
                for label, photos in grouped_photos.items():
                    for photo in photos:
                        cnt += 1
                        logger.info("[%d/%d] [%s] 分析: %s", cnt, total, label, photo["id"])
                        photo["analysis"] = analyzer.analyze_photo(photo, llm_config)

            # Phase 3: 渲染
            renderer.save_archive(grouped_photos, target_date, output_dir)
            renderer.render_web(grouped_photos, styles, target_date, output_dir)
            renderer.render_markdown(grouped_photos, target_date, output_dir)
            renderer.update_index(output_dir)

            done += 1
        except Exception as e:
            logger.error("日期 %s 处理失败: %s", target_date, e)
            failed += 1

        time.sleep(1)

    logger.info("=" * 60)
    logger.info("回填完成！成功: %d, 跳过: %d, 失败: %d", done, skipped, failed)
    logger.info("总去重池大小: %d 张照片", len(global_seen))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
