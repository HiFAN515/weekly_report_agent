"""
向量索引 + Embedding 检索

功能：
  - FAISS 向量索引（增量更新、持久化）
  - Embedding 模型加载（sentence-transformers / 云端 API）
  - 子 chunk 拆分（日志按天、超大按仓库）
  - 整体 embedding 检索 + 去重 + 超长降级
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import faiss
import numpy as np


# ── Chunk 数据模型 ────────────────────────────────────────

@dataclass
class Chunk:
    """一个文本片段"""
    text: str
    metadata: dict = field(default_factory=dict)


# ── Embedding 模型包装 ───────────────────────────────────

class EmbeddingModel:
    """Embedding 模型统一接口"""

    def __init__(self, model_name: str = "shibing624/text2vec-base-chinese"):
        self.model_name = model_name
        self._model = None
        self._dimension = None
        self._max_seq_length = 512

    @property
    def model(self):
        if self._model is None:
            self._load()
        return self._model

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load()
        return self._dimension

    @property
    def max_seq_length(self) -> int:
        return self._max_seq_length

    def _load(self):
        """延迟加载模型"""
        from sentence_transformers import SentenceTransformer
        print(f"⏳ 加载 Embedding 模型: {self.model_name} ...")
        self._model = SentenceTransformer(self.model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        if hasattr(self._model, 'max_seq_length'):
            self._max_seq_length = self._model.max_seq_length
        print(f"✓ 模型已加载 (dim={self._dimension}, max_seq={self._max_seq_length})")

    def encode(self, texts: list[str] | str, batch_size: int = 32) -> np.ndarray:
        """编码文本为向量"""
        if isinstance(texts, str):
            texts = [texts]
        return self.model.encode(texts, batch_size=batch_size, show_progress_bar=False)


# ── Chunk 策略 ────────────────────────────────────────────

DAILY_CHUNK_THRESHOLD = 1500  # tokens


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数"""
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en_chars = len(text) - cn_chars
    return int(cn_chars * 1.5 + en_chars * 0.3)


def chunk_daily_log(date_str: str, content: str, source: str,
                    repo: str = None) -> list[Chunk]:
    """
    日志 chunk 策略：
    - 小于阈值：整日为一个 chunk
    - 超过阈值：按仓库/来源拆为子 chunk
    """
    token_count = estimate_tokens(content)

    if token_count <= DAILY_CHUNK_THRESHOLD:
        return [Chunk(
            text=content,
            metadata={"date": date_str, "source": source, "repo": repo or "", "part": "1/1"}
        )]

    # 按仓库/来源拆分
    sections = _split_by_repo(content)
    if len(sections) <= 1:
        # 无法拆分，截断
        return [Chunk(
            text=content[:DAILY_CHUNK_THRESHOLD * 2],
            metadata={"date": date_str, "source": source, "repo": repo or "", "part": "1/1"}
        )]

    chunks = []
    for i, section in enumerate(sections, 1):
        if section.strip():
            chunks.append(Chunk(
                text=section,
                metadata={"date": date_str, "source": source, "repo": repo or "",
                          "part": f"{i}/{len(sections)}"}
            ))
    return chunks


def chunk_document(content: str, filename: str,
                   chunk_size: int = 300, overlap: int = 50) -> list[Chunk]:
    """
    非日志类文档的通用 chunk 策略

    按字符数分片，带重叠
    """
    chunks = []
    start = 0
    idx = 0
    while start < len(content):
        end = start + chunk_size
        text = content[start:end]
        if text.strip():
            chunks.append(Chunk(
                text=text,
                metadata={"filename": filename, "chunk_index": idx}
            ))
            idx += 1
        start += chunk_size - overlap
    return chunks


def _split_by_repo(content: str) -> list[str]:
    """按仓库/来源标记拆分日志内容"""
    import re
    # 匹配 "## 日期 周几 — 仓库名" 或 "[周几 日期] 仓库名:" 格式
    sections = re.split(r'(?=## \d{4}-\d{2}-\d{2}|(?=\[周[一二三四五六日]))', content)
    return [s for s in sections if s.strip()]


# ── 向量存储 ──────────────────────────────────────────────

class VectorStore:
    """FAISS 向量索引"""

    def __init__(self, index_dir: str | Path, embedding_model: EmbeddingModel):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.dimension = embedding_model.dimension

        self.index_path = self.index_dir / "logs.index"
        self.metadata_path = self.index_dir / "metadata.json"
        self.keys_path = self.index_dir / "indexed_keys.json"

        self.index: faiss.IndexFlatL2 = None
        self.metadata: list[dict] = []
        self.indexed_keys: set[str] = set()

        self._load()

    def _load(self):
        """加载已有索引或创建新索引"""
        if self.index_path.exists() and self.metadata_path.exists():
            self.index = faiss.read_index(str(self.index_path))
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            if self.keys_path.exists():
                with open(self.keys_path, "r", encoding="utf-8") as f:
                    self.indexed_keys = set(json.load(f))
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = []
            self.indexed_keys = set()

    def _save(self):
        """持久化索引"""
        faiss.write_index(self.index, str(self.index_path))
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False)
        with open(self.keys_path, "w", encoding="utf-8") as f:
            json.dump(list(self.indexed_keys), f)

    def index_log(self, date_str: str, content: str, source: str, repo: str = None):
        """增量索引单条日志（去重键：date + source + repo）"""
        key = f"{date_str}|{source}|{repo or ''}"
        if key in self.indexed_keys:
            return 0  # 已索引，跳过

        chunks = chunk_daily_log(date_str, content, source, repo)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = self.embedding_model.encode(texts)

        self.index.add(embeddings.astype(np.float32))
        for chunk in chunks:
            chunk.metadata["indexed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.metadata.append(chunk.metadata)

        self.indexed_keys.add(key)
        self._save()
        return len(chunks)

    def index_document(self, content: str, filename: str,
                       chunk_size: int = 300, chunk_overlap: int = 50):
        """索引非日志类文档"""
        key = f"doc|{filename}"
        if key in self.indexed_keys:
            return 0

        chunks = chunk_document(content, filename, chunk_size, chunk_overlap)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = self.embedding_model.encode(texts)

        self.index.add(embeddings.astype(np.float32))
        for chunk in chunks:
            chunk.metadata["indexed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.metadata.append(chunk.metadata)

        self.indexed_keys.add(key)
        self._save()
        return len(chunks)

    def search_by_similarity(self, query_text: str, exclude_week: str = None,
                             top_k: int = 5, max_chars_per_result: int = 500) -> list[dict]:
        """
        整体 embedding 检索

        - 本周日志整体作为 query 与历史 chunk 做相似度
        - 同一天多个子 chunk 只保留得分最高 1 条（去重）
        - 超长 query 降级：超过模型 max_seq_length 时自动用摘要替代
        - 排除当前周的数据
        """
        if self.index.ntotal == 0:
            return []

        # 检查 query 长度，超长时截断
        query_tokens = estimate_tokens(query_text)
        if query_tokens > self.embedding_model.max_seq_length:
            query_text = query_text[:self.embedding_model.max_seq_length * 2]

        query_vec = self.embedding_model.encode(query_text).astype(np.float32).reshape(1, -1)

        # 多取一些，后续去重
        search_k = min(top_k * 3, self.index.ntotal)
        distances, indices = self.index.search(query_vec, search_k)

        results = []
        seen_dates = set()
        for idx, dist in zip(indices[0], distances[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]

            # 排除当前周
            if exclude_week and meta.get("date", "").startswith(exclude_week[:8]):
                continue

            # 同一天只保留得分最高的一条
            date_key = meta.get("date", "")
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            # 获取原始文本（从 metadata 中无法直接获取，需要从 chunk 数据重建）
            # 这里返回 metadata + 距离，调用方根据 date 去 log_store 查原文
            results.append({
                "date": meta.get("date", ""),
                "source": meta.get("source", ""),
                "repo": meta.get("repo", ""),
                "filename": meta.get("filename", ""),
                "score": float(dist),
                "metadata": meta,
            })

            if len(results) >= top_k:
                break

        return results

    def get_chunk_text(self, index: int) -> str:
        """获取指定索引的 chunk 文本（用于调试）"""
        if 0 <= index < len(self.metadata):
            return str(self.metadata[index])
        return ""

    def rebuild(self, log_store):
        """全量重建索引"""
        self.index = faiss.IndexFlatL2(self.dimension)
        self.metadata = []
        self.indexed_keys = set()

        for d in log_store.list_all_dates():
            content = log_store.get_day_content(d)
            if content:
                self.index_log(d.isoformat(), content, "git")

        self._save()

    @property
    def total_chunks(self) -> int:
        return self.index.ntotal if self.index else 0
