"""核心流程：抓取博主视频 → 分批转录 → 分批写入飞书。"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable, Optional

from lib.cookie_store import get_cookie_manager
from lib.douyin_web_client import (
    extract_stable_user_id,
    fetch_creator_posts,
    resolve_redirect_url,
)
from lib.douyin_link_utils import normalize_creator_source_url
from lib.feishu_client import FeishuClient
from lib.media_tools import extract_audio_from_url
from lib.video_fetch_service import parse_video_data, get_video_download_url

logger = logging.getLogger(__name__)

TRANSCRIPT_BATCH_SIZE = 20  # 每批转录 & 写入的数量

# 本地 FunASR 模型（延迟加载）
_asr_model = None


def _get_asr_model():
    """延迟加载本地 FunASR Paraformer 模型（含 VAD + 标点）。"""
    global _asr_model
    if _asr_model is None:
        from funasr import AutoModel
        logger.info("  加载本地 FunASR Paraformer 模型...")
        _asr_model = AutoModel(
            model="iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            pnc_model="iic/punc_ct-transformer_cn-en-common-vocab471067-large",
        )
        logger.info("  模型加载完成")
    return _asr_model


def _transcribe_audio(audio_path: str) -> Optional[str]:
    """使用本地 FunASR Paraformer 转录。"""
    try:
        model = _get_asr_model()
        result = model.generate(input=audio_path, batch_size_s=300)
        if result and len(result) > 0:
            text = result[0].get("text", "").strip()
            if text:
                logger.info("  转录完成: %d 字", len(text))
                return text
        return ""
    except Exception as exc:
        logger.warning("  转录失败: %s", exc)
    return None


def _format_duration(duration_ms: int) -> str:
    """格式化时长为 mm:ss。"""
    if not duration_ms:
        return "00:00"
    seconds = duration_ms // 1000
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{int(s):02d}"


def _paginate_all_videos(
    stable_user_id: str,
    cookie: str,
    resolved_url: str,
    max_count: int = 0,
    page_size: int = 20,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> tuple[list, str]:
    """
    翻页抓取博主全部视频元数据。

    Args:
        max_count: 最大抓取数量，0 表示全部

    Returns:
        (aweme_list, author_name)
    """
    all_items = []
    seen_ids = set()
    cursor = 0
    author_name = "未知博主"
    page = 0

    while True:
        page += 1
        resp = fetch_creator_posts(
            stable_user_id=stable_user_id,
            cookie=cookie,
            max_cursor=cursor,
            count=page_size,
            referer_url=resolved_url,
        )
        if resp is None:
            logger.warning("第 %d 页请求失败，停止翻页", page)
            break

        items = resp.get("aweme_list") or []
        has_more = resp.get("has_more", 0)

        new_count = 0
        for item in items:
            aid = item.get("aweme_id")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                all_items.append(item)
                new_count += 1
                if not author_name or author_name == "未知博主":
                    author_info = item.get("author") or {}
                    author_name = author_info.get("nickname", "未知博主")

        logger.info("第 %d 页: +%d 条, total=%d, has_more=%s", page, new_count, len(all_items), has_more)

        if progress_callback:
            progress_callback({"type": "page", "page": page, "total": len(all_items)})

        if max_count > 0 and len(all_items) >= max_count:
            all_items = all_items[:max_count]
            break
        if not items or not has_more:
            break
        cursor = resp.get("max_cursor", 0)
        time.sleep(1.5)

    return all_items, author_name


def fetch_and_write(
    creator_url: str,
    feishu_client: FeishuClient,
    env_path: str,
    count: int = 20,
    skip_transcript: bool = False,
    fetch_all: bool = False,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    一键流程：解析博主 → 抓取视频元数据 → 分批转录+写入飞书。

    分批策略：每 TRANSCRIPT_BATCH_SIZE 条视频转录完成后立即写入飞书，
    再处理下一批。崩溃后重新运行可自动跳过已写入的记录。

    Args:
        creator_url: 博主主页链接
        feishu_client: 飞书客户端
        env_path: .env 文件路径
        count: 抓取视频数量（默认 20）
        skip_transcript: 是否跳过转录
        fetch_all: 是否抓取全部视频（忽略 count）
        progress_callback: 进度回调

    Returns:
        结果摘要
    """
    def emit(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback({"type": "log", "message": msg})

    # 1. 解析博主身份
    emit("解析博主链接...")
    normalized_url = normalize_creator_source_url(creator_url)
    if not normalized_url:
        raise ValueError("请输入有效的博主主页链接")

    resolved_url = resolve_redirect_url(normalized_url) or normalized_url
    stable_user_id = extract_stable_user_id(resolved_url)
    if not stable_user_id:
        raise ValueError("无法从链接中解析博主标识")

    emit(f"博主标识: {stable_user_id[:20]}...")

    # 2. 确保飞书表格
    emit("检查飞书表格...")
    app_token, table_id = feishu_client.ensure_table(env_path)

    # 3. 抓取视频元数据（仅元数据，不转录）
    cookie = get_cookie_manager().get_cookie()
    max_count = 0 if fetch_all else count
    emit(f"抓取{'全部' if fetch_all else f'最新 {count} 条'}视频元数据...")

    aweme_list, author_name = _paginate_all_videos(
        stable_user_id=stable_user_id,
        cookie=cookie,
        resolved_url=resolved_url,
        max_count=max_count,
        progress_callback=progress_callback,
    )

    if not aweme_list:
        raise ValueError("未获取到视频，可能是 Cookie 权限不足")

    emit(f"博主: {author_name}，获取到 {len(aweme_list)} 条视频元数据")

    # 4. 过滤已存在的记录
    emit("查询已有记录...")
    existing_ids = feishu_client.query_existing_video_ids(app_token, table_id)
    emit(f"已有 {len(existing_ids)} 条记录")

    todo_items = [item for item in aweme_list
                  if parse_video_data(item).video_id not in existing_ids]
    emit(f"需要处理: {len(todo_items)} 条 (去重后)")

    if not todo_items:
        emit("全部视频已在飞书中，无需处理")
        return {
            "author": author_name,
            "total_fetched": len(aweme_list),
            "new_records": 0,
            "skipped": len(aweme_list) - len(todo_items),
            "remaining": 0,
        }

    # 5. 分批转录 + 写入飞书
    total_written = 0
    total_covers = 0
    batch_size = TRANSCRIPT_BATCH_SIZE

    for batch_start in range(0, len(todo_items), batch_size):
        batch = todo_items[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(todo_items) + batch_size - 1) // batch_size
        emit(f"\n--- 批次 {batch_num}/{total_batches} ({len(batch)} 条) ---")

        # 逐条转录
        records = []
        for i, item in enumerate(batch):
            info = parse_video_data(item)
            idx = batch_start + i + 1
            emit(f"  [{idx}/{len(todo_items)}] {info.title[:40]}")

            transcript = ""
            if not skip_transcript:
                download_url = get_video_download_url(item)
                if download_url:
                    audio_path = extract_audio_from_url(download_url)
                    if audio_path:
                        try:
                            transcript = _transcribe_audio(audio_path) or ""
                        finally:
                            if os.path.exists(audio_path):
                                os.unlink(audio_path)

            fields = {
                "视频ID": info.video_id,
                "标题": info.title,
                "作者": info.author or author_name,
                "发布时间": info.create_time * 1000 if info.create_time else None,
                "时长": _format_duration(info.duration),
                "播放量": info.play_count,
                "点赞数": info.like_count,
                "评论数": info.comment_count,
                "视频链接": {
                    "text": info.share_url,
                    "link": info.share_url,
                } if info.share_url else None,
            }
            if transcript:
                fields["转录文案"] = transcript
            # 清理 None 值
            fields = {k: v for k, v in fields.items() if v is not None}

            records.append({"fields": fields, "cover_url": info.cover_url})

            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "current": idx,
                    "total": len(todo_items),
                })

        # 本批写入飞书
        emit(f"  写入飞书: {len(records)} 条...")
        fields_only = [r["fields"] for r in records]
        # 刷新 token（长时间运行可能过期）
        feishu_client.refresh_token()
        record_ids = feishu_client.batch_create_records(app_token, table_id, fields_only)
        total_written += len(record_ids)
        emit(f"  写入完成: {len(record_ids)} 条")

        # 本批上传封面
        cover_ok = 0
        for record, rid in zip(records, record_ids):
            cover_url = record.get("cover_url", "")
            if cover_url and rid:
                file_token = feishu_client.upload_image(app_token, cover_url)
                if file_token:
                    try:
                        feishu_client.update_record_attachment(
                            app_token, table_id, rid, "封面", file_token
                        )
                        cover_ok += 1
                    except Exception:
                        pass
        total_covers += cover_ok
        emit(f"  封面: {cover_ok}/{len(record_ids)}")

        # 批次间休息（避免API频率限制）
        if batch_start + batch_size < len(todo_items):
            emit(f"  等待 2 秒...")
            time.sleep(2)

    remaining = max(0, len(todo_items) - total_written)
    emit(f"\n=== 完成 ===")
    emit(f"写入: {total_written} 条, 封面: {total_covers} 个")
    if remaining > 0:
        emit(f"剩余: {remaining} 条待处理（可重新运行继续）")

    return {
        "author": author_name,
        "total_fetched": len(aweme_list),
        "new_records": total_written,
        "skipped": len(aweme_list) - len(todo_items),
        "covers_uploaded": total_covers,
        "remaining": remaining,
    }
