"""PRD Import — 从外部文档导入需求

参考 Ralph 的 ralph-import 功能：
- 支持 Markdown / Text / JSON 格式
- 通过 LLM 将非结构化文档转化为 AutoC 项目计划
- 自动拆解为可执行的任务列表

用法:
    autoc import requirements.md
    autoc import api-spec.json --project-name my-app
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autoc.prd_import")

# 支持的文件格式
SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".rst", ".yaml", ".yml"}


def read_prd_file(file_path: str) -> str:
    """读取 PRD 文件内容，自动检测格式"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        logger.warning(f"未知文件格式 {ext}，将按纯文本处理")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        raise ValueError(f"文件为空: {file_path}")

    logger.info(f"已读取 PRD 文件: {file_path} ({len(content)} 字符, 格式: {ext})")
    return content


def detect_format(content: str, ext: str) -> str:
    """检测内容格式"""
    if ext == ".json":
        try:
            json.loads(content)
            return "json"
        except json.JSONDecodeError:
            pass
    if ext in (".yaml", ".yml"):
        return "yaml"
    if ext == ".md" or "# " in content[:500]:
        return "markdown"
    return "text"


def build_import_prompt(content: str, format_type: str, project_name: str = "") -> str:
    """构建 LLM 转换 prompt"""
    name_hint = f'项目名使用 "{project_name}"' if project_name else "根据内容自动生成项目名"

    return (
        "你是规划者。请将以下需求文档转化为 AutoC 项目计划。\n"
        "直接输出纯 JSON，不要任何解释或 markdown 代码块。\n\n"
        f"## 原始文档 (格式: {format_type})\n\n"
        f"{content}\n\n"
        f"## 转化要求\n"
        f"1. {name_hint}\n"
        "2. 提取所有功能需求，拆解为可执行任务\n"
        "3. 每个任务必须有 description、files、verification_steps\n"
        "4. 识别技术栈并填入 tech_stack\n"
        "5. 生成验收标准 (acceptance_criteria)\n"
        "6. 按优先级排序（核心功能优先）\n\n"
        "输出 JSON 格式：\n"
        '{"project_name": "...", "description": "...", '
        '"tech_stack": ["..."], '
        '"tasks": [{"id": "task-1", "title": "...", '
        '"description": "详细实现描述", "priority": 0, '
        '"dependencies": [], "files": ["..."], '
        '"verification_steps": ["..."]}], '
        '"requirement": {"id": "req-1", "title": "需求简称", '
        '"acceptance_criteria": ["标准1"]}}'
    )


def import_prd(
    file_path: str,
    llm_client,
    project_name: str = "",
) -> dict:
    """导入 PRD 文件并通过 LLM 转换为项目计划

    Args:
        file_path: PRD 文件路径
        llm_client: LLMClient 实例
        project_name: 可选项目名

    Returns:
        解析后的项目计划 dict
    """
    content = read_prd_file(file_path)
    ext = Path(file_path).suffix.lower()
    format_type = detect_format(content, ext)

    # JSON 格式直接尝试解析
    if format_type == "json":
        try:
            data = json.loads(content)
            if "tasks" in data:
                logger.info("JSON 文件已是 AutoC 计划格式，直接使用")
                return data
        except json.JSONDecodeError:
            pass

    # 截断过长内容（防止超 LLM 上下文窗口）
    max_chars = 50000
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n... (文档已截断，共 {len(content)} 字符)"
        logger.warning(f"文档过长，已截断至 {max_chars} 字符")

    prompt = build_import_prompt(content, format_type, project_name)

    response = llm_client.chat(
        messages=[
            {"role": "system", "content": "你是规划者，负责将需求文档转化为结构化项目计划。只输出 JSON。"},
            {"role": "user", "content": prompt},
        ]
    )

    output = response.get("content", "")

    # 解析 JSON
    try:
        raw = output.strip()
        if raw.startswith("```"):
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]
        return json.loads(raw)
    except json.JSONDecodeError:
        start = output.find("{")
        end = output.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(output[start:end])
            except json.JSONDecodeError:
                pass

    raise ValueError(f"LLM 输出无法解析为 JSON: {output[:200]}")
