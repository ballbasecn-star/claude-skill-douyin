from __future__ import annotations

"""
Cookie 存储与管理
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.settings import COOKIE_DIR

COOKIE_FILE = COOKIE_DIR / "douyin_cookie.json"

logger = logging.getLogger(__name__)


class CookieManager:
    """Cookie 管理器。"""

    def __init__(self, cookie_dir: str | None = None):
        self.cookie_dir = Path(cookie_dir) if cookie_dir else COOKIE_DIR
        self.cookie_file = self.cookie_dir / "douyin_cookie.json"
        self.cookie_dir.mkdir(parents=True, exist_ok=True)

    def get_cookie(self) -> Optional[str]:
        """获取当前保存的 Cookie。"""
        if not self.cookie_file.exists():
            return None

        try:
            with self.cookie_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            cookie = data.get("cookie", "")
            if cookie:
                timestamp = data.get("timestamp", "")
                logger.debug("加载 Cookie (更新于: %s)", timestamp)
                return cookie
        except Exception as exc:
            logger.warning("读取 Cookie 失败: %s", exc)

        return None

    def save_cookie(self, cookie: str, source: str = "manual") -> None:
        """保存 Cookie。"""
        try:
            data = {
                "cookie": cookie,
                "source": source,
                "timestamp": datetime.now().isoformat(),
                "service": "douyin",
            }

            with self.cookie_file.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)

            logger.info("Cookie 已保存 (来源: %s, 长度: %s)", source, len(cookie))
        except Exception as exc:
            logger.error("保存 Cookie 失败: %s", exc)

    def has_cookie(self) -> bool:
        """检查是否有保存的 Cookie。"""
        return self.get_cookie() is not None

    def get_cookie_info(self) -> dict:
        """获取 Cookie 元信息。"""
        if not self.cookie_file.exists():
            return {"exists": False}

        try:
            with self.cookie_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            return {
                "exists": True,
                "source": data.get("source", "unknown"),
                "timestamp": data.get("timestamp", ""),
                "cookie_length": len(data.get("cookie", "")),
            }
        except Exception:
            return {"exists": False}


_cookie_manager: CookieManager | None = None


def get_cookie_manager() -> CookieManager:
    """获取全局 Cookie 管理器。"""
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = CookieManager(str(COOKIE_DIR))
    return _cookie_manager
