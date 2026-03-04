#!/bin/bash
# AutoC PM2 管理脚本

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

show_help() {
    cat << EOF
AutoC PM2 管理脚本
==================

用法: ./pm2-manage.sh [命令]

开发环境命令（后端 + 前端 Vite dev）:
    dev             启动完整开发环境
    dev:stop        停止开发环境
    dev:restart     重启开发环境
    dev:logs        查看开发环境日志
    dev:status      查看开发环境状态
    dev:delete      删除开发环境进程

生产环境命令（仅后端）:
    start       启动 AutoC Web 服务
    stop        停止服务
    restart     重启服务
    reload      重载服务（零停机）

通用命令:
    status      查看所有服务状态
    logs        查看实时日志
    logs:err    查看错误日志
    logs:out    查看输出日志
    monit       打开 PM2 监控面板
    list        列出所有 PM2 进程
    delete      删除生产服务（完全清理）
    flush       清空日志文件
    info        显示详细信息

示例:
    ./pm2-manage.sh dev           # 启动开发环境
    ./pm2-manage.sh dev:logs      # 查看开发日志
    ./pm2-manage.sh dev:stop      # 停止开发环境
    ./pm2-manage.sh start         # 启动生产服务

EOF
}

check_pm2() {
    if ! command -v pm2 &> /dev/null; then
        echo -e "${RED}错误: 未安装 pm2${NC}"
        echo "请运行: npm install -g pm2"
        exit 1
    fi
}

check_venv() {
    if [ ! -d ".venv" ]; then
        echo -e "${RED}错误: 虚拟环境不存在${NC}"
        echo "请先运行: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
}

case "$1" in
    # ── 开发环境（后端 + 前端 Vite dev）──────────────────────────────
    dev)
        check_pm2
        check_venv
        # PM2 不支持路径含空格，使用 ~/.autoc 软链接绕过
        if [ ! -L "$HOME/.autoc" ]; then
            echo -e "${YELLOW}创建软链接 ~/.autoc → $PROJECT_DIR${NC}"
            ln -sfn "$PROJECT_DIR" "$HOME/.autoc"
        fi
        echo -e "${GREEN}正在启动开发环境（后端 + 前端）...${NC}"
        mkdir -p "$PROJECT_DIR/logs"
        pm2 start "$PROJECT_DIR/scripts/ecosystem.dev.config.js"
        pm2 save
        echo -e "${GREEN}✓ 开发环境已启动${NC}"
        echo "  后端 API : http://localhost:8080"
        echo "  前端 UI  : http://localhost:3000"
        echo "  查看日志 : ./pm2-manage.sh dev:logs"
        ;;

    dev:stop)
        check_pm2
        echo -e "${YELLOW}正在停止开发环境...${NC}"
        pm2 stop autoc-backend autoc-frontend 2>/dev/null || pm2 stop ecosystem.dev.config.js 2>/dev/null || true
        echo -e "${GREEN}✓ 开发环境已停止${NC}"
        ;;

    dev:restart)
        check_pm2
        echo -e "${YELLOW}正在重启开发环境...${NC}"
        pm2 restart autoc-backend autoc-frontend
        echo -e "${GREEN}✓ 开发环境已重启${NC}"
        ;;

    dev:logs)
        check_pm2
        echo -e "${GREEN}开发环境日志（按 Ctrl+C 退出）${NC}"
        pm2 logs autoc-backend autoc-frontend
        ;;

    dev:status)
        check_pm2
        pm2 status autoc-backend autoc-frontend
        ;;

    dev:delete)
        check_pm2
        echo -e "${RED}正在删除开发环境进程...${NC}"
        pm2 delete autoc-backend autoc-frontend 2>/dev/null || true
        pm2 save --force
        echo -e "${GREEN}✓ 开发环境进程已删除${NC}"
        ;;

    # ── 生产环境（仅后端）────────────────────────────────────────────
    start)
        check_pm2
        check_venv
        if [ ! -L "$HOME/.autoc" ]; then
            echo -e "${YELLOW}创建软链接 ~/.autoc → $PROJECT_DIR${NC}"
            ln -sfn "$PROJECT_DIR" "$HOME/.autoc"
        fi
        echo -e "${GREEN}正在启动 AutoC Web 服务（生产）...${NC}"
        mkdir -p "$PROJECT_DIR/logs"
        pm2 start "$PROJECT_DIR/scripts/ecosystem.config.js"
        pm2 save
        echo -e "${GREEN}✓ 服务已启动${NC}"
        echo "访问: http://localhost:8080"
        echo "查看日志: ./pm2-manage.sh logs"
        ;;

    stop)
        check_pm2
        echo -e "${YELLOW}正在停止服务...${NC}"
        pm2 stop autoc-web
        echo -e "${GREEN}✓ 服务已停止${NC}"
        ;;

    restart)
        check_pm2
        echo -e "${YELLOW}正在重启服务...${NC}"
        pm2 restart autoc-web
        echo -e "${GREEN}✓ 服务已重启${NC}"
        ;;

    reload)
        check_pm2
        echo -e "${YELLOW}正在重载服务（零停机）...${NC}"
        pm2 reload autoc-web
        echo -e "${GREEN}✓ 服务已重载${NC}"
        ;;

    # ── 通用命令 ─────────────────────────────────────────────────────
    status)
        check_pm2
        pm2 list
        ;;

    logs)
        check_pm2
        echo -e "${GREEN}实时日志（按 Ctrl+C 退出）${NC}"
        pm2 logs
        ;;

    logs:err)
        check_pm2
        echo -e "${RED}错误日志${NC}"
        pm2 logs --err --lines 100
        ;;

    logs:out)
        check_pm2
        echo -e "${GREEN}输出日志${NC}"
        pm2 logs --out --lines 100
        ;;

    monit)
        check_pm2
        echo -e "${GREEN}打开 PM2 监控面板${NC}"
        pm2 monit
        ;;

    list)
        check_pm2
        pm2 list
        ;;

    delete)
        check_pm2
        echo -e "${RED}正在删除生产服务...${NC}"
        pm2 delete autoc-web
        pm2 save --force
        echo -e "${GREEN}✓ 服务已删除${NC}"
        ;;

    flush)
        check_pm2
        echo -e "${YELLOW}正在清空日志...${NC}"
        pm2 flush
        echo -e "${GREEN}✓ 日志已清空${NC}"
        ;;

    info)
        check_pm2
        pm2 info autoc-web
        ;;

    help|--help|-h|"")
        show_help
        ;;

    *)
        echo -e "${RED}错误: 未知命令 '$1'${NC}"
        echo "运行 './pm2-manage.sh help' 查看帮助"
        exit 1
        ;;
esac
