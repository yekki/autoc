"""需求智能优化器 (Requirement Refiner)

在用户输入和规划阶段之间增加轻量级 AI 预处理层，提升需求质量:
  1. 质量评估 — 规则匹配 + 多维度打分
  2. 静默增强 — LLM 自动补全技术细节、明确范围
  3. 交互式澄清 — 质量过低时生成澄清问题
  4. 范围检测 — 过大需求建议拆分

设计原则:
  - 轻量: 单次 LLM 调用，约 500-1000 tokens
  - 透明: 增强内容可追溯 (enhancements 字段)
  - 可选: 通过 config.yaml 的 refiner 段开关控制
"""

import json
import logging
import os
import re
from typing import Optional

from autoc.core.project.models import (
    QualityIssue,
    QualityScore,
    RefinedRequirement,
    ClarificationRequest,
)

logger = logging.getLogger("autoc.refiner")

# 增强 prompt 模板
ENHANCE_PROMPT = """\
你是一个软件需求优化专家。请将以下用户原始需求改写为结构化的软件需求描述。

## 规则
1. 保持用户原始意图不变，不要添加用户没有暗示的功能
2. 补全缺失的关键技术细节（技术栈、存储方式、前后端等）
3. 明确范围边界（包含什么、不包含什么）
4. 使描述可测试、可验证
5. 如果原始需求已经足够清晰，只做轻微润色即可
6. 使用中文输出

## 用户原始需求
{requirement}

{context_section}

## 输出格式（严格 JSON）
```json
{{
  "refined": "优化后的需求描述（一段完整的文字，200-500字）",
  "enhancements": ["增强项1: 说明做了什么补充", "增强项2: ..."],
  "scope": "范围说明: 包含XX，不包含YY",
  "tech_hints": ["推断的技术约束1", "技术约束2"],
  "suggested_split": []
}}
```

如果需求范围过大（涉及 3 个以上独立功能模块），请在 suggested_split 中建议拆分为多个子需求。
"""

CLARIFY_PROMPT = """\
你是一个软件需求分析专家。以下用户需求存在质量问题，请生成 3-5 个关键澄清问题帮助用户完善需求。

参考 snarktank/ralph 的 PRD 生成流程，每个问题必须提供 A/B/C/D 选项，
让用户可以快速回复 "1A, 2C, 3B" 来选择。

## 用户原始需求
{requirement}

## 已识别的问题
{issues}

## 规则
1. 每个问题聚焦一个关键缺失信息
2. 每个问题提供 3-4 个选项（A/B/C/D），最后一个选项为"其他"
3. 问题要简洁、具体
4. 覆盖：目标/核心功能/范围边界/技术栈/成功标准
5. 使用中文

## 输出格式（严格 JSON）
```json
{{
  "questions": [
    "1. 核心目标是什么？\\n   A. 选项1\\n   B. 选项2\\n   C. 选项3\\n   D. 其他",
    "2. 技术栈偏好？\\n   A. Python + Flask\\n   B. Node + Express\\n   C. React SPA\\n   D. 其他"
  ],
  "defaults": ["A", "B"],
  "reason": "需要澄清的原因（一句话）"
}}
```
"""


class RequirementRefiner:
    """
    需求智能优化器

    三种工作模式:
      - "auto": 自动决定策略（根据质量评分）
      - "enhance": 强制静默增强
      - "off": 关闭优化，直接透传

    使用方式:
        refiner = RequirementRefiner(llm_client, config)
        result = refiner.refine(requirement, workspace_dir)
        # result.refined 为优化后的需求
    """

    def __init__(
        self,
        llm_client,
        mode: str = "auto",
        quality_threshold_high: float = 0.7,
        quality_threshold_low: float = 0.4,
        max_split_suggestions: int = 5,
    ):
        self.llm = llm_client
        self.mode = mode
        self.quality_threshold_high = quality_threshold_high
        self.quality_threshold_low = quality_threshold_low
        self.max_split_suggestions = max_split_suggestions

    # ==================== 公共接口 ====================

    def refine(
        self,
        requirement: str,
        workspace_dir: str = "",
        on_event=None,
    ) -> RefinedRequirement:
        """
        主入口: 评估需求质量并决定优化策略

        Returns:
            RefinedRequirement 包含原始和优化后的需求
        """
        emit = on_event or (lambda e: None)

        if self.mode == "off":
            return RefinedRequirement(
                original=requirement, refined=requirement, skipped=True,
            )

        quality = self.assess_quality(requirement)
        logger.info(
            f"需求质量评估: score={quality.score:.2f}, level={quality.level}, "
            f"issues={len(quality.issues)}"
        )

        emit({
            "type": "refiner_quality",
            "agent": "refiner",
            "data": {
                "score": quality.score,
                "level": quality.level,
                "issues": [i.model_dump() for i in quality.issues],
            },
        })

        if self.mode == "auto" and quality.score >= self.quality_threshold_high:
            logger.info("需求质量足够高，跳过优化")
            return RefinedRequirement(
                original=requirement,
                refined=requirement,
                quality_before=quality.score,
                quality_after=quality.score,
                skipped=True,
            )

        # 质量中等或 mode=enhance: 静默增强
        try:
            result = self._enhance(requirement, workspace_dir)
            result.quality_before = quality.score

            after_quality = self.assess_quality(result.refined)
            result.quality_after = after_quality.score

            emit({
                "type": "refiner_enhanced",
                "agent": "refiner",
                "data": {
                    "quality_before": result.quality_before,
                    "quality_after": result.quality_after,
                    "enhancements": result.enhancements,
                    "has_split_suggestion": len(result.suggested_split) > 0,
                },
            })

            logger.info(
                f"需求已增强: quality {result.quality_before:.2f} → {result.quality_after:.2f}, "
                f"enhancements={len(result.enhancements)}"
            )
            return result

        except Exception as e:
            logger.warning(f"需求增强失败，使用原始需求: {e}")
            return RefinedRequirement(
                original=requirement,
                refined=requirement,
                quality_before=quality.score,
                quality_after=quality.score,
                skipped=True,
            )

    def needs_clarification(self, requirement: str) -> bool:
        """判断需求是否质量过低，需要交互式澄清"""
        if self.mode == "off":
            return False
        quality = self.assess_quality(requirement)
        return quality.score < self.quality_threshold_low

    def generate_clarification(self, requirement: str) -> ClarificationRequest:
        """
        生成澄清问题（用于 Web 预处理接口）

        Returns:
            ClarificationRequest 包含待回答的问题和建议默认值
        """
        quality = self.assess_quality(requirement)
        issues_text = "\n".join(
            f"- [{i.category}] {i.description}" for i in quality.issues
        )
        if not issues_text:
            issues_text = "- 需求描述过于简短或模糊"

        prompt = CLARIFY_PROMPT.format(
            requirement=requirement,
            issues=issues_text,
        )

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
            )
            data = self._parse_json_response(response["content"])
            return ClarificationRequest(
                questions=data.get("questions", [])[:3],
                defaults=data.get("defaults", [])[:3],
                reason=data.get("reason", "需求信息不完整"),
            )
        except Exception as e:
            logger.warning(f"生成澄清问题失败: {e}")
            return ClarificationRequest(
                questions=[
                    "1. 核心目标是什么？\n   A. 学习/练手项目\n   B. 生产可用的工具\n   C. 原型/演示\n   D. 其他",
                    "2. 技术栈偏好？\n   A. Python + Flask\n   B. Node + Express\n   C. React SPA\n   D. 纯 HTML/CSS/JS",
                    "3. 数据存储需求？\n   A. 无需持久化\n   B. SQLite 本地存储\n   C. MySQL/PostgreSQL\n   D. 其他",
                ],
                defaults=["B", "A", "B"],
                reason="需求描述过于简略，请快速选择（如 1B, 2A, 3B）",
            )

    @staticmethod
    def merge_clarification(
        requirement: str, questions: list[str], answers: list[str],
    ) -> str:
        """将用户的澄清回答合并到原始需求中"""
        parts = [requirement, "\n\n补充信息:"]
        for q, a in zip(questions, answers):
            if a.strip():
                parts.append(f"- {q} → {a}")
        return "\n".join(parts)

    # ==================== 质量评估 (纯规则) ====================

    def assess_quality(self, requirement: str) -> QualityScore:
        """
        多维度评估需求质量（纯规则匹配，不调用 LLM）

        评估维度:
          1. 长度充分性 (10-300 字为合理区间)
          2. 目标明确性 (是否有动词 + 名词结构)
          3. 技术上下文 (是否在需求文本中提及技术栈、框架、语言)
          4. 范围约束 (是否有"不需要"、"仅"、"只"等限定词)
          5. 可测试性 (是否有具体的功能描述)
          6. 是否混杂多个无关需求
        """
        text = requirement.strip()
        word_count = len(text)
        issues: list[QualityIssue] = []
        score = 0.5  # 基线分

        # --- 维度1: 长度充分性 ---
        if word_count < 5:
            score -= 0.3
            issues.append(QualityIssue(
                category="vague",
                description="需求描述过短，无法判断意图",
                suggestion="请用至少一句完整的话描述你想要的功能",
            ))
        elif word_count < 10:
            score -= 0.15
            issues.append(QualityIssue(
                category="vague",
                description="需求描述较短，可能缺少关键细节",
                suggestion="建议补充功能细节和预期效果",
            ))
        elif 10 <= word_count <= 300:
            score += 0.1
        elif word_count > 500:
            score += 0.05
            issues.append(QualityIssue(
                category="too_broad",
                description="需求描述非常长，可能包含过多内容",
                suggestion="考虑拆分为多个独立需求",
            ))

        # --- 维度2: 目标明确性 ---
        goal_verbs = [
            "创建", "开发", "实现", "构建", "搭建", "编写", "生成", "设计",
            "添加", "修复", "优化", "重构", "迁移", "部署",
            "create", "build", "develop", "implement", "make", "write",
            "add", "fix", "optimize", "refactor", "deploy",
        ]
        has_goal = any(v in text.lower() for v in goal_verbs)
        if has_goal:
            score += 0.1
        else:
            # 检查是否是纯名词短语（如 "Todo 应用"），也算有目标
            if word_count > 3:
                score += 0.05
            else:
                issues.append(QualityIssue(
                    category="vague",
                    description="缺少明确的动作目标",
                    suggestion="建议使用 '创建/开发/实现...' 等动词描述想要做什么",
                ))

        # --- 维度3: 技术上下文 ---
        tech_keywords = [
            "python", "flask", "django", "fastapi", "node", "express", "react",
            "vue", "angular", "typescript", "javascript", "java", "spring",
            "go", "rust", "sqlite", "mysql", "postgres", "mongodb", "redis",
            "docker", "api", "rest", "graphql", "html", "css",
        ]
        tech_found = [kw for kw in tech_keywords if kw in text.lower()]
        has_tech = len(tech_found) > 0
        if has_tech:
            score += 0.1

        # --- 维度4: 范围约束 ---
        scope_keywords = [
            "不需要", "不用", "不包含", "仅", "只需", "只要",
            "简单", "基本", "最小", "MVP", "原型",
            "不含", "排除", "without", "only", "simple", "basic",
        ]
        has_scope = any(kw in text.lower() for kw in scope_keywords)
        if has_scope:
            score += 0.1

        # --- 维度5: 可测试性 ---
        testable_patterns = [
            r"能够.+", r"支持.+", r"可以.+", r"包含.+功能",
            r"用户可以.+", r"实现.+功能", r"提供.+接口",
            r"输入.+输出", r"当.+时.+",
        ]
        is_testable = any(re.search(p, text) for p in testable_patterns)
        if is_testable:
            score += 0.1

        # --- 维度6: 多需求混杂检测 ---
        split_indicators = [
            "还要", "另外", "同时还", "以及还需要", "再加上",
            "第一.*第二.*第三", "1\\.", "2\\.", "①", "②",
        ]
        is_mixed = sum(1 for kw in split_indicators if re.search(kw, text)) >= 2
        if is_mixed:
            score -= 0.05
            issues.append(QualityIssue(
                category="mixed",
                description="需求可能包含多个独立功能，建议分批实现",
                suggestion="将不同功能拆分为独立需求，逐个实现效果更好",
            ))

        # 超大范围检测
        mega_keywords = [
            "电商系统", "电商平台", "ERP", "CRM", "社交平台", "社交网络",
            "操作系统", "完整的.*系统", "全栈.*平台",
        ]
        is_mega = any(re.search(kw, text) for kw in mega_keywords)
        if is_mega and word_count < 100:
            score -= 0.1
            issues.append(QualityIssue(
                category="too_broad",
                description="需求范围非常大，但描述过于简略",
                suggestion="建议缩小范围到 MVP（最小可行产品），或详细描述核心功能",
            ))

        # P5: 可行性维度 — 基于 scope 估算评估 AI 单次完成的可能性
        try:
            from autoc.core.analysis.complexity import estimate_scope
            scope = estimate_scope(text)
            model_count = scope.get("model_count", 0)
            endpoint_count = scope.get("endpoint_count", 0)
            if model_count >= 8 or endpoint_count >= 30:
                score -= 0.1
                issues.append(QualityIssue(
                    category="too_broad",
                    description=(
                        f"需求涉及 ~{model_count} 个数据模型 / ~{endpoint_count} 个端点，"
                        "AI 单次完成风险较高"
                    ),
                    suggestion=(
                        "建议分 2-3 个阶段实现: 先完成核心数据模型和基础 CRUD，"
                        "再逐步添加高级功能（实时通信、排行榜等）"
                    ),
                ))
            elif model_count >= 5:
                score -= 0.05
                issues.append(QualityIssue(
                    category="missing_info",
                    description=f"需求涉及 ~{model_count} 个数据模型，复杂度较高",
                    suggestion="建议明确核心模型的关键字段和关联关系",
                ))
        except Exception:
            pass

        # 归一化到 [0, 1]
        score = max(0.0, min(1.0, score))

        level = "high" if score >= 0.7 else ("low" if score < 0.4 else "medium")

        return QualityScore(
            score=round(score, 2),
            level=level,
            issues=issues,
            has_clear_goal=has_goal,
            has_tech_context=has_tech,
            has_scope=has_scope,
            is_testable=is_testable,
            word_count=word_count,
        )

    # ==================== 静默增强 (LLM) ====================

    def _enhance(
        self, requirement: str, workspace_dir: str = "",
    ) -> RefinedRequirement:
        """调用 LLM 增强需求"""
        context_section = ""
        if workspace_dir and os.path.isdir(workspace_dir):
            existing_files = self._scan_workspace(workspace_dir)
            if existing_files:
                context_section = (
                    "## 当前工作区已有文件\n"
                    + "\n".join(f"- {f}" for f in existing_files[:20])
                    + "\n\n请基于已有项目上下文优化需求。"
                )

        prompt = ENHANCE_PROMPT.format(
            requirement=requirement,
            context_section=context_section,
        )

        response = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )

        data = self._parse_json_response(response["content"])

        refined_text = data.get("refined", requirement)
        if not refined_text or len(refined_text.strip()) < 5:
            refined_text = requirement

        return RefinedRequirement(
            original=requirement,
            refined=refined_text,
            enhancements=data.get("enhancements", []),
            scope=data.get("scope", ""),
            tech_hints=data.get("tech_hints", []),
            suggested_split=data.get("suggested_split", [])[:self.max_split_suggestions],
        )

    # ==================== 工具方法 ====================

    @staticmethod
    def _scan_workspace(workspace_dir: str, max_files: int = 30) -> list[str]:
        """扫描工作区已有文件（用于提供上下文）"""
        files = []
        skip_dirs = {
            "__pycache__", "node_modules", ".git", ".venv", "venv",
            ".autoc_state", ".autoc_experience", "dist", "build",
        }
        try:
            for root, dirs, filenames in os.walk(workspace_dir):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    rel = os.path.relpath(os.path.join(root, fname), workspace_dir)
                    files.append(rel)
                    if len(files) >= max_files:
                        return files
        except OSError:
            pass
        return files

    @staticmethod
    def _parse_json_response(content: str) -> dict:
        """从 LLM 回复中提取 JSON（容错 markdown 代码块）"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试提取 ```json ... ``` 块
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { ... } 块
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法从 LLM 回复中提取 JSON: {content[:200]}...")
        return {}
