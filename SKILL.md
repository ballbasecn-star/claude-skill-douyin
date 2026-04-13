---
name: douyin
description: |
  抖音视频解析、博主视频抓取/转录/运营分析/写入飞书。
  触发词：解析抖音、抖音视频、抓取视频、博主视频、创作者视频、douyin、抖音解析、飞书多维表格
  子命令：
    douyin:fetch - 抓取博主最新视频 → 本地转录 → AI运营分析 → 直写飞书多维表格
    douyin:parse - 解析单个抖音短视频（链接/分享文本 → 元数据 + 转录）
---

# 抖音解析 & 飞书写入

> 抓取博主视频，分批本地转录 + AI运营分析后写入飞书多维表格。

## 环境发现

每次执行前确认虚拟环境：

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"
CLI="$SKILL_DIR/scripts/cli.py"

test -f "$CLI" || echo "ERROR: 请先运行 bash $SKILL_DIR/scripts/setup_venv.sh"
```

---

## 子命令：`douyin:fetch` — 抓取博主视频 → 转录 → AI分析 → 写飞书

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

# JSON 输出
$PYTHON "$CLI" fetch "博主主页链接" --json
```

### 流程（分批处理）

```
解析博主链接 → 获取 stable_user_id
  ↓
调用抖音 API 抓取视频元数据（支持 --all 自动翻页获取全量）
  ↓
查询飞书已有记录 → 去重 → 得到待处理列表
  ↓
【分批转录+写入】每 20 条为一批：
  ├─ 逐条提取音频 → 本地 FunASR Paraformer 转录
  ├─ 批量写入飞书多维表格
  └─ 上传封面图片
  → 本批完成后自动处理下一批
  → 中途崩溃可重新运行，已写入的自动跳过
  ↓
【分批AI分析】由 Claude 手动执行（见下方）
```

### 分批策略

| 步骤 | 批次大小 | 断点续传 |
|------|---------|---------|
| 视频元数据抓取 | 20条/页，翻页获取 | 通过 seen_ids 去重 |
| 转录 + 写入飞书 | 20条/批 | 通过 query_existing_video_ids 自动跳过已写入 |
| AI运营分析 | 10条/批 | 通过查询"无运营建议"记录自动续跑 |

---

### 【关键】AI 运营分析步骤（由 Claude 手动分批执行）

fetch 命令完成后，**必须**分批执行 AI 运营分析。每批处理 10 条：

#### 批量分析流程

```
1. 查询飞书中"有转录文案但无运营建议"的记录（最多取 10 条）
2. 对每条记录，Claude 读取标题+转录文案，分析 7 个维度
3. 批量将分析结果写回飞书
4. 重复步骤 1-3，直到所有记录分析完成
```

#### 查询待分析记录的代码

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"

# 查询需要AI分析的记录（有转录文案、无运营建议）
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

# 搜索有转录文案但无运营建议的记录
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

# 取前10条作为本批
batch = all_records[:10]
print(json.dumps({"total_pending": len(all_records), "this_batch": len(batch), "records": batch}, ensure_ascii=False, indent=2))
PYEOF
```

#### 分析维度与标准（基于7980陪跑课三大体系）

**1. 脚本类型**（单选：聊观点/晒过程/讲故事/教知识）
- 聊观点：表达立场观点，"有观点才有真粉丝"，适合强化个人IP
- 晒过程：展示做事过程，适合直接转化变现，常见问题是变成流水账
- 讲故事：讲述经历故事，"小有成就"四段结构（成果→困境→转机→感悟）
- 教知识：教授干货知识，涨粉利器，"信息多、效果快、料够猛"

**2. 爆款元素**（多选：成本/人群/奇葩/头牌/最差/反差/怀旧/荷尔蒙/无）
- 成本：与钱相关，花小钱干大事，门槛越低越容易爆
- 人群：精准人群定位，如"宝妈产后3个月"
- 奇葩：超出常规认知，如"2000个易拉罐做裙子"
- 头牌：蹭名人/IP流量，如"迪丽热巴同款"
- 最差：突出最差的方面，如"贬值最快的小区"
- 反差：反转操作、身份互换，如"带大爷做脏辫"
- 怀旧：回忆过去，如"1996年十大金曲"
- 荷尔蒙：与魅力/吸引力相关

**3. 情绪波动点**（文本：描述文案中关键情绪变化）
- 识别文案中的情绪曲线：回忆、行动号召、分析、困境、转机、感动、焦虑等
- 关键原则："能制造用户的情绪曲线，而不是一条水平线"

**4. 画面感**（文本：评分1-10 + 原因）
- "写文案=说画面"——文案是否有具体场景和视觉描述
- 高分标志：具体时间、地点、动作、感官描写
- 低分标志：纯抽象说教、没有场景

**5. 力量感**（文本：评分1-10 + 原因）
- 观点强度：是否有明确立场，还是模棱两可
- 情感冲击：是否触发用户共鸣
- 行动号召力：是否有明确的行动指引

**6. 人设类型**（单选：崇拜者/教导者/分享者/陪伴者/衬托者/搞笑者）
- 崇拜者：通过个人魅力吸引
- 教导者：行业专家身份
- 分享者：擅长某事但不以专家自居
- 陪伴者：与观众一起成长
- 衬托者：刻意展示弱点/不足
- 搞笑者：以幽默为主

**7. 运营建议**（文本：一句话改进建议）
- 基于以上分析，给出具体可操作的优化建议
- 参考方向：开头3秒钩子、情绪曲线优化、爆款元素植入、人设强化等

#### 更新飞书记录的代码模板

```bash
SKILL_DIR="/Users/apple/.claude/skills/douyin"
PYTHON="$SKILL_DIR/.venv/bin/python"

# 更新单条记录的分析字段
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

# 更新记录
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

### 前置条件

1. **Cookie**: 需要有效的抖音 Cookie（`cli.py cookie set "Cookie值"`）
2. **飞书应用**: .env 中配置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`（自建应用，开通 `bitable:app` 权限）
3. **转录**: 本地 FunASR Paraformer 模型（已安装）

### 首次 vs 增量

| 场景 | 操作 |
|------|------|
| 首次（无飞书表格） | 自动创建多维表格 + 字段 → 写入数据 → AI分析 |
| 增量（已有表格） | 查已有 video_id 去重 → 仅写入新视频 → AI分析新视频 |
| 中断恢复 | 重新运行同一命令，已写入的自动跳过 |

---

## 子命令：`douyin:parse` — 解析单个抖音视频

### 触发场景

- "解析这个抖音视频"、"这个视频讲了什么"
- 用户提供抖音分享文本或链接

### 执行命令

```bash
# 基本信息 + 转录
$PYTHON "$CLI" "分享文本或链接"

# 仅基本信息
$PYTHON "$CLI" --no-transcript "分享文本"

# JSON 输出
$PYTHON "$CLI" --json "分享文本"
```

---

## Cookie 管理

```bash
# 设置 Cookie
$PYTHON "$CLI" cookie set "你的Cookie字符串"

# 查看 Cookie 状态
$PYTHON "$CLI" cookie show
```

---

## 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 抓取失败 | Cookie 过期 | `$PYTHON "$CLI" cookie set "新Cookie"` |
| 飞书写入失败 | 应用未配置 | 检查 .env 中 FEISHU_APP_ID/SECRET |
| 飞书权限不足 | 应用权限未开通 | 开通 bitable:app 权限并发布新版本 |
| 转录失败 | FunASR 未安装 | 运行 `pip install funasr modelscope torch torchaudio` |
| 封面上传失败 | 图片 URL 失效 | 不影响数据写入，封面可后补 |
| AI分析失败 | 飞书读取权限不足 | 开通 bitable:app 权限 |
