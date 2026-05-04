"""
文档摄入器

功能：
  - 读取 .md / .docx / .txt 文件
  - 批量扫描目录
  - 管道输入
  - 摄入后自动索引到 VectorStore
"""

from __future__ import annotations

from pathlib import Path

from src.storage.vector_store import VectorStore


class DocCollector:
    """文档摄入器"""

    SUPPORTED_FORMATS = {".md", ".txt", ".docx"}

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def ingest_file(self, filepath: str | Path, chunk_size: int = 300,
                    chunk_overlap: int = 50) -> int:
        """
        摄入单个文件

        Returns:
            生成的 chunk 数量
        """
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        content = self._read_file(path)
        if not content.strip():
            return 0

        count = self.vector_store.index_document(
            content, path.name, chunk_size, chunk_overlap
        )
        return count

    def ingest_dir(self, dirpath: str | Path, chunk_size: int = 300,
                   chunk_overlap: int = 50) -> tuple[int, int]:
        """
        批量摄入目录下的所有文档

        Returns:
            (文件数, chunk 总数)
        """
        dir_path = Path(dirpath).expanduser().resolve()
        if not dir_path.is_dir():
            raise NotADirectoryError(f"不是目录: {dir_path}")

        file_count = 0
        chunk_count = 0

        for f in sorted(dir_path.rglob("*")):
            if f.is_file() and f.suffix.lower() in self.SUPPORTED_FORMATS:
                try:
                    count = self.ingest_file(f, chunk_size, chunk_overlap)
                    if count > 0:
                        file_count += 1
                        chunk_count += count
                        print(f"  ✓ {f.name} → {count} chunks")
                except Exception as e:
                    print(f"  ⚠️ {f.name}: {e}")

        return file_count, chunk_count

    def ingest_text(self, text: str, name: str = "manual_input",
                    chunk_size: int = 300, chunk_overlap: int = 50) -> int:
        """摄入文本内容"""
        if not text.strip():
            return 0
        return self.vector_store.index_document(text, name, chunk_size, chunk_overlap)

    def _read_file(self, path: Path) -> str:
        """读取文件内容"""
        suffix = path.suffix.lower()

        if suffix in (".md", ".txt"):
            return path.read_text(encoding="utf-8")
        elif suffix == ".docx":
            return self._read_docx(path)
        else:
            raise ValueError(f"不支持的格式: {suffix}")

    def _read_docx(self, path: Path) -> str:
        """读取 docx 文件"""
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise ImportError("需要安装 python-docx: pip install python-docx")
