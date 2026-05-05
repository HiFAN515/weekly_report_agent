"""
配置管理模块

功能：
  - 从 CLI 读写 config.yaml 的指定字段
  - 支持嵌套 key（如 llm.provider、security.level）
  - 支持 list 类型（如 repositories）的增删改
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_raw_config(config_path: str | Path) -> dict:
    """加载原始 config.yaml（dict 格式）"""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_raw_config(config_path: str | Path, data: dict):
    """保存 dict 到 config.yaml"""
    config_path = Path(config_path)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_nested(data: dict, key: str):
    """
    获取嵌套 key 的值

    示例：
      get_nested(data, "llm.provider") → data["llm"]["provider"]
      get_nested(data, "repositories") → data["repositories"]
    """
    parts = key.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def set_nested(data: dict, key: str, value):
    """
    设置嵌套 key 的值

    自动创建中间层 dict。
    """
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def parse_value(raw: str):
    """将字符串解析为合适的 Python 类型"""
    # 布尔值
    if raw.lower() in ("true", "yes", "1"):
        return True
    if raw.lower() in ("false", "no", "0"):
        return False
    # 整数
    try:
        return int(raw)
    except ValueError:
        pass
    # 浮点数
    try:
        return float(raw)
    except ValueError:
        pass
    # None
    if raw.lower() in ("null", "none", ""):
        return None
    # 字符串
    return raw


def add_repo(data: dict, path: str, branch: str = "main", alias: str = "", author: str = ""):
    """添加一个 Git 仓库到 repositories 列表"""
    if "repositories" not in data:
        data["repositories"] = []

    # 检查路径是否存在且是 Git 仓库
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return False, f"路径不存在: {resolved}"
    if not (resolved / ".git").exists():
        return False, f"不是 Git 仓库（缺少 .git 目录）: {resolved}"

    # 检查分支是否存在
    try:
        import git
        repo = git.Repo(str(resolved))
        remote_branches = [b.name.replace("origin/", "") for b in repo.remote().refs]
        local_branches = [b.name for b in repo.branches]
        all_branches = set(remote_branches + local_branches)
        if branch not in all_branches:
            available = ", ".join(sorted(all_branches)[:10])
            return False, f"分支 '{branch}' 不存在。可用分支: {available}"
    except Exception:
        pass  # 无法检查时跳过（允许后续采集时报错）

    # 检查是否已存在（路径 + 分支 组合去重）
    resolved_str = str(resolved)
    for repo_entry in data["repositories"]:
        existing_resolved = str(Path(repo_entry.get("path", "")).expanduser().resolve())
        if existing_resolved == resolved_str and repo_entry.get("branch") == branch:
            return False, f"仓库已存在: {repo_entry.get('path')} (分支: {branch})"

    entry = {"path": str(resolved), "branch": branch}
    if alias:
        entry["alias"] = alias
    if author:
        entry["author"] = author
    data["repositories"].append(entry)
    return True, f"已添加仓库: {resolved} (分支: {branch})"


def remove_repo(data: dict, path: str):
    """从 repositories 列表移除一个仓库"""
    if "repositories" not in data:
        return False, "未配置任何仓库"

    before = len(data["repositories"])
    data["repositories"] = [r for r in data["repositories"] if r.get("path") != path]
    if len(data["repositories"]) < before:
        return True, f"已移除仓库: {path}"
    return False, f"未找到仓库: {path}"


# ── 可配置字段说明 ───────────────────────────────────────

CONFIG_FIELDS = {
    "project.name": "项目名称",
    "project.author": "默认作者",
    "git.timezone": "时区（Asia/Shanghai, Asia/Tokyo, US/Eastern, Europe/London, UTC 等）",
    "git.branch_strategy": "分支策略（merged/all/current）",
    "git.no_merges": "过滤 merge commit（true/false）",
    "security.level": "安全等级（strict/balanced/full）",
    "security.max_diff_chars": "full 模式 diff 最大字符数",
    "llm.provider": "LLM 提供商（openai/anthropic/ollama）",
    "llm.model": "模型名称",
    "llm.api_key": "API Key",
    "llm.base_url": "自定义 API 地址",
    "llm.temperature": "温度（0.0-1.0）",
    "rag.embedding_model": "Embedding 模型",
    "rag.top_k": "RAG 检索返回条数",
    "rag.incremental": "增量索引（true/false）",
    "report.template": "默认周报模板",
    "report.output_dir": "周报输出目录",
    "report.format": "导出格式（markdown/docx/html）",
    "report.auto_open": "生成后自动打开（true/false）",
    "schedule.cron": "定时 cron 表达式",
    "schedule.notify.enabled": "Webhook 通知（true/false）",
    "schedule.notify.webhook": "Webhook URL",
}
