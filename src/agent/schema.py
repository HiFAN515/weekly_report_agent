"""
JSON Schema 定义 + 校验

功能：
  - 全局周报 JSON Schema 定义
  - 校验函数：字段完整性、类型、枚举值
  - 精确错误信息
"""

from __future__ import annotations

import json
from typing import Any


# ── 全局 JSON Schema ─────────────────────────────────────

REPORT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["highlights", "daily_work", "issues", "next_week", "data_summary"],
    "properties": {
        "highlights": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 7,
            "description": "核心成果，每条一句话概括",
        },
        "daily_work": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["date", "weekday", "tasks"],
                "properties": {
                    "date": {"type": "string"},
                    "weekday": {
                        "type": "string",
                        "enum": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
                    },
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["description", "status"],
                "properties": {
                    "description": {"type": "string"},
                    "impact": {"type": "string"},
                    "solution": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["已解决", "处理中", "待解决", "已搁置"],
                    },
                },
            },
        },
        "next_week": {
            "type": "array",
            "items": {"type": "string"},
            "description": "下周计划，每项应有明确交付物",
        },
        "data_summary": {
            "type": "object",
            "properties": {
                "git_commits": {"type": "integer"},
                "files_changed": {"type": "integer"},
                "insertions": {"type": "integer"},
                "deletions": {"type": "integer"},
                "log_days": {"type": "integer"},
                "repos_touched": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


# ── 校验函数 ──────────────────────────────────────────────

class ValidationError(Exception):
    """Schema 校验失败"""
    def __init__(self, errors: list[str]):
        self.errors = errors
        msg = "JSON Schema 校验失败:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


def validate_report(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    校验周报 JSON 数据是否符合全局 Schema

    Returns:
        (是否通过, 错误列表)
    """
    errors = []

    if not isinstance(data, dict):
        return False, ["输出不是 JSON 对象"]

    # 检查必需字段
    for field in REPORT_SCHEMA["required"]:
        if field not in data:
            errors.append(f"缺少必需字段: {field}")

    if errors:
        return False, errors

    # 检查 highlights
    hl = data.get("highlights", [])
    if not isinstance(hl, list):
        errors.append("highlights: 期望 array，收到 " + type(hl).__name__)
    elif len(hl) < 1:
        errors.append("highlights: 至少需要 1 条")
    elif len(hl) > 7:
        errors.append(f"highlights: 最多 7 条，收到 {len(hl)} 条")
    else:
        for i, item in enumerate(hl):
            if not isinstance(item, str):
                errors.append(f"highlights[{i}]: 期望 string，收到 {type(item).__name__}")

    # 检查 daily_work
    dw = data.get("daily_work", [])
    if not isinstance(dw, list):
        errors.append("daily_work: 期望 array，收到 " + type(dw).__name__)
    else:
        for i, day in enumerate(dw):
            if not isinstance(day, dict):
                errors.append(f"daily_work[{i}]: 期望 object，收到 {type(day).__name__}")
                continue
            for req in ("date", "weekday", "tasks"):
                if req not in day:
                    errors.append(f"daily_work[{i}]: 缺少字段 {req}")
            wd = day.get("weekday", "")
            valid_weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            if wd and wd not in valid_weekdays:
                errors.append(f"daily_work[{i}].weekday: 值 \"{wd}\" 不在 {valid_weekdays} 中")
            tasks = day.get("tasks", [])
            if not isinstance(tasks, list):
                errors.append(f"daily_work[{i}].tasks: 期望 array，收到 {type(tasks).__name__}")

    # 检查 issues
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        errors.append("issues: 期望 array，收到 " + type(issues).__name__)
    else:
        valid_statuses = ["已解决", "处理中", "待解决", "已搁置"]
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                errors.append(f"issues[{i}]: 期望 object，收到 {type(issue).__name__}")
                continue
            if "description" not in issue:
                errors.append(f"issues[{i}]: 缺少 description")
            if "status" not in issue:
                errors.append(f"issues[{i}]: 缺少 status")
            elif issue["status"] not in valid_statuses:
                errors.append(
                    f"issues[{i}].status: 值 \"{issue['status']}\" 不在 {valid_statuses} 中"
                )

    # 检查 next_week
    nw = data.get("next_week", [])
    if not isinstance(nw, list):
        errors.append("next_week: 期望 array，收到 " + type(nw).__name__)
    else:
        for i, item in enumerate(nw):
            if not isinstance(item, str):
                errors.append(f"next_week[{i}]: 期望 string，收到 {type(item).__name__}")

    # 检查 data_summary
    ds = data.get("data_summary", {})
    if not isinstance(ds, dict):
        errors.append("data_summary: 期望 object，收到 " + type(ds).__name__)
    else:
        for key in ("git_commits", "files_changed", "insertions", "deletions"):
            val = ds.get(key)
            if val is not None and not isinstance(val, int):
                errors.append(f"data_summary.{key}: 期望 integer，收到 {type(val).__name__}")

    return len(errors) == 0, errors


def validate_and_raise(data: dict[str, Any]):
    """校验，失败则抛出 ValidationError"""
    valid, errors = validate_report(data)
    if not valid:
        raise ValidationError(errors)
