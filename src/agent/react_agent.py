"""
ReportAgent — 周报生成 Agent

功能：
  - ReAct 模式（OpenAI FC 多轮工具调用）
  - 降级模式（单次调用）
  - FC 自动检测
  - 健壮 JSON 提取（四级容错）
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from src.agent.prompts import REACT_SYSTEM_PROMPT, FALLBACK_SYSTEM_PROMPT, FEWSHOT_EXAMPLE
from src.agent.tools import TOOL_DEFINITIONS, ToolExecutor
from src.config import LLMConfig


# ── 异常类 ────────────────────────────────────────────────

class JsonExtractionError(Exception):
    """无法从 LLM 输出中提取合法 JSON"""
    def __init__(self, raw_output: str):
        self.raw_output = raw_output
        super().__init__(
            "无法从 LLM 输出中提取合法 JSON。\n\n"
            "自助排查建议：\n"
            "  1. 运行 wkr report --dump-context 检查预处理输出是否正常\n"
            "  2. 如果使用本地模型，尝试切换到更大的模型（推荐 ≥7B）\n"
            "  3. 如果使用云端 API，检查 API Key 是否有效\n"
            "  4. 尝试减少本周日志量（缩短时间范围）后重试\n\n"
            f"原始输出前 500 字符：\n{raw_output[:500]}"
        )


class FCNotSupportedError(Exception):
    """LLM 不支持 Function Calling"""
    pass


# ── Agent 主类 ────────────────────────────────────────────

class ReportAgent:
    """周报生成 Agent"""

    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.client = self._create_client()
        self.mode = self._detect_mode()

    def _create_client(self) -> OpenAI:
        """创建 OpenAI 客户端"""
        kwargs = {"api_key": self.llm_config.api_key or "dummy"}
        if self.llm_config.base_url:
            kwargs["base_url"] = self.llm_config.base_url
        elif self.llm_config.provider == "ollama":
            kwargs["base_url"] = "http://localhost:11434/v1"
            kwargs["api_key"] = "ollama"
        return OpenAI(**kwargs)

    def _detect_mode(self) -> str:
        """
        检测 LLM 是否支持 Function Calling

        云端 API 默认 react，Ollama 先测试一次 FC 调用
        """
        if self.llm_config.provider in ("openai", "dashscope"):
            return "react"
        elif self.llm_config.provider == "ollama":
            try:
                self._test_fc()
                return "react"
            except (FCNotSupportedError, Exception):
                print("⚠️ 本地模型不支持 Function Calling，切换为降级模式")
                return "fallback"
        return "fallback"

    def _test_fc(self):
        """测试 FC 能力"""
        try:
            response = self.client.chat.completions.create(
                model=self.llm_config.model,
                messages=[{"role": "user", "content": "test"}],
                tools=TOOL_DEFINITIONS[:1],
                max_tokens=10,
            )
            # 如果返回 choices 且没有报错，认为支持 FC
            if not response.choices:
                raise FCNotSupportedError("空响应")
        except FCNotSupportedError:
            raise
        except Exception as e:
            error_msg = str(e).lower()
            if "tool" in error_msg or "function" in error_msg or "not support" in error_msg:
                raise FCNotSupportedError(f"FC 测试失败: {e}")
            # 其他错误（如网络）不视为不支持 FC
            pass

    def generate(self, context: str, tool_executor: ToolExecutor) -> dict:
        """
        生成结构化周报数据

        Args:
            context: 预处理后的上下文文本
            tool_executor: 工具执行器

        Returns:
            结构化周报 JSON 数据
        """
        if self.mode == "react":
            return self._react_generate(context, tool_executor)
        else:
            return self._fallback_generate(context)

    # ── ReAct 模式 ────────────────────────────────────────

    def _react_generate(self, context: str, tool_executor: ToolExecutor) -> dict:
        """ReAct 模式：多轮工具调用循环"""
        messages = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是本周工作数据，请提取结构化周报信息。\n\n{context}"},
        ]

        max_steps = 10
        for step in range(max_steps):
            response = self.client.chat.completions.create(
                model=self.llm_config.model,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=self.llm_config.temperature,
            )

            choice = response.choices[0]
            message = choice.message

            # 没有工具调用，说明 LLM 直接输出了内容
            if not message.tool_calls:
                # 尝试从 content 提取 JSON
                if message.content:
                    return self._extract_json_robust(message.content)
                break

            # 处理工具调用
            messages.append(message)
            for tool_call in message.tool_calls:
                func = tool_call.function
                try:
                    args = json.loads(func.arguments) if func.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                result = tool_executor.execute(func.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

                # 如果是 submit_report_data，检查是否已提交
                if func.name == "submit_report_data" and tool_executor.submitted_data:
                    return tool_executor.submitted_data

        # 循环结束仍未提交，尝试从最后一条消息提取
        if tool_executor.submitted_data:
            return tool_executor.submitted_data
        raise JsonExtractionError("ReAct 循环结束，LLM 未提交有效数据")

    # ── 降级模式 ──────────────────────────────────────────

    def _fallback_generate(self, context: str) -> dict:
        """降级模式：单次调用"""
        prompt = f"""{FALLBACK_SYSTEM_PROMPT}

=== 以下是本周工作数据 ===
{context}

=== 参考示例 ===
{json.dumps(FEWSHOT_EXAMPLE, ensure_ascii=False, indent=2)}

请基于上述数据，输出结构化周报 JSON。"""

        # 检测是否支持 response_format
        extra_kwargs = {}
        if self.llm_config.provider == "openai":
            extra_kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(
            model=self.llm_config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.llm_config.temperature,
            **extra_kwargs,
        )

        raw = response.choices[0].message.content
        return self._extract_json_robust(raw)

    # ── 健壮 JSON 提取 ────────────────────────────────────

    def _extract_json_robust(self, raw: str, max_retries: int = 2) -> dict:
        """
        四级容错 JSON 提取：
          1. 直接 json.loads
          2. 正则匹配最外层 { ... }
          3. 去除 markdown 标记后重试
          4. 追询 LLM 修正格式
        """
        # 策略 1: 直接解析
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

        # 策略 2: 正则提取最外层 JSON 对象
        if raw:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        # 策略 3: 去除 markdown 代码块标记
        if raw:
            cleaned = re.sub(r'```(?:json)?\s*', '', raw)
            cleaned = re.sub(r'```', '', cleaned).strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        # 策略 4: 追询 LLM 修正格式
        for attempt in range(max_retries):
            fix_prompt = f"""你上次输出的内容不是合法 JSON。请仅回复 JSON 本身，不要包含任何其他文字。

你上次的输出：
{raw[:2000] if raw else '(空)'}"""

            try:
                fix_response = self.client.chat.completions.create(
                    model=self.llm_config.model,
                    messages=[{"role": "user", "content": fix_prompt}],
                    temperature=0.1,
                )
                fixed_raw = fix_response.choices[0].message.content
            except Exception:
                break

            # 尝试解析修正后的输出
            for parser in [json.loads, lambda s: json.loads(re.search(r'\{[\s\S]*\}', s).group())]:
                try:
                    return parser(fixed_raw)
                except (json.JSONDecodeError, AttributeError, TypeError):
                    continue
            raw = fixed_raw

        # 所有策略失败
        raise JsonExtractionError(raw or "(空输出)")
