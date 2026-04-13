# claude-skill-douyin

Claude Code skill: 抖音视频解析、博主视频抓取/转录/AI运营分析、写入飞书多维表格。

## 功能

- **douyin:fetch** — 抓取博主视频 → 本地 FunASR 转录 → AI 运营分析 → 写入飞书
  - 支持全量抓取（`--all` 自动翻页）
  - 分批转录+写入（每 20 条一批，崩溃可续跑）
  - 自动去重（基于视频 ID）
- **douyin:parse** — 解析单个抖音视频（链接/分享文本 → 元数据 + 转录）

## AI 运营分析维度

每条视频转录后，Claude 自动分析 7 个维度：

| 维度 | 说明 |
|------|------|
| 脚本类型 | 聊观点 / 晒过程 / 讲故事 / 教知识 |
| 爆款元素 | 成本 / 人群 / 奇葩 / 头牌 / 最差 / 反差 / 怀旧 / 荷尔蒙 |
| 情绪波动点 | 文案中情绪变化曲线 |
| 画面感 | 1-10 分 + 原因 |
| 力量感 | 1-10 分 + 原因 |
| 人设类型 | 崇拜者 / 教导者 / 分享者 / 陪伴者 / 衬托者 / 搞笑者 |
| 运营建议 | 一句话改进建议 |

## 安装

```bash
# 1. Clone 到本地
git clone https://github.com/ballbasecn-star/claude-skill-douyin.git
cd claude-skill-douyin

# 2. 创建 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 安装 FunASR 模型（首次需要下载）
# 模型会在首次运行时自动下载

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入飞书应用和 SiliconFlow API 配置

# 5. 设置抖音 Cookie
.venv/bin/python scripts/cli.py cookie set "你的Cookie字符串"

# 6. 链接到 Claude Code skills 目录
ln -s $(pwd) ~/.claude/skills/douyin
```

## 使用

安装后在 Claude Code 中自然语言触发：

```
"抓取这个博主的视频 https://v.douyin.com/xxx/"
"解析这个抖音视频 [分享文本]"
```

或直接运行 CLI：

```bash
PYTHON=".venv/bin/python"

# 抓取最新 20 条视频
$PYTHON scripts/cli.py fetch "博主主页链接"

# 抓取全部视频
$PYTHON scripts/cli.py fetch "博主主页链接" --all

# 仅抓取不转录
$PYTHON scripts/cli.py fetch "博主主页链接" --no-transcript

# 解析单个视频
$PYTHON scripts/cli.py parse "分享文本或链接"
```

## 前置条件

1. **飞书应用**: 自建应用，开通 `bitable:app` 权限
2. **SiliconFlow API Key**: 用于 AI 分析（[申请地址](https://siliconflow.cn)）
3. **抖音 Cookie**: 需要有效的登录 Cookie
4. **FunASR**: 本地语音转录模型（pip 安装，约 2GB）

## License

MIT
