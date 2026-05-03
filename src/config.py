"""
配置加载模块

支持：
  - YAML 配置文件读取
  - ${ENV_VAR} 环境变量替换
  - dataclass 结构化
  - 默认值填充
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ── 数据类定义 ────────────────────────────────────────────

@dataclass
class ProjectConfig:
    name: str = "MyProject"
    author: str = ""


@dataclass
class RepoConfig:
    path: str = "."
    branch: str = "main"
    alias: str = ""
    author: Optional[str] = None


@dataclass
class GitConfig:
    timezone: str = "Asia/Shanghai"
    branch_strategy: str = "merged"  # merged | all | current
    no_merges: bool = True


@dataclass
class SecurityConfig:
    level: str = "balanced"  # strict | balanced | full
    filter_keywords: list[str] = field(default_factory=lambda: [
        "password", "secret", "token", "api_key", "credential"
    ])
    max_diff_chars: int = 500


@dataclass
class LLMConfig:
    provider: str = "openai"  # openai | dashscope | ollama
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: Optional[str] = None
    temperature: float = 0.3


@dataclass
class RAGConfig:
    embedding_model: str = "shibing624/text2vec-base-chinese"
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 5
    incremental: bool = True


@dataclass
class ReportConfig:
    template: str = "standard"
    output_dir: str = "./reports"
    format: str = "markdown"  # markdown | docx | html
    auto_open: bool = True


@dataclass
class NotifyConfig:
    enabled: bool = False
    webhook: str = ""


@dataclass
class ScheduleConfig:
    cron: str = "0 17 * * 5"
    notify: NotifyConfig = field(default_factory=NotifyConfig)


@dataclass
class IngestConfig:
    watch_dirs: list[str] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=lambda: [".md", ".txt", ".docx"])


@dataclass
class AppConfig:
    """应用全局配置"""
    project: ProjectConfig = field(default_factory=ProjectConfig)
    repositories: list[RepoConfig] = field(default_factory=lambda: [RepoConfig()])
    git: GitConfig = field(default_factory=GitConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)

    # 运行时派生字段（不序列化）
    config_dir: str = field(default="", repr=False)
    data_dir: str = field(default="", repr=False)


# ── 环境变量替换 ───────────────────────────────────────────

_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env(value: str) -> str:
    """替换字符串中的 ${ENV_VAR} 为环境变量值"""
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name, "")
        if not env_val:
            print(f"⚠️ 环境变量 {var_name} 未设置，保留空值")
        return env_val
    return _ENV_PATTERN.sub(_replacer, value)


def _walk_and_expand(obj):
    """递归遍历 dict/list，对所有字符串值做环境变量替换"""
    if isinstance(obj, str):
        return _expand_env(obj)
    elif isinstance(obj, dict):
        return {k: _walk_and_expand(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_expand(item) for item in obj]
    return obj


# ── 加载函数 ──────────────────────────────────────────────

def _dict_to_dataclass(cls, data: dict):
    """将 dict 递归转换为 dataclass 实例"""
    if not isinstance(data, dict):
        return data

    import typing
    hints = typing.get_type_hints(cls)
    kwargs = {}

    for fname in cls.__dataclass_fields__:
        if fname in ("config_dir", "data_dir"):
            continue  # 运行时字段，跳过
        if fname not in data:
            continue  # 使用默认值

        ftype = hints.get(fname)
        val = data[fname]

        # 处理嵌套 dataclass（对象类型）
        if ftype and hasattr(ftype, "__dataclass_fields__") and isinstance(val, dict):
            kwargs[fname] = _dict_to_dataclass(ftype, val)
        # 处理 list 中的 dataclass（如 repositories）
        elif isinstance(val, list):
            if fname == "repositories":
                kwargs[fname] = [_dict_to_dataclass(RepoConfig, item) for item in val]
            else:
                kwargs[fname] = val
        else:
            kwargs[fname] = val

    return cls(**kwargs)


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为当前目录下的 config.yaml

    Returns:
        AppConfig 实例
    """
    config_path = Path(config_path).resolve()

    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}\n"
            f"请运行 wkr init 初始化配置"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 环境变量替换
    expanded = _walk_and_expand(raw)

    # 转换为 dataclass
    config = _dict_to_dataclass(AppConfig, expanded)

    # 填充运行时字段
    config.config_dir = str(config_path.parent)
    config.data_dir = str(config_path.parent / "data")

    # 展开 ~ 路径
    for repo in config.repositories:
        repo.path = str(Path(repo.path).expanduser().resolve())

    config.report.output_dir = str(
        Path(config.config_dir) / config.report.output_dir.lstrip("./")
    )

    return config


def find_config(start_dir: str | Path = ".") -> Path:
    """
    从 start_dir 向上查找 config.yaml

    Returns:
        config.yaml 的 Path

    Raises:
        FileNotFoundError: 未找到配置文件
    """
    current = Path(start_dir).resolve()
    while True:
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent

    raise FileNotFoundError(
        "未找到 config.yaml，请在项目目录下运行 wkr init"
    )
