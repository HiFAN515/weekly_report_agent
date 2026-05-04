"""
Token 估算工具

Phase 1：字符近似
Phase 2：接入 tiktoken 做精确计算
"""

from __future__ import annotations


def estimate_tokens(text: str, model_type: str = "auto") -> int:
    """
    估算文本的 token 数

    Args:
        text: 输入文本
        model_type: "openai" / "anthropic" / "auto"

    Returns:
        估算的 token 数
    """
    if not text:
        return 0

    # 优先用 tiktoken（OpenAI 模型精确计算）
    if model_type in ("openai", "auto"):
        try:
            return _estimate_tiktoken(text)
        except ImportError:
            pass

    # 降级：字符近似
    return _estimate_heuristic(text)


def _estimate_tiktoken(text: str) -> int:
    """使用 tiktoken 精确计算"""
    import tiktoken
    try:
        enc = tiktoken.get_encoding("cl100k_base")  # GPT-4 / GPT-3.5 通用编码
    except Exception:
        enc = tiktoken.get_encoding("gpt2")
    return len(enc.encode(text))


def _estimate_heuristic(text: str) -> int:
    """字符近似估算（中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1.3 token）"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = len(text) - cn_chars
    return int(cn_chars * 1.5 + en_chars * 0.3)
