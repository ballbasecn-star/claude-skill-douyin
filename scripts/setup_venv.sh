#!/bin/bash
# 创建虚拟环境并安装依赖
set -e

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$SKILL_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    echo "虚拟环境已存在: $VENV_DIR"
else
    echo "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "安装依赖..."
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q -r "$SKILL_DIR/requirements.txt"

echo ""
echo "✅ 环境准备完成"
echo "   Python: $VENV_DIR/bin/python"
echo "   CLI:    $VENV_DIR/bin/python $SKILL_DIR/scripts/cli.py"
