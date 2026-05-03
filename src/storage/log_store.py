"""
日志存储

功能：
  - 日志文件读写（按天、按仓库）
  - _merged/ 合并视图按需生成
  - Markdown 格式渲染
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.collectors.git_collector import GitCommit, DayCommits
from src.config import SecurityConfig


# ── Markdown 格式化 ──────────────────────────────────────

def format_commit_markdown(commit: GitCommit, security_level: str) -> str:
    """单个 commit 的 Markdown 渲染，按安全级别过滤"""
    lines = []
    prefix = "[低信息量 commit] " if commit.is_low_quality else ""
    lines.append(f"- {prefix}`{commit.hash}` {commit.message}")

    if commit.files_changed:
        if security_level == "strict":
            # strict：不显示文件名
            pass
        elif security_level in ("balanced", "full"):
            file_list = ", ".join(commit.files_changed[:10])
            extra = f" (+{len(commit.files_changed) - 10} more)" if len(commit.files_changed) > 10 else ""
            lines.append(f"  - 文件: {file_list}{extra}")
            lines.append(f"  - 变更: +{commit.insertions} / -{commit.deletions}")

    return "\n".join(lines)


def format_day_markdown(day: DayCommits, security_level: str) -> str:
    """单天日志的 Markdown 渲染"""
    lines = [
        f"## {day.date.isoformat()} {day.weekday} — {day.repo_alias}",
        "",
        f"共 {len(day.commits)} 次提交 | +{day.total_insertions} / -{day.total_deletions} | "
        f"{len(day.unique_files)} 个文件",
        "",
    ]
    for commit in day.commits:
        lines.append(format_commit_markdown(commit, security_level))
        lines.append("")
    return "\n".join(lines)


def format_week_summary_markdown(days: list[DayCommits], stats: dict) -> str:
    """本周摘要的 Markdown 渲染（供 get_week_summary 工具使用）"""
    lines = [
        f"本周概览：",
        f"- 记录天数：{stats['log_days']} 天",
        f"- Git 提交：{stats['git_commits']} 次",
        f"- 涉及仓库：{', '.join(stats['repos_touched'])}",
        f"- 代码变更：+{stats['insertions']} / -{stats['deletions']}",
        f"- 涉及文件：{stats['files_changed']} 个",
        "",
        "按天摘要：",
    ]
    for day in days:
        commit_msgs = []
        for c in day.commits[:5]:
            msg = c.message.split("\n")[0][:60]
            prefix = "[低信息量] " if c.is_low_quality else ""
            commit_msgs.append(f"{prefix}{msg}")
        extra = f"（另有 {len(day.commits) - 5} 条）" if len(day.commits) > 5 else ""
        lines.append(f"[{day.weekday} {day.date.isoformat()}] {day.repo_alias}: "
                     f"{len(day.commits)} commits")
        for msg in commit_msgs:
            lines.append(f"  - {msg}")
        if extra:
            lines.append(f"  {extra}")
    return "\n".join(lines)


# ── 日志存储 ──────────────────────────────────────────────

class LogStore:
    """日志文件读写管理"""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.git_dir = self.data_dir / "logs" / "git"
        self.manual_dir = self.data_dir / "logs" / "manual"
        self.merged_dir = self.git_dir / "_merged"

        # 确保目录存在
        for d in [self.git_dir, self.manual_dir, self.merged_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save_git_day(self, day: DayCommits, security_level: str):
        """保存单天单仓库的 Git 日志"""
        repo_dir = self.git_dir / day.repo_alias
        repo_dir.mkdir(parents=True, exist_ok=True)
        filepath = repo_dir / f"{day.date.isoformat()}.md"
        content = format_day_markdown(day, security_level)
        filepath.write_text(content, encoding="utf-8")

    def save_manual(self, d: date, content: str):
        """保存手动录入的日志"""
        filepath = self.manual_dir / f"{d.isoformat()}.md"
        # 追加模式，多次录入不覆盖
        existing = ""
        if filepath.exists():
            existing = filepath.read_text(encoding="utf-8")
        if existing:
            existing += "\n\n---\n\n"
        filepath.write_text(existing + content, encoding="utf-8")

    def get_day_content(self, d: date) -> str:
        """获取指定日期的所有日志内容（合并所有来源）"""
        parts = []

        # Git 日志（所有仓库）
        for repo_dir in self.git_dir.iterdir():
            if repo_dir.is_dir() and repo_dir.name != "_merged":
                filepath = repo_dir / f"{d.isoformat()}.md"
                if filepath.exists():
                    parts.append(filepath.read_text(encoding="utf-8"))

        # 手动日志
        manual_file = self.manual_dir / f"{d.isoformat()}.md"
        if manual_file.exists():
            parts.append(f"## 手动录入\n\n{manual_file.read_text(encoding='utf-8')}")

        return "\n\n".join(parts) if parts else ""

    def get_week_dates(self, week_start: date) -> list[date]:
        """获取一周的日期列表（周一到周日）"""
        return [week_start + __import__("datetime").timedelta(days=i) for i in range(7)]

    def get_week_content(self, week_start: date) -> str:
        """获取一周的完整日志内容"""
        parts = []
        for d in self.get_week_dates(week_start):
            content = self.get_day_content(d)
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def get_week_days(self, week_start: date, security_level: str) -> list[DayCommits]:
        """
        读取一周的 DayCommits（从已保存的文件反序列化）

        注意：这是一个简化实现，用于 report 时读取已有数据。
        完整数据在 collect 阶段已结构化保存。
        """
        # 这里返回空列表，实际的 DayCommits 由 GitCollector 直接传递
        # LogStore 主要负责文件持久化和读取原始文本
        return []

    def list_all_dates(self) -> list[date]:
        """列出所有有日志的日期"""
        dates = set()
        for repo_dir in self.git_dir.iterdir():
            if repo_dir.is_dir() and repo_dir.name != "_merged":
                for f in repo_dir.glob("*.md"):
                    try:
                        dates.add(date.fromisoformat(f.stem))
                    except ValueError:
                        pass
        for f in self.manual_dir.glob("*.md"):
            try:
                dates.add(date.fromisoformat(f.stem))
            except ValueError:
                pass
        return sorted(dates)
