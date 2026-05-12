"""限流友好的慢速回填脚本。

每小时严格跑 2 天（48 次 Unsplash 请求，留 2 次余量），
每完成一批自动 git push 部署。
目标：10 小时跑 20 天。

用法:
    python backfill_slow.py
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import fetcher
import analyzer
import renderer
from main import load_config, PROJECT_ROOT, DEFAULT_CONFIG

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DAYS_PER_HOUR = 2
HOUR_WAIT = 3660  # 61 minutes between batches


def find_empty_days(output_dir: str) -> list[str]:
    """找出所有空数据的日期，按时间倒序（先填最近的）。"""
    output_path = Path(output_dir)
    empty = []
    for d in sorted(output_path.iterdir(), reverse=True):
        if not d.is_dir() or not (d / "photos.json").exists():
            continue
        try:
            data = json.loads((d / "photos.json").read_text("utf-8"))
            if not any(data.values()):
                empty.append(d.name)
        except Exception:
            continue
    return empty


def run_one_day(config, target_date, output_dir, global_seen, styles):
    """跑一天的抓取+分析+渲染。"""
    access_key = config["unsplash"]["access_key"]
    llm_config = config["llm"]
    photos_per_style = config["daily"]["photos_per_style"]

    logger.info(">>> 处理: %s (去重池: %d)", target_date, len(global_seen))

    grouped_photos = fetcher.fetch_daily(access_key, styles, photos_per_style, global_seen=global_seen)
    actual = sum(len(v) for v in grouped_photos.values())
    if actual == 0:
        logger.warning(">>> %s: 0 张照片（可能限流），跳过", target_date)
        return False

    logger.info(">>> %s: 抓取 %d 张，开始 AI 分析...", target_date, actual)
    total = sum(len(v) for v in grouped_photos.values())
    cnt = 0
    for label, photos in grouped_photos.items():
        for photo in photos:
            cnt += 1
            logger.info("  [%d/%d] [%s] %s", cnt, total, label, photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)

    renderer.save_archive(grouped_photos, target_date, output_dir)
    renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    renderer.update_index(output_dir)
    logger.info(">>> %s 完成! %d 张照片", target_date, actual)
    return True


def git_push():
    """提交并推送 output/ 到 GitHub。"""
    try:
        subprocess.run(["git", "add", "output/"], cwd=str(PROJECT_ROOT), check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(
                ["git", "commit", "-m", f"backfill: auto batch at {now}"],
                cwd=str(PROJECT_ROOT), check=True,
            )
            subprocess.run(
                ["git", "push", "origin", "master"],
                cwd=str(PROJECT_ROOT), check=True,
            )
            logger.info("=== Git push 完成 ===")
        else:
            logger.info("=== 无新变更，跳过 push ===")
    except Exception as e:
        logger.error("Git push 失败: %s", e)


def main():
    config = load_config(DEFAULT_CONFIG)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    styles = config["daily"]["styles"]

    empty_days = find_empty_days(output_dir)
    logger.info("=" * 60)
    logger.info("慢速回填启动")
    logger.info("  空数据天数: %d", len(empty_days))
    logger.info("  每小时目标: %d 天", DAYS_PER_HOUR)
    logger.info("  预计需要: %d 小时", (len(empty_days) + DAYS_PER_HOUR - 1) // DAYS_PER_HOUR)
    logger.info("=" * 60)

    global_seen = fetcher.load_historical_ids(output_dir)
    total_done = 0
    batch = 0

    while empty_days:
        batch += 1
        batch_days = empty_days[:DAYS_PER_HOUR]
        empty_days = empty_days[DAYS_PER_HOUR:]

        logger.info("\n" + "=" * 60)
        logger.info("批次 %d: 处理 %s", batch, batch_days)
        logger.info("=" * 60)

        batch_success = 0
        for target_date in batch_days:
            try:
                ok = run_one_day(config, target_date, output_dir, global_seen, styles)
                if ok:
                    batch_success += 1
                    total_done += 1
                else:
                    empty_days.append(target_date)
            except Exception as e:
                logger.error("日期 %s 失败: %s", target_date, e)
                empty_days.append(target_date)

        if batch_success > 0:
            git_push()

        logger.info(
            ">>> 批次 %d 完成: %d/%d 天成功，累计 %d 天，剩余 %d 天",
            batch, batch_success, len(batch_days), total_done, len(empty_days),
        )

        if empty_days:
            logger.info(">>> 等待 %d 分钟后继续下一批...", HOUR_WAIT // 60)
            time.sleep(HOUR_WAIT)

    logger.info("\n" + "=" * 60)
    logger.info("全部回填完成! 共处理 %d 天", total_done)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
