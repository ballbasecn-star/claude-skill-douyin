"""抖音链接文本处理工具。"""

from __future__ import annotations

import re

CREATOR_LINK_PATTERN = re.compile(r"https?://(?:v\.douyin\.com|(?:www\.)?douyin\.com)/[^\s]+")
TRAILING_PUNCTUATION = "。，“”‘’！？!?,，；;:：)]）】}>》"


def normalize_creator_source_url(raw_input: str) -> str:
    """从分享文本中提取可访问的主页链接。"""
    text = (raw_input or "").strip()
    if not text:
        return ""

    match = CREATOR_LINK_PATTERN.search(text)
    candidate = match.group(0) if match else text
    return candidate.rstrip(TRAILING_PUNCTUATION)
