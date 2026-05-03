"""
Jinja2 模板引擎

功能：
  - 模板加载
  - 变量合并（config 默认值 + LLM 输出）
  - 渲染
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, TemplateNotFound


class TemplateEngine:
    """Jinja2 模板渲染引擎"""

    def __init__(self, templates_dir: str | Path):
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            keep_trailing_newline=True,
        )

    def render(self, template_name: str, data: dict, config_defaults: dict = None) -> str:
        """
        渲染模板

        Args:
            template_name: 模板名（不含 .md.j2 后缀）
            data: LLM 输出的结构化数据
            config_defaults: 从 config 填充的默认值（author、year 等）

        Returns:
            渲染后的 Markdown 文本
        """
        # 加载模板 Schema 获取默认值
        schema_defaults = self._load_schema_defaults(template_name)

        # 合并：schema 默认值 < config 默认值 < LLM 输出
        merged = {**schema_defaults}
        if config_defaults:
            merged.update(config_defaults)
        merged.update(data)

        # 加载模板
        template_file = f"{template_name}.md.j2"
        try:
            template = self.env.get_template(template_file)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"模板文件不存在: {self.templates_dir / template_file}\n"
                f"可用模板: {', '.join(self.list_templates())}"
            )

        return template.render(**merged)

    def list_templates(self) -> list[str]:
        """列出可用模板"""
        templates = []
        for f in self.templates_dir.glob("*.md.j2"):
            templates.append(f.stem.replace(".md", ""))
        return sorted(templates)

    def _load_schema_defaults(self, template_name: str) -> dict:
        """从 .schema.yaml 加载默认值"""
        schema_path = self.templates_dir / f"{template_name}.schema.yaml"
        if not schema_path.exists():
            return {}

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = yaml.safe_load(f) or {}

        defaults = {}
        variables = schema.get("variables", {})
        for var_name, var_def in variables.items():
            if isinstance(var_def, dict) and "default" in var_def:
                defaults[var_name] = var_def["default"]
        return defaults


def build_config_defaults(config, week_start: date) -> dict:
    """从 config 和 week_start 构建模板默认值"""
    from datetime import timedelta

    week_end = week_start + timedelta(days=6)
    iso = week_start.isocalendar()

    return {
        "author": config.project.author,
        "year": iso[0],
        "week_num": iso[1],
        "date_range": f"{week_start.isoformat()} 至 {week_end.isoformat()}",
        "project_name": config.project.name,
    }
