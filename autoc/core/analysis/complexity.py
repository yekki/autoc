"""需求复杂度评估

纯规则匹配，不调用 LLM，用于动态调整流水线策略和任务拆分粒度。
"""
import math
import re


def assess_complexity(requirement: str) -> str:
    """
    评估需求复杂度（纯规则匹配，不调用 LLM）

    Args:
        requirement: 用户需求文本

    Returns:
        "simple" | "medium" | "complex"
    """
    text = requirement.lower()
    word_count = len(requirement)

    # 真正的复杂指标：多服务架构、高级业务、DevOps、前后端分离框架
    complex_indicators = [
        "graphql", "websocket", "微服务", "microservice",
        "docker", "部署", "deploy", "nginx", "redis", "缓存",
        "前后端", "fullstack", "react", "vue", "angular", "next",
        "管理系统", "dashboard", "cms", "admin",
        "支付", "订单", "购物车", "电商",
        "oauth", "jwt",
        "kubernetes", "k8s", "ci/cd",
    ]
    complex_count = sum(1 for kw in complex_indicators if kw in text)

    # 中等指标：标准 Web 应用特征（数据库、基本认证、REST API）
    medium_indicators = [
        "数据库", "database", "db", "mysql", "postgres", "sqlite", "mongodb",
        "登录", "注册", "认证", "auth", "session",
        "api", "rest",
        "web", "app", "应用", "网页", "网站", "前端", "后端",
        "flask", "fastapi", "django", "express",
        "server", "服务器", "服务", "接口",
    ]

    # 合并所有已注册技术栈的复杂度指标
    try:
        from autoc.stacks._registry import get_all_complexity_indicators
        extra = get_all_complexity_indicators()
        complex_indicators.extend(extra.get("complex", []))
        medium_indicators.extend(extra.get("medium", []))
    except Exception:
        pass

    medium_count = sum(1 for kw in medium_indicators if kw in text)

    # 简单指标：单文件项目、小游戏、脚本、命令行工具
    simple_indicators = [
        "打印", "print", "你好", "输出", "控制台",
        "计算", "求和", "排序", "斐波那契", "阶乘",
        "脚本", "script", "一个函数", "一个文件",
        "游戏", "game", "贪吃蛇", "俄罗斯方块", "tetris",
        "snake", "2048", "扫雷", "五子棋", "井字棋",
        "tic-tac-toe", "pong", "flappy", "breakout",
        "todo", "待办", "记事本", "计算器", "calculator",
        "爬虫", "crawler", "spider",
        "cli", "命令行", "工具",
    ]
    simple_count = sum(1 for kw in simple_indicators if kw in text)

    hello_simple = (
        ("hello" in text or "hello world" in text)
        and medium_count == 0
        and complex_count == 0
    )

    short_and_simple = (
        word_count <= 80
        and complex_count == 0
        and medium_count <= 1
    )

    if simple_count >= 1 and complex_count == 0 and medium_count <= 2:
        return "simple"
    if hello_simple or word_count <= 15:
        return "simple"
    if short_and_simple:
        return "simple"

    if complex_count >= 3:
        return "complex"
    if complex_count >= 2 and medium_count >= 2:
        return "complex"
    if complex_count >= 1 or medium_count >= 2 or word_count > 100:
        return "medium"
    return "medium"


def estimate_scope(requirement: str) -> dict:
    """估算需求涉及的数据模型数和 API 端点数（纯规则匹配）

    用于驱动 PM 任务粒度下限，防止复杂需求被拆分为过少的任务。

    Returns:
        {"model_count": int, "endpoint_count": int, "min_tasks": int}
    """
    text = requirement.lower()

    model_patterns = [
        r"\buser\b", r"\bquiz\b", r"\bquestion\b", r"\bsession\b",
        r"\bparticipant\b", r"\banswer\b", r"\bleaderboard\b",
        r"\bcategory\b", r"\bboard\b", r"\bcard\b", r"\blist\b",
        r"\blabel\b", r"\btag\b", r"\bcomment\b", r"\bproject\b",
        r"\bissue\b", r"\bsprint\b", r"\btask\b", r"\bteam\b",
        r"\bmessage\b", r"\bchannel\b", r"\bnotification\b",
        r"\bproduct\b", r"\border\b", r"\bcart\b", r"\breview\b",
        r"\bpayment\b", r"\binvoice\b", r"\bpost\b", r"\barticle\b",
        r"数据模型", r"模型",
    ]
    model_kw_hits = sum(1 for p in model_patterns if re.search(p, text))

    explicit_model_match = re.search(r"(\d+)\s*(?:个|种)?\s*(?:数据)?模型", text)
    explicit_model_count = int(explicit_model_match.group(1)) if explicit_model_match else 0

    explicit_endpoint_match = re.search(r"~?(\d+)\+?\s*(?:个)?\s*(?:restful\s*)?(?:api\s*)?端点|endpoints?", text)
    explicit_endpoint_count = int(explicit_endpoint_match.group(1)) if explicit_endpoint_match else 0

    model_count = max(explicit_model_count, min(model_kw_hits, 12))
    endpoint_count = explicit_endpoint_count or (model_count * 4)

    min_tasks = max(
        math.ceil(model_count / 2),
        math.ceil(endpoint_count / 8),
        3,
    )

    return {
        "model_count": model_count,
        "endpoint_count": endpoint_count,
        "min_tasks": min_tasks,
    }
