"""飞书多维表格 Open API 客户端。"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

FEISHU_BASE = "https://open.feishu.cn"

# 多维表格字段定义：(field_name, type)
TABLE_FIELDS = [
    ("视频ID", 1),       # Text — 去重用
    ("封面", 17),        # Attachment
    ("标题", 1),         # Text
    ("作者", 1),         # Text
    ("发布时间", 5),     # DateTime
    ("时长", 1),         # Text (mm:ss)
    ("播放量", 2),       # Number
    ("点赞数", 2),       # Number
    ("评论数", 2),       # Number
    ("转录文案", 1),     # Text
    ("视频链接", 15),    # URL
    ("脚本类型", 3, {    # SingleSelect
        "options": [
            {"name": "聊观点"}, {"name": "晒过程"},
            {"name": "讲故事"}, {"name": "教知识"},
        ]
    }),
    ("爆款元素", 7, {    # MultiSelect
        "options": [
            {"name": "成本"}, {"name": "人群"}, {"name": "奇葩"},
            {"name": "头牌"}, {"name": "最差"}, {"name": "反差"},
            {"name": "怀旧"}, {"name": "荷尔蒙"}, {"name": "无"},
        ]
    }),
    ("情绪波动点", 1),   # Text
    ("画面感", 1),       # Text (评分+原因)
    ("力量感", 1),       # Text (评分+原因)
    ("人设类型", 3, {    # SingleSelect
        "options": [
            {"name": "崇拜者"}, {"name": "教导者"}, {"name": "分享者"},
            {"name": "陪伴者"}, {"name": "衬托者"}, {"name": "搞笑者"},
        ]
    }),
    ("运营建议", 1),     # Text
]


class FeishuClient:
    """飞书多维表格客户端。"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str = ""
        self._token_expires: float = 0

    def _ensure_token(self):
        """获取或刷新 tenant_access_token。"""
        if self._token and time.time() < self._token_expires - 300:
            return
        logger.info("获取飞书 tenant_access_token...")
        resp = requests.post(
            f"{FEISHU_BASE}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书认证失败: {data.get('msg')}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.time() + data.get("expire", 7200)
        logger.info("✅ 飞书认证成功")

    def refresh_token(self):
        """强制刷新 token（长时间运行时使用）。"""
        self._token = ""
        self._token_expires = 0
        self._ensure_token()

    @property
    def _headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _check_response(self, resp: requests.Response, action: str) -> dict:
        """检查飞书 API 响应。"""
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书 {action} 失败: code={data.get('code')} msg={data.get('msg')}")
        return data.get("data", {})

    def create_bitable(self, name: str = "抖音视频库") -> tuple[str, str]:
        """创建多维表格，返回 (app_token, table_id)。"""
        logger.info("创建飞书多维表格: %s", name)
        data = self._check_response(
            requests.post(
                f"{FEISHU_BASE}/open-apis/bitable/v1/apps",
                headers=self._headers,
                json={"name": name},
                timeout=15,
            ),
            "创建多维表格",
        )
        app = data["app"]
        app_token = app["app_token"]
        table_id = app["default_table_id"]
        logger.info("✅ 创建成功: app_token=%s table_id=%s", app_token, table_id)
        return app_token, table_id

    def create_fields(self, app_token: str, table_id: str):
        """在表格中创建预定义的字段。"""
        logger.info("创建表格字段...")
        for spec in TABLE_FIELDS:
            field_name = spec[0]
            field_type = spec[1]
            payload = {"field_name": field_name, "type": field_type}
            if len(spec) > 2:
                payload["property"] = spec[2]
            self._check_response(
                requests.post(
                    f"{FEISHU_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                    headers=self._headers,
                    json=payload,
                    timeout=10,
                ),
                f"创建字段 {field_name}",
            )
            time.sleep(0.1)  # 避免限流
        logger.info("✅ 字段创建完成 (%d 个)", len(TABLE_FIELDS))

    def batch_create_records(self, app_token: str, table_id: str, records: list[dict]) -> list[str]:
        """批量写入记录，返回 record_id 列表。"""
        if not records:
            return []

        # 飞书限制每次最多 500 条
        all_ids = []
        for offset in range(0, len(records), 500):
            batch = records[offset : offset + 500]
            payload = {
                "records": [{"fields": r} for r in batch],
            }
            data = self._check_response(
                requests.post(
                    f"{FEISHU_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create",
                    headers=self._headers,
                    json=payload,
                    timeout=30,
                ),
                "批量写入记录",
            )
            for rec in data.get("records", []):
                all_ids.append(rec.get("record_id", ""))
            if offset + 500 < len(records):
                time.sleep(0.5)
        logger.info("✅ 写入 %d 条记录", len(all_ids))
        return all_ids

    def upload_image(self, app_token: str, image_url: str) -> Optional[str]:
        """下载图片并上传为飞书附件，返回 file_token。"""
        try:
            # 下载图片
            resp = requests.get(image_url, timeout=30, stream=True)
            if resp.status_code != 200:
                logger.warning("封面下载失败: HTTP %s", resp.status_code)
                return None

            img_data = resp.content
            if len(img_data) < 100:
                return None

            # 上传到飞书
            self._ensure_token()
            upload_headers = {
                "Authorization": f"Bearer {self._token}",
            }
            files = {
                "file_name": (None, "cover.jpg"),
                "parent_type": (None, "bitable_image"),
                "parent_node": (None, app_token),
                "size": (None, str(len(img_data))),
                "file": ("cover.jpg", io.BytesIO(img_data), "image/jpeg"),
            }
            resp = requests.post(
                f"{FEISHU_BASE}/open-apis/drive/v1/medias/upload_all",
                headers=upload_headers,
                files=files,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("封面上传失败: %s", data.get("msg"))
                return None
            return data["data"]["file_token"]
        except Exception as exc:
            logger.warning("封面上传异常: %s", exc)
            return None

    def update_record_attachment(
        self, app_token: str, table_id: str, record_id: str, field_name: str, file_token: str
    ):
        """更新记录的附件字段。"""
        self._check_response(
            requests.put(
                f"{FEISHU_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
                headers=self._headers,
                json={"fields": {field_name: [{"file_token": file_token}]}},
                timeout=10,
            ),
            "更新附件",
        )

    @staticmethod
    def _extract_text(val) -> str:
        """从飞书字段值中提取文本（兼容 str 和 list[dict] 格式）。"""
        if isinstance(val, list):
            return "".join(x.get("text", "") for x in val if isinstance(x, dict))
        return str(val) if val else ""

    def query_existing_video_ids(self, app_token: str, table_id: str) -> set[str]:
        """查询表格中已有的视频 ID，用于去重。"""
        existing = set()
        page_token = None
        while True:
            params = {
                "field_names": json.dumps(["视频ID"]),
                "page_size": 500,
            }
            if page_token:
                params["page_token"] = page_token

            try:
                resp = requests.post(
                    f"{FEISHU_BASE}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                    headers=self._headers,
                    json={"filter": {"conjunction": "and", "conditions": []}},
                    params=params,
                    timeout=15,
                )
                data = resp.json()
                if data.get("code") != 0:
                    logger.warning("查询已有记录失败: %s", data.get("msg"))
                    break

                for item in data.get("data", {}).get("items", []):
                    fields = item.get("fields", {})
                    vid = self._extract_text(fields.get("视频ID", ""))
                    if vid:
                        existing.add(vid)

                page_token = data.get("data", {}).get("page_token")
                if not page_token:
                    break
            except Exception as exc:
                logger.warning("查询已有记录异常: %s", exc)
                break
        return existing

    def ensure_table(self, env_path: str) -> tuple[str, str]:
        """确保飞书表格已创建。如果 .env 中没有配置，自动创建。"""
        from dotenv import dotenv_values

        vals = dotenv_values(env_path)
        app_token = vals.get("FEISHU_BASE_TOKEN", "")
        table_id = vals.get("FEISHU_TABLE_ID", "")

        if app_token and table_id:
            logger.info("使用已有飞书表格: %s", app_token)
            return app_token, table_id

        # 首次创建
        app_token, table_id = self.create_bitable()
        self.create_fields(app_token, table_id)

        # 保存到 .env
        self._save_env(env_path, app_token, table_id)
        return app_token, table_id

    def _save_env(self, env_path: str, app_token: str, table_id: str):
        """将飞书表格配置追加/更新到 .env 文件。"""
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                lines = f.readlines()

        updated_base = False
        updated_table = False
        for i, line in enumerate(lines):
            if line.startswith("FEISHU_BASE_TOKEN="):
                lines[i] = f"FEISHU_BASE_TOKEN={app_token}\n"
                updated_base = True
            elif line.startswith("FEISHU_TABLE_ID="):
                lines[i] = f"FEISHU_TABLE_ID={table_id}\n"
                updated_table = True

        if not updated_base:
            lines.append(f"FEISHU_BASE_TOKEN={app_token}\n")
        if not updated_table:
            lines.append(f"FEISHU_TABLE_ID={table_id}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)
        logger.info("✅ 飞书配置已保存到 .env")
