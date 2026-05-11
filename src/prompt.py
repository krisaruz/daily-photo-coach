"""摄影导师 Prompt 模板 -- 引导 LLM 对照片进行精要摄影点评。"""

SYSTEM_PROMPT = """你是一位资深摄影导师。对每张照片给出精炼、实用的点评。
严格按以下四段输出（Markdown 格式），总字数控制在 200-300 字：

## 直觉
1-2 句话，这张照片最打动你的点。

## 技法拆解
3-5 个要点，每条一句话。挑最值得说的（曝光/构图/光线/色彩），不必面面俱到。
如有 EXIF 数据，结合实际参数点评。

## 复刻提示
焦段、光线条件、关键操作 1-2 步，让读者能照着拍。

## 带走一句话
这张照片最值得记住的一个拍摄心得。"""


def build_user_message(photo: dict) -> list[dict]:
    """构建发送给 LLM 的 user message（图片 + 文字指令）。"""
    exif = photo.get("exif", {})
    exif_parts = []
    if exif.get("make") or exif.get("model"):
        exif_parts.append(f"相机: {exif.get('make', '')} {exif.get('model', '')}".strip())
    if exif.get("aperture"):
        exif_parts.append(f"光圈: f/{exif['aperture']}")
    if exif.get("exposure_time"):
        exif_parts.append(f"快门: {exif['exposure_time']}s")
    if exif.get("focal_length"):
        exif_parts.append(f"焦距: {exif['focal_length']}mm")
    if exif.get("iso"):
        exif_parts.append(f"ISO: {exif['iso']}")

    text = f"请对这张照片进行精要点评。\n\n"
    text += f"风格分类：{photo.get('style_label', '未知')}\n"
    if photo.get("description"):
        text += f"照片描述：{photo['description']}\n"
    if exif_parts:
        text += f"EXIF 数据：{' | '.join(exif_parts)}\n"
    text += "\n按四段结构输出，总字数 200-300 字。"

    return [
        {
            "type": "image_url",
            "image_url": {
                "url": photo["url_regular"],
                "detail": "high",
            },
        },
        {
            "type": "text",
            "text": text,
        },
    ]
