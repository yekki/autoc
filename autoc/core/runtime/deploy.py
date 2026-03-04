"""一键部署 — Docker Compose 导出 + 部署脚本生成

个人项目场景下的轻量部署方案：
1. Docker Compose 导出：生成 Dockerfile + docker-compose.yml
2. 部署脚本生成：适配 Vercel / Railway 等平台
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("autoc.deploy")


def generate_dockerfile(workspace_dir: str, tech_stack: list[str] | None = None) -> str:
    """根据项目类型自动生成 Dockerfile"""
    tech = set(t.lower() for t in (tech_stack or []))
    files = set(os.listdir(workspace_dir))

    # Python 项目
    if "requirements.txt" in files or "pyproject.toml" in files or tech & {"python", "flask", "fastapi", "django"}:
        return _python_dockerfile(workspace_dir, tech)

    # Node.js 项目
    if "package.json" in files or tech & {"node", "react", "vue", "next.js"}:
        return _node_dockerfile(workspace_dir, tech)

    # Go 项目
    if "go.mod" in files or "go" in tech:
        return _go_dockerfile()

    # 静态 HTML
    if "index.html" in files:
        return _static_dockerfile()

    return _python_dockerfile(workspace_dir, tech)


def generate_compose(workspace_dir: str, project_name: str, port: int = 8000) -> str:
    """生成 docker-compose.yml"""
    return f"""version: '3.8'

services:
  {project_name}:
    build: .
    ports:
      - "{port}:{port}"
    environment:
      - PORT={port}
    restart: unless-stopped
    volumes:
      - ./data:/app/data
"""


def generate_deploy_script(workspace_dir: str, platform: str = "docker") -> str:
    """生成部署脚本"""
    if platform == "vercel":
        return _vercel_config()
    elif platform == "railway":
        return _railway_config()
    return _docker_deploy_script()


def export_deploy_files(workspace_dir: str, project_name: str = "app",
                        platform: str = "docker", port: int = 8000) -> list[str]:
    """一键导出所有部署文件，返回生成的文件列表"""
    created = []

    from autoc.core.project.manager import ProjectManager
    pm = ProjectManager(workspace_dir)
    metadata = pm.load()
    tech_stack = metadata.tech_stack if metadata else None
    name = project_name or (metadata.name if metadata else "app")

    # Dockerfile
    dockerfile_content = generate_dockerfile(workspace_dir, tech_stack)
    dockerfile_path = os.path.join(workspace_dir, "Dockerfile")
    if not os.path.exists(dockerfile_path):
        Path(dockerfile_path).write_text(dockerfile_content, encoding="utf-8")
        created.append("Dockerfile")

    # docker-compose.yml
    compose_content = generate_compose(workspace_dir, name, port)
    compose_path = os.path.join(workspace_dir, "docker-compose.yml")
    if not os.path.exists(compose_path):
        Path(compose_path).write_text(compose_content, encoding="utf-8")
        created.append("docker-compose.yml")

    # 平台特定配置
    if platform == "vercel":
        vercel_path = os.path.join(workspace_dir, "vercel.json")
        if not os.path.exists(vercel_path):
            Path(vercel_path).write_text(_vercel_config(), encoding="utf-8")
            created.append("vercel.json")
    elif platform == "railway":
        railway_path = os.path.join(workspace_dir, "railway.toml")
        if not os.path.exists(railway_path):
            Path(railway_path).write_text(_railway_config(), encoding="utf-8")
            created.append("railway.toml")

    # 部署脚本
    deploy_path = os.path.join(workspace_dir, "deploy.sh")
    if not os.path.exists(deploy_path):
        Path(deploy_path).write_text(_docker_deploy_script(), encoding="utf-8")
        os.chmod(deploy_path, 0o755)
        created.append("deploy.sh")

    logger.info(f"部署文件已生成: {created}")
    return created


# ==================== 各平台 Dockerfile 模板 ====================

def _python_dockerfile(workspace_dir: str, tech: set) -> str:
    has_requirements = os.path.exists(os.path.join(workspace_dir, "requirements.txt"))
    install_cmd = "pip install -r requirements.txt" if has_requirements else "pip install ."
    cmd = "python -m flask run --host=0.0.0.0" if "flask" in tech else "uvicorn main:app --host=0.0.0.0 --port=8000"

    return f"""FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt* ./
RUN {install_cmd} --no-cache-dir 2>/dev/null || true
COPY . .
EXPOSE 8000
CMD ["{cmd.split()[0]}", {', '.join(f'"{a}"' for a in cmd.split()[1:])}]
"""


def _node_dockerfile(workspace_dir: str, tech: set) -> str:
    return """FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --production
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
"""


def _go_dockerfile() -> str:
    return """FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o main .

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/main .
EXPOSE 8080
CMD ["./main"]
"""


def _static_dockerfile() -> str:
    return """FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""


def _docker_deploy_script() -> str:
    return """#!/bin/bash
# AutoC 一键部署脚本
set -e

echo "🚀 构建 Docker 镜像..."
docker compose build

echo "🔄 启动服务..."
docker compose up -d

echo "✅ 部署完成！"
docker compose ps
"""


def _vercel_config() -> str:
    return '{\n  "version": 2,\n  "builds": [{"src": "**/*", "use": "@vercel/static"}]\n}\n'


def _railway_config() -> str:
    return '[build]\nbuilder = "nixpacks"\n\n[deploy]\nstartCommand = "python main.py"\n'
