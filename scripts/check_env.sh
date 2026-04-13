#!/bin/bash
# 检查并安装 FunASR 依赖
set -e

echo "检查 FunASR 依赖..."
python3 -c "import funasr" 2>/dev/null && {
    echo "FunASR 已安装"
    exit 0
}

echo "安装 FunASR 及依赖（可能需要几分钟）..."
pip3 install -U funasr modelscope torch torchaudio
echo "安装完成"
