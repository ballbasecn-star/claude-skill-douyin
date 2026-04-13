"""应用配置。"""

import os
from pathlib import Path

# Skill 根目录（.claude/skills/douyin/）
SKILL_DIR = Path(__file__).resolve().parents[2]
COOKIE_DIR = Path(os.environ.get("COOKIE_DIR", str(SKILL_DIR / "cookie_data")))
