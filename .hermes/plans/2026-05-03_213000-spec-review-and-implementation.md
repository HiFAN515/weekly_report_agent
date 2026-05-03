# 周报 Agent V2.1 产品方案评审 + 实施计划

## 总体评价

方案质量很高，V2.1 修订解决了一批工程落地的实际问题。结构清晰，数据流明确，伪代码可直接转为实现。

---

## 一、方案亮点（做对了的事）

1. **路径 B 设计决策正确** — LLM 只输出 JSON，模板负责渲染。这是结构化输出的标准做法，比让 LLM 直接写 Markdown 可靠得多。
2. **三级 LLM 兼容** — ReAct + 降级模式 + 自动检测，覆盖了从 GPT-4o 到 Ollama 7B 的完整光谱。
3. **token 预算控制** — 预处理层独立于 LLM，按优先级分配预算。这是大多数 RAG 系统做不好的地方。
4. **两级 Schema 校验** — 全局 JSON Schema + 模板二次校验，错误信息精确到字段路径。
5. **安全三级策略** — strict/balanced/full 对应不同数据泄露风险，实用。
6. **SQLite 缓存 + 增量 FAISS** — 性能考虑到位，不搞全量重建。

## 二、需要关注的问题

### 2.1 高优先级（影响 Phase 1 开发）

**P1: Embedding 模型选择与 token 预算的衔接**

方案中 token 预算按字符数估算（`len(summary)`、`len(assembled_logs)`），但 embedding 模型和 LLM 的 token 计算方式不同。建议统一用 tokenizer 做精确计算：

```python
# 不要用 len(text)，用 tokenizer
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained("shibing624/text2vec-base-chinese")
token_count = len(tokenizer.encode(text))
```

对 LLM 端，OpenAI SDK 有 `tiktoken`，Ollama 没有。需要一个统一的 `estimate_tokens(text, model_type)` 工具函数。

**P2: 降级模式的 `response_format` 兼容性**

代码中写了 `response_format={"type": "json_object"}`，但：
- Ollama 不支持这个参数（会报错或忽略）
- 通义千问支持但行为不一致
- 只有 OpenAI 和部分 Azure 端点稳定支持

建议：先检测 provider 是否支持 `response_format`，不支持时去掉这个参数，完全依赖 prompt 引导。

**P3: `_merged/` 合并视图的实现细节**

方案说 `_merged/` 是"自动维护的按天合并视图"，但没说什么时候触发合并。需要明确：
- 每次 `wkr log --from-git` 后自动重建？
- 还是 `wkr report` 时按需合并？
- 建议后者，避免每次采集都写文件。

### 2.2 中优先级（Phase 2 考虑）

**P4: FAISS 索引持久化方案不完整**

方案提到 `faiss.IndexFlatL2`，但没说怎么持久化。FAISS 索引需要显式 `faiss.write_index()` / `faiss.read_index()`。metadata 和索引文件需要配对保存：

```
index/
├── logs.index          # FAISS 二进制索引
├── metadata.json       # [{date, source, repo, part, chunk_text}, ...]
└── indexed_keys.json   # {(date, source, repo), ...}
```

**P5: 整体 embedding 检索的 query 拼接**

方案说"用本周日志整体作为 query"，但多天日志直接拼接会丢失时间结构。建议加日期标记：

```
[2026-04-28 周一] 后端服务: feat: 新增JWT...
[2026-04-29 周二] 后端服务: fix: 修复登录...
```

**P6: 周起始日判断**

方案默认"本周一"，但没提 ISO week vs US week 的差异。中国用 ISO（周一为起始），但 `datetime.isocalendar()` 在跨年时可能返回上一年最后一周。建议用 `isoweek` 库或手动处理。

### 2.3 低优先级（Phase 3+ 再处理）

**P7: 多仓库的 `_merged/` 合并排序**

当后端和前端都有 commit 时，`_merged/` 应该按时间戳排序合并，而不是简单拼接。

**P8: Webhook 通知格式**

方案提到钉钉/飞书 Webhook，但没定义 payload 格式。这是 Phase 3 的事，但可以先预留接口。

---

## 三、实施计划

### Phase 1：MVP（2 周）— 跑通核心流程

**Week 1：基础设施 + 数据采集**

| Day | 任务 | 产出文件 |
|-----|------|----------|
| D1 | 项目脚手架：pyproject.toml、config.yaml 加载、${ENV_VAR} 替换 | `src/config.py` |
| D2 | Git 采集器：GitPython 读取、SQLite 缓存、单仓库采集 | `src/collectors/git_collector.py` |
| D3 | 日志存储：Markdown 文件读写、按天聚合、`_merged/` 按需生成 | `src/storage/log_store.py` |
| D4 | 手动录入 + 日志文件管理 | `src/collectors/manual_collector.py` |
| D5 | CLI 框架：Click 入口、`log`、`show` 命令 | `src/cli.py` |

**Week 2：Agent + 渲染**

| Day | 任务 | 产出文件 |
|-----|------|----------|
| D6 | ContextBuilder：读取日志 + Git 统计 + 安全过滤 + token 预算 | `src/preprocessor/context_builder.py` |
| D7 | ReportAgent：ReAct 模式 + 降级模式 + 健壮 JSON 提取 | `src/agent/react_agent.py` |
| D8 | Schema 校验：全局 JSON Schema + 模板二次校验 + 重试 | `src/agent/schema.py` |
| D9 | Jinja2 模板引擎 + 标准模板 | `src/generator/template_engine.py`, `templates/standard.md.j2` |
| D10 | CLI `report` 命令串联 + `--dry-run` + `--dump-context` + 端到端测试 | `src/cli.py` |

**MVP 交付物**：`wkr log --from-git && wkr report` 生成一份可读周报

### Phase 2：增强（2 周）

- FAISS 增量索引 + 语义搜索
- 多仓库支持（含 per-repo author override）
- 文档摄入（.md / .docx）
- 自定义模板 + Schema 校验
- DOCX 导出
- commit message 质量检测

### Phase 3：自动化（1 周）

- 系统 cron 安装/卸载（CronHelper）
- Windows schtasks 兼容
- Webhook 通知

### Phase 4：Web Dashboard（2 周，可选）

- FastAPI 后端
- React 前端
- APScheduler 调度

---

## 四、技术风险清单

| 风险 | 概率 | 缓解 |
|------|------|------|
| 本地模型 JSON 输出不稳定 | 高 | `_extract_json_robust` 四级容错已覆盖 |
| Embedding 模型下载慢/首次加载慢 | 中 | 首次 init 时预下载，后续缓存在 ~/.cache |
| Git 大仓库 diff --stat 慢 | 中 | SQLite 缓存，增量计算 |
| token 估算不准导致上下文超限 | 中 | 用 tokenizer 精确计算，预留 10% buffer |
| Jinja2 模板变量不匹配 | 低 | 两级 Schema 校验 + 默认值填充 |

---

## 五、建议的开发顺序（具体文件）

```
1. src/config.py              # 配置加载，所有模块依赖它
2. src/collectors/git_collector.py  # 核心数据源
3. src/storage/log_store.py   # 日志读写
4. src/preprocessor/context_builder.py  # 预处理层
5. src/agent/schema.py        # JSON Schema 定义
6. src/agent/prompts.py       # System Prompt
7. src/agent/react_agent.py   # Agent 主逻辑
8. src/generator/template_engine.py  # Jinja2 渲染
9. src/cli.py                 # CLI 入口
10. templates/standard.md.j2  # 标准模板
11. config.yaml               # 默认配置
12. pyproject.toml            # 项目元数据
```

每个模块写完后立即写对应的 test，不要等全部写完再测。
