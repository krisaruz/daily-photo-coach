"""Choose a stable random hour in the 09:00-22:00 Asia/Shanghai teaching window."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_START = 9
WINDOW_END = 22
WINDOW_HOURS = WINDOW_END - WINDOW_START + 1


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def target_hour(day: date) -> int:
    """Return a deterministic hour in [9, 22] for the given local day."""
    digest = hashlib.sha256(day.isoformat().encode("utf-8")).hexdigest()
    return WINDOW_START + (int(digest[:8], 16) % WINDOW_HOURS)


def should_run(
    now: datetime,
    *,
    force: bool = False,
    already_complete: bool = False,
) -> bool:
    """Decide whether today's analysis job should run at this moment."""
    if force:
        return True
    if already_complete:
        return False

    local = now.astimezone(SHANGHAI) if now.tzinfo else now.replace(tzinfo=SHANGHAI)
    hour = local.hour
    if hour < WINDOW_START or hour > WINDOW_END:
        return False

    target = target_hour(local.date())
    if hour == target:
        return True
    return hour > target


def day_is_complete(output_dir: str | Path, day: date) -> bool:
    """Return True when today's Unsplash photos already have usable analysis."""
    archive = Path(output_dir) / day.isoformat() / "photos.json"
    if not archive.exists():
        return False
    try:
        import json

        grouped = json.loads(archive.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(grouped, dict):
        return False

    photos: list[dict[str, Any]] = []
    for group in grouped.values():
        if isinstance(group, list):
            photos.extend(item for item in group if isinstance(item, dict))
    unsplash = [
        photo
        for photo in photos
        if photo.get("source_platform") != "xhs" and photo.get("source_name") != "小红书"
    ]
    if not unsplash:
        return False
    return all(
        str(photo.get("analysis") or "").strip()
        and "分析失败" not in str(photo.get("analysis") or "")
        for photo in unsplash
    )


def _write_github_output(should: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    Path(output_path).write_text(
        f"should_run={'true' if should else 'false'}\n",
        encoding="utf-8",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Decide whether Daily Photo Coach should run now")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    force = args.force or os.environ.get("FORCE_RUN", "").lower() in {"1", "true", "yes"}
    now = shanghai_now()
    complete = day_is_complete(args.output_dir, now.date())
    run = should_run(now, force=force, already_complete=complete)
    logger.info(
        "schedule gate: local=%s target_hour=%02d already_complete=%s force=%s should_run=%s",
        now.isoformat(timespec="minutes"),
        target_hour(now.date()),
        complete,
        force,
        run,
    )
    _write_github_output(run)
    print(f"should_run={'true' if run else 'false'}")
    sys.exit(0)


if __name__ == "__main__":
    main()
