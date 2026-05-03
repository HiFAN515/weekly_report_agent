# Phase 1 MVP 工作清单

> 基于产品方案 V2.1，按依赖顺序排列。
> 状态标记：[ ] 待开发  [~] 进行中  [x] 已完成

---

## 阶段 1：脚手架 + 配置

- [ ] **1.1** 项目脚手架
  - pyproject.toml（依赖：click, openai, gitpython, faiss-cpu, sentence-transformers, jinja2, python-docx, pydantic, pyyaml, rich）
  - src/__init__.py
  - 包结构：collectors/, storage/, agent/, preprocessor/, generator/, scheduler/

- [ ] **1.2** 配置系统
  - config.yaml 默认模板（含 project、repositories、git、security、llm、rag、report、schedule、ingest 全部字段）
  - src/config.py：YAML 加载、${ENV_VAR} 替换、dataclass 结构化、默认值填充

---

## 阶段 2：数据采集 + 存储

- [ ] **2.1** Git 采集器
  - src/collectors/git_collector.py：GitCollector 类
  - GitPython 读取 commit 列表（hash、author、date、message、files_changed、insertions、deletions）
  - 按天聚合、分支策略（merged/all/current）、时区转换（Asia/Shanghai）、author 过滤
  - 支持 per-repo author override（仓库级覆盖全局默认）

- [ ] **2.2** Git 统计缓存
  - src/storage/cache_store.py：GitStatsCache 类
  - SQLite 表：commit_stats(hash TEXT PK, repo TEXT, insertions INT, deletions INT, files TEXT)
  - 接口：has(hash) / get(hash) / set(hash, stats) / gc(existing_hashes)

- [ ] **2.3** GitCollector 接入缓存
  - 采集时先查 SQLite 缓存，命中直接用，未命中执行 git diff --stat 后写入缓存
  - amend/rebase 时新 hash 自动重算，旧 hash 成为孤立条目（不主动清理，gc 可选）

- [ ] **2.4** 低质量 commit 检测
  - 检测规则：长度 < 10 字符，或匹配 /^(fix|update|wip|test)$/i
  - 在日志中标注 [低信息量 commit]，提示用户 wkr log --manual 补充

- [ ] **2.5** 日志存储
  - src/storage/log_store.py：LogStore 类
  - 路径规范：logs/git/{repo_alias}/{date}.md、logs/manual/{date}.md
  - 按需生成 _merged/{date}.md（report 时合并，非每次采集都写）
  - 跨仓库同名 commit hash 去重

- [ ] **2.6** 日志 Markdown 格式
  - 每个 commit 的渲染模板，按安全级别过滤内容：
    - strict：message + 文件名
    - balanced：message + 文件名 + 增删行数
    - full：+ diff 摘要片段（截断到 max_diff_chars）
  - files_changed = 不重复文件总数（跨仓库同路径算不同文件）

- [ ] **2.7** 手动录入
  - src/collectors/manual_collector.py
  - stdin 读取 / 交互式输入 → 写入 logs/manual/{date}.md

---

## 阶段 3：Agent 核心

- [ ] **3.1** Schema 定义
  - src/agent/schema.py
  - 全局 JSON Schema（highlights、daily_work、issues、next_week、data_summary）
  - 校验函数：validate(data) → (bool, list[str])
  - 精确错误信息：字段路径 + 期望类型 + 实际值

- [ ] **3.2** System Prompt
  - src/agent/prompts.py
  - ReAct 模式 prompt（含工具使用说明 + JSON 输出格式 + Few-shot 示例）
  - 降级模式 prompt（更直接的指令，无工具调用说明）
  - 原则：数据驱动、成果导向、commit 不足时标注 [需补充]、禁止编造

- [ ] **3.3** Agent 工具定义
  - src/agent/tools.py
  - get_week_summary：返回按天聚合的统计摘要（非完整日志）
  - get_day_detail：返回指定日期完整日志
  - get_file_change_summary：文件名 + 增删行数，full 模式含 diff（include_diff 参数由安全级别自动控制）
  - submit_report_data：接收 JSON，触发 Schema 校验
  - 所有工具返回格式与 Schema 对齐

- [ ] **3.4** 上下文组装
  - src/preprocessor/context_builder.py：ContextBuilder 类
  - build() 流程：读日志 → 聚合统计 → 安全过滤 → RAG 检索（Phase 1 先跳过，留接口） → token 预算分配 → 组装

- [ ] **3.5** Token 预算控制
  - estimate_tokens() 统一工具函数（Phase 1 用字符近似，Phase 2 接入 tokenizer）
  - 预算分配：系统 prompt 2000 + 输出预留 4000 = 固定开销；剩余按 摘要 10% : 历史 20% : 日志 70%
  - 日志优先保留最新一天，其余按时间倒序截断
  - 降级模式：更激进压缩（top_k 3→5 降为 3，每条 500→300 字符，最旧日志丢弃保留最新 3 天）

- [ ] **3.6** ContextBuilder.build_debug()
  - --dump-context 专用，输出 token 预算分配详情 + 预处理上下文
  - 完全离线，不调用 LLM

- [ ] **3.7** ReportAgent — ReAct 模式
  - src/agent/react_agent.py：ReportAgent 类
  - OpenAI FC 多轮工具调用循环（while + tool_calls）
  - 最后一步调用 submit_report_data 输出 JSON

- [ ] **3.8** ReportAgent — 降级模式
  - 单次调用，prompt 注入完整上下文
  - response_format 兼容检测：先尝试 {"type": "json_object"}，不支持则去掉该参数
  - Ollama/通义千问/小模型走这条路径

- [ ] **3.9** 健壮 JSON 提取
  - _extract_json_robust() 四级容错：
    1. 直接 json.loads
    2. 正则匹配最外层 { ... }
    3. 去除 ```json``` 标记后重试
    4. 追询 LLM 修正格式（最多 2 次）
  - JsonExtractionError 异常类（含自助排查建议）

- [ ] **3.10** FC 自动检测
  - _detect_mode()：云端 API 默认 react，Ollama 先测试一次 FC 调用，失败降级
  - 打印提示：⚠️ 本地模型不支持 Function Calling，切换为降级模式

---

## 阶段 4：模板渲染 + CLI 串联

- [ ] **4.1** 标准模板
  - templates/standard.md.j2：标准研发周报 Jinja2 模板
  - 含核心成果、详细工作（按天）、问题与风险（表格）、下周计划、数据摘要

- [ ] **4.2** 模板 Schema
  - templates/standard.schema.yaml：模板二次校验
  - 类型约束（list/object/string/integer）、枚举值、默认值
  - 区分 LLM 输出字段 和 程序自动填充字段（author、year、week_num、date_range）

- [ ] **4.3** 模板引擎
  - src/generator/template_engine.py：TemplateEngine 类
  - Jinja2 加载、config 默认值 + LLM 输出合并渲染
  - 变量缺失时用 schema.yaml 中的 default 填充，不报错

- [ ] **4.4** 两级 Schema 校验
  - ReportSchemaValidator 类
  - 第 1 级：全局 JSON Schema（字段完整性 + 类型 + 枚举）
  - 第 2 级：模板 Schema 二次校验（子结构完整性 + 模板特有约束）
  - validate_with_retry()：最多 3 次重试，失败时打印精确错误（如 issues[0].status 值 "已完成" 不在枚举中）

- [ ] **4.5** 导出器
  - src/generator/exporter.py
  - Markdown 写文件（默认）
  - DOCX 导出（python-docx，Phase 1 可简化）
  - 输出路径：reports/{start}_{end}_weekly_report.md

- [ ] **4.6** CLI 框架
  - src/cli.py：Click 主命令 wkr + 子命令注册
  - 子命令：init、log、ingest、report、show、search、schedule、config、template

- [ ] **4.7** wkr init
  - 交互式向导：项目名、仓库路径、Git 用户名、模板选择、LLM provider、安全等级、Embedding 模型、定时时间
  - 选择云端 API 时打印数据安全提醒
  - 写入 config.yaml

- [ ] **4.8** wkr log 命令
  - --from-git：采集今日 Git 提交（本地仓库，不必 push）
  - --manual：交互式手动输入
  - --file：导入指定文档
  - 采集后询问是否补充说明

- [ ] **4.9** wkr report 命令
  - 串联完整流程：ContextBuilder → ReportAgent → SchemaValidator → TemplateEngine → Exporter
  - 参数：--week（指定周）、--template（指定模板）、--preview（打开预览）、--dry-run（输出 JSON 不渲染）、--dump-context（离线调试）
  - 交互：生成后询问 保存/修改/导出DOCX

- [ ] **4.10** wkr show 命令
  - 无参数：今日日志
  - --date：指定日期
  - --week：本周汇总
  - 用 rich 美化输出

---

## 阶段 5：测试验证

- [ ] **5.1** 端到端冒烟测试
  - wkr init → wkr log --from-git → wkr report → 生成可读周报
  - 验证：Git 统计正确、JSON Schema 校验通过、模板渲染无报错、文件输出到 reports/

- [ ] **5.2** 降级模式测试
  - 配置 Ollama 小模型（如 qwen2.5:7b），跑一遍完整流程
  - 验证：_detect_mode() 自动降级、_extract_json_robust() 四级容错

- [ ] **5.3** --dump-context 测试
  - 验证 token 预算分配正确（摘要/日志/历史比例）
  - 验证安全过滤生效（strict 模式下无文件名、full 模式下有 diff）
  - 验证截断逻辑（超长日志保留最新、标注"共 M 条"）

---

## 后续阶段（Phase 2+，暂不展开）

- Phase 2：FAISS 增量索引 + RAG 语义搜索、多仓库、文档摄入、自定义模板、DOCX 导出、commit 质量检测
- Phase 3：系统 Cron / Windows schtasks、Webhook 通知
- Phase 4：FastAPI 后端 + React 前端 Dashboard
