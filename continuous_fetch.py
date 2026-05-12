"""持续抓取脚本 -- 每小时抓取24张图片（两天的量），支持 Unsplash 限流。

用法:
    python continuous_fetch.py                # 持续运行
    python continuous_fetch.py --once         # 只运行一次
    python continuous_fetch.py --hours 2      # 运行2小时
"""

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import fetcher
import analyzer
import renderer
from main import load_config, PROJECT_ROOT, DEFAULT_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def find_next_dates(output_dir: str, count: int = 2) -> list[str]:
    """找出下一个需要抓取的日期（从今天开始往后找）"""
    output_path = Path(output_dir)
    today = date.today()
    dates = []

    # 从今天开始往后找没有数据的日期
    for i in range(count * 10):  # 最多找10倍的数量
        target = today + timedelta(days=i)
        archive_path = output_path / target.isoformat() / "photos.json"
        if not archive_path.exists():
            dates.append(target.isoformat())
            if len(dates) >= count:
                break

    # 如果未来都有数据了，就从过去找没有数据的日期
    if len(dates) < count:
        for i in range(1, 365):  # 往前找一年
            target = today - timedelta(days=i)
            archive_path = output_path / target.isoformat() / "photos.json"
            if not archive_path.exists():
                dates.append(target.isoformat())
                if len(dates) >= count:
                    break

    return dates


def fetch_and_analyze(config: dict, target_date: str) -> bool:
    """抓取并分析一天的照片"""
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    llm_config = config["llm"]
    access_key = config["unsplash"]["access_key"]
    photos_per_style = config["daily"]["photos_per_style"]
    styles = config["daily"]["styles"]

    logger.info("=" * 50)
    logger.info("开始处理: %s", target_date)

    # Phase 1: 抓取
    global_seen = fetcher.load_historical_ids(output_dir)
    logger.info("全局去重池: %d 张已有照片", len(global_seen))

    grouped_photos = fetcher.fetch_daily(access_key, styles, photos_per_style, global_seen=global_seen)
    actual = sum(len(v) for v in grouped_photos.values())
    logger.info("抓取完成: %d 张", actual)

    if actual == 0:
        logger.warning("没有抓取到照片，跳过")
        return False

    # Phase 2: 分析
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

    logger.info("完成: %s", target_date)
    return True


def main():
    parser = argparse.ArgumentParser(description="持续抓取脚本")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--hours", type=int, default=None, help="运行指定小时数")
    parser.add_argument("--dates-per-hour", type=int, default=2, help="每小时抓取几天的数据（默认2天）")
    args = parser.parse_args()

    config = load_config(DEFAULT_CONFIG)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])

    logger.info("=" * 60)
    logger.info("持续抓取脚本启动")
    logger.info("模式: %s", "单次" if args.once else f"运行 {args.hours} 小时" if args.hours else "持续运行")
    logger.info("每小时抓取: %d 天的数据", args.dates_per_hour)
    logger.info("=" * 60)

    start_time = time.time()
    hour_count = 0

    while True:
        # 找出需要抓取的日期
        dates = find_next_dates(output_dir, args.dates_per_hour)
        if not dates:
            logger.info("所有日期都有数据了，等待 1 小时后检查...")
            if args.once:
                break
            time.sleep(3600)
            continue

        logger.info("本轮抓取日期: %s", dates)

        # 逐天抓取
        success_count = 0
        for target_date in dates:
            try:
                if fetch_and_analyze(config, target_date):
                    success_count += 1
            except Exception as e:
                logger.error("处理 %s 失败: %s", target_date, e)

        hour_count += 1
        logger.info("第 %d 小时完成，成功抓取 %d 天", hour_count, success_count)

        # 检查是否应该停止
        if args.once:
            logger.info("单次模式，完成")
            break
        if args.hours and hour_count >= args.hours:
            logger.info("已运行 %d 小时，停止", args.hours)
            break

        # 等待到下一个小时
        elapsed = time.time() - start_time
        wait_time = max(0, 3600 - (elapsed % 3600))
        logger.info("等待 %.0f 秒后开始下一轮...", wait_time)
        time.sleep(wait_time)


if __name__ == "__main__":
    main()
