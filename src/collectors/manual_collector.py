"""
手动录入采集器

功能：
  - stdin / 交互式输入工作日志
  - 写入 logs/manual/{date}.md
"""

from __future__ import annotations

import sys
from datetime import date

from src.storage.log_store import LogStore


class ManualCollector:
    """手动录入日志采集器"""

    def __init__(self, log_store: LogStore):
        self.log_store = log_store

    def collect_from_text(self, text: str, d: date | None = None) -> date:
        """
        从文本录入日志

        Args:
            text: 日志内容
            d: 日期，默认今天

        Returns:
            录入的日期
        """
        d = d or date.today()
        self.log_store.save_manual(d, text)
        return d

    def collect_interactive(self, d: date | None = None) -> date:
        """
        交互式录入日志（从 stdin 读取）

        Args:
            d: 日期，默认今天

        Returns:
            录入的日期
        """
        d = d or date.today()
        print(f"📝 录入 {d.isoformat()} 的工作日志（输入完毕后按 Ctrl+D 结束）：")

        lines = []
        try:
            for line in sys.stdin:
                lines.append(line)
        except KeyboardInterrupt:
            pass

        if not lines:
            print("⚠️ 未输入任何内容")
            return d

        content = "".join(lines).strip()
        self.log_store.save_manual(d, content)
        print(f"✓ 已保存到 logs/manual/{d.isoformat()}.md")
        return d

    def collect_from_file(self, filepath: str, d: date | None = None) -> date:
        """
        从文件导入日志

        Args:
            filepath: 文件路径
            d: 日期，默认今天

        Returns:
            录入的日期
        """
        from pathlib import Path
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        content = path.read_text(encoding="utf-8")
        d = d or date.today()
        self.log_store.save_manual(d, content)
        print(f"✓ 已导入 {path.name} 到 logs/manual/{d.isoformat()}.md")
        return d
