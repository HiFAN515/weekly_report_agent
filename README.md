# 周报自动生成 Agent

自动采集 Git 提交记录 + 用户文档，基于 LLM 提取结构化事实，通过模板引擎渲染，按周生成工作周报。

支持 OpenAI / Anthropic / Ollama 本地模型。

## 环境要求

- Python >= 3.10
- Git（需在 PATH 中）

## 快速开始

### 1. 安装

```bash
git clone https://github.com/JinfanShen/weekly_report_agent.git
cd weekly_report_agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. 初始化配置

```bash
wkr init
```

交互式填写项目信息、Git 仓库、LLM 提供商、安全等级等，生成 `config.yaml`。

### 3. 设置 API Key

```bash
# OpenAI
export OPENAI_API_KEY=sk-xxx

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-xxx

# 也可以直接写在 config.yaml 的 api_key 字段
# config.yaml 已在 .gitignore 中，不会被提交
```

### 4. 查看所有命令

```bash
wkr --help              # 快速参考：所有命令和选项
wkr log --help          # 详细说明：采集方式、示例、注意事项
wkr report --help       # 详细说明：工作流程、示例、输出路径
wkr show --help         # 详细说明：查看日志的用法
```

---

## 命令速查

### 采集日志

```bash
wkr log --from-git                  # 采集今日本地 commit（不必先 push）
wkr log --from-git --date 2026-05-01
                                    # 采集指定日期
wkr log --manual                    # 手动输入（输入完 Ctrl+D 结束）
wkr log --file notes.md             # 从文件导入
echo "做了XX" | wkr log --manual    # 管道输入
```

日志保存在 `data/logs/` 目录：
- `data/logs/git/{仓库名}/{日期}.md` — Git 采集
- `data/logs/manual/{日期}.md` — 手动录入 / 文件导入

### 生成周报

```bash
wkr report                          # 生成本周周报
wkr report --week 2026-04-28        # 指定周
wkr report --template minimal       # 指定模板
wkr report --dry-run                # 只输出 JSON，不渲染
wkr report --dump-context           # 输出预处理上下文（不调用 LLM，调试用）
```

周报输出到 `reports/{start}_{end}_weekly_report.md`。

### 查看日志

```bash
wkr show                            # 今日日志
wkr show --date 2026-05-01          # 指定日期
wkr show --week                     # 本周汇总
```

---

## 完整工作流

```bash
# ── 周一到周五：每天下班前采集 ──
wkr log --from-git
? 是否补充说明？y
> 今天完成了用户认证模块的重构

# ── 周五下班前：生成周报 ──
wkr report
📊 数据预处理...
  ── Git 统计：23 commits, +1247/-413
🤖 Agent 提取结构化数据...
  ── 模式: react
  ── 全局 Schema 校验通过 ✓
  ── 模板 Schema 校验通过 ✓
📝 模板渲染...
✓ 周报已生成: reports/2026-04-28_2026-05-04_weekly_report.md
```

---

## 配置说明

参考 `config.yaml.example`，主要配置项：

```yaml
# Git 仓库（支持多仓库）
repositories:
  - path: ~/projects/backend
    branch: main
    alias: 后端服务
  - path: ~/projects/frontend
    branch: develop
    alias: 前端应用

# LLM 配置
llm:
  provider: "anthropic"              # openai | anthropic | dashscope | ollama
  model: "claude-sonnet-4-20250514"
  api_key: "${ANTHROPIC_API_KEY}"    # 环境变量替换
  # base_url: "http://localhost:11434/v1"  # Ollama 或自定义网关

# 安全等级
security:
  level: "balanced"  # strict | balanced | full
```

### 安全等级

| 等级 | 传给 LLM 的内容 | 适用场景 |
|------|-----------------|----------|
| strict | commit message | 涉密项目 |
| balanced（默认） | message + 文件名 + 增删行数 | 大多数团队 |
| full | + diff 摘要片段 | 个人项目 + 本地模型 |

---

## 自定义模板

内置 `standard` 模板，也可以自己创建。每个模板由两个文件组成：

```
templates/
├── my_template.md.j2           # Jinja2 模板（决定周报格式）
└── my_template.schema.yaml     # 校验 Schema（类型约束 + 默认值）
```

使用：`wkr report --template my_template`

详细教程见 `templates/README.md`，包含：
- 模板语法速查
- Schema 字段说明
- 4 种常见模板示例（标准 / 极简 / 项目管理 / 个人日志）

---

## 输出示例

```markdown
# 周报 — 2026年第18周
> 2026-04-28 至 2026-05-04 | 张三

## 一、本周工作总结

### 核心成果
- 完成用户认证模块重构，JWT 刷新机制上线
- 修复首页加载 P0 超时问题，响应时间从 3.2s 降至 0.8s

### 详细工作
**周一 (2026-04-28)**
- [commit a1b2c3d] 实现 JWT token 自动刷新

## 二、问题与风险
| 问题 | 影响 | 解决方案 | 状态 |
|------|------|----------|------|
| 首页超时 | 跳出率+15% | Redis缓存 | 已解决 |

## 三、下周计划
- [ ] OAuth2.0 社交登录接入

## 四、数据摘要
- Git 提交：23 次
- 代码变更：+1247 / -413
```

---

## 目录结构

```
weekly_report_agent/
├── README.md              # 本文件
├── config.yaml.example    # 配置模板
├── pyproject.toml         # 项目元数据 + 依赖
├── src/
│   ├── cli.py             # CLI 入口（wkr 命令）
│   ├── config.py          # 配置加载（YAML + 环境变量替换）
│   ├── collectors/
│   │   ├── git_collector.py    # Git 日志采集 + SQLite 缓存
│   │   └── manual_collector.py # 手动录入 / 文件导入
│   ├── storage/
│   │   ├── log_store.py        # 日志文件读写
│   │   └── cache_store.py      # Git 统计缓存（SQLite）
│   ├── agent/
│   │   ├── react_agent.py      # LLM Agent（OpenAI + Anthropic）
│   │   ├── schema.py           # JSON Schema + 两级校验
│   │   ├── prompts.py          # System Prompt
│   │   └── tools.py            # Agent 工具定义
│   ├── preprocessor/
│   │   └── context_builder.py  # 数据预处理 + token 预算控制
│   └── generator/
│       ├── template_engine.py  # Jinja2 模板渲染
│       └── exporter.py         # Markdown / DOCX 导出
├── templates/
│   ├── standard.md.j2          # 标准周报模板
│   ├── standard.schema.yaml    # 标准模板 Schema
│   └── README.md               # 自定义模板教程
├── data/
│   ├── logs/                   # 日志文件（git/ + manual/）
│   ├── cache/                  # SQLite 缓存
│   └── index/                  # 向量索引（Phase 2）
├── reports/                    # 生成的周报输出目录
└── docs/
    ├── 产品方案_v2.1.md        # 产品设计文档
    └── 全阶段工作清单.md       # 开发进度跟踪
```
