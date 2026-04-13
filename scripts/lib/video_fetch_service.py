"""
单视频抓取与基础解析服务
"""

import logging
import re
from typing import Dict, Optional

from lib.domain import VideoInfo
from lib.cookie_store import get_cookie_manager
from lib.douyin_web_client import extract_aweme_id, fetch_video_detail, resolve_short_url

logger = logging.getLogger(__name__)

SHORT_URL_PATTERN = re.compile(r"https?://v\.douyin\.com/[\w\-]+/?")
FULL_URL_PATTERN = re.compile(r"https?://(?:www\.)?douyin\.com/(?:video|note)/(\d+)")


def extract_share_link(text: str) -> Optional[str]:
    """从分享文本中提取抖音链接。"""
    match = SHORT_URL_PATTERN.search(text)
    if match:
        link = match.group(0).rstrip("/") + "/"
        logger.info("提取到短链接: %s", link)
        return link

    match = FULL_URL_PATTERN.search(text)
    if match:
        link = match.group(0)
        logger.info("提取到完整链接: %s", link)
        return link

    return None


def parse_video_data(data: Dict) -> VideoInfo:
    """将抖音 API 返回的数据解析为 VideoInfo。"""
    info = VideoInfo()

    try:
        info.video_id = str(data.get("aweme_id", ""))
        info.title = data.get("desc", "")
        info.description = data.get("desc", "")
        info.share_url = f"https://www.douyin.com/video/{info.video_id}" if info.video_id else ""
        info.create_time = data.get("create_time", 0)

        author = data.get("author", {}) or {}
        info.author = author.get("nickname", "")
        info.author_id = author.get("unique_id", "") or author.get("short_id", "")
        avatar = author.get("avatar_thumb", {})
        if avatar and isinstance(avatar, dict):
            url_list = avatar.get("url_list", [])
            if url_list:
                info.author_avatar = url_list[0]

        stats = data.get("statistics", {}) or {}
        info.play_count = stats.get("play_count", 0) or 0
        info.like_count = stats.get("digg_count", 0) or 0
        info.comment_count = stats.get("comment_count", 0) or 0
        info.share_count = stats.get("share_count", 0) or 0
        info.collect_count = stats.get("collect_count", 0) or 0

        video = data.get("video", {}) or {}
        cover = video.get("cover", {}) or data.get("cover", {})
        if cover and isinstance(cover, dict):
            url_list = cover.get("url_list", [])
            if url_list:
                info.cover_url = url_list[0]

        info.duration = video.get("duration", 0) or data.get("duration", 0) or 0

        text_extra = data.get("text_extra", [])
        if isinstance(text_extra, list):
            for extra in text_extra:
                if isinstance(extra, dict):
                    tag = extra.get("hashtag_name", "")
                    if tag:
                        info.hashtags.append(f"#{tag}")
        if not info.hashtags and info.description:
            tags = re.findall(r"#([^\s#]+)", info.description)
            info.hashtags = [f"#{tag}" for tag in tags[:10]]

    except Exception as exc:
        logger.error("解析视频数据失败: %s", exc)

    return info


def get_video_download_url(data: Dict) -> Optional[str]:
    """从 API 数据中提取无水印视频下载链接。"""
    try:
        video = data.get("video", {})
        play_addr = video.get("play_addr", {})
        if play_addr:
            url_list = play_addr.get("url_list", [])
            if url_list:
                url = url_list[0]
                return url.replace("playwm", "play")

        bit_rate = video.get("bit_rate", [])
        if bit_rate:
            play_addr = bit_rate[0].get("play_addr", {})
            url_list = play_addr.get("url_list", [])
            if url_list:
                return url_list[0]
    except Exception as exc:
        logger.error("提取下载链接失败: %s", exc)
    return None


def crawl_video(share_text: str) -> Optional[tuple[VideoInfo, Dict]]:
    """完整的本地爬取流程。"""
    link = extract_share_link(share_text)
    if not link:
        logger.error("未找到抖音链接")
        return None

    aweme_id = extract_aweme_id(link)
    if not aweme_id:
        aweme_id = resolve_short_url(link)

    if not aweme_id:
        logger.error("无法获取 aweme_id")
        return None

    cookie = get_cookie_manager().get_cookie()
    if not cookie:
        logger.warning("⚠️ 未设置 Cookie，API 可能返回受限数据")
        logger.warning("   请运行: python main.py cookie set \"你的Cookie\"")

    raw_data = fetch_video_detail(aweme_id, cookie)
    if not raw_data:
        logger.error("❌ 抖音 API 请求失败")
        return None

    video_info = parse_video_data(raw_data)
    logger.info("✅ 解析成功: %s", video_info.title[:50])
    return video_info, raw_data
