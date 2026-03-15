#!/usr/bin/env bash
#
# bump-version.sh — 统一更新项目版本号
#
# 用法：
#   ./scripts/bump-version.sh 0.6.0
#
# 会更新：
#   1. VERSION                     （唯一来源）
#   2. frontend/package.json       （npm 版本）
#   3. frontend/package-lock.json  （lock 文件）
#   4. electron/package.json       （桌面端版本）
#
# Python 侧无需更新 —— pyproject.toml 通过 dynamic version 直接读取 VERSION 文件，
# main.py 通过 importlib.metadata 读取已安装包版本。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ $# -ne 1 ]; then
    echo "用法: $0 <version>"
    echo "示例: $0 0.6.0"
    exit 1
fi

NEW_VERSION="$1"

# 校验版本格式（semver）
if ! echo "$NEW_VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
    echo "错误: 版本号格式不正确，需要 semver 格式（如 0.6.0 或 1.0.0-beta.1）"
    exit 1
fi

echo "升级版本 → $NEW_VERSION"
echo ""

# 1. VERSION 文件
echo "$NEW_VERSION" > "$ROOT_DIR/VERSION"
echo "  ✓ VERSION"

# 2. frontend/package.json
if [ -f "$ROOT_DIR/frontend/package.json" ]; then
    sed -i.bak "s/\"version\": \"[^\"]*\"/\"version\": \"$NEW_VERSION\"/" "$ROOT_DIR/frontend/package.json"
    rm -f "$ROOT_DIR/frontend/package.json.bak"
    echo "  ✓ frontend/package.json"
fi

# 3. frontend/package-lock.json（顶层两处）
if [ -f "$ROOT_DIR/frontend/package-lock.json" ]; then
    # 只更新文件头部的 name+version 和 packages[""] 中的 version
    python3 -c "
import json, sys
with open('$ROOT_DIR/frontend/package-lock.json', 'r') as f:
    data = json.load(f)
data['version'] = '$NEW_VERSION'
if '' in data.get('packages', {}):
    data['packages']['']['version'] = '$NEW_VERSION'
with open('$ROOT_DIR/frontend/package-lock.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"
    echo "  ✓ frontend/package-lock.json"
fi

# 4. electron/package.json
if [ -f "$ROOT_DIR/electron/package.json" ]; then
    sed -i.bak "s/\"version\": \"[^\"]*\"/\"version\": \"$NEW_VERSION\"/" "$ROOT_DIR/electron/package.json"
    rm -f "$ROOT_DIR/electron/package.json.bak"
    echo "  ✓ electron/package.json"
fi

echo ""
echo "完成！所有版本已更新为 $NEW_VERSION"
echo ""
echo "Python 侧会自动生效（重新 pip install -e . 后）"
