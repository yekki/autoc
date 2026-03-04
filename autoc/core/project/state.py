"""State — 迭代循环状态管理器

管理 .autoc/ 目录下三个核心状态文件:
- prd.json: 任务列表 + passes 状态
- progress.txt: Append-only 经验日志（顶部 Codebase Patterns + 每轮日志）
- guardrails.md: 动态 guardrails（Agent 每轮可更新的注意事项）

文件布局:
  workspace/
  ├── .autoc/
  │   ├── prd.json          # 任务列表
  │   ├── progress.txt      # 经验日志
  │   └── guardrails.md     # 动态 guardrails
  └── src/                  # 项目源码
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, model_validator

from autoc.core.project.models import Task, TaskStatus

logger = logging.getLogger("autoc.state")


# ==================== 数据模型 ====================

class PRDState(BaseModel):
    """prd.json 完整结构

    alias 保持 camelCase 与旧存盘格式兼容，populate_by_name=True 允许 snake_case 直接构造。
    """
    project: str = ""
    branch_name: str = Field(default="", alias="branchName")
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list, alias="techStack")
    tasks: list[Task] = Field(default_factory=list)

    # PM 生成的接口规格（跨任务契约）
    interface_spec: str = Field(default="", alias="interfaceSpec")
    # PM 生成的结构化规约（ORM/DDL 级数据模型 + 可验证 API 契约）
    data_models: str = Field(default="", alias="dataModels")
    api_design: str = Field(default="", alias="apiDesign")

    # 增量规划扩展字段
    requirement: str = ""
    plan_batch: int = Field(default=0, alias="planBatch")
    completed_summary: str = Field(default="", alias="completedSummary")
    plan_complete: bool = Field(default=False, alias="planComplete")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data):
        """向后兼容：旧 prd.json 中 userStories/user_stories 键迁移为 tasks"""
        if isinstance(data, dict):
            if "userStories" in data and "tasks" not in data:
                data["tasks"] = data.pop("userStories")
            elif "user_stories" in data and "tasks" not in data:
                data["tasks"] = data.pop("user_stories")
        return data

    def pick_next_task(self) -> Optional[Task]:
        """选择下一个待完成的任务 (最高优先级 + passes=false)"""
        pending = [t for t in self.tasks if not t.passes]
        if not pending:
            return None
        pending.sort(key=lambda t: t.priority)
        return pending[0]

    def all_passed(self) -> bool:
        return bool(self.tasks) and all(t.passes for t in self.tasks)

    def needs_planning(self) -> bool:
        """判断是否需要规划下一批任务"""
        if self.plan_complete:
            return False
        if not self.tasks:
            return True
        pending = [t for t in self.tasks if not t.passes]
        return len(pending) == 0

    def progress_summary(self) -> str:
        total = len(self.tasks)
        passed = sum(1 for t in self.tasks if t.passes)
        batch_info = f" batch={self.plan_batch}" if self.plan_batch > 0 else ""
        return f"{passed}/{total} tasks passed{batch_info}"

    def build_completed_summary(self) -> str:
        """构建已完成任务的摘要，供 PM 增量规划时参考"""
        passed = [t for t in self.tasks if t.passes]
        if not passed:
            return ""
        lines = [f"- [{t.id}] {t.title}" for t in passed]
        return "\n".join(lines)

    def mark_task_passed(self, task_id: str, passed: bool = True, notes: str = ""):
        for t in self.tasks:
            if t.id == task_id:
                t.passes = passed
                if passed:
                    t.status = TaskStatus.COMPLETED
                if notes:
                    t.notes = notes
                return
        logger.warning(f"mark_task_passed: task_id='{task_id}' 不存在，操作被忽略")



# ==================== 状态管理器 ====================

class StateManager:
    """文件状态管理器

    管理 .autoc/ 目录下三个核心状态文件:
    - prd.json: 任务追踪
    - progress.txt: 经验日志
    - guardrails.md: 动态 guardrails
    """

    def __init__(self, workspace_dir: str, state_dir_name: str = ".autoc"):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.state_dir = os.path.join(self.workspace_dir, state_dir_name)
        self._prd_path = os.path.join(self.state_dir, "prd.json")
        self._progress_path = os.path.join(self.state_dir, "progress.txt")
        self._guardrails_path = os.path.join(self.state_dir, "guardrails.md")

    def ensure_dir(self):
        os.makedirs(self.state_dir, exist_ok=True)

    # ==================== prd.json ====================

    def load_prd(self) -> PRDState:
        if not os.path.exists(self._prd_path):
            return PRDState()
        try:
            with open(self._prd_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PRDState(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            # 文件损坏：备份后返回空状态，防止数据静默丢失
            backup_path = self._prd_path + ".corrupted"
            try:
                import shutil
                shutil.copy2(self._prd_path, backup_path)
                logger.error(
                    f"prd.json 解析失败（{type(e).__name__}: {e}），"
                    f"已备份到 {backup_path}，本次返回空状态"
                )
            except Exception as backup_err:
                logger.error(f"prd.json 解析失败且备份失败: {e} / 备份错误: {backup_err}")
            return PRDState()

    def save_prd(self, prd: PRDState):
        self.ensure_dir()
        data = prd.model_dump(by_alias=True)
        # 原子写入：用 mkstemp 生成唯一临时文件，防止并发场景竞争同一 .tmp 文件
        dir_path = os.path.dirname(self._prd_path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".prd_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._prd_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.debug(f"prd.json 已保存: {prd.progress_summary()}")
        # P-DC-04: 文件总线 — 同步拆分到 plan/ 目录，供按需加载
        try:
            self._sync_plan_files(prd)
        except Exception as e:
            logger.warning(f"plan/ 文件同步失败（prd.json 已成功保存）: {e}")

    def has_prd(self) -> bool:
        return os.path.exists(self._prd_path)

    # ==================== 文件总线 (P-DC-04) ====================

    @staticmethod
    def _atomic_write(path: str, content: str):
        """原子写文件：写临时文件后 rename，防止写入中断留下半损文件"""
        dir_path = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _sync_plan_files(self, prd: PRDState):
        """将 prd 中的规约拆分到 plan/ 目录，供 Agent 按需加载"""
        plan_dir = os.path.join(self.state_dir, "plan")
        os.makedirs(plan_dir, exist_ok=True)

        # plan/tasks.json — 纯任务结构（不含大段规约）
        tasks_data = []
        for t in prd.tasks:
            tasks_data.append({
                "id": t.id, "title": t.title,
                "description": t.description,
                "files": t.files,
                "verification_steps": t.verification_steps,
                "acceptance_criteria": t.acceptance_criteria,
                "priority": t.priority,
                "passes": t.passes,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "error": t.error or "",
                "feature_tag": t.feature_tag,
            })
        tasks_path = os.path.join(plan_dir, "tasks.json")
        self._atomic_write(tasks_path, json.dumps(tasks_data, indent=2, ensure_ascii=False))

        # plan/data_models.md
        if prd.data_models and prd.data_models.strip():
            dm_path = os.path.join(plan_dir, "data_models.md")
            self._atomic_write(dm_path, prd.data_models)

        # plan/api_design.md
        if prd.api_design and prd.api_design.strip():
            api_path = os.path.join(plan_dir, "api_design.md")
            self._atomic_write(api_path, prd.api_design)

        # plan/tech_stack.json
        if prd.tech_stack:
            ts_path = os.path.join(plan_dir, "tech_stack.json")
            self._atomic_write(ts_path, json.dumps(prd.tech_stack, ensure_ascii=False))

    def load_task_by_id(self, task_id: str) -> dict | None:
        """按需加载单个任务（P-INV-02: 不加载全量 prd）"""
        tasks_path = os.path.join(self.state_dir, "plan", "tasks.json")
        if not os.path.exists(tasks_path):
            return None
        try:
            with open(tasks_path, "r", encoding="utf-8") as f:
                tasks = json.load(f)
            for t in tasks:
                if t.get("id") == task_id:
                    return t
        except Exception:
            pass
        return None

    def load_plan_file(self, filename: str) -> str:
        """按需加载 plan/ 下的规约文件"""
        fp = os.path.join(self.state_dir, "plan", filename)
        if not os.path.exists(fp):
            return ""
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def write_test_report(self, round_num: int, report: dict):
        """写入 test/round-{n}.json"""
        test_dir = os.path.join(self.state_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        report_path = os.path.join(test_dir, f"round-{round_num}.json")
        self._atomic_write(report_path, json.dumps(report, indent=2, ensure_ascii=False))

    # ==================== progress.txt ====================

    def load_progress(self) -> str:
        if not os.path.exists(self._progress_path):
            return ""
        with open(self._progress_path, "r", encoding="utf-8") as f:
            return f.read()

    def load_codebase_patterns(self) -> str:
        """提取 progress.txt 顶部的 Codebase Patterns 区域

        参考 snarktank/ralph 的设计:
        顶部 ## Codebase Patterns 区域存放可复用的通用模式,
        Agent 每次迭代开始时先读这部分, 避免重复踩坑。
        """
        content = self.load_progress()
        if not content:
            return ""
        marker = "## Codebase Patterns"
        if marker not in content:
            return ""
        start = content.index(marker)
        next_section = content.find("\n## ", start + len(marker))
        if next_section == -1:
            separator = content.find("\n---", start + len(marker))
            end = separator if separator != -1 else len(content)
        else:
            end = next_section
        return content[start:end].strip()

    def append_progress(
        self,
        story: Task,
        iteration: int,
        summary: str,
        files_changed: list[str],
        learnings: list[str],
    ):
        """追加一条进度记录 (参考 snarktank/ralph prompt.md 的格式)"""
        self.ensure_dir()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry_parts = [
            f"\n## [{now}] - {story.id}: {story.title}",
            f"Iteration: {iteration}",
            f"- {summary}",
        ]
        if files_changed:
            entry_parts.append(f"- Files changed: {', '.join(files_changed[:10])}")
        if learnings:
            entry_parts.append("- **Learnings for future iterations:**")
            for learning in learnings:
                entry_parts.append(f"  - {learning}")
        entry_parts.append("---")
        entry = "\n".join(entry_parts) + "\n"

        with open(self._progress_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def update_codebase_patterns(self, patterns: list[str]):
        """更新 Codebase Patterns 区域 (合并新 pattern, 去重)"""
        content = self.load_progress()
        marker = "## Codebase Patterns\n"

        existing_patterns: list[str] = []
        rest_content = content

        if marker in content:
            start = content.index(marker) + len(marker)
            next_section = content.find("\n## ", start)
            separator = content.find("\n---\n", start)
            candidates = [x for x in [next_section, separator] if x != -1]
            end = min(candidates) if candidates else len(content)
            patterns_text = content[start:end].strip()
            existing_patterns = [
                line.lstrip("- ").strip()
                for line in patterns_text.split("\n")
                if line.strip().startswith("- ")
            ]
            rest_content = content[:content.index(marker)] + content[end:]

        all_patterns = list(dict.fromkeys(existing_patterns + patterns))

        pattern_lines = "\n".join(f"- {p}" for p in all_patterns)
        if marker in content:
            # 原位替换：保持 marker 在文件中的位置不变，不破坏文件头部
            marker_start = content.index(marker)
            new_content = content[:marker_start] + marker + pattern_lines + "\n\n" + content[end:].lstrip()
        else:
            new_content = f"{marker}{pattern_lines}\n\n{rest_content.lstrip()}"

        self.ensure_dir()
        self._atomic_write(self._progress_path, new_content)

    def init_progress(self, project_name: str):
        """初始化 progress.txt (仅在首次创建时)"""
        if os.path.exists(self._progress_path):
            return
        self.ensure_dir()
        content = (
            f"# Ralph Progress Log — {project_name}\n"
            f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            "## Codebase Patterns\n"
            "(Patterns will be added as development progresses)\n\n"
            "---\n"
        )
        self._atomic_write(self._progress_path, content)

    # ==================== guardrails.md ====================

    def load_guardrails(self) -> str:
        if not os.path.exists(self._guardrails_path):
            return ""
        with open(self._guardrails_path, "r", encoding="utf-8") as f:
            return f.read()

    def save_guardrails(self, content: str):
        self.ensure_dir()
        self._atomic_write(self._guardrails_path, content)

    def init_guardrails(self, project_name: str, tech_stack: list[str]):
        """初始化 guardrails.md"""
        if os.path.exists(self._guardrails_path):
            return
        self.ensure_dir()
        stack_str = ", ".join(tech_stack) if tech_stack else "未指定"
        content = (
            f"# Guardrails — {project_name}\n\n"
            f"> 技术栈: {stack_str}\n\n"
            "## 代码规范\n\n"
            "- 使用相对路径引用文件\n"
            "- 不要引入未声明的依赖\n"
            "- 保持代码风格与现有代码一致\n\n"
            "## 已发现的模式\n\n"
            "(Agent 会在每次迭代后自动补充)\n\n"
            "## 注意事项\n\n"
            "(Agent 发现的 gotchas 和注意点)\n"
        )
        self._atomic_write(self._guardrails_path, content)

    def append_guardrail(self, section: str, items: list[str]):
        """向 guardrails.md 的指定 section 追加条目"""
        content = self.load_guardrails()
        if not content:
            return

        section_header = f"## {section}"
        if section_header not in content:
            content += f"\n{section_header}\n\n"

        existing_lines = set(content.splitlines())
        for item in items:
            entry = f"- {item}"
            if entry not in existing_lines:
                idx = content.index(section_header) + len(section_header)
                next_section = content.find("\n## ", idx)
                insert_at = next_section if next_section != -1 else len(content)
                content = content[:insert_at] + f"\n{entry}" + content[insert_at:]
                existing_lines.add(entry)

        self.save_guardrails(content)

    # ==================== 从 PM 计划导入 ====================

    def import_from_tasks(self, tasks_data: list[dict],
                          project_name: str = "",
                          tech_stack: list[str] | None = None,
                          description: str = "",
                          requirement: str = "") -> PRDState:
        """从 AutoC 的任务列表格式导入为 prd.json"""
        tasks = []
        for t in tasks_data:
            tasks.append(Task(
                id=t.get("id", ""),
                title=t.get("title", ""),
                description=t.get("description", ""),
                verification_steps=t.get("verification_steps", []),
                acceptance_criteria=t.get("acceptance_criteria", []),
                priority=t.get("priority", 1),
                passes=t.get("passes", False),
                notes="",
                feature_tag=t.get("feature_tag", ""),
                files=t.get("files", []),
                dependencies=t.get("dependencies", []),
            ))

        prd = PRDState(
            project=project_name or "(imported)",
            description=description,
            tech_stack=tech_stack or [],
            tasks=tasks,
            requirement=requirement,
        )
        self.save_prd(prd)
        return prd

    def append_tasks(self, new_tasks: list[Task], batch: int = 0):
        """追加新任务到已有 prd.json（增量规划用）"""
        prd = self.load_prd()
        existing_ids = {t.id for t in prd.tasks}
        for t in new_tasks:
            if t.id not in existing_ids:
                prd.tasks.append(t)
        if batch > 0:
            prd.plan_batch = batch
        prd.completed_summary = prd.build_completed_summary()
        self.save_prd(prd)
        return prd

    # ==================== 归档 (参考 snarktank/ralph) ====================

    def archive_run(self, label: str = "") -> str:
        """归档当前 prd.json + progress.txt（参考 snarktank/ralph 的 archive 机制）

        当分支/需求变更时，自动将当前状态归档到 .autoc/archive/ 目录，
        然后重置 progress.txt。

        Args:
            label: 归档标签（如 branch name 或 requirement id）

        Returns:
            归档目录路径，归档失败返回空字符串
        """
        if not self.has_prd():
            return ""

        archive_base = os.path.join(self.state_dir, "archive")
        os.makedirs(archive_base, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_label = label.replace("/", "-").replace(" ", "-")[:40] if label else "run"
        archive_dir = os.path.join(archive_base, f"{date_str}-{safe_label}")

        # 防重名
        counter = 0
        final_dir = archive_dir
        while os.path.exists(final_dir):
            counter += 1
            final_dir = f"{archive_dir}-{counter}"

        os.makedirs(final_dir)

        import shutil
        if os.path.exists(self._prd_path):
            shutil.copy2(self._prd_path, os.path.join(final_dir, "prd.json"))
        if os.path.exists(self._progress_path):
            shutil.copy2(self._progress_path, os.path.join(final_dir, "progress.txt"))
        if os.path.exists(self._guardrails_path):
            shutil.copy2(self._guardrails_path, os.path.join(final_dir, "guardrails.md"))

        logger.info(f"已归档到: {final_dir}")
        return final_dir

    def clear_state_files(self):
        """删除 prd.json / progress.txt / guardrails.md / plan/，用于 revise 归档后重置状态。

        确保后续 run_dev_and_test() 会从新计划创建全新的 prd.json，
        而不是加载到旧的 passes=True 状态。
        """
        for path in (self._prd_path, self._progress_path, self._guardrails_path):
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"状态文件已清理: {path}")
        import shutil
        plan_dir = os.path.join(self.state_dir, "plan")
        if os.path.isdir(plan_dir):
            shutil.rmtree(plan_dir, ignore_errors=True)
            logger.info(f"状态文件已清理: {plan_dir}")

    def should_archive(self, new_branch: str = "", new_requirement: str = "") -> bool:
        """判断是否需要归档（branch 或 requirement 变更时）"""
        if not self.has_prd():
            return False
        prd = self.load_prd()
        if new_branch and prd.branch_name and new_branch != prd.branch_name:
            return True
        if new_requirement and prd.requirement and new_requirement != prd.requirement:
            return True
        return False
