"""
单视频领域模型
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class VideoInfo:
    """抖音视频信息"""

    # 基本信息
    video_id: str = ""
    title: str = ""
    description: str = ""  # 完整文案

    # 作者信息
    author: str = ""
    author_id: str = ""
    author_avatar: Optional[str] = None

    # 媒体链接
    cover_url: Optional[str] = None
    video_url: Optional[str] = None
    share_url: str = ""

    # 时间和时长
    duration: int = 0  # 毫秒
    create_time: int = 0  # 时间戳

    # 统计数据
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int = 0

    # 标签
    hashtags: List[str] = field(default_factory=list)

    # 视频内语音转录文案
    transcript: str = ""

    # AI 文案拆解结果 (JSON)
    analysis: dict = field(default_factory=dict)

    @property
    def duration_formatted(self) -> str:
        """格式化时长 mm:ss"""
        if not self.duration:
            return "00:00"
        seconds = self.duration // 1000
        minutes, secs = divmod(seconds, 60)
        return f"{int(minutes):02d}:{int(secs):02d}"

    @property
    def create_time_formatted(self) -> str:
        """格式化发布时间"""
        if not self.create_time:
            return ""
        try:
            return datetime.fromtimestamp(self.create_time).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError):
            return ""

    def to_dict(self) -> dict:
        """转换为字典"""
        data = asdict(self)
        data["duration_formatted"] = self.duration_formatted
        data["create_time_formatted"] = self.create_time_formatted
        return data

    def format_output(self) -> str:
        """格式化输出为可读文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("📹 抖音视频信息")
        lines.append("=" * 60)

        if self.title:
            lines.append(f"\n📌 标题: {self.title}")

        if self.author:
            author_str = f"👤 作者: {self.author}"
            if self.author_id:
                author_str += f" (@{self.author_id})"
            lines.append(author_str)

        if self.video_id:
            lines.append(f"🔗 视频ID: {self.video_id}")

        if self.duration:
            lines.append(f"⏱️  时长: {self.duration_formatted}")

        if self.create_time:
            lines.append(f"📅 发布时间: {self.create_time_formatted}")

        stats = []
        if self.play_count:
            stats.append(f"▶️ {self.play_count:,}")
        if self.like_count:
            stats.append(f"❤️ {self.like_count:,}")
        if self.comment_count:
            stats.append(f"💬 {self.comment_count:,}")
        if self.share_count:
            stats.append(f"🔄 {self.share_count:,}")
        if self.collect_count:
            stats.append(f"⭐ {self.collect_count:,}")
        if stats:
            lines.append(f"\n📊 数据: {' | '.join(stats)}")

        if self.hashtags:
            lines.append(f"\n🏷️  标签: {' '.join(self.hashtags)}")

        if self.description:
            lines.append("\n📝 视频描述:")
            lines.append("-" * 40)
            lines.append(self.description)
            lines.append("-" * 40)

        if self.transcript:
            lines.append("\n🎙️  视频内完整文案 (语音转录):")
            lines.append("=" * 40)
            lines.append(self.transcript)
            lines.append("=" * 40)

        if self.cover_url:
            lines.append(f"\n🖼️  封面: {self.cover_url}")

        if self.share_url:
            lines.append(f"🔗 链接: {self.share_url}")

        if self.analysis:
            lines.append("\n" + "=" * 60)
            lines.append("📊 爆款文案深度剖析 (AI 提供)")
            lines.append("=" * 60)
            hook_text = self.analysis.get("hook_text", "")
            hook_type = self.analysis.get("hook_type", "")
            if hook_text or hook_type:
                lines.append(f"🎯 黄金前3秒: {hook_text} [{hook_type}]")

            structure_type = self.analysis.get("structure_type", "")
            if structure_type:
                lines.append(f"🏗️  内容框架: {structure_type}")

            retention_points = self.analysis.get("retention_points", [])
            if retention_points:
                lines.append("🔥 情绪留存点:")
                for index, point in enumerate(retention_points, 1):
                    lines.append(f"   {index}. {point}")

            scenario_expression = self.analysis.get("scenario_expression", [])
            if scenario_expression:
                lines.append("🎬 场景化表达:")
                for index, expression in enumerate(scenario_expression, 1):
                    lines.append(f"   {index}. {expression}")

            cta = self.analysis.get("cta", "")
            if cta:
                lines.append(f"📣 互动引导: {cta}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)
