"""插拔式技术栈适配器 — 一栈一文件，一接口统管

新增技术栈只需在本目录下新建一个文件，实现 StackAdapter 即可。
_registry.py 会自动扫描发现并注册。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProjectContext:
    """系统层解析的项目环境信息（零 LLM Token 消耗）"""
    language: str = ""
    framework: str = ""
    project_type: str = "unknown"
    manifest_file: str = ""
    entry_point: str = ""
    start_command: str = ""
    build_command: str = ""
    test_command: str = ""
    install_command: str = ""
    default_port: int = 0
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    has_dockerfile: bool = False
    has_env_example: bool = False
    env_vars: list[str] = field(default_factory=list)

    def to_prompt_summary(self) -> str:
        """生成注入 Agent prompt 的简洁摘要（~50-80 tokens）"""
        lines = ["## 项目环境信息（系统已预解析，无需再读配置文件）"]
        if self.language:
            lines.append(f"- 语言: {self.language}")
        if self.framework:
            lines.append(f"- 框架: {self.framework}")
        if self.project_type != "unknown":
            lines.append(f"- 类型: {self.project_type}")
        if self.manifest_file:
            lines.append(f"- 清单: {self.manifest_file}")
        if self.start_command:
            lines.append(f"- 启动: `{self.start_command}`")
        if self.test_command:
            lines.append(f"- 测试: `{self.test_command}`")
        if self.install_command:
            lines.append(f"- 安装依赖: `{self.install_command}`")
        if self.build_command:
            lines.append(f"- 构建: `{self.build_command}`")
        if self.default_port:
            lines.append(f"- 默认端口: {self.default_port}")
        if self.entry_point:
            lines.append(f"- 入口: {self.entry_point}")
        if self.dependencies:
            show = self.dependencies[:15]
            lines.append(f"- 依赖({len(self.dependencies)}): {', '.join(show)}")
        if self.scripts:
            lines.append(f"- scripts: {', '.join(list(self.scripts.keys())[:10])}")
        if self.has_dockerfile:
            lines.append("- Dockerfile: 有")
        if self.env_vars:
            lines.append(f"- 环境变量: {', '.join(self.env_vars[:10])}")
        lines.append("")
        manifest = self.manifest_file or "配置文件"
        lines.append(
            f"**提示**: 以上信息已由系统解析。无需 read_file 读取 {manifest}。"
            "如需修改依赖，直接 write_file。"
        )
        return "\n".join(lines)


class StackAdapter(ABC):
    """技术栈适配器抽象基类 — 每个技术栈实现一个子类"""

    @staticmethod
    @abstractmethod
    def detect(workspace_dir: str) -> str | None:
        """探测工作区是否属于此技术栈，返回 manifest 路径或 None"""
        ...

    @staticmethod
    def priority() -> int:
        """探测优先级，数值越小越先匹配（默认 100）"""
        return 100

    @abstractmethod
    def parse(self, manifest_path: str, workspace_dir: str) -> ProjectContext:
        """解析 manifest 文件，填充 ProjectContext"""
        ...

    @staticmethod
    @abstractmethod
    def hidden_dirs() -> set[str]:
        """该技术栈的构建/依赖/缓存目录（Agent 不可见）"""
        ...

    @staticmethod
    @abstractmethod
    def noread_files() -> set[str]:
        """该技术栈的 lock/生成文件（Agent 不应读取）"""
        ...

    @staticmethod
    def noread_extensions() -> set[str]:
        return set()

    @staticmethod
    def config_files() -> set[str]:
        """read_file 时追加"已预解析"提醒的配置文件名"""
        return set()

    @staticmethod
    @abstractmethod
    def coding_guidelines() -> str:
        """注入 Agent system prompt 的编码规范片段"""
        ...

    @staticmethod
    @abstractmethod
    def testing_guidelines() -> str:
        """注入 Agent system prompt 的测试框架片段"""
        ...

    @staticmethod
    def complexity_indicators() -> dict[str, list[str]]:
        """返回 {"complex": [...], "medium": [...]} 框架/关键词"""
        return {"complex": [], "medium": []}

    def setup_environment(self, workspace_dir: str) -> dict[str, str]:
        """安装依赖 + 准备环境，返回环境变量 dict"""
        import subprocess, os
        ctx = self.parse("", workspace_dir)
        if ctx.install_command:
            subprocess.run(
                ctx.install_command, shell=True,
                cwd=workspace_dir, capture_output=True, timeout=120,
            )
        return dict(os.environ)
