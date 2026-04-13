"""
媒体处理基础设施
"""

import logging
import os
import subprocess
import tempfile
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FFMPEG_HEADERS = (
    "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/90.0.4430.212 Safari/537.36\r\n"
    "Referer: https://www.douyin.com/\r\n"
)


def extract_audio_from_url(video_url: str) -> Optional[str]:
    """直接从视频 URL 提取音频（不下载视频文件）。"""
    audio_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name

    try:
        logger.info("⚡ 从 URL 直接提取音频流（跳过视频下载）...")
        cmd = [
            "ffmpeg",
            "-headers", FFMPEG_HEADERS,
            "-i", video_url,
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            "-y",
            audio_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and os.path.exists(audio_path):
            size_kb = os.path.getsize(audio_path) / 1024
            logger.info("✅ 音频提取完成: %.0fKB", size_kb)
            return audio_path

        stderr = result.stderr.strip().split("\n")
        error_msg = stderr[-1] if stderr else "未知错误"
        logger.error("ffmpeg 失败: %s", error_msg)
    except FileNotFoundError:
        logger.error("未找到 ffmpeg，请安装: brew install ffmpeg")
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg 超时（120秒），视频可能过长或网络过慢")
    except Exception as exc:
        logger.error("音频提取异常: %s", exc)

    if os.path.exists(audio_path):
        os.unlink(audio_path)
    return None


def extract_audio_from_file(video_path: str) -> Optional[str]:
    """从本地视频文件提取音频。"""
    audio_path = video_path.rsplit(".", 1)[0] + ".wav"

    try:
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0 and os.path.exists(audio_path):
            size_mb = os.path.getsize(audio_path) / 1024 / 1024
            logger.info("音频提取完成: %s (%.1fMB)", audio_path, size_mb)
            return audio_path

        logger.error("ffmpeg 失败: %s", result.stderr[:200])
    except FileNotFoundError:
        logger.error("未找到 ffmpeg，请安装: brew install ffmpeg")
    except Exception as exc:
        logger.error("音频提取异常: %s", exc)

    return None


def download_video(video_url: str) -> Optional[str]:
    """下载完整视频到临时文件。"""
    try:
        logger.info("降级: 下载完整视频...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/90.0.4430.212 Safari/537.36",
            "Referer": "https://www.douyin.com/",
        }

        response = requests.get(
            video_url,
            headers=headers,
            timeout=300,
            stream=True,
        )

        if response.status_code == 200:
            temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            size = 0
            for chunk in response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
                size += len(chunk)
            temp_file.close()

            if size > 1000:
                logger.info("视频下载完成: (%.1fMB)", size / 1024 / 1024)
                return temp_file.name

            os.unlink(temp_file.name)
            logger.warning("下载的文件过小")
        else:
            logger.warning("下载失败: HTTP %s", response.status_code)

    except Exception as exc:
        logger.error("下载视频异常: %s", exc)

    return None
