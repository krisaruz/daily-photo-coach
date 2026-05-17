"""每小时限流回填脚本 -- 从今天倒着往回补全照片和 AI 分析。

Unsplash Demo 模式: 每小时 50 次请求。
策略:
  - 补分析: 不消耗 Unsplash 额度，连续快速跑
  - 补照片: 每天 3 风格 × 8 张 ≈ 28-35 次请求，每小时跑 1 天，留余量给重试
自动 git push 部署。

用法:
    python backfill_hourly.py                  # 无限运行，自动补全所有缺失天数
    python backfill_hourly.py --max-batches 5  # 最多跑 5 批
"""

import argparse
import json
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BATCH_WAIT = 3660  # 61 分钟


def find_days_needing_work(output_dir: str, current_styles: list) -> tuple[list[str], list[str]]:
    """扫描所有天数（只到今天），返回 (需要补照片的日期, 需要补分析的日期)，按时间倒序。

    旧格式（8 类 × 3 张）会被归入 need_photos 重新抓取。
    """
    output_path = Path(output_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    current_labels = {s["label"] for s in current_styles}
    need_photos: list[str] = []
    need_analysis: list[str] = []

    for d in sorted(output_path.iterdir(), reverse=True):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name > today:
            continue
        try:
            datetime.fromisoformat(d.name)
        except ValueError:
            continue

        photos_json = d / "photos.json"
        if not photos_json.exists():
            need_photos.append(d.name)
            continue

        try:
            data = json.loads(photos_json.read_text("utf-8"))
            total = sum(len(v) for v in data.values())
            if total == 0:
                need_photos.append(d.name)
                continue
            # 旧格式（风格数 != 当前配置）需要重新抓取
            existing_labels = set(data.keys())
            if existing_labels != current_labels:
                logger.info("  %s: 旧格式 (%s), 需重新抓取", d.name, list(existing_labels))
                need_photos.append(d.name)
                continue
            analyzed = sum(
                1
                for v in data.values()
                for p in v
                if p.get("analysis") and "分析失败" not in p.get("analysis", "")
            )
            if analyzed < total:
                need_analysis.append(d.name)
        except Exception:
            need_photos.append(d.name)

    return need_photos, need_analysis


def run_one_day(
    config: dict,
    target_date: str,
    output_dir: str,
    global_seen: set[str],
    styles: list,
    analysis_only: bool = False,
) -> bool:
    """处理一天: 抓图 + 分析 + 渲染。"""
    access_key = config["unsplash"]["access_key"]
    llm_config = config["llm"]
    photos_per_style = config["daily"]["photos_per_style"]
    archive_path = Path(output_dir) / target_date / "photos.json"

    if analysis_only and archive_path.exists():
        grouped_photos = json.loads(archive_path.read_text("utf-8"))
        logger.info("  加载已有照片，补分析")
    else:
        grouped_photos = fetcher.fetch_daily(
            access_key, styles, photos_per_style, global_seen=global_seen
        )
        actual = sum(len(v) for v in grouped_photos.values())
        if actual == 0:
            logger.warning("  %s: 抓取 0 张，跳过", target_date)
            return False
        logger.info("  抓取 %d 张照片", actual)

    # 只分析没有 analysis 的照片
    total = sum(len(v) for v in grouped_photos.values())
    cnt = 0
    analyzed_now = 0
    for label, photos in grouped_photos.items():
        for photo in photos:
            cnt += 1
            if photo.get("analysis") and "分析失败" not in photo.get("analysis", ""):
                continue
            logger.info("  [%d/%d] [%s] 分析: %s", cnt, total, label, photo["id"])
            photo["analysis"] = analyzer.analyze_photo(photo, llm_config)
            analyzed_now += 1

    if analyzed_now > 0:
        logger.info("  新增 %d 条分析", analyzed_now)

    renderer.save_archive(grouped_photos, target_date, output_dir)
    renderer.render_web(grouped_photos, styles, target_date, output_dir)
    renderer.render_markdown(grouped_photos, target_date, output_dir)
    renderer.update_index(output_dir)
    return True


def git_push():
    """提交并推送。"""
    try:
        subprocess.run(["git", "add", "output/"], cwd=str(PROJECT_ROOT), check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(PROJECT_ROOT)
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
            logger.info("Git push 完成")
        else:
            logger.info("无新变更，跳过 push")
    except Exception as e:
        logger.error("Git push 失败: %s", e)


def main():
    parser = argparse.ArgumentParser(description="每小时限流回填")
    parser.add_argument("--max-batches", type=int, default=0, help="最大批次数 (0=无限)")
    args = parser.parse_args()

    config = load_config(DEFAULT_CONFIG)
    output_dir = str(PROJECT_ROOT / config["output"]["dir"])
    styles = config["daily"]["styles"]

    need_photos, need_analysis = find_days_needing_work(output_dir, styles)
    logger.info("=" * 60)
    logger.info("回填任务启动")
    logger.info("  缺照片: %d 天 (需消耗 Unsplash 额度)", len(need_photos))
    logger.info("  缺分析: %d 天 (仅消耗 LLM，不消耗 Unsplash)", len(need_analysis))
    logger.info("=" * 60)

    if not need_photos and not need_analysis:
        logger.info("没有需要补全的天数，退出")
        return

    global_seen = fetcher.load_historical_ids(output_dir)
    batch = 0
    total_done = 0

    while need_photos or need_analysis:
        if args.max_batches and batch >= args.max_batches:
            logger.info("已达最大批次限制 (%d)，停止", args.max_batches)
            break

        batch += 1

        # 优先补分析（不消耗 Unsplash 额度，可以连续跑）
        if need_analysis:
            target_date = need_analysis.pop(0)
            task_type = "补分析"
            analysis_only = True
        elif need_photos:
            target_date = need_photos.pop(0)
            task_type = "补照片+分析"
            analysis_only = False
        else:
            break

        logger.info("")
        logger.info("=" * 60)
        logger.info("批次 %d [%s]: %s", batch, task_type, target_date)
        logger.info("  剩余: %d 天缺照片, %d 天缺分析", len(need_photos), len(need_analysis))
        logger.info("=" * 60)

        try:
            ok = run_one_day(
                config, target_date, output_dir, global_seen, styles, analysis_only
            )
            if ok:
                total_done += 1
                logger.info("  %s 完成!", target_date)
            else:
                need_photos.append(target_date)
                logger.warning("  %s 失败，稍后重试", target_date)
        except Exception as e:
            logger.error("  %s 异常: %s", target_date, e)
            if not analysis_only:
                need_photos.append(target_date)
            else:
                need_analysis.append(target_date)

        git_push()

        # 只有抓图才需要等 Unsplash 限流窗口
        if (need_photos or need_analysis) and not analysis_only:
            logger.info("等待 %d 分钟后继续下一批 (Unsplash 限流)...", BATCH_WAIT // 60)
            time.sleep(BATCH_WAIT)

    logger.info("")
    logger.info("=" * 60)
    logger.info("回填完成! 共处理 %d 天", total_done)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
