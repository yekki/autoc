"""中国区镜像源配置 — 统一管理 pip/npm/go 等包管理器的国内镜像

通过环境变量 AUTOC_USE_CN_MIRROR=1 启用。启用后：
1. Docker 沙箱容器自动写入 pip.conf / .npmrc
2. Agent 提示词注入镜像使用指南
3. 代码层 pip install 自动附加 -i 参数
"""

import os

# 镜像源 URL（集中管理，修改一处全局生效）
PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_TRUSTED_HOST = "pypi.tuna.tsinghua.edu.cn"
NPM_REGISTRY = "https://registry.npmmirror.com"
GO_PROXY = "https://goproxy.cn,direct"


def use_cn_mirror() -> bool:
    """判断是否启用中国区镜像"""
    return os.environ.get("AUTOC_USE_CN_MIRROR", "").lower() in ("1", "true", "yes")


def pip_install_cmd(target: str) -> str:
    """生成 pip install 命令，自动附加镜像参数

    Args:
        target: 包名或 "-r requirements.txt"
    """
    if use_cn_mirror():
        return f"pip install -i {PIP_INDEX_URL} {target}"
    return f"pip install {target}"


def npm_install_cmd(target: str = "") -> str:
    """生成 npm install 命令，自动附加镜像参数"""
    base = f"npm install {target}".strip()
    if use_cn_mirror():
        return f"{base} --registry={NPM_REGISTRY}"
    return base


def get_agent_mirror_instructions() -> str:
    """返回 Agent 提示词中的镜像使用指南（仅启用时返回内容）"""
    if not use_cn_mirror():
        return ""
    return (
        "\n## 依赖安装与镜像加速\n"
        "当前网络环境为中国区，安装依赖时**必须使用国内镜像**以避免超时：\n"
        f"- **pip**: `pip install -i {PIP_INDEX_URL} <包名>` 或 `pip install -i {PIP_INDEX_URL} -r requirements.txt`\n"
        f"- **npm**: `npm install --registry={NPM_REGISTRY}` 或 `npm install --registry={NPM_REGISTRY} <包名>`\n"
        f"- **Go**: 先执行 `go env -w GOPROXY={GO_PROXY}` 再 `go mod tidy`\n"
        "- 如果环境已预配置镜像（pip.conf / .npmrc），直接 `pip install` / `npm install` 即可\n"
    )


def get_mirror_env_hint() -> str:
    """返回任务提示中的简短镜像提示（仅启用时返回内容）"""
    if not use_cn_mirror():
        return ""
    return (
        f"\n- 中国区网络: pip 使用 `-i {PIP_INDEX_URL}`，"
        f"npm 使用 `--registry={NPM_REGISTRY}`"
    )


def get_developer_mirror_guideline(stack: str) -> str:
    """返回技术栈 coding_guidelines 中的镜像提示（仅启用时返回内容）"""
    if not use_cn_mirror():
        return ""
    if stack == "python":
        return f"- 依赖安装使用清华镜像: `pip install -i {PIP_INDEX_URL} <包名>`\n"
    if stack == "node":
        return f"- 依赖安装使用 npmmirror 镜像: `npm install --registry={NPM_REGISTRY}`\n"
    return ""
