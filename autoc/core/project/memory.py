"""共享记忆系统 - Agent 之间的信息传递和上下文管理

层级模型:
  Project → Task(s)
  - 一个项目包含多个任务 (Task)
  - Task 通过 feature_tag 做可选的 UI 分组显示

数据模型定义在 autoc.core.models 中，本模块只包含 SharedMemory 业务逻辑。
"""

import dataclasses
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from .models import (  # noqa: F401
    TaskStatus,
    Task,
    FileRecord,
    TestResult,
    BugReport,
    ProjectPlan,
    QualityIssue,
    QualityScore,
    RefinedRequirement,
    ClarificationRequest,
)

if TYPE_CHECKING:
    from autoc.core.infra.profile import TechProfile

logger = logging.getLogger("autoc.memory")


class SharedMemory:
    """
    共享记忆系统 - 所有 Agent 之间的信息枢纽

    存储内容:
    - 项目计划 (PM 产出)
    - 任务列表及状态
    - 已创建的文件记录
    - 测试结果
    - Bug 报告
    - Agent 之间的消息
    - 全局上下文
    """

    def __init__(self):
        self.project_plan: Optional[ProjectPlan] = None
        self.plan_md: str = ""
        self.plan_history: list[dict[str, Any]] = []
        self.plan_source: str = ""  # "primary" | "secondary" | ""
        self.tasks: dict[str, Task] = {}
        self.files: dict[str, FileRecord] = {}
        self.test_results: list[TestResult] = []
        self.bug_reports: dict[str, BugReport] = {}
        self.messages: list[dict[str, Any]] = []
        self.context: dict[str, Any] = {}
        self.requirement: str = ""
        self.tech_profile: Optional["TechProfile"] = None

    def set_requirement(self, requirement: str):
        """设置原始需求文本"""
        self.requirement = requirement
        logger.info(f"需求已设置: {requirement[:100]}...")

    # ==================== Plan 历史管理 ====================

    def archive_current_plan(self, version: str, requirement_label: str):
        """归档当前 plan 到历史，在 plan 被覆盖前调用"""
        if not self.plan_md:
            return
        self.plan_history.append({
            "version": version,
            "plan_md": self.plan_md,
            "requirement": requirement_label,
            "source": self.plan_source or "primary",
            "archived_at": datetime.now().isoformat(),
        })
        logger.info(f"Plan 已归档: v{version} ({requirement_label[:60]}...)")

    def get_primary_plan(self) -> str:
        """获取主需求的 plan（从历史中找最近的 primary plan）"""
        for entry in reversed(self.plan_history):
            if entry.get("source") == "primary":
                return entry["plan_md"]
        if self.plan_source == "primary":
            return self.plan_md
        return ""

    def set_plan(self, plan_md: str, source: str = "primary"):
        """设置当前 plan 并记录来源"""
        self.plan_md = plan_md
        self.plan_source = source

    # ==================== 项目计划 ====================

    def set_project_plan(self, plan: ProjectPlan):
        """设置项目计划"""
        self.project_plan = plan
        for task in plan.tasks:
            self.tasks[task.id] = task
        logger.info(
            f"项目计划已设置: {plan.project_name}, 任务数: {len(plan.tasks)}"
        )

    def update_task(self, task_id: str, **kwargs):
        """更新任务状态"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            task.updated_at = datetime.now().isoformat()
            logger.info(f"任务已更新: {task_id} -> {kwargs}")

    def get_pending_tasks(self) -> list[Task]:
        """获取待处理的任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    def get_tasks_by_status(self, status: TaskStatus) -> list[Task]:
        """按状态获取任务"""
        return [t for t in self.tasks.values() if t.status == status]

    def register_file(self, path: str, description: str = "", created_by: str = "", language: str = ""):
        """注册创建的文件"""
        self.files[path] = FileRecord(
            path=path, description=description,
            created_by=created_by, language=language,
        )
        logger.info(f"文件已注册: {path} (by {created_by})")

    def add_test_result(self, result: TestResult):
        """添加测试结果"""
        self.test_results.append(result)
        status = "PASS" if result.passed else "FAIL"
        logger.info(f"测试结果: {result.test_name} {status}")

    def add_bug_report(self, bug: BugReport):
        """添加 Bug 报告"""
        self.bug_reports[bug.id] = bug
        logger.info(f"Bug 报告: [{bug.severity}] {bug.title}")

    def update_bug(self, bug_id: str, **kwargs):
        """更新 Bug 状态"""
        if bug_id in self.bug_reports:
            bug = self.bug_reports[bug_id]
            for key, value in kwargs.items():
                if hasattr(bug, key):
                    setattr(bug, key, value)

    def send_message(self, from_agent: str, to_agent: str, content: str, msg_type: str = "info"):
        """Agent 间发送消息"""
        msg = {
            "from": from_agent, "to": to_agent,
            "content": content, "type": msg_type,
            "timestamp": datetime.now().isoformat(),
        }
        self.messages.append(msg)
        logger.debug(f"消息: {from_agent} -> {to_agent}: {content[:80]}...")

    def get_messages_for(self, agent_name: str) -> list[dict]:
        """获取发送给指定 Agent 的消息"""
        return [m for m in self.messages if m["to"] == agent_name or m["to"] == "all"]

    def get_open_bugs(self) -> list[BugReport]:
        return [b for b in self.bug_reports.values() if b.status == "open"]

    def get_failed_tests(self) -> list[TestResult]:
        return [t for t in self.test_results if not t.passed]

    def get_verified_tasks(self) -> list[Task]:
        """获取已验证通过的任务 (passes=True)"""
        return [t for t in self.tasks.values() if t.passes]

    def get_unverified_tasks(self) -> list[Task]:
        """获取已完成但未验证的任务"""
        return [
            t for t in self.tasks.values()
            if t.status == TaskStatus.COMPLETED and not t.passes
        ]

    def get_blocked_tasks(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status == TaskStatus.BLOCKED]

    def get_next_unfinished_task(self) -> Optional[Task]:
        """获取下一个未完成的任务（按优先级，跳过 BLOCKED）"""
        candidates = [
            t for t in self.tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.FAILED)
               and not t.passes
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda t: t.priority)
        return candidates[0]

    def get_summary(self) -> str:
        """获取项目状态摘要"""
        total_tasks = len(self.tasks)
        completed = len(self.get_tasks_by_status(TaskStatus.COMPLETED))
        failed = len(self.get_tasks_by_status(TaskStatus.FAILED))
        blocked = len(self.get_blocked_tasks())
        verified = len(self.get_verified_tasks())
        total_tests = len(self.test_results)
        passed_tests = len([t for t in self.test_results if t.passed])
        open_bugs = len(self.get_open_bugs())

        return "\n".join([
            f"项目状态摘要",
            f"{'='*40}",
            f"任务: {completed}/{total_tasks} 完成, {failed} 失败, {blocked} 阻塞",
            f"验证: {verified}/{total_tasks} 通过 (passes)",
            f"测试: {passed_tests}/{total_tests} 通过",
            f"Bug: {open_bugs} 待修复",
            f"文件: {len(self.files)} 个",
            f"{'='*40}",
        ])

    def to_context_string(self, agent_role: str = "all") -> str:
        """转换为上下文字符串，供 Agent 使用。

        所有角色都能看到所有 Task（按状态过滤展示），
        已通过的 Task 作为"已完成功能"提供上下文。
        """
        parts = []

        if self.requirement:
            parts.append(f"## 原始需求\n{self.requirement}")

        if self.plan_md:
            plan_preview = self.plan_md[:2000]
            if len(self.plan_md) > 2000:
                plan_preview += "\n...(计划已截断)"
            parts.append(f"## 实现计划 (PLAN.md)\n{plan_preview}")

        # 已通过的任务摘要（为所有角色提供已完成功能上下文）
        verified = self.get_verified_tasks()
        if verified and agent_role != "all":
            parts.append(f"## 已完成功能 ({len(verified)} 个任务已通过)")
            for t in verified:
                files_str = f" — 文件: {', '.join(t.files[:3])}" if t.files else ""
                parts.append(f"- [{t.id}] {t.title}{files_str}")

        # 任务列表（根据角色过滤）
        if self.tasks:
            icon = {
                TaskStatus.PENDING: "P", TaskStatus.IN_PROGRESS: "...",
                TaskStatus.COMPLETED: "OK", TaskStatus.FAILED: "X", TaskStatus.BLOCKED: "!",
            }
            if agent_role == "coder":
                relevant = [t for t in self.tasks.values()
                            if t.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.FAILED)]
                label = "## 待完成任务"
            else:
                relevant = list(self.tasks.values())
                label = "## 任务列表"

            if relevant:
                parts.append(label)
                for task in relevant:
                    passes_str = " [PASSES]" if task.passes else ""
                    blocked_str = f" (阻塞: {task.block_reason})" if task.block_reason else ""
                    parts.append(
                        f"- [{icon.get(task.status, '?')}] [{task.id}] "
                        f"{task.title} ({task.status.value}){passes_str}{blocked_str}"
                    )
                    if agent_role == "coder" and task.verification_steps:
                        for step in task.verification_steps:
                            parts.append(f"    - 验证: {step}")

        # 技术栈 Profile
        if self.tech_profile and not self.tech_profile.is_empty():
            profile_ctx = self.tech_profile.for_agent(agent_role)
            if profile_ctx:
                parts.append(profile_ctx)

        # 文件列表
        if self.files and agent_role != "helper":
            parts.append("## 已创建文件")
            file_list = list(self.files.values())
            if len(file_list) > 20:
                for f in file_list:
                    parts.append(f"- {f.path}")
            else:
                for f in file_list:
                    parts.append(f"- {f.path}: {f.description}")

        # Bug 信息
        open_bugs = self.get_open_bugs()
        if open_bugs and agent_role in ("main", "all"):
            parts.append("## 待修复 Bug")
            for bug in open_bugs:
                parts.append(f"- [{bug.severity}] {bug.title}: {bug.description}")
                if bug.suggested_fix and agent_role in ("main", "all"):
                    parts.append(f"  建议修复: {bug.suggested_fix}")

        return "\n\n".join(parts)

    # ==================== 状态持久化 ====================

    def save_state(self, filepath: str):
        """保存完整状态到 JSON 文件，用于断点续传。"""
        state = {
            "requirement": self.requirement,
            "plan_md": self.plan_md,
            "plan_history": self.plan_history,
            "plan_source": self.plan_source,
            "project_plan": self.project_plan.model_dump() if self.project_plan else None,
            "tasks": {k: v.model_dump() for k, v in self.tasks.items()},
            "files": {k: v.model_dump() for k, v in self.files.items()},
            "test_results": [t.model_dump() for t in self.test_results],
            "bug_reports": {k: v.model_dump() for k, v in self.bug_reports.items()},
            "messages": self.messages,
            "context": self.context,
            "tech_profile": dataclasses.asdict(self.tech_profile) if self.tech_profile else None,
            "saved_at": datetime.now().isoformat(),
        }
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info(f"状态已保存: {filepath}")

    def load_state(self, filepath: str) -> bool:
        """从 JSON 文件恢复状态。"""
        if not os.path.exists(filepath):
            logger.warning(f"状态文件不存在: {filepath}")
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.requirement = state.get("requirement", "")
            self.plan_md = state.get("plan_md", "")
            self.plan_history = state.get("plan_history", [])
            self.plan_source = state.get("plan_source", "")
            if state.get("project_plan"):
                self.project_plan = ProjectPlan(**state["project_plan"])
            self.tasks = {k: Task(**v) for k, v in state.get("tasks", {}).items()}
            self.files = {k: FileRecord(**v) for k, v in state.get("files", {}).items()}
            self.test_results = [TestResult(**t) for t in state.get("test_results", [])]
            self.bug_reports = {k: BugReport(**v) for k, v in state.get("bug_reports", {}).items()}
            self.messages = state.get("messages", [])
            self.context = state.get("context", {})
            if state.get("tech_profile"):
                from autoc.core.infra.profile import TechProfile
                self.tech_profile = TechProfile(**state["tech_profile"])
            logger.info(
                f"状态已恢复: {filepath} "
                f"(任务: {len(self.tasks)}, 文件: {len(self.files)}, Bug: {len(self.bug_reports)})"
            )
            return True
        except Exception as e:
            logger.error(f"状态恢复失败: {e}")
            return False
