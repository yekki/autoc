"""工具注册与调度 Mixin — 从 BaseAgent 拆分

职责：
- 内置工具处理函数（文件/Shell/Git/代码质量）
- ToolRegistry 注册与分发
- ask_helper Agent 间协作
"""

import logging
import os
from typing import Any

from autoc.exceptions import ToolError

logger = logging.getLogger("autoc.agent")


class _ToolMixin:
    """工具注册 + 处理函数 + 统一调度"""

    # ── 工具注册 ──

    def _register_builtin_tools(self):
        """将内置工具处理函数注册到 ToolRegistry"""
        reg = self._registry

        reg.register_handler("read_file", self._tool_read_file, "file", "读取文件内容")
        reg.register_handler("write_file", self._tool_write_file, "file", "写入文件内容")
        reg.register_handler("edit_file", self._tool_edit_file, "file", "精确编辑文件（替换片段）")
        reg.register_handler("create_directory", self._tool_create_directory, "file", "创建目录")
        reg.register_handler("list_files", self._tool_list_files, "file", "列出目录文件")
        reg.register_handler("glob_files", self._tool_glob_files, "file", "按 glob 模式匹配文件")
        reg.register_handler("search_in_files", self._tool_search_in_files, "file", "搜索文件内容")
        reg.register_handler("execute_command", self._tool_execute_command, "shell", "执行 Shell 命令")
        if hasattr(self, 'shell') and self.shell and getattr(self.shell, 'supports_interactive', False):
            reg.register_handler("send_input", self._tool_send_input, "shell", "向交互式进程发送输入")

        if self.git_ops:
            reg.register_handler("git_diff", self._tool_git_diff, "git", "查看 Git 差异")
            reg.register_handler("git_log", self._tool_git_log, "git", "查看 Git 日志")
            reg.register_handler("git_status", self._tool_git_status, "git", "查看 Git 状态")

        if self.code_quality:
            reg.register_handler("format_code", self._tool_format_code, "quality", "格式化代码")
            reg.register_handler("lint_code", self._tool_lint_code, "quality", "代码 Lint 检查")

        reg.register_handler("think", self._tool_think, "meta", "结构化思考（不执行任何操作）")
        reg.register_handler("ask_helper", self._handle_ask_helper, "collaboration", "向辅助 AI 请教")

    # ── Meta 工具 ──

    def _tool_think(self, args: dict) -> str:
        """结构化思考：不执行任何操作，仅作为 LLM 的安全思考空间"""
        thought = args.get("thought", "")
        logger.debug(f"[{self.name}] Think: {thought[:100]}")
        return "思考已记录。请继续执行下一步操作。"

    # ── 文件工具 ──

    def _tool_read_file(self, args: dict) -> str:
        """读取文件（带缓存），FileToolError 向上传播由 _handle_tool_call 统一处理"""
        path = args["path"]
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        # 行号范围查询不走缓存
        if start_line is not None or end_line is not None:
            return self.file_ops.read_file(path, start_line=start_line, end_line=end_line)
        full_path = os.path.join(self.file_ops.workspace_dir, path)
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0
        cached = self._file_cache.get(path)
        if cached and cached[1] == mtime and mtime > 0:
            logger.debug(f"[{self.name}] 文件缓存命中: {path}")
            return cached[0]
        content = self.file_ops.read_file(path)
        self._file_cache[path] = (content, mtime)
        return content

    def _tool_write_file(self, args: dict) -> str:
        path = args["path"]
        result = self.file_ops.write_file(path, args["content"])
        self._changed_files.add(path)
        self._file_cache.pop(path, None)
        lang = self._guess_language(path)
        self.memory.register_file(
            path=path,
            description=args.get("description", ""),
            created_by=self.name,
            language=lang,
        )
        self._emit("file_created", path=path, language=lang)
        return result

    def _tool_edit_file(self, args: dict) -> str:
        path = args["path"]
        result = self.file_ops.edit_file(path, args["old_str"], args["new_str"])
        self._changed_files.add(path)
        self._file_cache.pop(path, None)
        self._emit("file_edited", path=path)
        return result

    def _tool_create_directory(self, args: dict) -> str:
        return self.file_ops.create_directory(args["path"])

    def _tool_list_files(self, args: dict) -> str:
        return self.file_ops.list_files(args.get("path", "."), args.get("recursive", False))

    def _tool_glob_files(self, args: dict) -> str:
        return self.file_ops.glob_files(args["pattern"])

    def _tool_search_in_files(self, args: dict) -> str:
        return self.file_ops.search_in_files(args["keyword"], args.get("file_pattern", "*.*"))

    # ── Shell / Git / 代码质量 ──

    def _tool_execute_command(self, args: dict) -> str:
        return self.shell.execute(args["command"], args.get("timeout", 120))

    def _tool_send_input(self, args: dict) -> str:
        return self.shell.send_input(args["text"])

    def _tool_git_diff(self, args: dict) -> str:
        return self.git_ops.diff() if self.git_ops else "[跳过] Git 未启用"

    def _tool_git_log(self, args: dict) -> str:
        return self.git_ops.log(args.get("count", 10)) if self.git_ops else "[跳过] Git 未启用"

    def _tool_git_status(self, args: dict) -> str:
        return self.git_ops.get_status() if self.git_ops else "[跳过] Git 未启用"

    def _tool_format_code(self, args: dict) -> str:
        if not self.code_quality:
            return "[跳过] 代码质量工具未启用"
        path = args.get("path", ".")
        langs = self.code_quality.detect_languages()
        results = []
        if "python" in langs:
            results.append(self.code_quality.format_python(path))
        if "javascript" in langs:
            results.append(self.code_quality.format_js(path))
        return "\n".join(results) if results else "未检测到需要格式化的代码"

    def _tool_lint_code(self, args: dict) -> str:
        if not self.code_quality:
            return "[跳过] 代码质量工具未启用"
        path = args.get("path", ".")
        langs = self.code_quality.detect_languages()
        results = []
        if "python" in langs:
            results.append(self.code_quality.lint_python(path))
        if "javascript" in langs:
            results.append(self.code_quality.lint_js(path))
        return "\n".join(results) if results else "未检测到需要检查的代码"

    # ── ask_helper — Agent 间协作（schema 定义在 autoc/tools/schemas.py） ──

    def _handle_ask_helper(self, args: dict) -> str:
        """调用辅助 AI 回答 Coder 的问题"""
        if not self._helper_llm:
            return "[跳过] 辅助 AI 咨询通道未就绪"

        question = args.get("question", "")
        task_id = args.get("task_id", "")

        task_context = ""
        if task_id and self.memory.tasks.get(task_id):
            task = self.memory.tasks[task_id]
            task_context = (
                f"\n任务 [{task.id}] {task.title}\n"
                f"描述: {task.description[:300]}\n"
                f"文件: {', '.join(task.files) if task.files else '无'}\n"
                f"验证步骤: {task.verification_steps}\n"
            )

        plan_context = ""
        if self.memory.project_plan:
            plan = self.memory.project_plan
            plan_context = f"项目: {plan.project_name}\n技术栈: {', '.join(plan.tech_stack)}\n"
            if plan.api_design:
                plan_context += f"API 契约:\n{plan.api_design[:500]}\n"
            if plan.data_models:
                plan_context += f"数据模型:\n{plan.data_models[:500]}\n"

        helper_prompt = (
            f"你是辅助 AI，你的队友（{self.name}）在执行任务时遇到问题，向你请教。\n\n"
            f"## 项目上下文\n{plan_context}\n"
            f"## 任务上下文\n{task_context}\n"
            f"## 队友的问题\n{question}\n\n"
            "请**简洁、直接**地回答，给出可操作的建议。"
        )

        try:
            response = self._helper_llm.chat(
                messages=[
                    {"role": "system", "content": "你是辅助 AI，负责回答团队成员关于需求和验证方法的问题。简洁直接。"},
                    {"role": "user", "content": helper_prompt},
                ],
                temperature=0.2, max_tokens=1200,
            )
            answer = response.get("content", "").strip()
            logger.info(f"[ask_helper] {self.name} 提问，辅助 AI 回复 {len(answer)} 字符")
            self._emit("ask_helper", agent=self.name, question=question[:100], answer=answer[:200])
            return f"[辅助 AI 回复]\n{answer}"
        except Exception as e:
            logger.error(f"[ask_helper] 辅助 AI 咨询失败: {e}")
            return f"[错误] 辅助 AI 咨询失败: {e}"

    # ── 工具调用统一调度 ──

    def _handle_tool_call(self, name: str, arguments: dict) -> str:
        """执行工具调用 — 委托给 ToolRegistry 分发"""
        try:
            result = self._registry.dispatch(name, arguments)
            return result
        except ToolError as e:
            logger.warning(f"[{self.name}] {e}")
            return f"[错误] {e}"
        except Exception as e:
            logger.error(f"工具调用失败: {name}({arguments}) -> {e}")
            return f"[错误] 工具调用失败: {e}"
