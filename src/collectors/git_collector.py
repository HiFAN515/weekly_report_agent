"""
Git 采集器

功能：
  - GitPython 读取本地仓库 commit 列表
  - 按天聚合、分支策略、时区转换、author 过滤
  - SQLite 缓存 diff --stat 结果
  - 低质量 commit 检测
  - 安全级别过滤
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

import git

from src.config import GitConfig, RepoConfig, SecurityConfig


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class GitCommit:
    """单个 commit 的结构化数据"""
    hash: str                   # 短 hash
    author: str                 # 提交者
    date: datetime              # 带时区的时间戳
    message: str                # commit message
    files_changed: list[str]    # 变更文件路径列表
    insertions: int             # 新增行数
    deletions: int              # 删除行数
    is_low_quality: bool = False  # 低信息量标记


@dataclass
class DayCommits:
    """某一天的 commit 聚合"""
    date: date
    weekday: str
    repo_alias: str
    commits: list[GitCommit] = field(default_factory=list)

    @property
    def total_insertions(self) -> int:
        return sum(c.insertions for c in self.commits)

    @property
    def total_deletions(self) -> int:
        return sum(c.deletions for c in self.commits)

    @property
    def unique_files(self) -> set[str]:
        return set(f for c in self.commits for f in c.files_changed)


# ── 低质量检测 ────────────────────────────────────────────

_LOW_QUALITY_PATTERN = re.compile(r"^(fix|update|wip|test|done|tmp|debug)$", re.IGNORECASE)


def is_low_quality_message(message: str) -> bool:
    """检测 commit message 是否低信息量"""
    first_line = message.strip().split("\n")[0].strip()
    if len(first_line) < 10:
        return True
    if _LOW_QUALITY_PATTERN.match(first_line):
        return True
    return False


# ── 时区处理 ──────────────────────────────────────────────

_WEEKDAY_MAP = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}


def _get_timezone(tz_name: str) -> timezone:
    """
    获取时区对象

    支持常见命名，不依赖 pytz/zoneinfo。
    """
    tz_map = {
        # 亚洲
        "Asia/Shanghai":  timezone(timedelta(hours=8)),    # 中国
        "Asia/Hong_Kong": timezone(timedelta(hours=8)),    # 香港
        "Asia/Taipei":    timezone(timedelta(hours=8)),    # 台湾
        "Asia/Tokyo":     timezone(timedelta(hours=9)),    # 日本
        "Asia/Seoul":     timezone(timedelta(hours=9)),    # 韩国
        "Asia/Singapore": timezone(timedelta(hours=8)),    # 新加坡
        "Asia/Kolkata":   timezone(timedelta(hours=5, minutes=30)),  # 印度
        "Asia/Dubai":     timezone(timedelta(hours=4)),    # 迪拜
        # 欧洲
        "Europe/London":  timezone(timedelta(hours=0)),    # 英国
        "Europe/Berlin":  timezone(timedelta(hours=1)),    # 德国
        "Europe/Paris":   timezone(timedelta(hours=1)),    # 法国
        "Europe/Moscow":  timezone(timedelta(hours=3)),    # 俄罗斯
        # 北美
        "US/Eastern":     timezone(timedelta(hours=-5)),   # 美东
        "US/Central":     timezone(timedelta(hours=-6)),   # 美中
        "US/Mountain":    timezone(timedelta(hours=-7)),   # 美山
        "US/Pacific":     timezone(timedelta(hours=-8)),   # 美西
        # 其他
        "Australia/Sydney": timezone(timedelta(hours=11)), # 澳洲
        "Pacific/Auckland": timezone(timedelta(hours=13)), # 新西兰
        "UTC":            timezone.utc,
    }
    return tz_map.get(tz_name, timezone.utc)


# 支持的时区列表（供 CLI 展示）
SUPPORTED_TIMEZONES = [
    "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei", "Asia/Tokyo",
    "Asia/Seoul", "Asia/Singapore", "Asia/Kolkata", "Asia/Dubai",
    "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Moscow",
    "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
    "Australia/Sydney", "Pacific/Auckland", "UTC",
]


# ── 采集器 ───────────────────────────────────────────────

class GitCollector:
    """Git 日志采集器"""

    def __init__(self, git_config: GitConfig, security_config: SecurityConfig,
                 cache_store=None):
        self.git_config = git_config
        self.security_config = security_config
        self.cache_store = cache_store
        self.tz = _get_timezone(git_config.timezone)

    def collect(self, repo_config: RepoConfig, since: date, until: date,
                global_author: str = "") -> list[DayCommits]:
        """
        采集指定仓库在日期范围内的 commit，按天聚合

        Args:
            repo_config: 仓库配置
            since: 起始日期（含）
            until: 结束日期（含）
            global_author: 全局默认 author

        Returns:
            按日期排序的 DayCommits 列表
        """
        repo_path = Path(repo_config.path).expanduser().resolve()
        if not (repo_path / ".git").exists():
            raise FileNotFoundError(f"不是 Git 仓库: {repo_path}")

        repo = git.Repo(repo_path)
        author = repo_config.author or global_author or self._get_default_author(repo)

        # 获取 commit 列表
        commits = self._get_commits(repo, since, until, author, repo_config.branch)

        # 获取每个 commit 的 diff stats（带缓存）
        for c in commits:
            stats = self._get_commit_stats(repo, c.hash, str(repo_path))
            c.files_changed = stats["files"]
            c.insertions = stats["insertions"]
            c.deletions = stats["deletions"]

        # 安全过滤
        commits = self._filter_by_security(commits)

        # 低质量检测
        for c in commits:
            c.is_low_quality = is_low_quality_message(c.message)

        # 按天聚合
        return self._group_by_day(commits, repo_config.alias or repo_path.name)

    def collect_all_repos(self, repos_config: list[RepoConfig], since: date,
                          until: date, global_author: str = "") -> list[DayCommits]:
        """采集所有仓库，返回合并后的按天聚合列表"""
        all_days: dict[date, DayCommits] = {}

        for repo_config in repos_config:
            days = self.collect(repo_config, since, until, global_author)
            for day in days:
                if day.date in all_days:
                    # 合并同一天的不同仓库
                    existing = all_days[day.date]
                    existing.commits.extend(day.commits)
                else:
                    all_days[day.date] = day

        # 排序
        return sorted(all_days.values(), key=lambda d: d.date)

    def get_week_stats(self, days: list[DayCommits]) -> dict:
        """从 DayCommits 列表中汇总周统计"""
        all_files = set()
        total_insertions = 0
        total_deletions = 0
        total_commits = 0
        repos = set()

        for day in days:
            total_commits += len(day.commits)
            total_insertions += day.total_insertions
            total_deletions += day.total_deletions
            all_files.update(day.unique_files)
            repos.add(day.repo_alias)

        return {
            "git_commits": total_commits,
            "files_changed": len(all_files),
            "insertions": total_insertions,
            "deletions": total_deletions,
            "log_days": len(days),
            "repos_touched": sorted(repos),
        }

    # ── 内部方法 ──────────────────────────────────────────

    def _get_default_author(self, repo: git.Repo) -> str:
        """获取仓库的 git config user.name"""
        try:
            return repo.config_reader().get_value("user", "name", "")
        except Exception:
            return ""

    def _get_commits(self, repo: git.Repo, since: date, until: date,
                     author: str, branch: str) -> list[GitCommit]:
        """读取 commit 列表"""
        since_dt = datetime(since.year, since.month, since.day, tzinfo=self.tz)
        until_dt = datetime(until.year, until.month, until.day, 23, 59, 59, tzinfo=self.tz)

        kwargs = {
            "since": since_dt.isoformat(),
            "until": until_dt.isoformat(),
            "no_merges": self.git_config.no_merges,
        }

        if author:
            kwargs["author"] = author

        # 分支策略 — rev 作为第一个位置参数传入
        strategy = self.git_config.branch_strategy
        if strategy == "current":
            rev = "HEAD"
        elif strategy == "all":
            rev = "--all"
        else:  # merged / default
            rev = branch

        commits = []
        try:
            for c in repo.iter_commits(rev, **kwargs):
                local_date = c.committed_datetime.astimezone(self.tz)
                # 本地二次过滤：确保 commit 日期在 [since, until] 范围内
                # git 的 --since/--until 基于 author date，且时区处理可能不一致
                commit_date = local_date.date()
                if commit_date < since or commit_date > until:
                    continue
                commits.append(GitCommit(
                    hash=c.hexsha[:8],
                    author=str(c.author),
                    date=local_date,
                    message=c.message.strip(),
                    files_changed=[],  # 后续填充
                    insertions=0,
                    deletions=0,
                ))
        except git.exc.GitCommandError as e:
            print(f"⚠️ Git 命令执行失败: {e}")

        return commits

    def _get_commit_stats(self, repo: git.Repo, commit_hash: str,
                          repo_path: str) -> dict:
        """获取 commit 的 diff --stat（带缓存）"""
        # 查缓存
        if self.cache_store and self.cache_store.has(commit_hash, repo_path):
            return self.cache_store.get(commit_hash, repo_path)

        # 执行 git diff --stat
        try:
            commit = repo.commit(commit_hash)
            stats = commit.stats
            files = list(stats.files.keys())
            result = {
                "files": files,
                "insertions": stats.total["insertions"],
                "deletions": stats.total["deletions"],
            }
        except Exception:
            result = {"files": [], "insertions": 0, "deletions": 0}

        # 写入缓存
        if self.cache_store:
            self.cache_store.set(commit_hash, repo_path, result)

        return result

    def _filter_by_security(self, commits: list[GitCommit]) -> list[GitCommit]:
        """按安全级别过滤 commit 内容"""
        level = self.security_config.level
        keywords = [kw.lower() for kw in self.security_config.filter_keywords]

        filtered = []
        for c in commits:
            # 关键词过滤
            msg_lower = c.message.lower()
            if any(kw in msg_lower for kw in keywords):
                continue

            if level == "strict":
                # strict：只保留 message，清空文件列表和统计
                c.files_changed = []
                c.insertions = 0
                c.deletions = 0
            elif level == "balanced":
                # balanced：保留 message + 文件名 + 统计，不做额外处理
                pass
            elif level == "full":
                # full：保留所有信息（diff 在 get_file_change_summary 中按需获取）
                pass

            filtered.append(c)
        return filtered

    def _group_by_day(self, commits: list[GitCommit], repo_alias: str) -> list[DayCommits]:
        """按日期聚合 commit"""
        day_map: dict[date, DayCommits] = {}

        for c in commits:
            d = c.date.date()
            if d not in day_map:
                day_map[d] = DayCommits(
                    date=d,
                    weekday=_WEEKDAY_MAP[d.weekday()],
                    repo_alias=repo_alias,
                )
            day_map[d].commits.append(c)

        return sorted(day_map.values(), key=lambda d: d.date)
