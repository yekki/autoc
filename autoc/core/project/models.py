"""纯数据模型 — Pydantic 模型定义

层级模型:
  Project → Task(s)
  - 一个项目包含多个任务 (Task)
  - Task 通过 feature_tag 做可选的 UI 分组显示（无状态机）

本模块只包含数据结构定义，不含任何业务逻辑。
"""

from datetime import datetime
from enum import Enum
from typing import Optional

import json
import re

from pydantic import BaseModel, Field, field_validator, model_validator


# ── 版本语义工具 ──────────────────────────────────────────────────────

class RequirementType(str, Enum):
    """需求类型"""
    PRIMARY = "primary"       # 主需求（定义项目是什么）
    SECONDARY = "secondary"   # 次级需求（追加功能）
    PATCH = "patch"           # 修复补丁


def parse_version(version: str) -> tuple[int, int, int]:
    """解析 SemVer 版本号 → (major, minor, patch)"""
    v = version.lstrip("v")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", v)
    if not m:
        return (0, 1, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def format_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def bump_major(version: str) -> str:
    """主需求变更: v1.2.1 → v2.0.0"""
    major, _, _ = parse_version(version)
    return format_version(major + 1, 0, 0)


def bump_minor(version: str) -> str:
    """追加功能: v1.0.0 → v1.1.0"""
    major, minor, _ = parse_version(version)
    return format_version(major, minor + 1, 0)


def bump_patch(version: str) -> str:
    """修复补丁: v1.1.0 → v1.1.1"""
    major, minor, patch = parse_version(version)
    return format_version(major, minor, patch + 1)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ProjectStatus(str, Enum):
    """项目状态

    执行中（Agent 活跃）:
      planning   — 正在分析需求 / 拆解任务
      developing — Coder Agent 正在写代码
      testing    — Coder Agent 正在运行测试 / 修 Bug

    静止态（持久结果）:
      idle       — 已创建，从未执行过（无 session 历史）
      incomplete — 执行过，但任务未全部 passes（可恢复执行 / 快修 / 修订）
      completed  — 全部任务 Tester 验证通过
      aborted    — 执行异常终止（服务崩溃 / 用户中止 / 未处理异常）
    """
    IDLE       = "idle"
    PLANNING   = "planning"
    DEVELOPING = "developing"
    TESTING    = "testing"
    INCOMPLETE = "incomplete"
    COMPLETED  = "completed"
    ABORTED    = "aborted"

    @classmethod
    def active_statuses(cls) -> set["ProjectStatus"]:
        return {cls.PLANNING, cls.DEVELOPING, cls.TESTING}

    def is_active(self) -> bool:
        return self in self.active_statuses()


VALID_STATUS_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.IDLE:        {ProjectStatus.PLANNING},
    ProjectStatus.PLANNING:    {ProjectStatus.DEVELOPING, ProjectStatus.INCOMPLETE, ProjectStatus.ABORTED},
    ProjectStatus.DEVELOPING:  {
        ProjectStatus.TESTING,      # 有独立测试阶段时
        ProjectStatus.COMPLETED,    # Implementer 模式：Agent 内置验证，无独立 TESTING 阶段
        ProjectStatus.INCOMPLETE,
        ProjectStatus.ABORTED,
    },
    ProjectStatus.TESTING:     {ProjectStatus.COMPLETED, ProjectStatus.INCOMPLETE, ProjectStatus.ABORTED},
    ProjectStatus.INCOMPLETE:  {ProjectStatus.PLANNING, ProjectStatus.TESTING, ProjectStatus.DEVELOPING, ProjectStatus.ABORTED},
    ProjectStatus.COMPLETED:   {ProjectStatus.PLANNING, ProjectStatus.DEVELOPING},
    ProjectStatus.ABORTED:     {ProjectStatus.PLANNING, ProjectStatus.DEVELOPING, ProjectStatus.TESTING},
}


_DOMAIN_ALIASES: dict[str, str] = {
    # browser
    "web": "browser", "frontend": "browser", "ui": "browser",
    # api
    "http": "api", "rest": "api", "https": "api",
    # cli
    "command": "cli", "shell": "cli", "terminal": "cli", "cmd": "cli",
    # llm_judge
    "llm": "llm_judge", "judge": "llm_judge",
}
_VALID_DOMAINS = frozenset({"browser", "api", "cli", "llm_judge"})


class AcceptanceTest(BaseModel):
    """行为级验收测试 — 描述可观察的用户行为，而非 shell 命令

    与 verification_steps（技术层面 shell 命令）互补：
    - verification_steps: Dev 自测，How（怎么跑）
    - AcceptanceTest: 行为验证，What（用户能做什么）

    domain 决定执行协议:
    - "browser": Web 前端，使用 Playwright（需沙箱内安装）
    - "api": HTTP 接口，使用 curl/requests
    - "cli": 命令行程序，执行命令检查 stdout
    - "llm_judge": 兜底，LLM 独立评判（无需运行时环境）

    LLM 生成 "web"/"http"/"command" 等变体时自动归一化，未知值 fallback 到 "llm_judge"。
    """
    description: str          # "用户输入待办并点击添加，列表出现新条目"
    preconditions: list[str] = Field(default_factory=list)  # ["应用已启动"]
    actions: list[str] = Field(default_factory=list)        # ["在输入框输入'买牛奶'", "点击'添加'按钮"]
    expected: list[str] = Field(default_factory=list)       # ["列表中出现'买牛奶'", "输入框被清空"]
    domain: str = "llm_judge"  # "browser" | "api" | "cli" | "llm_judge"

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, v) -> str:
        if v is None:
            return "llm_judge"
        normalized = str(v).lower().strip()
        if normalized in _VALID_DOMAINS:
            return normalized
        return _DOMAIN_ALIASES.get(normalized, "llm_judge")


class Task(BaseModel):
    """单个任务 (参考 Anthropic/SamuelQZQ 的 passes 验证机制)"""

    @model_validator(mode="before")
    @classmethod
    def _migrate_camel_case(cls, data):
        """兼容旧 prd.json 中仍使用 camelCase 的字段名（单次迁移，静默处理）"""
        if isinstance(data, dict):
            _renames = {
                "featureTag": "feature_tag",
                "verificationSteps": "verification_steps",
                "acceptanceCriteria": "acceptance_criteria",
                "acceptanceTests": "acceptance_tests",
                "failureTrajectory": "failure_trajectory",
            }
            for old, new in _renames.items():
                if old in data and new not in data:
                    data[new] = data.pop(old)
        return data

    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    assignee: str = ""  # agent name
    priority: int = 0  # 0=high, 1=medium, 2=low
    dependencies: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)  # 相关文件
    result: str = ""
    error: str = ""
    # UI 分组标签（可选，仅用于显示分组，无状态机）
    feature_tag: str = ""
    # 验证机制 (参考 SamuelQZQ task.json 的 passes 字段)
    verification_steps: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    # 行为级验收测试 — 验收驱动架构的核心，由 PlanningAgent 生成
    acceptance_tests: list[AcceptanceTest] = Field(default_factory=list)
    passes: bool = False
    # 运行时标注
    notes: str = ""
    # 失败轨迹：跨迭代传递错误信息，防止 Dev "失忆重试"
    failure_trajectory: list[dict] = Field(default_factory=list)
    # 阻塞处理 (参考 SamuelQZQ 阻塞协议)
    block_reason: str = ""  # 阻塞原因
    block_attempts: int = 0  # 尝试解决的次数
    block_context: str = ""  # 阻塞时的上下文信息
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @field_validator("id", "title", "description", "assignee", "result",
                     "error", "feature_tag", "notes", "block_reason",
                     "block_context", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    @field_validator("priority", "block_attempts", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        if v is None or v == "":
            return 0
        if isinstance(v, str):
            _map = {"high": 0, "medium": 1, "low": 2, "critical": 0}
            if v.lower() in _map:
                return _map[v.lower()]
            try:
                return int(v)
            except ValueError:
                return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    @field_validator("dependencies", "files", "verification_steps",
                     "acceptance_criteria", mode="before")
    @classmethod
    def _coerce_str_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(item) for item in v]
        return v

    @field_validator("acceptance_tests", mode="before")
    @classmethod
    def _coerce_acceptance_tests(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, AcceptanceTest):
                    result.append(item)
                elif isinstance(item, dict):
                    try:
                        result.append(AcceptanceTest(**item))
                    except Exception:
                        pass
            return result
        return []

    def to_prd_dict(self) -> dict:
        """序列化为 PRD/progress 通用字典格式"""
        return {
            "id": self.id, "title": self.title,
            "description": self.description, "priority": self.priority,
            "verification_steps": self.verification_steps,
            "acceptance_criteria": self.acceptance_criteria,
            "acceptance_tests": [t.model_dump() for t in self.acceptance_tests],
            "feature_tag": self.feature_tag,
            "passes": self.passes, "files": self.files,
            "dependencies": self.dependencies,
        }


class FileRecord(BaseModel):
    """文件记录"""
    path: str
    description: str = ""
    created_by: str = ""
    language: str = ""
    last_modified: str = Field(default_factory=lambda: datetime.now().isoformat())


class TestResult(BaseModel):
    """测试结果"""
    test_name: str
    passed: bool
    output: str = ""
    error: str = ""
    file_path: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class BugReport(BaseModel):
    """Bug 报告"""
    id: str
    title: str
    description: str
    severity: str = "medium"  # critical, high, medium, low
    file_path: str = ""
    line_number: int = 0
    suggested_fix: str = ""
    root_cause: str = ""  # 根因分析
    fix_strategy: str = ""  # 修复策略（局部修复 / 重构 / 重写）
    affected_functions: list[str] = Field(default_factory=list)  # 受影响函数列表
    status: str = "open"  # open, fixing, fixed, wontfix
    reported_by: str = ""
    fixed_by: str = ""
    fix_attempts: int = 0  # 已尝试修复次数

    @field_validator("id", "title", "description", "severity", "file_path",
                     "suggested_fix", "root_cause", "fix_strategy",
                     "status", "reported_by", "fixed_by", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        if v is None:
            return ""
        return str(v)

    @field_validator("line_number", "fix_attempts", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        if v is None or v == "":
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    @field_validator("affected_functions", mode="before")
    @classmethod
    def _coerce_str_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(item) for item in v]
        return v


class TechDecision(BaseModel):
    """规划阶段对单项技术的决策记录"""
    tech: str = ""
    action: str = "adopted"  # adopted / replaced / added / removed
    original: str = ""       # 被替换的原技术（仅 replaced 时有值）
    reason: str = ""


class ProjectPlan(BaseModel):
    """项目计划 (参考 MetaGPT 的增强设计)"""
    project_name: str = ""
    description: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    tech_decisions: list[TechDecision] = Field(default_factory=list)
    architecture: str = ""
    directory_structure: str = ""
    tasks: list[Task] = Field(default_factory=list)
    risk_assessment: str = ""
    interface_spec: str = ""  # 模块间接口规格 + 目标文件树
    plan_complete: bool = False  # 增量规划：LLM 标记所有功能已覆盖
    # 增强字段 (参考 MetaGPT: 用户故事/数据模型/API设计)
    user_stories: list[str] = Field(default_factory=list)
    data_models: str = ""
    api_design: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @field_validator("risk_assessment", "api_design", "architecture",
                     "directory_structure", "data_models", "description",
                     "project_name", "interface_spec", mode="before")
    @classmethod
    def _coerce_to_str(cls, v):
        """LLM 可能返回 dict/list 而非 string，自动序列化为 JSON 字符串"""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False, indent=2)
        if v is None:
            return ""
        return v

    @field_validator("user_stories", mode="before")
    @classmethod
    def _coerce_to_list(cls, v):
        """LLM 可能返回 string 而非 list，自动包装"""
        if isinstance(v, str):
            return [v] if v.strip() else []
        if v is None:
            return []
        return v

    @field_validator("tech_stack", mode="before")
    @classmethod
    def _coerce_tech_stack(cls, v):
        """LLM 可能返回逗号分隔字符串"""
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if v is None:
            return []
        return v


class QualityIssue(BaseModel):
    """需求质量问题"""
    category: str          # "vague" | "missing_info" | "too_broad" | "ambiguous" | "mixed"
    description: str       # 问题描述
    suggestion: str = ""   # 改进建议


class QualityScore(BaseModel):
    """需求质量评估结果"""
    score: float = 0.5               # 0.0 ~ 1.0
    level: str = "medium"             # "high" | "medium" | "low"
    issues: list[QualityIssue] = Field(default_factory=list)
    has_clear_goal: bool = True       # 有明确目标
    has_tech_context: bool = False    # 有技术上下文
    has_scope: bool = False           # 有范围约束
    is_testable: bool = False         # 可验证
    word_count: int = 0


class RefinedRequirement(BaseModel):
    """优化后的需求"""
    original: str                          # 用户原始输入
    refined: str                           # 优化后的需求描述
    quality_before: float = 0.0            # 优化前质量评分
    quality_after: float = 0.0             # 优化后质量评分
    enhancements: list[str] = Field(default_factory=list)  # AI 做了哪些增强
    scope: str = ""                        # 范围说明
    tech_hints: list[str] = Field(default_factory=list)    # 推断的技术约束
    suggested_split: list[str] = Field(default_factory=list)  # 建议拆分的子需求
    skipped: bool = False                  # 是否跳过优化（质量足够高）

    @field_validator("enhancements", "tech_hints", "suggested_split", mode="before")
    @classmethod
    def _coerce_str_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(item) for item in v]
        return v

    @field_validator("quality_before", "quality_after", mode="before")
    @classmethod
    def _coerce_float(cls, v):
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0


class ClarificationRequest(BaseModel):
    """需要用户澄清的问题"""
    questions: list[str] = Field(default_factory=list)   # 需要回答的问题
    defaults: list[str] = Field(default_factory=list)    # 每个问题的建议默认值
    reason: str = ""                                     # 为什么需要澄清

    @field_validator("questions", "defaults", mode="before")
    @classmethod
    def _coerce_str_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        if isinstance(v, list):
            return [str(item) for item in v]
        return v


class ProjectMetadata(BaseModel):
    """项目元数据 — autoc-project.json 的 Pydantic 表示"""
    name: str
    description: str
    project_path: str
    created_at: str
    updated_at: str

    status: str = ProjectStatus.PLANNING.value
    version: str = "1.0.0"

    tech_stack: list[str] = Field(default_factory=list)
    architecture: str = ""

    # 任务进度
    total_tasks: int = 0
    completed_tasks: int = 0
    verified_tasks: int = 0

    # Token 消耗
    total_tokens: int = 0
    ai_assist_tokens: int = 0

    # 历史记录
    sessions: list[dict] = Field(default_factory=list)
    milestones: list[dict] = Field(default_factory=list)

    # 配置
    autoc_version: str = "0.1.0"
    git_enabled: bool = True
    use_project_venv: bool = False  # True: 项目独立 .venv；False: 全局共享 venv（默认）
    single_task: bool = False       # True: 每次只完成一个任务
