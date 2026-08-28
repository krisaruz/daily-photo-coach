"""一次性脚本：扫描 output/*/photos.json，把因 GBK 误解码产生的 mojibake label 还原成正确中文。

背景：daily.yml / xhs-daily.yml 早期版本在命令行直接传 `--style "小红书｜人像写真"`，
某些 GitHub Actions 链路把 UTF-8 字节按 GBK 解码后传给 Python，写入 photos.json
时就变成了 mojibake（例如 "灏忕孩涔︼綔浜哄儚鍐欑湡"）。本脚本遍历历史归档，
检测所有 label / style_label 字段的 mojibake 并就地修复，然后重新渲染所有公开页面。

用法：
    PYTHONPATH=src python scripts/fix_xhs_mojibake.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# 让脚本可以在仓库根目录直接运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from renderer import rebuild_public_pages, render_xhs_site  # noqa: E402
from xhs_daily import _fix_mojibake  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fix_xhs_mojibake")


def _fix_value(value):
    if isinstance(value, str):
        return _fix_mojibake(value)
    return value


def _fix_photos_json(path: Path) -> bool:
    """就地修复一个 photos.json，返回是否有改动。"""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    changed = False

    # 顶层 key 是风格 label
    if isinstance(data, dict):
        new_data = {}
        for key, photos in data.items():
            fixed_key = _fix_value(key)
            if fixed_key != key:
                logger.info("  %s: label %r -> %r", path.parent.name, key, fixed_key)
                changed = True
            if isinstance(photos, list):
                for photo in photos:
                    if not isinstance(photo, dict):
                        continue
                    for field in ("style_label", "source_name", "note_title", "caption", "description"):
                        original = photo.get(field)
                        fixed = _fix_value(original)
                        if fixed != original:
                            logger.info(
                                "  %s: photo %s.%s %r -> %r",
                                path.parent.name,
                                photo.get("id", "?"),
                                field,
                                original,
                                fixed,
                            )
                            photo[field] = fixed
                            changed = True
            new_data[fixed_key] = photos
        data = new_data

    if changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return changed


def main() -> None:
    output_dir = PROJECT_ROOT / "output"
    if not output_dir.exists():
        logger.error("output 目录不存在: %s", output_dir)
        sys.exit(1)

    fixed_count = 0
    scanned = 0
    for json_file in sorted(output_dir.glob("*/photos.json")):
        scanned += 1
        try:
            if _fix_photos_json(json_file):
                fixed_count += 1
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("跳过损坏归档 %s: %s", json_file, exc)

    logger.info("扫描 %d 个 photos.json，修复 %d 个", scanned, fixed_count)

    # 重新渲染所有公开页面
    logger.info("重新渲染所有公开页面...")
    rebuild_public_pages(str(output_dir))
    render_xhs_site(str(output_dir))
    logger.info("完成")


if __name__ == "__main__":
    main()
