"""
Agent 工具定义 + 执行器

工具负责数据获取，LLM 负责信息提取，模板负责格式渲染。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from src.collectors.git_collector import DayCommits
from src.storage.log_store import format_week_summary_markdown, format_day_markdown


# ── 工具 JSON Schema（OpenAI FC 格式）────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_week_summary",
            "description": "获取本周工作数据摘要（按天聚合的统计摘要，非完整日志）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_day_detail",
            "description": "获取指定日期的完整工作日志",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD",
                    }
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_change_summary",
            "description": "获取文件变更摘要（文件名 + 增删行统计）",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期，格式 YYYY-MM-DD。留空则返回全周汇总",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_report_data",
            "description": "提交最终的结构化周报 JSON 数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_data": {
                        "type": "object",
                        "description": "符合周报 Schema 的 JSON 数据",
                    }
                },
                "required": ["report_data"],
            },
        },
    },
]


# ── 工具执行器 ────────────────────────────────────────────

class ToolExecutor:
    """工具执行器，绑定实际数据"""

    def __init__(self, week_days: list[DayCommits], week_stats: dict,
                 day_contents: dict[str, str], security_level: str):
        """
        Args:
            week_days: 本周 DayCommits 列表
            week_stats: 本周统计数据
            day_contents: {日期字符串: 完整日志文本}
            security_level: 安全级别
        """
        self.week_days = week_days
        self.week_stats = week_stats
        self.day_contents = day_contents
        self.security_level = security_level
        self.submitted_data: dict | None = None

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """执行工具调用，返回结果文本"""
        handler = {
            "get_week_summary": self._get_week_summary,
            "get_day_detail": self._get_day_detail,
            "get_file_change_summary": self._get_file_change_summary,
            "submit_report_data": self._submit_report_data,
        }.get(tool_name)

        if handler is None:
            return json.dumps({"error": f"未知工具: {tool_name}"})

        try:
            return handler(**arguments)
        except Exception as e:
            return json.dumps({"error": f"工具执行失败: {str(e)}"})

    def _get_week_summary(self) -> str:
        """返回本周数据摘要"""
        return format_week_summary_markdown(self.week_days, self.week_stats)

    def _get_day_detail(self, date: str) -> str:
        """返回指定日期的完整日志"""
        content = self.day_contents.get(date)
        if content:
            return content
        return f"未找到 {date} 的日志记录"

    def _get_file_change_summary(self, date: str = "") -> str:
        """返回文件变更摘要"""
        lines = []
        for day in self.week_days:
            if date and day.date.isoformat() != date:
                continue
            lines.append(f"[{day.date.isoformat()} {day.weekday}] {day.repo_alias}:")
            for c in day.commits:
                files_str = ", ".join(c.files_changed[:5]) if c.files_changed else "(无文件信息)"
                extra = f" +{len(c.files_changed) - 5} more" if len(c.files_changed) > 5 else ""
                lines.append(f"  {c.hash} {c.message.split(chr(10))[0][:50]}")
                lines.append(f"    {files_str}{extra} | +{c.insertions}/-{c.deletions}")
            lines.append("")
        return "\n".join(lines) if lines else "无文件变更数据"

    def _submit_report_data(self, report_data: dict) -> str:
        """接收 LLM 提交的结构化数据"""
        self.submitted_data = report_data
        return json.dumps({"status": "received", "message": "数据已接收，等待校验"})
