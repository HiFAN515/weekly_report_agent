# 周报自动生成 Agent

自动采集 Git 提交记录，基于 LLM 提取结构化事实，通过模板引擎渲染，按周生成工作周报。

## 快速开始

### 1. 安装

```bash
cd weekly_report_agent
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. 初始化配置

```bash
wkr init
```

按提示填写：
- 项目名称
- Git 仓库路径（默认当前目录）
- Git 用户名（自动从 git config 读取）
- LLM 提供商（openai / anthropic / dashscope / ollama）
- 模型名称
- 安全等级（strict / balanced / full）

生成 `config.yaml`，之后可手动编辑。

### 3. 设置 API Key

```bash
# OpenAI
export OPENAI_API_KEY=sk-xxx

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-xxx

# 或者直接写在 config.yaml 的 api_key 字段（不推荐提交到 git）
```

### 4. 日常使用

**每日：采集 Git 提交**

```bash
wkr log --from-git           # 采集今日本地 commit（不必先 push）
wkr log --manual             # 手动输入工作日志
wkr log --file notes.md      # 从文件导入
wkr log --from-git --date 2026-05-01  # 采集指定日期
```

**周五：生成周报**

```bash
wkr report                   # 生成本周周报
wkr report --week 2026-04-28 # 生成指定周
wkr report --dry-run         # 只输出原始 JSON，不渲染模板
wkr report --dump-context    # 输出预处理上下文（调试用，不调用 LLM）
wkr report --template minimal # 指定模板
```

**查看日志**

```bash
wkr show                     # 今日日志
wkr show --date 2026-05-01   # 指定日期
wkr show --week              # 本周汇总
```

## 完整工作流示例

```bash
# 周一到周五：每天下班前采集
wkr log --from-git
? 是否补充说明？y
> 今天完成了用户认证模块的重构

# 周五下班前：生成周报
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
  # base_url: "http://localhost:11434/v1"  # Ollama 地址

# 安全等级
security:
  level: "balanced"  # strict: 只传 message | balanced: +文件名+统计 | full: +diff
```

### 安全等级说明

| 等级 | 传给 LLM 的内容 | 适用场景 |
|------|-----------------|----------|
| strict | commit message | 涉密项目 |
| balanced（默认） | message + 文件名 + 增删行数 | 大多数团队 |
| full | + diff 摘要片段 | 个人项目 + 本地模型 |

## 输出示例

生成的周报保存在 `reports/` 目录，格式如下：

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

## 目录结构

```
weekly_report_agent/
├── config.yaml          # 用户配置（不提交 git）
├── config.yaml.example  # 配置模板
├── src/
│   ├── cli.py           # CLI 入口
│   ├── config.py        # 配置加载
│   ├── collectors/      # 数据采集（Git、手动录入）
│   ├── storage/         # 存储（日志文件、SQLite 缓存）
│   ├── agent/           # LLM Agent（Schema、Prompt、ReAct）
│   ├── preprocessor/    # 数据预处理 + 上下文组装
│   └── generator/       # 模板渲染 + 导出
├── templates/           # Jinja2 模板
│   ├── standard.md.j2
│   └── standard.schema.yaml
├── data/
│   ├── logs/            # 日志文件
│   ├── reports/         # 生成的周报
│   └── cache/           # Git 统计缓存
└── reports/             # 周报输出目录
```
