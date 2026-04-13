#!/usr/bin/env python3
"""
抖音解析工具 - CLI 入口

用法:
    python cli.py fetch "博主主页链接"          # 抓取20条视频 → 转录 → 写飞书
    python cli.py fetch "链接" --no-transcript  # 仅抓取，不转录
    python cli.py fetch "链接" --count 50       # 抓取50条
    python cli.py parse "分享文本"              # 解析单个视频
    python cli.py cookie set "Cookie值"         # 设置 Cookie
    python cli.py cookie show                   # 查看 Cookie
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

# ---- 路径设置 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

SKILL_DIR = os.path.dirname(SCRIPT_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(SKILL_DIR, ".env"))
except ImportError:
    pass


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")


# ========== Fetch 命令 ==========

def handle_fetch_command(args: list[str]) -> int:
    """抓取博主视频 → 转录 → 写入飞书。"""
    parser = argparse.ArgumentParser(description="抓取博主视频并写入飞书")
    parser.add_argument("url", help="博主主页链接")
    parser.add_argument("--count", type=int, default=20, help="抓取数量 (默认 20)")
    parser.add_argument("--all", action="store_true", dest="fetch_all", help="抓取全部视频（翻页）")
    parser.add_argument("--no-transcript", action="store_true", help="跳过转录")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("-v", "--verbose", action="store_true")
    parsed = parser.parse_args(args)
    setup_logging(parsed.verbose)

    from lib.feishu_client import FeishuClient
    from lib.fetch_to_feishu import fetch_and_write

    # 检查飞书配置
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("❌ 缺少飞书应用配置，请在 .env 中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        return 1

    feishu = FeishuClient(app_id, app_secret)

    if not parsed.no_transcript:
        if not os.environ.get("SILICONFLOW_API_KEY"):
            print("⚠️  未设置 SILICONFLOW_API_KEY，将跳过转录")
            print("   可在 .env 中设置，或使用 --no-transcript 跳过")

    fetch_desc = "全部" if parsed.fetch_all else str(parsed.count)
    print(f"\n🔍 开始抓取博主视频 (数量: {fetch_desc})...\n")

    try:
        result = fetch_and_write(
            creator_url=parsed.url,
            feishu_client=feishu,
            env_path=os.path.join(SKILL_DIR, ".env"),
            count=parsed.count,
            skip_transcript=parsed.no_transcript,
            fetch_all=parsed.fetch_all,
        )
        if parsed.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"\n博主: {result['author']}")
            print(f"获取: {result['total_fetched']} 条 | 新增: {result['new_records']} 条 | 跳过: {result['skipped']} 条")
            if result.get("covers_uploaded"):
                print(f"封面: {result['covers_uploaded']} 个")
        return 0
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except Exception as exc:
        print(f"❌ 执行失败: {exc}")
        return 1


# ========== Parse 命令 ==========

def handle_parse_command(args: list[str]) -> int:
    """处理单视频解析命令。"""
    from lib.video_fetch_service import crawl_video

    parser = argparse.ArgumentParser(description="解析单个抖音视频")
    parser.add_argument("text", nargs="?", help="抖音分享文本或链接")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--no-transcript", action="store_true", help="不转录")
    parser.add_argument("--cloud", action="store_true", help="云端转录")
    parser.add_argument("--cloud-provider", default="groq", choices=["groq", "siliconflow"])
    parser.add_argument("--model", default="large-v3", help="本地模型大小")
    parser.add_argument("-v", "--verbose", action="store_true")
    parsed = parser.parse_args(args)
    setup_logging(parsed.verbose)

    share_text = parsed.text
    if not share_text:
        print("📋 请粘贴抖音分享文本:")
        try:
            share_text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n取消。")
            return 0
    if not share_text:
        print("❌ 未输入任何内容")
        return 1

    # 仅获取基本信息
    result = crawl_video(share_text)
    if not result:
        print("❌ 解析失败")
        return 1

    video_info, _ = result

    # 转录（可选）
    if not parsed.no_transcript:
        from lib.media_tools import extract_audio_from_url
        from lib.video_fetch_service import get_video_download_url

        download_url = get_video_download_url(_)
        if download_url:
            audio_path = extract_audio_from_url(download_url)
            if audio_path:
                try:
                    if parsed.cloud:
                        api_key = os.environ.get(
                            "SILICONFLOW_API_KEY" if parsed.cloud_provider == "siliconflow" else "GROQ_API_KEY"
                        )
                        if api_key:
                            import requests
                            headers = {"Authorization": f"Bearer {api_key}"}
                            with open(audio_path, "rb") as f:
                                files = {"file": (os.path.basename(audio_path), f, "audio/mpeg")}
                                model = "FunAudioLLM/SenseVoiceSmall" if parsed.cloud_provider == "siliconflow" else "whisper-large-v3-turbo"
                                data = {"model": model, "language": "zh", "response_format": "text"}
                                url = (
                                    "https://api.siliconflow.cn/v1/audio/transcriptions"
                                    if parsed.cloud_provider == "siliconflow"
                                    else "https://api.groq.com/openai/v1/audio/transcriptions"
                                )
                                resp = requests.post(url, headers=headers, files=files, data=data, timeout=300)
                                if resp.status_code == 200:
                                    video_info.transcript = resp.text.strip()
                    else:
                        try:
                            from faster_whisper import WhisperModel
                            model = WhisperModel(parsed.model, compute_type="int8")
                            segments, _ = model.transcribe(audio_path, language="zh", beam_size=5, vad_filter=True)
                            video_info.transcript = "\n".join(s.text.strip() for s in segments)
                        except ImportError:
                            print("⚠️  faster-whisper 未安装，跳过本地转录")
                finally:
                    if os.path.exists(audio_path):
                        os.unlink(audio_path)

    if parsed.json:
        print(json.dumps(video_info.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(video_info.format_output())
    return 0


# ========== Cookie 命令 ==========

def handle_cookie_command(args: list[str]) -> int:
    from lib.cookie_store import get_cookie_manager

    cookie_manager = get_cookie_manager()
    action = args[0] if args else "show"

    if action == "set":
        if len(args) < 2:
            print('❌ 用法: cli.py cookie set "Cookie值"')
            return 1
        cookie_manager.save_cookie(args[1], source="manual")
        print("✅ Cookie 已保存")
        return 0

    if action == "show":
        info = cookie_manager.get_cookie_info()
        if info.get("exists"):
            print(f"🍪 Cookie: 来源={info['source']} 更新={info['timestamp']} 长度={info['cookie_length']}")
        else:
            print("⚠️  未设置 Cookie")
        return 0

    print(f"未知命令: {action}")
    return 1


# ========== 主入口 ==========

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法: cli.py <fetch|parse|cookie> [参数]")
        print("  fetch  — 抓取博主视频 → 转录 → 写飞书")
        print("  parse  — 解析单个视频")
        print("  cookie — Cookie 管理")
        return 0
    if args[0] == "fetch":
        return handle_fetch_command(args[1:])
    if args[0] == "cookie":
        return handle_cookie_command(args[1:])
    # 默认走 parse
    return handle_parse_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
