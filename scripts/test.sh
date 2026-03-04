#!/bin/bash
# test.sh — 运行 AutoC 自身测试套件
#
# 用法:
#   ./scripts/test.sh                # 运行全部单元测试
#   ./scripts/test.sh -k state       # 只跑 state 相关测试
#   ./scripts/test.sh --cov          # 含覆盖率报告
#   ./scripts/test.sh --integration  # 单元测试 + Mock Agent 集成诊断
#   ./scripts/test.sh --integration-only  # 仅跑 Mock Agent 集成诊断

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 激活虚拟环境
if [[ -d ".venv" ]]; then
    source .venv/bin/activate
fi

# 确保 pytest 已安装
if ! python -m pytest --version &>/dev/null; then
    echo "安装 pytest..."
    pip install pytest pytest-cov
fi

# 解析 --integration / --integration-only 参数
RUN_UNIT=true
RUN_INTEGRATION=false
PYTEST_ARGS=()

for arg in "$@"; do
    case "$arg" in
        --integration)
            RUN_INTEGRATION=true
            ;;
        --integration-only)
            RUN_UNIT=false
            RUN_INTEGRATION=true
            ;;
        *)
            PYTEST_ARGS+=("$arg")
            ;;
    esac
done

# 单元测试
if [[ "$RUN_UNIT" == true ]]; then
    echo "========================================"
    echo "  AutoC 单元测试"
    echo "========================================"
    python -m pytest "${PYTEST_ARGS[@]}"
fi

# Mock Agent 集成诊断（需要 Docker）
if [[ "$RUN_INTEGRATION" == true ]]; then
    echo ""
    echo "========================================"
    echo "  Mock Agent 集成诊断"
    echo "========================================"

    if ! docker info &>/dev/null; then
        echo "[SKIP] Docker 未运行，跳过集成诊断"
        exit 0
    fi

    DIAG_FAILED=0
    for case_name in hello calculator; do
        echo ""
        echo "--- 用例: ${case_name} ---"
        if python scripts/diagnose.py --case "$case_name" --mock-pm; then
            echo "[PASS] ${case_name}"
        else
            echo "[FAIL] ${case_name}"
            DIAG_FAILED=1
        fi
    done

    if [[ "$DIAG_FAILED" -ne 0 ]]; then
        echo ""
        echo "[ERROR] 集成诊断存在失败用例"
        exit 1
    fi

    echo ""
    echo "[OK] 集成诊断全部通过"
fi
