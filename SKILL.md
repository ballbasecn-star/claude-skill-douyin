---
name: douyin
description: |
  抖音视频解析、博主视频抓取/转录/运营分析/写入飞书。
  触发词：解析抖音、抖音视频、抓取视频、博主视频、创作者视频、douyin、抖音解析、飞书多维表格
  子命令：
    douyin:fetch - 抓取博主最新视频 → 本地转录 → AI运营分析 → 直写飞书多维表格
    douyin:parse - 解析单个抖音短视频（链接/分享文本 → 元数据 + 转录）
---

# 抖音解析 & 飞书写入 Skill

> 抓取博主视频，本地 FunASR 转录 + AI 运营分析，写入飞书多维表格。

---

## 目录

- [整体架构](#整体架构)
- [环境与安装](#环境与安装)
- [配置说明](#配置说明)
- [子命令：fetch — 抓取博主视频](#子命令fetch--抓取博主视频)
- [子命令：parse — 解析单个视频](#子命令parse--解析单个视频)
- [Cookie 管理](#cookie-管理)
- [转录管线详解](#转录管线详解)
- [飞书多维表格结构](#飞书多维表格结构)
- [AI 运营分析](#ai-运营分析)
- [项目文件结构](#项目文件结构)
- [故障排查](#故障排查)

---

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    CLI 入口 (cli.py)                      │
│                                                          │
│   fetch 命令              parse 命令          cookie 命令  │
└──────┬──────────────────────┬────────────────────┬───────┘
       │                      │                    │
       ▼                      ▼                    ▼
┌──────────────────┐  ┌───────────────┐  ┌────────────────┐
│ fetch_to_feishu  │  │ video_fetch   │  │  cookie_store  │
│   (核心编排)      │  │  _service     │  │  (JSON 持久化)  │
└──────┬───────────┘  └───────┬───────┘  └────────────────┘
       │                      │
       │    ┌─────────────────┤
       │    │                 │
       ▼    ▼                 ▼
┌──────────────┐     ┌────────────────┐
│ douyin_web   │     │ douyin_link    │
│  _client     │     │  _utils        │
│ (API+签名)   │     │ (链接标准化)    │
└──────┬───────┘     └────────────────┘
       │
       ▼
┌────────────────┐
│ douyin_        │
│  signature     │
│ (ABogus 签名)  │
└────────────────┘

       │                      fetch 专属组件
       │    ┌─────────────┬───────────────┐
       ▼    ▼             ▼               ▼
┌────────────┐  ┌──────────────┐  ┌──────────────┐
│ media_tools│  │ feishu_      │  │  domain      │
│ (音频提取)  │  │  client      │  │ (VideoInfo)  │
└────────────┘  │ (飞书API)     │  └──────────────┘
                └──────────────┘
```

### 核心数据流

```
用户输入博主链接
       │
       ▼
  链接标准化 (douyin_link_utils)
       │
       ▼
  解析重定向 → 提取 stable_user_id (douyin_web_client)
       │
       ▼
  翻页调用抖音 API 获取视频元数据 (douyin_web_client + ABogus 签名)
       │
       ▼
  解析为 VideoInfo 对象 (video_fetch_service + domain)
       │
       ▼
  查询飞书已有记录 → 去重 (feishu_client)
       │
       ▼
  ┌────────── 分批循环 (20条/批) ──────────┐
  │                                        │
  │  逐条：提取音频 → FunASR 转录 → 清理    │
  │           │                            │
  │           ▼                            │
  │  批量写入飞书多维表格                     │
  │           │                            │
  │           ▼                            │
  │  逐条上传封面图片                        │
  │                                        │
  └────────────────────────────────────────┘
       │
       ▼
  AI 运营分析 (Claude 分批执行，10条/批)
```

---

## 环境与安装

### 前置依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| Python 3.9+ | 运行环境 | 系统自带或 pyenv |
| ffmpeg | 音频提取 | `brew install ffmpeg` |
| FunASR | 本地语音转录 | pip (已包含在 venv) |

### 虚拟环境

每次执行前确认虚拟环境：

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"
CLI="$SKILL_DIR/scripts/cli.py"

test -f "$CLI" || echo "ERROR: 请先运行 bash $SKILL_DIR/scripts/setup_venv.sh"
```

### Python 依赖

主要 Python 包（已安装在 `.venv` 中）：

| 包 | 用途 |
|---|------|
| funasr | 本地 FunASR Paraformer ASR 模型 |
| modelscope | 模型下载与缓存 |
| torch / torchaudio | 模型推理后端 |
| requests | HTTP 请求 |
| python-dotenv | 环境变量管理 |

---

## 配置说明

配置文件位于 `$SKILL_DIR/.env`：

```bash
# 抖音 API（转录用，目前 fetch 使用本地 FunASR）
SILICONFLOW_API_KEY=sk-xxx        # SiliconFlow API Key（parse 云端转录用）
GROQ_API_KEY=                     # Groq API Key（parse 云端转录用，可选）

# 飞书应用（自建应用，需开通 bitable:app 权限）
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=xxxx

# 飞书多维表格（首次 fetch 自动创建后填充，也可手动指定）
FEISHU_BASE_TOKEN=xxxx
FEISHU_TABLE_ID=xxxx
```

### 飞书应用权限

自建飞书应用需要开通以下权限：
- `bitable:app` — 多维表格读写权限

### Cookie

抖音 API 需要有效的登录 Cookie：

```bash
# 设置 Cookie
$PYTHON "$CLI" cookie set "你的Cookie字符串"

# 查看 Cookie 状态
$PYTHON "$CLI" cookie show
```

Cookie 保存在 `$SKILL_DIR/cookie_data/douyin_cookie.json`，包含来源、时间戳等元信息。

---

## 子命令：fetch — 抓取博主视频

### 触发场景

- "抓取这个博主的视频"、"把这个博主的视频导入飞书"
- 用户提供抖音博主主页链接

### 执行命令

```bash
# 一键抓取最新 20 条 + 转录 + 写飞书（默认）
$PYTHON "$CLI" fetch "博主主页链接"

# 仅抓取不转录
$PYTHON "$CLI" fetch "博主主页链接" --no-transcript

# 抓取更多（如 50 条）
$PYTHON "$CLI" fetch "博主主页链接" --count 50

# 抓取博主全部视频（自动翻页）
$PYTHON "$CLI" fetch "博主主页链接" --all

# JSON 输出（机器可读）
$PYTHON "$CLI" fetch "博主主页链接" --json

# 详细日志
$PYTHON "$CLI" fetch "博主主页链接" -v
```

### 完整流程

```
Step 1: 解析博主身份
  ├─ 输入：用户粘贴的分享文本（如 "长按复制此条消息...https://v.douyin.com/xxx/"）
  ├─ normalize_creator_source_url() → 提取链接，去除尾随标点
  ├─ resolve_redirect_url() → 跟随短链接重定向，获取最终 URL
  └─ extract_stable_user_id() → 从 URL 中提取 sec_user_id

Step 2: 确保飞书表格
  ├─ 读取 .env 中的 FEISHU_BASE_TOKEN + FEISHU_TABLE_ID
  ├─ 已有 → 直接使用
  └─ 无 → 自动创建多维表格 + 17个预定义字段 → 保存到 .env

Step 3: 抓取视频元数据（自动翻页）
  ├─ 调用抖音 POST_LIST_API，每页 20 条
  ├─ ABogus 签名防爬
  ├--all 参数时持续翻页直到 has_more=0
  ├─ 每页间隔 1.5 秒（防限流）
  └─ 通过 seen_ids 集合去重

Step 4: 过滤已存在记录
  ├─ query_existing_video_ids() → 分页查询飞书已有记录
  ├─ 对比 video_id 集合
  └─ 得到待处理列表 (todo_items)

Step 5: 分批转录 + 写入飞书（20条/批）
  │
  ┌─ 对每条视频：
  │   ├─ get_video_download_url() → 提取无水印视频下载链接
  │   ├─ extract_audio_from_url() → ffmpeg 直接提取音频流（不下载视频）
  │   │   ├─ 参数：16kHz 采样率，单声道，64kbps MP3
  │   │   └─ 超时：120 秒
  │   ├─ _transcribe_audio() → FunASR 转录（详见转录管线）
  │   │   ├─ Paraformer Large ASR + FSMN VAD
  │   │   ├─ _clean_transcript() → 去除字符间空格
  │   │   └─ 标点恢复模型 → 添加逗号句号等标点
  │   └─ 临时音频文件自动清理
  │
  ├─ 批量写入飞书（batch_create_records，最多 500 条/次）
  ├─ 刷新飞书 token（长时间运行可能过期）
  ├─ 逐条上传封面图片（download → upload_all API → file_token → 更新附件字段）
  └─ 批次间等待 2 秒（API 频率限制）

Step 6: AI 运营分析（由 Claude 分批手动执行）
  └─ 详见下方 AI 运营分析章节
```

### 分批策略

| 步骤 | 批次大小 | 断点续传机制 |
|------|---------|------------|
| 视频元数据抓取 | 20条/页，翻页获取 | seen_ids 集合去重 |
| 转录 + 写入飞书 | 20条/批 | query_existing_video_ids 自动跳过已写入 |
| AI 运营分析 | 10条/批 | 查询"无运营建议"记录自动续跑 |

### 首次 vs 增量

| 场景 | 行为 |
|------|------|
| 首次（无飞书表格） | 自动创建多维表格 + 17个字段 → 写入数据 → AI分析 |
| 增量（已有表格） | 查已有 video_id 去重 → 仅写入新视频 → AI分析新视频 |
| 中断恢复 | 重新运行同一命令，已写入的自动跳过 |

### fetch 输出示例

```
🔍 开始抓取博主视频 (数量: 全部)...

博主: 林克的AI运营局
获取: 11 条 | 新增: 11 条 | 跳过: 0 条
封面: 11 个
```

JSON 模式输出：

```json
{
  "author": "林克的AI运营局",
  "total_fetched": 11,
  "new_records": 11,
  "skipped": 0,
  "covers_uploaded": 11,
  "remaining": 0
}
```

---

## 子命令：parse — 解析单个视频

### 触发场景

- "解析这个抖音视频"、"这个视频讲了什么"
- 用户提供抖音分享文本或链接

### 执行命令

```bash
# 基本信息 + 转录
$PYTHON "$CLI" parse "分享文本或链接"

# 仅基本信息（不转录）
$PYTHON "$CLI" parse --no-transcript "分享文本"

# JSON 输出
$PYTHON "$CLI" parse --json "分享文本"

# 云端转录（SiliconFlow SenseVoiceSmall）
$PYTHON "$CLI" parse --cloud --cloud-provider siliconflow "分享文本"

# 云端转录（Groq Whisper）
$PYTHON "$CLI" parse --cloud --cloud-provider groq "分享文本"

# 本地 Whisper 转录（指定模型大小）
$PYTHON "$CLI" parse --model large-v3 "分享文本"
```

### 解析流程

```
1. 从分享文本中提取短链接或完整链接
   ├─ 匹配 https://v.douyin.com/xxx（短链接）
   └─ 匹配 https://www.douyin.com/video/xxx（完整链接）

2. 获取 aweme_id
   ├─ 从完整链接直接提取 /video/(\d+)
   └─ 短链接跟随重定向获取

3. 调用抖音详情 API（ABogus 签名）

4. 解析返回数据为 VideoInfo 对象
   ├─ 标题、作者、时长、发布时间
   ├─ 播放量、点赞数、评论数、分享数、收藏数
   ├─ 封面 URL、分享链接
   └─ 话题标签

5. 转录（可选）
   ├--no-transcript → 跳过
   ├─ 默认：本地 faster-whisper
   ├--cloud → 云端 API（SiliconFlow 或 Groq）
   └─ 本地 FunASR 仅 fetch 命令使用
```

### 输出示例

```
============================================================
📹 抖音视频信息
============================================================

📌 标题: 00后程序员从北京回县城...
👤 作者: 林克的AI运营局 (@xxx)
🔗 视频ID: 7xxxxxxxxxxxxx
⏱️  时长: 01:03
📅 发布时间: 2026-04-10 12:00:00

📊 数据: ▶️ 10,000 | ❤️ 500 | 💬 30 | 🔄 10 | ⭐ 20

🏷️  标签: #AI运营 #短视频运营 #程序员转型

📝 视频描述:
----------------------------------------
视频标题文案...
----------------------------------------

🎙️  视频内完整文案 (语音转录):
========================================
转录后的完整文案...
========================================

🖼️  封面: https://...
🔗 链接: https://www.douyin.com/video/xxx

============================================================
```

---

## Cookie 管理

Cookie 用于访问抖音 Web API，是数据抓取的前置条件。

### Cookie 获取方式

1. 打开 Chrome 浏览器，访问 `https://www.douyin.com`
2. 登录抖音账号
3. F12 打开开发者工具 → Network 标签
4. 刷新页面，找到任意请求
5. 复制请求头中的 `Cookie` 值

### Cookie 命令

```bash
# 设置 Cookie
$PYTHON "$CLI" cookie set "你的Cookie字符串"

# 查看 Cookie 状态（来源、更新时间、长度）
$PYTHON "$CLI" cookie show
```

### Cookie 存储

- 存储位置：`$SKILL_DIR/cookie_data/douyin_cookie.json`
- 格式：JSON，包含 cookie 值、来源（manual/auto）、时间戳
- Cookie 过期后需重新设置

---

## 转录管线详解

fetch 命令使用本地 FunASR 模型进行语音转录，管线分为三步：

### 三步转录管线

```
原始音频 (.mp3, 16kHz, 单声道)
       │
       ▼
Step 1: ASR 语音识别
  ├─ 模型：iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch
  ├─ VAD：iic/speech_fsmn_vad_zh-cn-16k-common-pytorch（语音活动检测）
  ├─ 输入：音频文件路径
  ├─ 参数：batch_size_s=300（按音频时长分批）
  └─ 输出：带空格的原始文本（每个字之间有空格）
       │
       ▼
Step 2: 文本清理 (_clean_transcript)
  ├─ 去除中文字符之间的空格（多轮迭代）
  │   "一 个 写 了" → "一个写了"
  ├─ 去除中文与英文/数字之间的多余空格
  │   "AI 工 具" → "AI工具"
  └─ 保留英文单词间空格和标点
       │
       ▼
Step 3: 标点恢复
  ├─ 模型：iic/punc_ct-transformer_cn-en-common-vocab471067-large
  ├─ 输入：清理后的连续文本
  └─ 输出：带标点的最终文本
       │
       ▼
最终转录文案（带标点、无多余空格）
```

### 为什么标点模型单独调用

FunASR AutoModel 的 `pnc_model` 参数对 `seaco_paraformer_large` 模型不生效。原因：

1. VAD 将音频分割为多个段落
2. AutoModel 内部用空格拼接段落（`auto_model.py` 第570行）
3. `seaco_paraformer_large` 输出是字符级文本（每字之间有空格）
4. 标点模型接收到的输入是"空格分隔的字符流"，无法正确处理

解决方案：ASR 完成后先清理空格，再将干净文本传给标点模型。

### 模型缓存

FunASR 模型缓存在 `~/.cache/modelscope/hub/models/` 目录下：
- `iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch/` — ASR 模型
- `iic/speech_fsmn_vad_zh-cn-16k-common-pytorch/` — VAD 模型
- `iic/punc_ct-transformer_cn-en-common-vocab471067-large/` — 标点模型

首次运行时会自动从 ModelScope 下载，后续使用缓存。

---

## 飞书多维表格结构

### 表格字段定义

共 17 个字段，分为三组：

#### 基础数据字段（fetch 自动写入）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 视频ID | Text | 去重主键（aweme_id） |
| 封面 | Attachment | 视频封面图片 |
| 标题 | Text | 视频标题/文案 |
| 作者 | Text | 作者昵称 |
| 发布时间 | DateTime | 视频发布时间（毫秒时间戳） |
| 时长 | Text | 格式化时长 mm:ss |
| 播放量 | Number | 播放次数 |
| 点赞数 | Number | 点赞次数 |
| 评论数 | Number | 评论次数 |
| 转录文案 | Text | 语音转录的完整文案 |
| 视频链接 | URL | 可点击的视频链接 |

#### AI 分析字段（Claude 手动写入）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 脚本类型 | SingleSelect | 聊观点/晒过程/讲故事/教知识 |
| 爆款元素 | MultiSelect | 成本/人群/奇葩/头牌/最差/反差/怀旧/荷尔蒙/无 |
| 情绪波动点 | Text | 关键情绪变化描述 |
| 画面感 | Text | 评分(1-10) + 原因 |
| 力量感 | Text | 评分(1-10) + 原因 |
| 人设类型 | SingleSelect | 崇拜者/教导者/分享者/陪伴者/衬托者/搞笑者 |
| 运营建议 | Text | 一句话改进建议 |

### 飞书 API 调用链

```
认证：POST /open-apis/auth/v3/tenant_access_token/internal
  → 获取 tenant_access_token（有效期 2 小时，自动续期）

创建表格：POST /open-apis/bitable/v1/apps
  → 返回 app_token + default_table_id

创建字段：POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/fields
  → 按 TABLE_FIELDS 定义逐个创建

查询去重：POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/search
  → 分页查询已有视频 ID（page_size=500）

批量写入：POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/batch_create
  → 每次最多 500 条

上传图片：POST /open-apis/drive/v1/medias/upload_all
  → 下载封面 → 上传 → 获取 file_token

更新附件：PUT /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/{id}
  → 将 file_token 写入封面字段

更新分析：PUT /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/{id}
  → 写入 AI 分析的 7 个维度字段
```

---

## AI 运营分析

fetch 命令完成后，**必须**由 Claude 分批执行 AI 运营分析。每批处理 10 条。

### 分析流程

```
1. 查询飞书中"有转录文案但无运营建议"的记录（最多取 10 条）
2. 对每条记录，Claude 读取标题 + 转录文案，分析 7 个维度
3. 批量将分析结果写回飞书对应记录
4. 重复步骤 1-3，直到所有记录分析完成
```

### 查询待分析记录

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"

$PYTHON << 'PYEOF'
import requests, json, os
from dotenv import load_dotenv
load_dotenv("$SKILL_DIR/.env")

app_id = os.getenv("FEISHU_APP_ID")
app_secret = os.getenv("FEISHU_APP_SECRET")
base_token = os.getenv("FEISHU_BASE_TOKEN")
table_id = os.getenv("FEISHU_TABLE_ID")

resp = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={
    "app_id": app_id, "app_secret": app_secret
})
token = resp.json()["tenant_access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

all_records = []
page_token = None
while True:
    params = {"page_size": 500}
    if page_token:
        params["page_token"] = page_token
    r = requests.post(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records/search",
        headers=headers, json={"filter": {"conjunction": "and", "conditions": []}},
        params=params, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        break
    for item in data.get("data", {}).get("items", []):
        f = item.get("fields", {})
        def extract(val):
            if isinstance(val, list):
                return "".join(x.get("text", "") for x in val if isinstance(x, dict))
            return str(val)
        has_transcript = bool(f.get("转录文案", ""))
        has_analysis = bool(f.get("运营建议", ""))
        if has_transcript and not has_analysis:
            all_records.append({
                "record_id": item["record_id"],
                "title": extract(f.get("标题", "")),
                "transcript": extract(f.get("转录文案", "")),
            })
    page_token = data.get("data", {}).get("page_token")
    if not page_token:
        break

batch = all_records[:10]
print(json.dumps({"total_pending": len(all_records), "this_batch": len(batch), "records": batch}, ensure_ascii=False, indent=2))
PYEOF
```

### 分析维度（基于7980陪跑课三大体系）

#### 1. 脚本类型（SingleSelect：聊观点/晒过程/讲故事/教知识）

- **聊观点**：表达立场观点，"有观点才有真粉丝"，适合强化个人 IP
- **晒过程**：展示做事过程，适合直接转化变现，常见问题是变成流水账
- **讲故事**：讲述经历故事，"小有成就"四段结构（成果→困境→转机→感悟）
- **教知识**：教授干货知识，涨粉利器，"信息多、效果快、料够猛"

#### 2. 爆款元素（MultiSelect：成本/人群/奇葩/头牌/最差/反差/怀旧/荷尔蒙/无）

- **成本**：与钱相关，花小钱干大事，门槛越低越容易爆
- **人群**：精准人群定位，如"宝妈产后3个月"
- **奇葩**：超出常规认知，如"2000个易拉罐做裙子"
- **头牌**：蹭名人/IP流量，如"迪丽热巴同款"
- **最差**：突出最差的方面，如"贬值最快的小区"
- **反差**：反转操作、身份互换，如"带大爷做脏辫"
- **怀旧**：回忆过去，如"1996年十大金曲"
- **荷尔蒙**：与魅力/吸引力相关

#### 3. 情绪波动点（Text）

识别文案中的情绪曲线：回忆、行动号召、分析、困境、转机、感动、焦虑等。
关键原则："能制造用户的情绪曲线，而不是一条水平线"。

#### 4. 画面感（Text：评分 1-10 + 原因）

"写文案=说画面"——文案是否有具体场景和视觉描述。
- 高分标志：具体时间、地点、动作、感官描写
- 低分标志：纯抽象说教、没有场景

#### 5. 力量感（Text：评分 1-10 + 原因）

- 观点强度：是否有明确立场，还是模棱两可
- 情感冲击：是否触发用户共鸣
- 行动号召力：是否有明确的行动指引

#### 6. 人设类型（SingleSelect：崇拜者/教导者/分享者/陪伴者/衬托者/搞笑者）

- **崇拜者**：通过个人魅力吸引
- **教导者**：行业专家身份
- **分享者**：擅长某事但不以专家自居
- **陪伴者**：与观众一起成长
- **衬托者**：刻意展示弱点/不足
- **搞笑者**：以幽默为主

#### 7. 运营建议（Text）

基于以上分析，给出具体可操作的优化建议。
参考方向：开头3秒钩子、情绪曲线优化、爆款元素植入、人设强化等。

### 更新飞书记录

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"

$PYTHON << 'PYEOF'
import requests, json, os
from dotenv import load_dotenv
load_dotenv("$SKILL_DIR/.env")

app_id = os.getenv("FEISHU_APP_ID")
app_secret = os.getenv("FEISHU_APP_SECRET")
base_token = os.getenv("FEISHU_BASE_TOKEN")
table_id = os.getenv("FEISHU_TABLE_ID")

resp = requests.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={
    "app_id": app_id, "app_secret": app_secret
})
token = resp.json()["tenant_access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

resp = requests.put(
    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records/{record_id}",
    headers=headers,
    json={"fields": {
        "脚本类型": "教知识",
        "爆款元素": "成本,人群",
        "情绪波动点": "...",
        "画面感": "7/10 - 原因...",
        "力量感": "8/10 - 原因...",
        "人设类型": "教导者",
        "运营建议": "建议..."
    }}
)
PYEOF
```

---

## 项目文件结构

```
.claude/skills/douyin/
├── .env                          # 环境变量配置（API Key、飞书凭证）
├── .gitignore                    # Git 忽略规则
├── .venv/                        # Python 虚拟环境
├── SKILL.md                      # Skill 定义 + 文档（本文件）
├── cookie_data/
│   └── douyin_cookie.json        # Cookie 持久化存储
└── scripts/
    ├── cli.py                    # CLI 入口（fetch/parse/cookie 三大命令）
    └── lib/
        ├── __init__.py
        ├── cookie_store.py       # Cookie 管理器（JSON 持久化）
        ├── domain.py             # VideoInfo 数据模型
        ├── douyin_link_utils.py  # 链接标准化处理
        ├── douyin_signature.py   # ABogus 签名生成
        ├── douyin_web_client.py  # 抖音 Web API 客户端
        ├── feishu_client.py      # 飞书多维表格 API 客户端
        ├── fetch_to_feishu.py    # fetch 核心编排（转录+写入管线）
        ├── media_tools.py        # ffmpeg 音频提取
        ├── settings.py           # 全局配置（路径常量）
        └── video_fetch_service.py # 单视频解析服务
```

### 各文件职责

| 文件 | 核心功能 |
|------|---------|
| `cli.py` | 命令行入口，解析参数并分派到 fetch/parse/cookie 处理函数 |
| `fetch_to_feishu.py` | fetch 核心编排：分页抓取 → 分批转录 → 写入飞书 → 上传封面 |
| `feishu_client.py` | 飞书 API 封装：认证、创建表格/字段、批量写入、上传图片、查询去重 |
| `video_fetch_service.py` | 单视频解析：提取链接 → 获取详情 → 解析为 VideoInfo |
| `douyin_web_client.py` | 抖音 API：详情/列表接口、短链接解析、ABogus 签名 |
| `douyin_signature.py` | ABogus 签名算法实现（反爬虫） |
| `douyin_link_utils.py` | 从分享文本中提取并标准化链接 |
| `media_tools.py` | ffmpeg 封装：从 URL 直接提取音频流、下载视频 |
| `domain.py` | VideoInfo 数据类：字段定义、格式化输出、序列化 |
| `cookie_store.py` | Cookie 管理：保存/读取/状态查询 |
| `settings.py` | 路径常量：SKILL_DIR、COOKIE_DIR |

---

## 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 抓取失败/返回空数据 | Cookie 过期 | `$PYTHON "$CLI" cookie set "新Cookie"` |
| 飞书写入失败 | 应用未配置 | 检查 .env 中 FEISHU_APP_ID/SECRET |
| 飞书权限不足 | 应用权限未开通 | 开通 bitable:app 权限并发布新版本 |
| 转录失败 | FunASR 未安装 | 运行 `pip install funasr modelscope torch torchaudio` |
| 转录无标点 | 标点模型未加载 | 检查 `~/.cache/modelscope/hub/` 下是否有 punc 模型 |
| 转录字符间有空格 | 清理函数未生效 | 确认 `_clean_transcript` 已在 `_transcribe_audio` 中调用 |
| 音频提取失败 | ffmpeg 未安装 | `brew install ffmpeg` |
| 封面上传失败 | 图片 URL 失效 | 不影响数据写入，封面可后补 |
| AI分析失败 | 飞书读取权限不足 | 开通 bitable:app 权限 |
| ABogus 签名失败 | 签名算法过期 | 需要更新 douyin_signature.py |
