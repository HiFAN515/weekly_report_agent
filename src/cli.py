"""
CLI 入口（Click）

命令：
  wkr init      初始化配置向导
  wkr log       记录今日工作
  wkr report    生成周报
  wkr show      查看日志
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import load_config, find_config, AppConfig

console = Console()


def _get_project_root() -> Path:
    """查找项目根目录（含 config.yaml）"""
    try:
        return find_config().parent
    except FileNotFoundError:
        console.print("[red]❌ 未找到 config.yaml，请先运行 wkr init[/red]")
        sys.exit(1)


def _load_cfg() -> AppConfig:
    """加载配置"""
    config_path = find_config()
    return load_config(config_path)


def _get_week_start(d: date = None) -> date:
    """获取指定日期所在周的周一"""
    d = d or date.today()
    return d - timedelta(days=d.weekday())


# ── 主命令 ────────────────────────────────────────────────

HELP_EPILOG = """快速参考

  wkr init                            初始化配置向导

  wkr log --from-git                  从 Git 采集今日提交
  wkr log --manual                    手动输入工作日志
  wkr log --file PATH                 从文件导入日志
  wkr log --date YYYY-MM-DD           指定日期（默认今天）

  wkr report                          生成本周周报
  wkr report --week YYYY-MM-DD        指定周
  wkr report --template NAME          指定模板
  wkr report --dry-run                输出 JSON 不渲染
  wkr report --dump-context           离线调试（不调用 LLM）

  wkr show                            查看今日日志
  wkr show --date YYYY-MM-DD          指定日期
  wkr show --week                     本周汇总
  wkr show --repos                    查看已配置的 Git 仓库

  wkr search "关键词"                  语义搜索历史日志
  wkr search "关键词" --top-k 10      指定返回数量

  wkr ingest --dir ~/notes/           批量摄入目录下的文档
  wkr ingest --file report.md         导入单个文件

  wkr template --list                 列出可用模板
  wkr template --new                  创建自定义模板

  wkr config                          查看当前配置
  wkr config --list-fields            列出所有可配置字段
  wkr config --set KEY VALUE          修改配置项
  wkr config --add-repo PATH          添加 Git 仓库
  wkr config --remove-repo PATH       移除 Git 仓库

各命令详细选项请运行: wkr <command> --help
"""


class WkrGroup(click.Group):
    """自定义 Group，保留 epilog 原始换行格式"""
    def format_epilog(self, ctx, formatter):
        if self.epilog:
            formatter.write_paragraph()
            with formatter.indentation():
                for line in self.epilog.split("\n"):
                    formatter.write_text(line)


@click.group(cls=WkrGroup, epilog=HELP_EPILOG)
@click.version_option(version="0.1.0")
def main():
    """wkr — 周报自动生成 Agent"""
    pass


# ── wkr init ─────────────────────────────────────────────

@main.command(short_help="初始化配置向导")
def init():
    """初始化配置向导

    交互式创建 config.yaml，包含项目信息、Git 仓库、LLM 配置等。
    首次使用必须先运行此命令。

    \b
    示例：
      wkr init
    """
    console.print(Panel("🔧 周报 Agent 初始化向导", style="bold blue"))

    name = click.prompt("项目名称", default="MyProject")
    repo_path = click.prompt("Git 仓库路径", default=".")
    author = click.prompt("你的 Git 用户名", default="", show_default=False)
    if not author:
        import git
        try:
            author = git.Repo(repo_path).config_reader().get_value("user", "name", "")
        except Exception:
            author = "Unknown"

    template = click.prompt("周报模板", default="standard",
                            type=click.Choice(["standard", "minimal", "project"]))

    provider = click.prompt("LLM 提供商", default="1",
                            type=click.Choice(["1", "2", "3"]))
    provider_map = {"1": "openai", "2": "anthropic", "3": "ollama"}
    provider_name = provider_map[provider]

    if provider_name in ("openai", "anthropic"):
        console.print("\n[yellow]⚠️ 提醒：使用云端 LLM 时，您的工作日志数据将被传输至第三方服务器。[/yellow]")
        console.print("[yellow]   对于敏感项目，建议选择本地 Ollama。[/yellow]\n")

    model = click.prompt("模型名称",
                         default="claude-sonnet-4-20250514" if provider_name == "anthropic"
                         else "gpt-4o-mini" if provider_name == "openai"
                         else "qwen2.5:7b")
    security = click.prompt("安全等级", default="balanced",
                            type=click.Choice(["strict", "balanced", "full"]))

    # 写入 config.yaml
    import yaml
    config_data = {
        "project": {"name": name, "author": author},
        "repositories": [{"path": repo_path, "branch": "main", "alias": ""}],
        "git": {"timezone": "Asia/Shanghai", "branch_strategy": "merged", "no_merges": True},
        "security": {
            "level": security,
            "filter_keywords": ["password", "secret", "token", "api_key", "credential"],
            "max_diff_chars": 500,
        },
        "llm": {"provider": provider_name, "model": model, "api_key": "", "base_url": None, "temperature": 0.3},
        "rag": {"embedding_model": "shibing624/text2vec-base-chinese", "chunk_size": 300, "chunk_overlap": 50, "top_k": 5, "incremental": True},
        "report": {"template": template, "output_dir": "./reports", "format": "markdown", "auto_open": True},
        "schedule": {"cron": "0 17 * * 5", "notify": {"enabled": False, "webhook": ""}},
        "ingest": {"watch_dirs": [], "supported_formats": [".md", ".txt", ".docx"]},
    }

    config_path = Path("config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    console.print(f"[green]✓ 配置已保存至 {config_path}[/green]")
    console.print(f"[dim]请设置环境变量: export OPENAI_API_KEY=your_key[/dim]")


# ── wkr log ──────────────────────────────────────────────

@main.command(short_help="记录今日工作")
@click.option("--from-git", is_flag=True, help="从 Git 采集今日提交")
@click.option("--manual", is_flag=True, help="手动输入工作日志")
@click.option("--file", "filepath", type=click.Path(), help="从文件导入日志")
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]),
              help="指定日期（默认今天）")
def log(from_git, manual, filepath, target_date):
    """记录今日工作

    支持三种采集方式：Git 自动采集、手动输入、文件导入。
    数据保存到 data/logs/ 目录下，生成周报时会自动读取。

    \b
    示例：
      wkr log --from-git                  采集今日本地 Git 提交
      wkr log --from-git --date 2026-05-01
                                          采集指定日期的 Git 提交
      wkr log --manual                    交互式手动输入（Ctrl+D 结束）
      wkr log --file notes.md             从文件导入到今天的日志
      echo "做了XX" | wkr log --manual    管道输入

    \b
    注意：
      --from-git 采集的是本地仓库的 commit，不需要先 push。
      采集后会询问是否补充说明。
    """
    cfg = _load_cfg()
    d = (target_date.date() if target_date else date.today())

    if from_git:
        from src.collectors.git_collector import GitCollector
        from src.storage.cache_store import GitStatsCache
        from src.storage.log_store import LogStore

        log_store = LogStore(cfg.data_dir)
        cache = GitStatsCache(Path(cfg.data_dir) / "cache" / "git_stats.db")
        collector = GitCollector(cfg.git, cfg.security, cache)

        days = collector.collect_all_repos(cfg.repositories, since=d, until=d,
                                           global_author=cfg.project.author)
        if not days:
            console.print("[yellow]今日无 Git 提交[/yellow]")
            return

        for day in days:
            log_store.save_git_day(day, cfg.security.level)
            console.print(f"[green]✓ 已采集 {day.date} Git 提交 {len(day.commits)} 条（{day.repo_alias}）[/green]")
            for c in day.commits:
                prefix = "[低信息量] " if c.is_low_quality else ""
                console.print(f"  - {c.hash} {prefix}{c.message.split(chr(10))[0][:60]}")

        # 询问是否补充
        if click.confirm("是否补充说明？", default=False):
            extra = click.prompt("> ", prompt_suffix="")
            log_store.save_manual(d, extra)
            console.print("[green]✓ 已保存补充说明[/green]")

    elif manual:
        from src.storage.log_store import LogStore
        from src.collectors.manual_collector import ManualCollector

        log_store = LogStore(cfg.data_dir)
        mc = ManualCollector(log_store)
        mc.collect_interactive(d)

    elif filepath:
        from src.storage.log_store import LogStore
        from src.collectors.manual_collector import ManualCollector

        log_store = LogStore(cfg.data_dir)
        mc = ManualCollector(log_store)
        mc.collect_from_file(filepath, d)

    else:
        console.print("[yellow]请指定采集方式: --from-git / --manual / --file[/yellow]")
        console.print("[dim]示例: wkr log --from-git[/dim]")


# ── wkr report ───────────────────────────────────────────

@main.command()
@click.option("--week", type=click.DateTime(formats=["%Y-%m-%d"]),
              help="指定周的日期（自动找到该周周一）")
@click.option("--template", "template_name", default=None, help="指定模板")
@click.option("--dry-run", is_flag=True, help="输出原始 JSON，不渲染模板")
@click.option("--dump-context", is_flag=True, help="输出预处理上下文（离线调试）")
@click.option("--format", "export_format", default=None,
              type=click.Choice(["markdown", "docx", "html"]),
              help="导出格式（默认读 config.yaml）")
def report(week, template_name, dry_run, dump_context, export_format):
    """生成周报

    读取本周 Git 日志 + 手动记录，通过 LLM 提取结构化数据，
    经两级 Schema 校验后用 Jinja2 模板渲染为 Markdown 周报。

    \b
    示例：
      wkr report                          生成本周周报（使用默认模板）
      wkr report --week 2026-04-28        生成指定周的周报
      wkr report --template minimal       使用极简模板
      wkr report --format docx            导出为 DOCX
      wkr report --format html            导出为 HTML
      wkr report --dry-run                只输出 LLM 提取的 JSON，不渲染
      wkr report --dump-context           输出预处理上下文（不调用 LLM，调试用）

    \b
    工作流程：
      1. 数据预处理：读日志 → 聚合统计 → 安全过滤 → token 预算分配
      2. LLM 提取：从上下文中提取结构化 JSON（ReAct 或降级模式）
      3. 两级校验：全局 JSON Schema → 模板 Schema
      4. 模板渲染：Jinja2 填充模板，输出到 reports/ 目录

    \b
    输出路径：
      reports/{start}_{end}_weekly_report.md
    """
    cfg = _load_cfg()
    week_start = _get_week_start(week.date() if week else None)
    template_name = template_name or cfg.report.template

    # 初始化组件
    from src.storage.log_store import LogStore
    from src.storage.cache_store import GitStatsCache
    from src.collectors.git_collector import GitCollector
    from src.preprocessor.context_builder import ContextBuilder

    log_store = LogStore(cfg.data_dir)
    cache = GitStatsCache(Path(cfg.data_dir) / "cache" / "git_stats.db")
    git_collector = GitCollector(cfg.git, cfg.security, cache)

    # 初始化 VectorStore（如果 RAG 依赖可用）
    vector_store = None
    if cfg.rag.incremental:
        try:
            from src.storage.vector_store import VectorStore, EmbeddingModel
            embedding_model = EmbeddingModel(cfg.rag.embedding_model)
            vector_store = VectorStore(Path(cfg.data_dir) / "index", embedding_model)
        except ImportError:
            console.print("[dim]⚠️ RAG 依赖未安装，跳过语义检索（pip install faiss-cpu sentence-transformers）[/dim]")
        except Exception as e:
            console.print(f"[dim]⚠️ RAG 初始化失败，跳过语义检索: {e}[/dim]")

    ctx_builder = ContextBuilder(cfg, log_store, git_collector, vector_store)

    # --dump-context：离线调试模式
    if dump_context:
        console.print("[bold]📊 数据预处理...[/bold]")
        debug = ctx_builder.build_debug(week_start)
        console.print(debug)
        return

    # 数据预处理
    console.print("[bold]📊 数据预处理...[/bold]")
    mode = "fallback"  # Phase 1 简化，后续由 agent 自动检测
    context, week_days, week_stats = ctx_builder.build(week_start, mode=mode)
    console.print(f"  ── Git 统计：{week_stats['git_commits']} commits, "
                  f"+{week_stats['insertions']}/-{week_stats['deletions']}")

    # LLM 提取
    console.print("[bold]🤖 Agent 提取结构化数据...[/bold]")
    from src.agent.react_agent import ReportAgent
    from src.agent.tools import ToolExecutor
    from src.agent.schema import ReportSchemaValidator

    # 构建 git_repos 映射 {alias: path}
    git_repos = {repo.alias or Path(repo.path).name: repo.path
                 for repo in cfg.repositories}

    tool_executor = ToolExecutor(
        week_days=week_days,
        week_stats=week_stats,
        day_contents={d.isoformat(): log_store.get_day_content(d)
                      for d in log_store.get_week_dates(week_start)},
        security_level=cfg.security.level,
        max_diff_chars=cfg.security.max_diff_chars,
        git_repos=git_repos,
    )

    agent = ReportAgent(cfg.llm)
    console.print(f"  ── 模式: {agent.mode}")

    validator = ReportSchemaValidator(Path(cfg.config_dir) / "templates")

    # 带重试的生成 + 两级校验
    max_retries = 3
    report_data = None
    for attempt in range(max_retries):
        try:
            report_data = agent.generate(context, tool_executor)

            # 第 1 级：全局 JSON Schema 校验
            valid, errors = validator.validate(report_data)
            if not valid:
                raise Exception(f"全局 Schema 校验失败: {errors}")
            console.print("  ── 全局 Schema 校验通过 ✓")

            # 第 2 级：模板 Schema 二次校验
            valid, errors = validator.validate_template(report_data, template_name)
            if not valid:
                raise Exception(f"模板校验失败: {errors}")
            console.print("  ── 模板 Schema 校验通过 ✓")

            # 填充默认值
            report_data = validator.fill_defaults(report_data, template_name)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                console.print(f"[yellow]  ⚠️ 第 {attempt + 1} 次失败: {str(e)[:80]}[/yellow]")
                console.print(f"[yellow]  正在重试...[/yellow]")
            else:
                console.print(f"[red]❌ 重试 {max_retries} 次后仍失败: {e}[/red]")
                sys.exit(1)

    # --dry-run：输出 JSON
    if dry_run:
        import json
        console.print(json.dumps(report_data, ensure_ascii=False, indent=2))
        return

    # 模板渲染
    console.print(f"[bold]📝 模板渲染...[/bold]")
    from src.generator.template_engine import TemplateEngine, build_config_defaults

    template_engine = TemplateEngine(Path(cfg.config_dir) / "templates")
    defaults = build_config_defaults(cfg, week_start)
    rendered = template_engine.render(template_name, report_data, defaults)
    console.print(f"  ── 使用模板: {template_name}.md.j2")

    # 导出
    from src.generator.exporter import Exporter
    exporter = Exporter(cfg.report.output_dir)
    week_end = week_start + timedelta(days=6)
    fmt = export_format or cfg.report.format

    if fmt == "docx":
        filepath = exporter.export_docx(rendered, week_start, week_end)
    elif fmt == "html":
        filepath = exporter.export_html(rendered, week_start, week_end)
    else:
        filepath = exporter.export_markdown(rendered, week_start, week_end)

    console.print(f"[green]✓ 周报已生成: {filepath}[/green]")

    # 自动打开
    if cfg.report.auto_open and click.confirm("打开预览？", default=True):
        click.launch(str(filepath), locate=True)


# ── wkr show ─────────────────────────────────────────────

@main.command(short_help="查看日志")
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]),
              help="指定日期")
@click.option("--week", is_flag=True, help="显示本周汇总")
@click.option("--repos", is_flag=True, help="显示当前配置的 Git 仓库")
def show(target_date, week, repos):
    """查看已记录的工作日志

    \b
    示例：
      wkr show                            查看今日日志
      wkr show --date 2026-05-01          查看指定日期
      wkr show --week                     查看本周汇总（所有天合并）
      wkr show --repos                    查看当前配置的 Git 仓库
    """
    cfg = _load_cfg()

    if repos:
        table = Table(title="已配置的 Git 仓库")
        table.add_column("#", style="dim")
        table.add_column("路径", style="cyan")
        table.add_column("别名", style="green")
        table.add_column("分支", style="magenta")
        table.add_column("Author", style="yellow")

        for i, repo in enumerate(cfg.repositories, 1):
            alias = repo.alias or Path(repo.path).name
            author = repo.author or f"{cfg.project.author} (默认)"
            table.add_row(str(i), repo.path, alias, repo.branch, author)

        console.print(table)
        return

    from src.storage.log_store import LogStore
    log_store = LogStore(cfg.data_dir)

    if week:
        week_start = _get_week_start()
        content = log_store.get_week_content(week_start)
        if content:
            console.print(Panel(content, title="本周日志", border_style="blue"))
        else:
            console.print("[yellow]本周暂无日志[/yellow]")
    else:
        d = target_date.date() if target_date else date.today()
        content = log_store.get_day_content(d)
        if content:
            console.print(Panel(content, title=f"{d.isoformat()} 日志", border_style="blue"))
        else:
            console.print(f"[yellow]{d.isoformat()} 暂无日志[/yellow]")


# ── wkr search ───────────────────────────────────────────

@main.command(short_help="语义搜索历史日志")
@click.argument("query")
@click.option("--top-k", default=5, help="返回结果数量")
def search(query, top_k):
    """语义搜索历史日志

    使用 Embedding 模型对查询文本和历史日志做相似度匹配。

    \b
    示例：
      wkr search "用户认证"
      wkr search "首页性能优化" --top-k 3
    """
    cfg = _load_cfg()
    try:
        from src.storage.vector_store import VectorStore, EmbeddingModel
    except ImportError:
        console.print("[red]❌ 需要安装 RAG 依赖: pip install faiss-cpu sentence-transformers[/red]")
        sys.exit(1)

    embedding_model = EmbeddingModel(cfg.rag.embedding_model)
    vector_store = VectorStore(Path(cfg.data_dir) / "index", embedding_model)

    if vector_store.total_chunks == 0:
        console.print("[yellow]向量索引为空，请先运行 wkr report 或 wkr ingest 建立索引[/yellow]")
        return

    results = vector_store.search_by_similarity(query, top_k=top_k)
    if not results:
        console.print("[yellow]未找到相关历史记录[/yellow]")
        return

    table = Table(title=f"搜索结果: \"{query}\"")
    table.add_column("日期", style="cyan")
    table.add_column("来源", style="green")
    table.add_column("距离", style="magenta")
    table.add_column("仓库", style="blue")

    for r in results:
        table.add_row(
            r.get("date", ""),
            r.get("source", ""),
            f"{r['score']:.4f}",
            r.get("repo", ""),
        )
    console.print(table)


# ── wkr ingest ───────────────────────────────────────────

@main.command(short_help="摄入文档到向量索引")
@click.option("--dir", "dirpath", type=click.Path(), help="扫描目录下的所有文档")
@click.option("--file", "filepath", type=click.Path(), help="导入单个文件")
def ingest(dirpath, filepath):
    """摄入用户文档，建立语义索引

    支持 .md / .txt / .docx 格式。摄入后可通过 wkr search 搜索。

    \b
    示例：
      wkr ingest --dir ~/notes/          扫描目录下所有文档
      wkr ingest --file report.md        导入单个文件
    """
    cfg = _load_cfg()
    try:
        from src.storage.vector_store import VectorStore, EmbeddingModel
        from src.collectors.doc_collector import DocCollector
    except ImportError:
        console.print("[red]❌ 需要安装 RAG 依赖: pip install faiss-cpu sentence-transformers[/red]")
        sys.exit(1)

    embedding_model = EmbeddingModel(cfg.rag.embedding_model)
    vector_store = VectorStore(Path(cfg.data_dir) / "index", embedding_model)
    doc_collector = DocCollector(vector_store)

    if dirpath:
        console.print(f"[bold]📂 扫描目录: {dirpath}[/bold]")
        file_count, chunk_count = doc_collector.ingest_dir(
            dirpath, cfg.rag.chunk_size, cfg.rag.chunk_overlap
        )
        console.print(f"[green]✓ 已摄入 {file_count} 个文件，生成 {chunk_count} 个 chunk[/green]")
    elif filepath:
        console.print(f"[bold]📄 导入文件: {filepath}[/bold]")
        count = doc_collector.ingest_file(
            filepath, cfg.rag.chunk_size, cfg.rag.chunk_overlap
        )
        console.print(f"[green]✓ 已导入，生成 {count} 个 chunk[/green]")
    else:
        console.print("[yellow]请指定摄入方式: --dir 或 --file[/yellow]")
        console.print("[dim]示例: wkr ingest --dir ~/notes/[/dim]")


# ── wkr template ─────────────────────────────────────────

@main.command(short_help="模板管理")
@click.option("--list", "list_templates", is_flag=True, help="列出可用模板")
@click.option("--new", is_flag=True, help="创建自定义模板")
def template(list_templates, new):
    """管理周报模板

    \b
    示例：
      wkr template --list            列出所有可用模板
      wkr template --new             交互式创建新模板
    """
    cfg = _load_cfg()
    templates_dir = Path(cfg.config_dir) / "templates"

    if list_templates:
        from src.generator.template_engine import TemplateEngine
        engine = TemplateEngine(templates_dir)
        templates = engine.list_templates()
        if not templates:
            console.print("[yellow]未找到模板[/yellow]")
            return
        for t in templates:
            marker = " (默认)" if t == cfg.report.template else ""
            console.print(f"  📄 {t}{marker}")
        return

    if new:
        name = click.prompt("模板名称", default="custom")
        md_path = templates_dir / f"{name}.md.j2"
        schema_path = templates_dir / f"{name}.schema.yaml"

        if md_path.exists():
            if not click.confirm(f"模板 {name} 已存在，覆盖？"):
                return

        # 交互式选择模板内容
        console.print("\n[bold]选择模板包含的内容（y/n）：[/bold]")

        sections = {
            "title": ("标题（项目名 + 周数 + 日期 + 作者）", True),
            "highlights": ("核心成果列表", True),
            "daily_work": ("按天详细工作", True),
            "issues": ("问题与风险表格", True),
            "next_week": ("下周计划", True),
            "data_summary": ("数据摘要（commit 数、文件数等）", True),
        }

        selected = {}
        for key, (desc, default) in sections.items():
            selected[key] = click.confirm(f"  {desc}？", default=default)

        # 标题样式选择
        title_style = "full"
        if selected["title"]:
            console.print("\n标题样式：")
            console.print("  1. 完整：# 项目名 — W周数\\n> 日期范围 | 作者")
            console.print("  2. 简洁：# 项目名 W周数")
            console.print("  3. 不要标题")
            style = click.prompt("选择", default="1", type=click.Choice(["1", "2", "3"]))
            title_style = {"1": "full", "2": "simple", "3": "none"}[style]

        # 生成模板
        md_parts = []
        schema_parts = []

        # 标题
        if title_style == "full":
            md_parts.append(f"# {{{{ project_name }}}} 周报 — W{{{{ week_num }}}}\n> {{{{ date_range }}}} | {{{{ author }}}}")
        elif title_style == "simple":
            md_parts.append(f"# {{{{ project_name }}}} W{{{{ week_num }}}}")

        # 核心成果
        if selected["highlights"]:
            md_parts.append("## 核心成果\n{% for item in highlights %}\n- {{ item }}\n{% endfor %}")
            schema_parts.append("  highlights:\n    type: list\n    items: string\n    min: 1\n    required: true")

        # 按天工作
        if selected["daily_work"]:
            md_parts.append("## 本周工作\n{% for day in daily_work %}\n**{{ day.weekday }} ({{ day.date }})**\n{% for task in day.tasks %}\n- {{ task }}\n{% endfor %}\n{% endfor %}")
            schema_parts.append("  daily_work:\n    type: list\n    items:\n      type: object\n      properties:\n        date: { type: string }\n        weekday: { type: string }\n        tasks: { type: list, items: string }\n    required: true")

        # 问题
        if selected["issues"]:
            md_parts.append("## 问题与风险\n{% if issues %}\n| 问题 | 状态 |\n|------|------|\n{% for issue in issues %}\n| {{ issue.description }} | {{ issue.status }} |\n{% endfor %}\n{% else %}\n本周无遗留问题 ✅\n{% endif %}")
            schema_parts.append("  issues:\n    type: list\n    items:\n      type: object\n      properties:\n        description: { type: string }\n        status: { type: string, enum: [已解决, 处理中, 待解决, 已搁置] }\n    required: false")

        # 下周计划
        if selected["next_week"]:
            md_parts.append("## 下周计划\n{% for plan in next_week %}\n- [ ] {{ plan }}\n{% endfor %}")
            schema_parts.append("  next_week:\n    type: list\n    items: string\n    required: true")

        # 数据摘要
        if selected["data_summary"]:
            md_parts.append("---\n> Git {{ data_summary.git_commits }} commits | +{{ data_summary.insertions }} / -{{ data_summary.deletions }} | {{ data_summary.files_changed }} files")
            schema_parts.append("  data_summary:\n    type: object\n    required: true")

        # 组合
        md_content = "\n\n".join(md_parts) + "\n"
        schema_content = "variables:\n" + "\n".join(schema_parts) + """
  author:
    type: string
    source: config
    default: "Unknown"
  year:
    type: integer
    source: computed
  week_num:
    type: integer
    source: computed
  date_range:
    type: string
    source: computed
  project_name:
    type: string
    source: config
    default: "MyProject"
"""

        md_path.write_text(md_content, encoding="utf-8")
        schema_path.write_text(schema_content, encoding="utf-8")
        console.print(f"\n[green]✓ 模板已创建:[/green]")
        console.print(f"  📄 {md_path}")
        console.print(f"  📋 {schema_path}")
        console.print(f"[dim]使用: wkr report --template {name}[/dim]")
        console.print(f"[dim]编辑模板: {md_path}[/dim]")
        return

    console.print("[yellow]请指定操作: --list 或 --new[/yellow]")


# ── wkr config ───────────────────────────────────────────

@main.command(short_help="配置管理")
@click.option("--show", is_flag=True, help="显示当前配置")
@click.option("--set", "set_key", nargs=2, type=str, default=None,
              metavar="KEY VALUE", help="设置配置值（如: llm.model gpt-4o）")
@click.option("--add-repo", "add_repo_path", type=str, default=None,
              help="添加 Git 仓库路径")
@click.option("--remove-repo", "remove_repo_path", type=str, default=None,
              help="移除 Git 仓库路径")
@click.option("--list-fields", is_flag=True, help="列出所有可配置字段")
def config(show, set_key, add_repo_path, remove_repo_path, list_fields):
    """配置管理

    在 CLI 中查看和修改 config.yaml，不用手动编辑文件。

    \b
    示例：
      wkr config --show                     查看当前配置
      wkr config --list-fields              列出所有可配置字段
      wkr config --set llm.model gpt-4o     修改 LLM 模型
      wkr config --set report.format docx   设置默认导出格式
      wkr config --set security.level strict
      wkr config --add-repo ~/projects/backend
      wkr config --remove-repo ~/projects/old-repo
    """
    from src.config import find_config
    from src.config_manager import (
        load_raw_config, save_raw_config, get_nested, set_nested,
        parse_value, add_repo, remove_repo, CONFIG_FIELDS,
    )

    config_path = find_config()

    if list_fields:
        data = load_raw_config(config_path)

        # 显示 repositories
        repos = data.get("repositories", [])
        if repos:
            repo_table = Table(title="Git 仓库")
            repo_table.add_column("#", style="dim")
            repo_table.add_column("路径", style="cyan")
            repo_table.add_column("别名", style="green")
            repo_table.add_column("分支", style="magenta")
            repo_table.add_column("Author", style="yellow")
            for i, repo in enumerate(repos, 1):
                alias = repo.get("alias") or Path(repo.get("path", "")).name or "—"
                author = repo.get("author") or "（默认）"
                repo_table.add_row(str(i), repo.get("path", ""), alias, repo.get("branch", "main"), author)
            console.print(repo_table)
            console.print("[dim]  添加: wkr config --add-repo PATH | 移除: wkr config --remove-repo PATH[/dim]\n")

        # 显示简单字段
        table = Table(title="配置字段")
        table.add_column("Key", style="cyan")
        table.add_column("说明", style="green")
        table.add_column("当前值", style="yellow")
        for key, desc in CONFIG_FIELDS.items():
            val = get_nested(data, key)
            table.add_row(key, desc, str(val) if val is not None else "—")
        console.print(table)
        return

    if show:
        data = load_raw_config(config_path)
        # 隐藏 api_key
        import copy
        display = copy.deepcopy(data)
        if "llm" in display and "api_key" in display["llm"]:
            key = display["llm"]["api_key"]
            if key and len(key) > 8:
                display["llm"]["api_key"] = key[:4] + "****" + key[-4:]
        console.print(yaml.dump(display, allow_unicode=True, default_flow_style=False, sort_keys=False))
        return

    if set_key:
        key, raw_value = set_key
        if key not in CONFIG_FIELDS:
            console.print(f"[red]❌ 未知字段: {key}[/red]")
            console.print("[dim]运行 wkr config --list-fields 查看所有可配置字段[/dim]")
            sys.exit(1)

        data = load_raw_config(config_path)
        old_val = get_nested(data, key)
        new_val = parse_value(raw_value)
        set_nested(data, key, new_val)
        save_raw_config(config_path, data)
        console.print(f"[green]✓ {key}: {old_val} → {new_val}[/green]")
        return

    if add_repo_path:
        path = str(Path(add_repo_path).expanduser().resolve())
        alias = click.prompt("仓库别名（留空用目录名）", default="", show_default=False)
        branch = click.prompt("默认分支", default="main")
        data = load_raw_config(config_path)
        ok, msg = add_repo(data, path, branch=branch, alias=alias)
        if ok:
            save_raw_config(config_path, data)
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[yellow]⚠️ {msg}[/yellow]")
        return

    if remove_repo_path:
        path = str(Path(remove_repo_path).expanduser().resolve())
        data = load_raw_config(config_path)
        ok, msg = remove_repo(data, path)
        if ok:
            save_raw_config(config_path, data)
            console.print(f"[green]✓ {msg}[/green]")
        else:
            console.print(f"[yellow]⚠️ {msg}[/yellow]")
        return

    # 无参数时显示当前配置
    data = load_raw_config(config_path)
    import copy
    display = copy.deepcopy(data)
    if "llm" in display and "api_key" in display["llm"]:
        key = display["llm"]["api_key"]
        if key and len(key) > 8:
            display["llm"]["api_key"] = key[:4] + "****" + key[-4:]
    console.print(yaml.dump(display, allow_unicode=True, default_flow_style=False, sort_keys=False))


if __name__ == "__main__":
    main()
