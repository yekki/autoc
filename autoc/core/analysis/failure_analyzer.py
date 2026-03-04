"""失败模式分析器 — 纯规则匹配，不调用 LLM

基于 Shepherd (ICLR 2026) 对 3,908 条执行轨迹的研究，
识别三类核心失败模式及两类衍生模式:

  - FALSE_TERMINATION: Agent 错误地认为任务已完成
  - FAILURE_TO_ACT:    Agent 知道该做什么但没行动
  - OUT_OF_ORDER:      操作顺序错误
  - REPEATED_FAILURE:  相同 Bug 连续出现
  - REGRESSION:        修复后引入新问题
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("autoc.failure_analyzer")


class FailurePattern(str, Enum):
    FALSE_TERMINATION = "false_termination"
    FAILURE_TO_ACT = "failure_to_act"
    OUT_OF_ORDER = "out_of_order"
    REPEATED_FAILURE = "repeated_failure"
    REGRESSION = "regression"
    UNKNOWN = "unknown"


class FailureType(str, Enum):
    """PALADIN ToolScan 分类法 — 按根因路由修复策略"""
    API_TOOL_FAILURE = "api_tool_failure"        # API/工具调用失败（超时、格式、权限）
    CODE_LOGIC_ERROR = "code_logic_error"        # 代码逻辑错误（TypeError、ValueError、断言失败）
    DEPENDENCY_MISSING = "dependency_missing"    # 依赖缺失（ModuleNotFoundError、command not found）
    SPEC_AMBIGUITY = "spec_ambiguity"            # 规约歧义（Dev 理解偏差、需求不完整）
    ENV_INFRASTRUCTURE = "env_infrastructure"    # 环境/基础设施（端口占用、Docker、文件权限）
    UNKNOWN = "unknown"


# 失败类型 → 推荐修复策略
FAILURE_TYPE_STRATEGIES: dict[FailureType, str] = {
    FailureType.API_TOOL_FAILURE: "cooldown_retry",     # 等待冷却后重试
    FailureType.CODE_LOGIC_ERROR: "targeted_fix",       # 定向修复（常规 Fix 流程）
    FailureType.DEPENDENCY_MISSING: "env_repair",       # 环境修复（pip install / npm install）
    FailureType.SPEC_AMBIGUITY: "planning_clarify",        # 澄清需求规约
    FailureType.ENV_INFRASTRUCTURE: "env_repair",       # 环境修复
    FailureType.UNKNOWN: "targeted_fix",                # 默认走定向修复
}


@dataclass
class FailureAnalysis:
    patterns: list[FailurePattern] = field(default_factory=list)
    failure_type: FailureType = FailureType.UNKNOWN
    recommended_strategy: str = "targeted_fix"
    diagnosis: str = ""
    recommendations: list[str] = field(default_factory=list)
    severity: str = "low"  # low / medium / high / critical
    should_revert: bool = False
    should_switch_strategy: bool = False


class FailureAnalyzer:
    """纯规则失败模式分析器（不依赖 LLM）"""

    def analyze(
        self,
        test_report: dict,
        bugs: list,
        round_num: int,
        previous_reports: list[dict] | None = None,
        fix_history: list[dict] | None = None,
    ) -> FailureAnalysis:
        analysis = FailureAnalysis()
        previous_reports = previous_reports or []
        fix_history = fix_history or []

        self._detect_false_termination(analysis, test_report)
        self._detect_repeated_failure(analysis, bugs, previous_reports)
        self._detect_regression(analysis, bugs, previous_reports, fix_history)
        self._detect_failure_to_act(analysis, fix_history)
        self._detect_out_of_order(analysis, test_report)

        # 改进 B (PALADIN ToolScan): 按根因分类并路由修复策略
        self._classify_failure_type(analysis, test_report, bugs)
        analysis.recommended_strategy = FAILURE_TYPE_STRATEGIES.get(
            analysis.failure_type, "targeted_fix"
        )

        self._set_severity(analysis)
        self._build_diagnosis(analysis, round_num)
        return analysis

    # ── 模式检测 ────────────────────────────────────────────────

    @staticmethod
    def _detect_false_termination(analysis: FailureAnalysis, report: dict):
        """任务标记通过但整体测试未通过"""
        task_verifications = report.get("task_verification", [])
        false_passes = [
            tv for tv in task_verifications
            if tv.get("passes") and not report.get("pass")
        ]
        if false_passes:
            analysis.patterns.append(FailurePattern.FALSE_TERMINATION)
            analysis.recommendations.append(
                f"检测到虚假完成: {len(false_passes)} 个任务标记通过但整体测试未通过，"
                "需要更严格的端到端验证"
            )

    @staticmethod
    def _detect_repeated_failure(analysis: FailureAnalysis, bugs: list,
                                 previous_reports: list[dict]):
        """相同 Bug 在连续轮次中反复出现"""
        if not previous_reports:
            return
        current_titles = set()
        for b in bugs:
            title = b.title if hasattr(b, "title") else b.get("title", "")
            if title:
                current_titles.add(title)
        for prev in previous_reports[-2:]:
            prev_titles = {b.get("title", "") for b in prev.get("bugs", [])}
            overlap = (current_titles & prev_titles) - {""}
            if overlap:
                analysis.patterns.append(FailurePattern.REPEATED_FAILURE)
                analysis.should_switch_strategy = True
                analysis.recommendations.append(
                    f"检测到 {len(overlap)} 个重复 Bug ({', '.join(list(overlap)[:3])})，"
                    "当前修复策略无效，建议切换到更大范围的重构"
                )
                break

    @staticmethod
    def _detect_regression(analysis: FailureAnalysis, bugs: list,
                           previous_reports: list[dict],
                           fix_history: list[dict]):
        """修复后 Bug 数量反而增加"""
        if not previous_reports or not fix_history:
            return
        prev_bug_count = len(previous_reports[-1].get("bugs", []))
        current_bug_count = len(bugs)
        if current_bug_count > prev_bug_count + 1:
            analysis.patterns.append(FailurePattern.REGRESSION)
            analysis.should_revert = True
            analysis.recommendations.append(
                f"检测到回归: Bug 从 {prev_bug_count} 增至 {current_bug_count}，"
                "修复引入了新问题，建议回滚到修复前状态"
            )

    @staticmethod
    def _detect_failure_to_act(analysis: FailureAnalysis, fix_history: list[dict]):
        """Developer 声称修复了但实际 Bug 未减少"""
        if not fix_history:
            return
        last = fix_history[-1]
        if last.get("fixed_count", 0) == 0 and last.get("total_bugs", 0) > 0:
            analysis.patterns.append(FailurePattern.FAILURE_TO_ACT)
            analysis.recommendations.append(
                "检测到未行动: Developer 未能修复任何 Bug，"
                "可能需要更具体的修复指导或换一种修复策略"
            )

    @staticmethod
    def _detect_out_of_order(analysis: FailureAnalysis, report: dict):
        """从测试报告中检测操作顺序问题"""
        summary = report.get("summary", "").lower()
        error_keywords = ["modulenotfounderror", "importerror", "no module named",
                          "command not found", "not installed"]
        if any(kw in summary for kw in error_keywords):
            analysis.patterns.append(FailurePattern.OUT_OF_ORDER)
            analysis.recommendations.append(
                "检测到依赖缺失: 可能是安装步骤遗漏或执行顺序错误，"
                "请确保先安装依赖再运行测试"
            )

    # ── 严重程度 + 诊断 ───────────────────────────────────────

    @staticmethod
    def _set_severity(analysis: FailureAnalysis):
        if FailurePattern.REGRESSION in analysis.patterns:
            analysis.severity = "critical"
        elif len(analysis.patterns) >= 2:
            analysis.severity = "high"
        elif analysis.patterns:
            analysis.severity = "medium"
        else:
            analysis.severity = "low"
            analysis.patterns.append(FailurePattern.UNKNOWN)
            analysis.recommendations.append("未检测到明显失败模式，继续常规修复流程")

    @staticmethod
    def _classify_failure_type(
        analysis: FailureAnalysis, report: dict, bugs: list,
    ):
        """改进 B (PALADIN ToolScan): 从错误信息中分类失败根因"""
        error_texts = []
        for b in bugs:
            desc = b.description if hasattr(b, "description") else b.get("description", "")
            title = b.title if hasattr(b, "title") else b.get("title", "")
            error_texts.append(f"{title} {desc}".lower())
        summary = report.get("summary", "").lower()
        all_text = " ".join(error_texts) + " " + summary

        dep_keywords = [
            "modulenotfounderror", "importerror", "no module named",
            "command not found", "not installed", "no such file",
            "pip install", "npm install", "package not found",
        ]
        env_keywords = [
            "port already in use", "address already in use", "econnrefused",
            "connection refused", "permission denied", "docker",
            "timeout", "eacces", "disk full",
            "no such table", "no such column", "operationalerror",
            "database is locked", "unable to open database",
            "table already exists", "init-db", "initdb", "migrate",
            "flask db", "alembic", "prisma migrate",
            "role does not exist", "database does not exist",
            "enoent", "errno", "oserror",
        ]
        api_keywords = [
            "api error", "rate limit", "429", "500", "503",
            "connection reset", "ssl", "certificate", "authentication",
        ]
        spec_keywords = [
            "不匹配", "不一致", "未定义", "undefined", "missing field",
            "expected", "mismatch", "schema", "contract",
        ]

        scores = {
            FailureType.DEPENDENCY_MISSING: sum(1 for kw in dep_keywords if kw in all_text),
            FailureType.ENV_INFRASTRUCTURE: sum(1 for kw in env_keywords if kw in all_text),
            FailureType.API_TOOL_FAILURE: sum(1 for kw in api_keywords if kw in all_text),
            FailureType.SPEC_AMBIGUITY: sum(1 for kw in spec_keywords if kw in all_text),
        }

        best_type = max(scores, key=scores.get)
        if scores[best_type] > 0:
            analysis.failure_type = best_type
        else:
            logic_keywords = [
                "typeerror", "valueerror", "attributeerror", "keyerror",
                "indexerror", "nameerror", "syntaxerror", "indentationerror",
                "assertionerror", "zerodivisionerror", "runtimeerror",
            ]
            if any(kw in all_text for kw in logic_keywords):
                analysis.failure_type = FailureType.CODE_LOGIC_ERROR
            else:
                analysis.failure_type = FailureType.UNKNOWN

        if analysis.failure_type != FailureType.UNKNOWN:
            analysis.recommendations.insert(
                0,
                f"失败类型: {analysis.failure_type.value} → "
                f"推荐策略: {FAILURE_TYPE_STRATEGIES[analysis.failure_type]}"
            )

    @staticmethod
    def _build_diagnosis(analysis: FailureAnalysis, round_num: int):
        names = [p.value for p in analysis.patterns]
        analysis.diagnosis = (
            f"第 {round_num} 轮失败分析: "
            f"{len(analysis.patterns)} 个失败模式 ({', '.join(names)}), "
            f"失败类型: {analysis.failure_type.value}, "
            f"推荐策略: {analysis.recommended_strategy}, "
            f"严重程度: {analysis.severity}"
        )
