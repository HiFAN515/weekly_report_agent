# 自定义周报模板 — 使用手册

## 概述

每个模板由两个文件组成：

```
templates/
├── my_template.md.j2           # 模板文件（决定周报长什么样）
└── my_template.schema.yaml     # 校验 Schema（约束变量类型 + 默认值）
```

文件名必须对应：`xxx.md.j2` 和 `xxx.schema.yaml` 中的 `xxx` 部分相同。
模板名 = 文件名去掉 `.md.j2` 后缀，即 `xxx`。

---

## 第一步：创建模板文件（.md.j2）

使用 Jinja2 模板语法，可用的变量见下方"可用变量"章节。

示例：创建一个极简模板 `minimal.md.j2`

```markdown
# {{ project_name }} 周报 W{{ week_num }}

## 核心成果
{% for item in highlights %}
- {{ item }}
{% endfor %}

## 本周工作
{% for day in daily_work %}
**{{ day.weekday }} {{ day.date }}**
{% for task in day.tasks %}
- {{ task }}
{% endfor %}
{% endfor %}

## 下周计划
{% for plan in next_week %}
- {{ plan }}
{% endfor %}

---
> {{ author }} | {{ date_range }} | Git {{ data_summary.git_commits }} commits
```

### Jinja2 语法速查

```jinja2
{{ variable }}                          {# 输出变量 #}
{% for item in list %}...{% endfor %}   {# 循环列表 #}
{% if condition %}...{% endif %}        {# 条件判断 #}
{{ value | default("fallback") }}       {# 默认值过滤器 #}
{{ list | join(", ") }}                 {# 列表拼接 #}
{{ value | upper }}                     {# 转大写 #}
{{ value | length }}                    {# 长度 #}
```

### 嵌套变量访问

```jinja2
{# daily_work 是列表，每个元素是对象 #}
{% for day in daily_work %}
  {{ day.date }}        {# 日期 #}
  {{ day.weekday }}     {# 星期 #}
  {% for task in day.tasks %}   {# 任务列表 #}
    - {{ task }}
  {% endfor %}
{% endfor %}

{# issues 也是列表，每个元素有 description/impact/solution/status #}
{% for issue in issues %}
  {{ issue.description }}
  {{ issue.status }}
{% endfor %}

{# data_summary 是对象 #}
{{ data_summary.git_commits }}
{{ data_summary.insertions }}
```

### 条件渲染

```jinja2
{# 只在有问题时渲染问题表格 #}
{% if issues %}
## 问题与风险
| 问题 | 状态 |
|------|------|
{% for issue in issues %}
| {{ issue.description }} | {{ issue.status }} |
{% endfor %}
{% endif %}

{# 某个字段可能为空，用 default 过滤器 #}
{{ issue.impact | default("—") }}
{{ issue.solution | default("—") }}
```

---

## 第二步：创建 Schema 文件（.schema.yaml）

Schema 文件定义：
1. 每个变量的类型约束（LLM 输出校验用）
2. 必填/选填
3. 枚举值限制
4. 默认值（程序自动填充）

### 完整示例

```yaml
# templates/minimal.schema.yaml

variables:
  # ── LLM 输出的变量（需要校验）──

  highlights:
    type: list           # 类型：list / object / string / integer
    items: string         # list 元素类型
    min: 1                # 最少几条
    max: 7                # 最多几条
    required: true        # 是否必填

  daily_work:
    type: list
    items:
      type: object
      properties:
        date: { type: string }
        weekday: { type: string, enum: [周一, 周二, 周三, 周四, 周五, 周六, 周日] }
        tasks: { type: list, items: string }
    required: true

  issues:
    type: list
    items:
      type: object
      properties:
        description: { type: string }
        impact: { type: string, default: "—" }
        solution: { type: string, default: "—" }
        status: { type: string, enum: [已解决, 处理中, 待解决, 已搁置] }
    required: true         # issues 列表本身必填，但可以是空列表 []

  next_week:
    type: list
    items: string
    required: true

  data_summary:
    type: object
    properties:
      git_commits: { type: integer }
      files_changed: { type: integer }
      insertions: { type: integer }
      deletions: { type: integer }
      log_days: { type: integer }
    required: true

  # ── 程序自动填充的变量（不依赖 LLM）──

  author:
    type: string
    source: config         # 从 config.yaml 的 project.author 读取
    default: "Unknown"

  year:
    type: integer
    source: computed       # 从当前日期自动计算

  week_num:
    type: integer
    source: computed

  date_range:
    type: string
    source: computed       # 格式: "2026-04-28 至 2026-05-04"

  project_name:
    type: string
    source: config         # 从 config.yaml 的 project.name 读取
    default: "MyProject"
```

### Schema 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| type | 变量类型 | list / object / string / integer |
| items | list 元素类型 | string 或 object（含 properties） |
| properties | object 子字段 | 嵌套 `{ field_name: { type: ... } }` |
| min / max | list 长度限制 | min: 1, max: 7 |
| required | 是否必填 | true / false |
| enum | 枚举值列表 | [已解决, 处理中, 待解决] |
| default | 默认值 | "—" / "Unknown" |
| source | 数据来源 | config（从配置读）/ computed（自动算） |

### 两级校验流程

```
LLM 输出 JSON
      │
      ▼
第 1 级：全局 JSON Schema 校验
  → 检查 highlights/daily_work/issues/next_week/data_summary 是否存在且类型正确
      │ 通过
      ▼
第 2 级：模板 Schema 校验（你的 .schema.yaml）
  → 检查子结构完整性、枚举值、list 长度
  → 自动填充 default 值
      │ 通过
      ▼
模板渲染
```

校验失败时会精确报错，例如：
```
❌ 模板校验失败：
  - issues[0].status: 值 "已完成" 不在允许的枚举 [已解决, 处理中, 待解决, 已搁置] 中
  - daily_work[2].tasks: 期望 list，收到 str
```

---

## 第三步：使用自定义模板

```bash
# 通过命令行参数指定
wkr report --template minimal

# 或在 config.yaml 中设为默认
report:
  template: "minimal"
```

---

## 常见模板类型参考

### 1. 标准研发周报（内置 standard）

适合：软件工程师日常周报

包含：核心成果 + 详细工作（按天）+ 问题表格 + 下周计划 + 数据摘要

### 2. 极简周报

适合：TL 快速汇报、只需要要点

```markdown
# {{ project_name }} W{{ week_num }}

{% for item in highlights %}
- {{ item }}
{% endfor %}

{% for plan in next_week %}
- [ ] {{ plan }}
{% endfor %}
```

### 3. 项目管理周报

适合：项目经理、需要进度跟踪

```markdown
# {{ project_name }} 周报 W{{ week_num }}

## 进度
| 模块 | 状态 | 备注 |
|------|------|------|
{% for day in daily_work %}
{% for task in day.tasks %}
| {{ task[:30] }} | ✅ | {{ day.date }} |
{% endfor %}
{% endfor %}

## 风险
{% for issue in issues %}
- ⚠️ {{ issue.description }}（{{ issue.status }}）
{% endfor %}

## 下周
{% for plan in next_week %}
- {{ plan }}
{% endfor %}
```

### 4. 个人工作日志

适合：个人记录、不需要正式格式

```markdown
# {{ date_range }} 工作记录

{% for day in daily_work %}
## {{ day.date }} {{ day.weekday }}
{% for task in day.tasks %}
- {{ task }}
{% endfor %}

{% endfor %}

## 问题
{% for issue in issues %}
- {{ issue.description }} → {{ issue.status }}
{% endfor %}

## 下周
{% for plan in next_week %}
- {{ plan }}
{% endfor %}
```

---

## FAQ

**Q: 变量不够用，想加自定义字段怎么办？**
A: LLM 输出的 JSON 结构是固定的（highlights/daily_work/issues/next_week/data_summary），不能加自定义字段。但你可以在模板里做计算和格式变换，比如 `{{ data_summary.insertions + data_summary.deletions }}` 算总变更行数。

**Q: 不写 .schema.yaml 行不行？**
A: 行。没有 schema 文件时跳过第 2 级校验，只走全局 JSON Schema 校验。但不会有默认值自动填充，模板中引用的 source: config/computed 变量需要通过 config_defaults 传入。

**Q: 模板里能写 HTML 吗？**
A: 能。Jinja2 渲染的是纯文本，你写什么它就输出什么。如果导出格式是 HTML，可以混用 Markdown 和 HTML 标签。

**Q: 想让某个字段在特定条件下不显示？**
A: 用 `{% if %}` 判断：
```jinja2
{% if issues %}
## 问题
{% for issue in issues %}
...
{% endfor %}
{% else %}
本周无遗留问题 ✅
{% endif %}
```
