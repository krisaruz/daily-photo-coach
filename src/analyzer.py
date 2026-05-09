"""LLM 多模态分析模块 -- 调用公司 AI Gateway 对照片进行摄影教学分析。"""

import json
import logging
import time
from typing import Any

import requests

from prompt import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)


def _call_llm(
    url: str,
    headers: dict[str, str],
    model: str,
    user_content: list[dict],
    timeout: int = 120,
) -> str:
    """调用 LLM API，流式读取并拼接完整回复。"""
    payload = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    req_headers = {**headers, "Content-Type": "application/json"}
    resp = requests.post(url, headers=req_headers, json=payload, stream=True, timeout=(30, timeout))

    if resp.status_code != 200:
        body = resp.text[:500]
        raise requests.RequestException(
            f"HTTP {resp.status_code}: {body}"
        )

    full_text = ""
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        raw = line[len("data:"):].strip()
        if raw == "[DONE]":
            break
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if chunk.get("code") and chunk.get("code") != "Success":
            logger.warning("LLM 返回非 Success: %s", chunk.get("code"))
            continue

        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            text = choice.get("text", "") or delta.get("content", "")
            if text:
                full_text += text

    return full_text


def analyze_photo(photo: dict, llm_config: dict[str, Any]) -> str:
    """对单张照片进行摄影教学分析，带重试机制。"""
    user_content = build_user_message(photo)
    max_retries = llm_config.get("max_retries", 3)
    timeout = llm_config.get("timeout", 120)

    url = llm_config["url"]
    model = llm_config["model"]
    headers = {k: str(v) for k, v in llm_config["headers"].items()}

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "分析照片 [%s] (尝试 %d/%d)...",
                photo.get("id", "unknown"),
                attempt,
                max_retries,
            )
            result = _call_llm(url, headers, model, user_content, timeout)
            if result.strip():
                logger.info("照片 [%s] 分析完成，%d 字", photo.get("id"), len(result))
                return result
            logger.warning("照片 [%s] 返回空结果，重试...", photo.get("id"))
        except requests.RequestException as e:
            logger.error("LLM 调用失败 (尝试 %d/%d): %s", attempt, max_retries, e)

        if attempt < max_retries:
            wait = 2 ** attempt
            logger.info("等待 %ds 后重试...", wait)
            time.sleep(wait)

    logger.error("照片 [%s] 分析失败，已耗尽重试次数", photo.get("id"))
    return "（分析失败，请稍后重试）"
