"""Runtime Builder — 根据项目依赖自动构建自定义 Docker 镜像

参考 OpenHands Runtime Builder 设计：
- 扫描项目根目录的依赖文件（requirements.txt / package.json / go.mod 等）
- 基于内容 hash 生成唯一镜像 tag，避免重复构建
- 生成 Dockerfile 并调用 docker build
- 构建后的镜像在后续 session 中直接复用

使用：
    builder = RuntimeBuilder(base_image="nikolaik/python-nodejs:python3.12-nodejs22")
    image = builder.build_if_needed("/path/to/workspace")
    # image = "autoc-custom:abc123" 或原镜像（无依赖时返回原镜像）
"""

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("autoc.runtime.builder")


@dataclass
class DependencyInfo:
    """检测到的项目依赖"""
    file_path: str
    dep_type: str  # pip / npm / go / gem / cargo
    content_hash: str
    install_cmd: str


_DEP_FILES = [
    ("requirements.txt", "pip", "pip install --no-cache-dir -r requirements.txt"),
    ("setup.py", "pip", "pip install --no-cache-dir -e ."),
    ("pyproject.toml", "pip", "pip install --no-cache-dir -e ."),
    ("package.json", "npm", "npm install --production"),
    ("go.mod", "go", "go mod download"),
    ("Gemfile", "gem", "bundle install"),
    ("Cargo.toml", "cargo", "cargo fetch"),
]


class RuntimeBuilder:
    """自定义 Docker 镜像构建器"""

    def __init__(
        self,
        base_image: str = "nikolaik/python-nodejs:python3.12-nodejs22",
        image_prefix: str = "autoc-custom",
        use_cn_mirror: bool = False,
    ):
        self._base_image = base_image
        self._image_prefix = image_prefix
        self._use_cn_mirror = use_cn_mirror

    def scan_dependencies(self, workspace_dir: str) -> list[DependencyInfo]:
        """扫描项目根目录的依赖文件"""
        deps: list[DependencyInfo] = []
        root = Path(workspace_dir)

        for filename, dep_type, install_cmd in _DEP_FILES:
            dep_path = root / filename
            if dep_path.exists():
                try:
                    content = dep_path.read_text(encoding="utf-8")
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
                    deps.append(DependencyInfo(
                        file_path=filename,
                        dep_type=dep_type,
                        content_hash=content_hash,
                        install_cmd=install_cmd,
                    ))
                except Exception as e:
                    logger.warning(f"读取 {filename} 失败: {e}")

        return deps

    def compute_image_tag(self, deps: list[DependencyInfo]) -> str:
        """基于依赖内容生成唯一镜像 tag"""
        if not deps:
            return ""
        combined = "|".join(f"{d.file_path}:{d.content_hash}" for d in sorted(deps, key=lambda x: x.file_path))
        tag_hash = hashlib.sha256(combined.encode()).hexdigest()[:10]
        return f"{self._image_prefix}:{tag_hash}"

    def image_exists(self, image_tag: str) -> bool:
        """检查本地是否已有该镜像"""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image_tag],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def generate_dockerfile(self, deps: list[DependencyInfo]) -> str:
        """根据依赖生成 Dockerfile"""
        lines = [f"FROM {self._base_image}"]
        lines.append("WORKDIR /workspace")

        if self._use_cn_mirror:
            if any(d.dep_type == "pip" for d in deps):
                lines.append("RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple")
            if any(d.dep_type == "npm" for d in deps):
                lines.append("RUN npm config set registry https://registry.npmmirror.com")

        for dep in deps:
            lines.append(f"COPY {dep.file_path} /workspace/{dep.file_path}")

        for dep in deps:
            lines.append(f"RUN {dep.install_cmd}")

        return "\n".join(lines) + "\n"

    def build(self, workspace_dir: str, image_tag: str, deps: list[DependencyInfo]) -> bool:
        """执行 docker build"""
        dockerfile_content = self.generate_dockerfile(deps)

        dockerfile_path = os.path.join(workspace_dir, ".autoc-Dockerfile")
        try:
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content)

            logger.info(f"开始构建自定义镜像: {image_tag}")
            result = subprocess.run(
                ["docker", "build", "-t", image_tag, "-f", dockerfile_path, workspace_dir],
                capture_output=True, text=True, timeout=600,
            )

            if result.returncode == 0:
                logger.info(f"自定义镜像构建成功: {image_tag}")
                return True
            else:
                logger.error(f"镜像构建失败: {result.stderr[:500]}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("镜像构建超时 (>600s)")
            return False
        except Exception as e:
            logger.error(f"镜像构建异常: {e}")
            return False
        finally:
            try:
                os.remove(dockerfile_path)
            except OSError:
                pass

    def build_if_needed(self, workspace_dir: str) -> str:
        """主入口：扫描依赖 → 计算 tag → 按需构建 → 返回镜像名

        无依赖文件时返回原始 base_image。
        已有缓存镜像时直接返回（跳过构建）。
        """
        deps = self.scan_dependencies(workspace_dir)
        if not deps:
            logger.debug("未检测到依赖文件，使用默认镜像")
            return self._base_image

        image_tag = self.compute_image_tag(deps)
        if self.image_exists(image_tag):
            logger.info(f"复用缓存镜像: {image_tag}")
            return image_tag

        dep_names = ", ".join(d.file_path for d in deps)
        logger.info(f"检测到依赖文件: {dep_names}，开始构建自定义镜像...")

        if self.build(workspace_dir, image_tag, deps):
            return image_tag

        logger.warning("自定义镜像构建失败，降级使用默认镜像")
        return self._base_image

    @property
    def base_image(self) -> str:
        return self._base_image
