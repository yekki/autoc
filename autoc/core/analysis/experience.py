"""经验学习系统（SQLite 版）

存储:
  - 项目级: {project_root}/.autoc.db （当前项目经验）

表:
  - experiences           历史经验条目
  - experience_patterns   技术栈模式统计
  - fix_trajectories      修复轨迹

公共 API 完全兼容，调用方无需修改。
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from autoc.core.infra.db import GlobalDB, jdump, jload

logger = logging.getLogger("autoc.core.experience")


class ExperienceStore:
    """经验存储系统（SQLite 后端，仅项目级存储）"""

    MAX_EXPERIENCES = 50

    def __init__(self, store_dir: str = ".autoc_experience", enable_global: bool = False):
        from pathlib import Path as _P
        p = _P(store_dir).resolve()
        root = str(p.parent) if p.name == ".autoc_experience" else str(p)
        self._db = GlobalDB(root)

    # ── 写 ────────────────────────────────────────────────────────────

    def record_project(
        self,
        requirement: str,
        project_name: str,
        tech_stack: list[str],
        architecture: str,
        directory_structure: str,
        files: list[str],
        bugs_found: list[dict],
        bugs_fixed: list[dict],
        quality_score: int,
        success: bool,
        elapsed_seconds: float,
        total_tokens: int = 0,
    ):
        """记录一次成功/失败的项目经验"""
        now = datetime.now().isoformat()
        common_issues = [
            {
                "title": b.get("title", ""),
                "description": b.get("description", "")[:100],
                "fix": b.get("suggested_fix", "")[:100],
            }
            for b in bugs_found[:5]
        ]
        with self._db.write() as conn:
            # 用 MAX(id) 分配 exp_id，避免 prune 后 COUNT 回退导致 ID 重复
            row = conn.execute("SELECT MAX(id) FROM experiences").fetchone()
            exp_id = f"exp-{(row[0] or 0) + 1}"
            conn.execute(
                """INSERT INTO experiences
                   (exp_id, requirement_summary, project_name, tech_stack, architecture,
                    directory_structure, file_count, files_sample,
                    bugs_found_count, bugs_fixed_count, common_issues,
                    quality_score, success, elapsed_seconds, total_tokens, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    exp_id, requirement[:200], project_name,
                    jdump(tech_stack), architecture[:300],
                    directory_structure[:500], len(files),
                    jdump(files[:10]), len(bugs_found), len(bugs_fixed),
                    jdump(common_issues), quality_score,
                    1 if success else 0,
                    round(elapsed_seconds, 1), total_tokens, now,
                ),
            )
            if success:
                self._update_patterns(conn, requirement, tech_stack)
            self._prune(conn)
        logger.info(f"项目经验已记录: {project_name} (score={quality_score}, success={success})")

    def record_failure(
        self,
        requirement: str,
        project_name: str,
        failure_reason: str,
        rounds_attempted: int,
        total_tokens: int,
        elapsed_seconds: float,
        bugs_unresolved: list[dict] | None = None,
    ):
        """记录失败经验"""
        now = datetime.now().isoformat()
        unresolved = [
            {"title": b.get("title", ""), "description": b.get("description", "")[:100]}
            for b in (bugs_unresolved or [])[:5]
        ]
        with self._db.write() as conn:
            # 用 MAX(id) 分配 exp_id，避免 prune 后 COUNT 回退导致 ID 重复
            row = conn.execute("SELECT MAX(id) FROM experiences").fetchone()
            exp_id = f"fail-{(row[0] or 0) + 1}"
            conn.execute(
                """INSERT INTO experiences
                   (exp_id, requirement_summary, project_name, tech_stack, architecture,
                    directory_structure, file_count, files_sample,
                    bugs_found_count, bugs_fixed_count, common_issues,
                    quality_score, success, elapsed_seconds, total_tokens,
                    failure_reason, rounds_attempted, unresolved_bugs, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    exp_id, requirement[:200], project_name,
                    jdump([]), "", "", 0, jdump([]),
                    len(bugs_unresolved or []), 0, jdump([]),
                    0, 0, round(elapsed_seconds, 1), total_tokens,
                    failure_reason[:300], rounds_attempted,
                    jdump(unresolved), now,
                ),
            )
            self._prune(conn)
        logger.info(f"失败经验已记录: {project_name}")

    # ── 读 ────────────────────────────────────────────────────────────

    def get_relevant_experiences(self, requirement: str, top_k: int = 3,
                                  include_global: bool = False) -> list[dict]:
        """检索相关经验"""
        keywords = self._extract_keywords(requirement)

        with self._db.read() as conn:
            rows = conn.execute("SELECT * FROM experiences ORDER BY id ASC").fetchall()
        experiences = [self._row_to_dict(r) for r in rows]

        if not experiences:
            return []

        if not keywords:
            successes = [e for e in experiences if e["success"]]
            return successes[-top_k:]

        scored = []
        for exp in experiences:
            score = 0
            text = (
                f"{exp['requirement_summary']} "
                f"{' '.join(exp['tech_stack'])}"
            ).lower()
            for kw in keywords:
                if kw in text:
                    score += 2 if exp["success"] else 1
            if exp.get("quality_score", 0) >= 7:
                score += 1
            if score > 0:
                scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    def get_avg_tokens_for_type(self, requirement: str) -> int:
        relevant = self.get_relevant_experiences(requirement, top_k=5)
        tokens = [e.get("total_tokens", 0) for e in relevant if e.get("total_tokens")]
        return int(sum(tokens) / len(tokens)) if tokens else 0

    def get_tech_recommendation(self, requirement: str) -> str:
        keywords = self._extract_keywords(requirement)
        if not keywords:
            return ""

        pattern_map: dict[str, dict[str, int]] = {}
        try:
            with self._db.read() as conn:
                for kw in keywords:
                    row = conn.execute(
                        """SELECT tech_stack, count FROM experience_patterns
                           WHERE keyword=? ORDER BY count DESC LIMIT 1""",
                        (kw,),
                    ).fetchone()
                    if row:
                        if kw not in pattern_map:
                            pattern_map[kw] = {}
                        ts = row["tech_stack"]
                        pattern_map[kw][ts] = pattern_map[kw].get(ts, 0) + row["count"]
        except Exception:
            pass

        recommendations = []
        for kw, stacks in pattern_map.items():
            best = max(stacks, key=stacks.get)
            recommendations.append(
                f"- 关键词 '{kw}': 历史上使用 [{best}] 成功 {stacks[best]} 次"
            )
        if recommendations:
            return "## 历史经验推荐\n" + "\n".join(recommendations)
        return ""

    def format_for_prompt(self, requirement: str) -> str:
        experiences = self.get_relevant_experiences(requirement)
        if not experiences:
            return ""

        parts = ["## 参考经验（来自历史成功项目）\n"]
        for i, exp in enumerate(experiences, 1):
            parts.append(f"### 案例 {i}: {exp['project_name']}")
            parts.append(f"- 需求: {exp['requirement_summary']}")
            parts.append(f"- 技术栈: {', '.join(exp['tech_stack'])}")
            if exp.get("architecture"):
                parts.append(f"- 架构: {exp['architecture'][:150]}")
            if exp.get("directory_structure"):
                parts.append(f"- 目录结构:\n```\n{exp['directory_structure'][:300]}\n```")
            if exp.get("common_issues"):
                parts.append("- 曾遇到的问题:")
                for issue in exp["common_issues"][:3]:
                    parts.append(f"  - {issue['title']}: {issue['fix']}")
            parts.append(f"- 质量评分: {exp['quality_score']}/10\n")

        tech_rec = self.get_tech_recommendation(requirement)
        if tech_rec:
            parts.append(tech_rec)
        return "\n".join(parts)

    # ── 修复轨迹 (P1-6) ─────────────────────────────────────────────

    def record_fix_trajectory(
        self,
        session_id: str,
        round_num: int,
        bug_id: str,
        bug_title: str,
        bug_severity: str,
        bug_description: str,
        fix_attempt: int,
        strategy: str,
        fix_result: str,
        code_changes: list[str] | None = None,
        test_passed: bool = False,
        reflection: str = "",
        failure_patterns: list[str] | None = None,
    ):
        """记录一次 Bug 修复轨迹（用于后续检索和学习）"""
        now = datetime.now().isoformat()
        with self._db.write() as conn:
            conn.execute(
                """INSERT INTO fix_trajectories
                   (session_id, round_num, bug_id, bug_title, bug_severity,
                    bug_description, fix_attempt, strategy, fix_result,
                    code_changes, test_passed, reflection, failure_patterns, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session_id, round_num, bug_id, bug_title, bug_severity,
                    bug_description[:500], fix_attempt, strategy[:200],
                    fix_result,
                    jdump(code_changes or []),
                    1 if test_passed else 0,
                    reflection[:500],
                    jdump(failure_patterns or []),
                    now,
                ),
            )
        logger.debug(f"修复轨迹已记录: {bug_id} (attempt={fix_attempt}, result={fix_result})")

    def get_similar_trajectories(self, bug_description: str, top_k: int = 3,
                                  include_global: bool = False) -> list[dict]:
        """检索与当前 Bug 相似的历史修复轨迹"""
        keywords = self._extract_keywords(bug_description)

        with self._db.read() as conn:
            rows = list(conn.execute(
                "SELECT * FROM fix_trajectories WHERE fix_result='fixed' "
                "ORDER BY id DESC LIMIT 50"
            ).fetchall())

        if not rows:
            return []

        scored = []
        for row in rows:
            d = dict(row)
            text = f"{d.get('bug_title', '')} {d.get('bug_description', '')}".lower()
            score = sum(2 for kw in keywords if kw in text)
            if score > 0:
                d["code_changes"] = jload(d.get("code_changes"), [])
                d["failure_patterns"] = jload(d.get("failure_patterns"), [])
                scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:top_k]]

    def format_trajectories_for_prompt(self, bug_description: str) -> str:
        """格式化相似修复轨迹供 Agent 参考"""
        trajectories = self.get_similar_trajectories(bug_description)
        if not trajectories:
            return ""

        parts = ["## 参考修复轨迹（来自历史成功修复）\n"]
        for i, t in enumerate(trajectories, 1):
            parts.append(f"### 案例 {i}: {t['bug_title']}")
            parts.append(f"- 问题: {t['bug_description'][:150]}")
            parts.append(f"- 策略: {t['strategy'] or '默认'}")
            parts.append(f"- 尝试次数: {t['fix_attempt']}")
            if t.get("reflection"):
                parts.append(f"- 反思: {t['reflection'][:150]}")
            parts.append("")

        return "\n".join(parts)

    # ── Phase 3.4: 增强经验学习 ──────────────────────────────────────

    def get_success_rate(self) -> dict:
        """计算总体和按技术栈的成功率"""
        with self._db.read() as conn:
            rows = conn.execute("SELECT * FROM experiences").fetchall()

        if not rows:
            return {"total": 0, "success_rate": 0.0, "by_tech": {}}

        experiences = [self._row_to_dict(r) for r in rows]
        total = len(experiences)
        successes = sum(1 for e in experiences if e["success"])

        # 按技术栈统计
        tech_stats: dict[str, dict] = {}
        for exp in experiences:
            for tech in exp.get("tech_stack", []):
                tech_lower = tech.lower()
                if tech_lower not in tech_stats:
                    tech_stats[tech_lower] = {"total": 0, "success": 0}
                tech_stats[tech_lower]["total"] += 1
                if exp["success"]:
                    tech_stats[tech_lower]["success"] += 1

        by_tech = {
            k: {"total": v["total"], "success_rate": v["success"] / v["total"]}
            for k, v in tech_stats.items()
            if v["total"] >= 2
        }

        return {
            "total": total,
            "success_rate": successes / total if total else 0.0,
            "by_tech": by_tech,
        }

    def get_common_failure_patterns(self, top_k: int = 5) -> list[dict]:
        """提取常见失败模式"""
        with self._db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM experiences WHERE success=0 ORDER BY id DESC LIMIT 20"
            ).fetchall()

        if not rows:
            return []

        pattern_count: dict[str, int] = {}
        for row in rows:
            d = dict(row)
            issues = jload(d.get("common_issues"), [])
            for issue in issues:
                title = issue.get("title", "").strip()
                if title:
                    pattern_count[title] = pattern_count.get(title, 0) + 1

            reason = d.get("failure_reason", "")
            if reason:
                # 简化 failure reason 为关键词
                for kw in ["timeout", "syntax", "import", "type", "key",
                           "connection", "permission", "memory"]:
                    if kw in reason.lower():
                        label = f"{kw}_error"
                        pattern_count[label] = pattern_count.get(label, 0) + 1

        sorted_patterns = sorted(pattern_count.items(), key=lambda x: x[1], reverse=True)
        return [
            {"pattern": p, "count": c}
            for p, c in sorted_patterns[:top_k]
        ]

    def get_optimal_config_for(self, requirement: str) -> dict:
        """基于历史经验推荐最优配置（迭代次数、Token 预算等）"""
        relevant = self.get_relevant_experiences(requirement, top_k=5)
        successful = [e for e in relevant if e["success"]]

        if not successful:
            return {}

        avg_tokens = int(sum(e.get("total_tokens", 0) for e in successful) / len(successful))
        avg_time = sum(e.get("elapsed_seconds", 0) for e in successful) / len(successful)
        avg_quality = sum(e.get("quality_score", 0) for e in successful) / len(successful)

        # 收集使用过的技术栈
        tech_counter: dict[str, int] = {}
        for exp in successful:
            for t in exp.get("tech_stack", []):
                tech_counter[t] = tech_counter.get(t, 0) + 1
        recommended_tech = sorted(tech_counter, key=tech_counter.get, reverse=True)[:5]

        return {
            "recommended_token_budget": int(avg_tokens * 1.2),
            "estimated_time_seconds": int(avg_time),
            "expected_quality": round(avg_quality, 1),
            "recommended_tech_stack": recommended_tech,
        }

    # ── 内部 ─────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        d["tech_stack"] = jload(d.get("tech_stack"), [])
        d["files_sample"] = jload(d.get("files_sample"), [])
        d["common_issues"] = jload(d.get("common_issues"), [])
        d["unresolved_bugs"] = jload(d.get("unresolved_bugs"), [])
        d["success"] = bool(d.get("success", 0))
        return d

    @staticmethod
    def _update_patterns(conn, requirement: str, tech_stack: list[str]):
        keywords = ExperienceStore._extract_keywords(requirement)
        tech_str = ", ".join(sorted(tech_stack))
        for kw in keywords:
            conn.execute(
                """INSERT INTO experience_patterns (keyword, tech_stack, count)
                   VALUES (?,?,1)
                   ON CONFLICT(keyword, tech_stack) DO UPDATE SET count=count+1""",
                (kw, tech_str),
            )

    @staticmethod
    def _prune(conn):
        total = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()[0]
        if total > ExperienceStore.MAX_EXPERIENCES:
            excess = total - ExperienceStore.MAX_EXPERIENCES
            conn.execute(
                "DELETE FROM experiences WHERE id IN "
                "(SELECT id FROM experiences ORDER BY id ASC LIMIT ?)",
                (excess,),
            )

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        type_keywords = [
            "web", "api", "rest", "blog", "博客", "商城", "电商", "todo", "待办",
            "聊天", "chat", "游戏", "game", "管理系统", "dashboard", "cms",
            "爬虫", "crawler", "cli", "命令行", "chrome插件", "chrome extension",
            "微服务", "microservice", "docker", "flask", "fastapi", "django",
            "react", "vue", "next", "nuxt", "express", "node",
        ]
        tl = text.lower()
        return [kw for kw in type_keywords if kw in tl][:5]
