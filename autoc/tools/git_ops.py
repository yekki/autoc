"""Git 操作工具 - 参考 MetaGPT 的版本控制集成

提供 Git 版本控制能力:
- 自动初始化 Git 仓库
- 在关键阶段自动提交
- 支持 diff 查看和回滚
- 为增量开发提供基础

设计理念:
- 参考 MetaGPT 的增量开发模式
- 参考 OpenHands 的 Git 集成
- 每个开发阶段自动 commit，支持回滚
"""

import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger("autoc.tools.git_ops")


class GitOps:
    """
    Git 版本控制工具

    在 Orchestrator 的关键阶段自动:
    - 规划阶段结束 → commit "feat: project plan"
    - 每个任务完成 → commit "feat: implement task-xxx"
    - Bug 修复 → commit "fix: resolve bug-xxx"
    - 测试通过 → tag "v1.0-pass"
    """

    def __init__(self, workspace_dir: str, auto_init: bool = True):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self._initialized = False

        if auto_init:
            self.ensure_init()

    def _run_git(self, *args, check: bool = False, timeout: int = 30) -> tuple[int, str]:
        """执行 git 命令"""
        cmd = ["git"] + list(args)
        try:
            result = subprocess.run(
                cmd,
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip()
            if result.stderr.strip():
                output += f"\n{result.stderr.strip()}" if output else result.stderr.strip()
            if check and result.returncode != 0:
                raise RuntimeError(f"git {' '.join(args)} 失败: {output}")
            return result.returncode, output
        except FileNotFoundError:
            return -1, "[错误] git 命令未找到，请安装 Git"
        except subprocess.TimeoutExpired:
            return -1, "[超时] git 命令执行超时"
        except RuntimeError:
            raise
        except Exception as e:
            return -1, f"[错误] {e}"

    def ensure_init(self) -> bool:
        """确保工作区已初始化 Git 仓库（必须是独立仓库，不能复用父级仓库）"""
        if self._initialized:
            return True

        os.makedirs(self.workspace_dir, exist_ok=True)

        # 检查是否已有 git 仓库，且仓库根目录恰好是 workspace_dir 自身
        code, top = self._run_git("rev-parse", "--show-toplevel")
        if code == 0:
            repo_root = os.path.normpath(top.strip())
            ws_dir = os.path.normpath(self.workspace_dir)
            if repo_root == ws_dir:
                self._initialized = True
                logger.info(f"Git 仓库已存在: {self.workspace_dir}")
                return True
            else:
                logger.warning(
                    f"工作区 {ws_dir} 位于父级仓库 {repo_root} 内，"
                    f"将创建独立 Git 仓库以避免污染父仓库"
                )

        # 初始化新仓库
        code, output = self._run_git("init")
        if code != 0:
            logger.error(f"Git 初始化失败: {output}")
            return False

        # 配置 git 用户（仅在仓库级别）
        self._run_git("config", "user.email", "autoc@autoc.dev")
        self._run_git("config", "user.name", "AutoC")

        # 创建 .gitignore
        gitignore_path = os.path.join(self.workspace_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w") as f:
                f.write(
                    "__pycache__/\n*.pyc\n.env\nnode_modules/\n"
                    "venv/\n.venv/\n*.egg-info/\ndist/\nbuild/\n"
                    ".autoc_state/\n*.log\n"
                    ".autoc.db\nautoc-progress.txt\n"
                )

        # 初始提交（限定当前目录，避免误提交父仓库文件）
        self._run_git("add", "-A", ".")
        self._run_git("commit", "-m", "init: AutoC project initialized", "--allow-empty")

        self._initialized = True
        logger.info(f"Git 仓库已初始化: {self.workspace_dir}")
        return True

    def _verify_repo_isolation(self) -> bool:
        """每次写操作前验证当前 repo root 是 workspace 自身，防止污染父仓库"""
        code, top = self._run_git("rev-parse", "--show-toplevel")
        if code != 0:
            return False
        repo_root = os.path.realpath(os.path.normpath(top.strip()))
        ws_dir = os.path.realpath(os.path.normpath(self.workspace_dir))
        if repo_root != ws_dir:
            logger.error(
                f"Git 隔离失败: repo root={repo_root} != workspace={ws_dir}，"
                f"跳过操作以防污染父仓库"
            )
            self._initialized = False
            return False
        return True

    def commit(self, message: str, add_all: bool = True) -> str:
        """
        提交变更

        Args:
            message: 提交消息
            add_all: 是否自动 add 所有变更

        Returns:
            提交结果信息
        """
        if not self.ensure_init():
            return "[跳过] Git 未初始化"

        if not self._verify_repo_isolation():
            self.ensure_init()
            if not self._verify_repo_isolation():
                return "[跳过] Git 仓库隔离失败，拒绝提交"

        if add_all:
            self._run_git("add", "-A", ".")

        code, status = self._run_git("status", "--porcelain", ".")
        if code == 0 and not status.strip():
            return "[跳过] 没有新的变更需要提交"

        code, output = self._run_git("commit", "-m", message)
        if code == 0:
            logger.info(f"Git 提交: {message}")
            return f"已提交: {message}"
        else:
            if "nothing to commit" in output:
                return "[跳过] 没有新的变更需要提交"
            logger.warning(f"Git 提交失败: {output}")
            return f"提交失败: {output}"

    def diff(self, staged: bool = False) -> str:
        """查看变更"""
        if not self.ensure_init():
            return ""

        args = ["diff"]
        if staged:
            args.append("--staged")

        code, output = self._run_git(*args)
        return output if code == 0 else ""

    def log(self, count: int = 10) -> str:
        """查看提交历史"""
        if not self.ensure_init():
            return ""

        code, output = self._run_git(
            "log", f"-{count}", "--oneline", "--decorate",
        )
        return output if code == 0 else ""

    # 回滚时需要保护的 AutoC 内部文件（不应随代码一起回滚）
    _PROTECTED_FILES = (".autoc.db", "autoc-progress.txt")

    def rollback(self, commit_hash: Optional[str] = None) -> str:
        """
        回滚到指定提交，保护 AutoC 内部文件不被覆盖。

        Args:
            commit_hash: 提交哈希，None 则回滚到上一个提交

        Returns:
            回滚结果
        """
        if not self.ensure_init():
            return "[错误] Git 未初始化"
        if not self._verify_repo_isolation():
            return "[错误] Git 仓库隔离失败，拒绝回滚"

        # 备份受保护文件，并在 finally 中保证恢复，防止中间崩溃导致数据丢失
        import shutil
        backups: dict[str, str] = {}
        for fname in self._PROTECTED_FILES:
            fpath = os.path.join(self.workspace_dir, fname)
            if os.path.exists(fpath):
                bak = fpath + ".bak"
                shutil.copy2(fpath, bak)
                backups[fpath] = bak

        target = commit_hash or "HEAD~1"
        # 提前初始化，防止 _run_git 抛出异常后 finally 执行完毕时 code/output 未定义
        code, output = -1, ""
        try:
            code, output = self._run_git("reset", "--hard", target)
        except Exception as e:
            output = str(e)
        finally:
            # 无论 reset 是否成功/抛出异常，都确保受保护文件得到恢复
            for fpath, bak in backups.items():
                if os.path.exists(bak):
                    shutil.copy2(bak, fpath)
                    os.remove(bak)

        if code == 0:
            logger.info(f"Git 回滚到: {target}")
            return f"已回滚到: {target}\n{output}"
        return f"回滚失败: {output}"

    def tag(self, name: str, message: str = "") -> str:
        """创建标签（已存在则跳过）"""
        if not self.ensure_init():
            return ""
        if not self._verify_repo_isolation():
            return "[跳过] Git 仓库隔离失败"
        if self.tag_exists(name):
            return f"标签已存在: {name}"

        args = ["tag", name]
        if message:
            args.extend(["-m", message])

        code, output = self._run_git(*args)
        return f"标签已创建: {name}" if code == 0 else f"创建标签失败: {output}"

    def tag_exists(self, name: str) -> bool:
        """检查标签是否已存在"""
        if not self.ensure_init():
            return False
        code, output = self._run_git("tag", "-l", name)
        return code == 0 and name in output.strip().split("\n")

    def get_status(self) -> str:
        """获取 Git 状态"""
        if not self.ensure_init():
            return "Git 未初始化"

        code, output = self._run_git("status", "--short")
        return output if code == 0 else "无法获取状态"

    def get_file_history(self, filepath: str) -> str:
        """获取文件的修改历史"""
        if not self.ensure_init():
            return ""
        code, output = self._run_git("log", "--oneline", "-5", "--", filepath)
        return output if code == 0 else ""

    def get_current_hash(self) -> str:
        """获取当前 HEAD 的短 commit hash"""
        if not self.ensure_init():
            return ""
        code, output = self._run_git("rev-parse", "--short", "HEAD")
        return output.strip() if code == 0 else ""


# 工具定义 (用于 Function Calling，供 Agent 使用)
GIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "查看当前未提交的代码变更（git diff），用于代码审查",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "查看最近的提交历史（git log），了解项目演变",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "显示的提交数量，默认10",
                        "default": 10,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "查看 Git 仓库状态，了解哪些文件被修改/新增",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]
