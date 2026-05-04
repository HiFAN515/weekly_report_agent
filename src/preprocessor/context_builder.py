"""
数据预处理 + 上下文组装 + Token 预算控制

功能：
  - 读取本周日志
  - 聚合 Git 统计
  - 安全过滤
  - Token 预算分配
  - 组装上下文文本
"""

from __future__ import annotations

from datetime import date, timedelta

from src.collectors.git_collector import DayCommits, GitCollector
from src.config import AppConfig
from src.storage.log_store import LogStore, format_week_summary_markdown


# ── Token 估算 ───────────────────────────────────────────

from src.preprocessor.token_estimator import estimate_tokens


# ── 预算组装 ─────────────────────────────────────────────

def assemble_with_budget(summary: str, logs: str, history: str,
                         llm_context_window: int, mode: str = "react") -> tuple[str, dict]:
    """
    按优先级分配 token 预算，组装上下文

    预算分配（按优先级递减）：
      1. 系统 prompt + 输出预留（固定）
      2. 数据摘要（必留，通常很短）
      3. 详细日志（优先最新一天，其余摘要化或截断）
      4. 历史上下文（固定 top_k 条，每条截断）

    Returns:
        (组装后的上下文文本, 预算信息 dict)
    """
    system_overhead = 2000 if mode == "react" else 3000
    output_reserve = 4000
    total_budget = llm_context_window - system_overhead - output_reserve

    # 按优先级分配
    summary_budget = min(estimate_tokens(summary), int(total_budget * 0.1))
    history_budget = int(total_budget * 0.2)
    logs_budget = total_budget - summary_budget - history_budget

    # 截断摘要
    truncated_summary = _truncate_to_budget(summary, summary_budget)

    # 截断日志（保留最新内容）
    truncated_logs = _truncate_to_budget(logs, logs_budget)

    # 截断历史
    truncated_history = _truncate_to_budget(history, history_budget)

    budget_info = {
        "total_budget": total_budget,
        "summary_budget": summary_budget,
        "logs_budget": logs_budget,
        "history_budget": history_budget,
        "summary_used": estimate_tokens(truncated_summary),
        "logs_used": estimate_tokens(truncated_logs),
        "history_used": estimate_tokens(truncated_history),
    }

    context = f"""=== 本周数据摘要 ===
{truncated_summary}

=== 本周详细日志 ===
{truncated_logs}

=== 相关历史背景 ===
{truncated_history}"""

    return context, budget_info


def _truncate_to_budget(text: str, budget_tokens: int) -> str:
    """截断文本到指定 token 预算"""
    if estimate_tokens(text) <= budget_tokens:
        return text
    # 按比例截断
    ratio = budget_tokens / max(estimate_tokens(text), 1)
    target_chars = int(len(text) * ratio * 0.9)  # 留 10% 余量
    return text[:target_chars] + "\n...(内容已截断)"


# ── 上下文构建器 ─────────────────────────────────────────

class ContextBuilder:
    """数据预处理 + 上下文组装"""

    def __init__(self, config: AppConfig, log_store: LogStore,
                 git_collector: GitCollector, vector_store=None):
        self.config = config
        self.log_store = log_store
        self.git_collector = git_collector
        self.vector_store = vector_store
        self._last_budget_info: dict = {}

    def build(self, week_start: date, mode: str = "react") -> tuple[str, list[DayCommits], dict]:
        """
        完整预处理流程

        Args:
            week_start: 本周一日期
            mode: "react" 或 "fallback"

        Returns:
            (上下文文本, 本周 DayCommits 列表, 本周统计数据)
        """
        # 1. 采集本周 Git 数据
        week_days = self.git_collector.collect_all_repos(
            self.config.repositories,
            since=week_start,
            until=week_start + timedelta(days=6),
            global_author=self.config.project.author,
        )

        # 2. 保存日志文件 + 索引到向量库
        for day in week_days:
            self.log_store.save_git_day(day, self.config.security.level)
            if self.vector_store:
                content = self.log_store.get_day_content(day.date)
                if content:
                    self.vector_store.index_log(
                        day.date.isoformat(), content, "git", day.repo_alias
                    )

        # 3. 聚合统计
        week_stats = self.git_collector.get_week_stats(week_days)

        # 4. 构建摘要
        summary = format_week_summary_markdown(week_days, week_stats)

        # 5. 构建详细日志
        log_parts = []
        for day in week_days:
            log_parts.append(
                f"[{day.weekday} {day.date.isoformat()}] {day.repo_alias}: "
                f"{len(day.commits)} commits"
            )
            for c in day.commits:
                prefix = "[低信息量] " if c.is_low_quality else ""
                files = ", ".join(c.files_changed[:5]) if c.files_changed else ""
                log_parts.append(
                    f"  - {prefix}{c.hash} {c.message.split(chr(10))[0]}"
                )
                if files:
                    log_parts.append(f"    文件: {files} | +{c.insertions}/-{c.deletions}")
        logs_text = "\n".join(log_parts)

        # 6. RAG 检索历史上下文
        history = ""
        if self.vector_store and self.vector_store.total_chunks > 0:
            week_logs_for_query = summary + "\n" + logs_text
            results = self.vector_store.search_by_similarity(
                query_text=week_logs_for_query,
                exclude_week=week_start.isoformat(),
                top_k=self.config.rag.top_k,
            )
            if results:
                history_parts = []
                for r in results:
                    date_str = r.get("date", "")
                    source = r.get("source", "")
                    repo = r.get("repo", "")
                    meta_info = f"[来源: {date_str}]"
                    if repo:
                        meta_info += f" {repo}"
                    # 从 log_store 获取原文
                    if date_str:
                        from datetime import datetime as dt
                        try:
                            d = dt.fromisoformat(date_str).date()
                            original = self.log_store.get_day_content(d)
                            if original:
                                # 截断
                                history_parts.append(
                                    f"{meta_info}\n{original[:500]}"
                                )
                        except (ValueError, OSError):
                            pass
                history = "\n\n".join(history_parts)

        if not history:
            history = "（暂无历史上下文）"

        # 7. 按预算组装
        llm_window = 128000  # 默认上下文窗口，后续从模型配置读取
        context, budget_info = assemble_with_budget(
            summary=summary,
            logs=logs_text,
            history=history,
            llm_context_window=llm_window,
            mode=mode,
        )

        self._last_budget_info = budget_info
        return context, week_days, week_stats

    def build_debug(self, week_start: date) -> str:
        """
        --dump-context 专用，输出预处理上下文供调试

        Returns:
            包含预算信息和完整上下文的调试文本
        """
        context, week_days, week_stats = self.build(week_start)
        bi = self._last_budget_info

        debug = f"""Token 预算分配：
  总预算: {bi['total_budget']} tokens
  摘要: {bi['summary_used']}/{bi['summary_budget']}
  日志: {bi['logs_used']}/{bi['logs_budget']}
  历史: {bi['history_used']}/{bi['history_budget']}

{context}"""
        return debug
