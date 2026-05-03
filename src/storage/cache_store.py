"""
Git 统计缓存（SQLite）

缓存 commit hash → diff --stat 结果，避免大仓库重复计算。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class GitStatsCache:
    """SQLite 缓存：commit hash → 统计结果"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_table()

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS commit_stats (
                hash TEXT NOT NULL,
                repo TEXT NOT NULL,
                insertions INTEGER DEFAULT 0,
                deletions INTEGER DEFAULT 0,
                files TEXT DEFAULT '[]',
                PRIMARY KEY (hash, repo)
            )
        """)
        self._conn.commit()

    def has(self, commit_hash: str, repo_path: str) -> bool:
        """检查缓存是否存在"""
        row = self._conn.execute(
            "SELECT 1 FROM commit_stats WHERE hash = ? AND repo = ?",
            (commit_hash, repo_path)
        ).fetchone()
        return row is not None

    def get(self, commit_hash: str, repo_path: str) -> dict:
        """获取缓存的统计结果"""
        row = self._conn.execute(
            "SELECT insertions, deletions, files FROM commit_stats WHERE hash = ? AND repo = ?",
            (commit_hash, repo_path)
        ).fetchone()
        if row is None:
            raise KeyError(f"缓存未命中: {commit_hash}")
        return {
            "insertions": row[0],
            "deletions": row[1],
            "files": json.loads(row[2]),
        }

    def set(self, commit_hash: str, repo_path: str, stats: dict):
        """写入缓存"""
        self._conn.execute(
            "INSERT OR REPLACE INTO commit_stats (hash, repo, insertions, deletions, files) "
            "VALUES (?, ?, ?, ?, ?)",
            (commit_hash, repo_path, stats["insertions"], stats["deletions"],
             json.dumps(stats["files"], ensure_ascii=False))
        )
        self._conn.commit()

    def gc(self, existing_hashes: set[str], repo_path: str):
        """清理孤立条目（不在 existing_hashes 中的记录）"""
        rows = self._conn.execute(
            "SELECT hash FROM commit_stats WHERE repo = ?", (repo_path,)
        ).fetchall()
        to_delete = [row[0] for row in rows if row[0] not in existing_hashes]
        if to_delete:
            placeholders = ",".join("?" * len(to_delete))
            self._conn.execute(
                f"DELETE FROM commit_stats WHERE hash IN ({placeholders}) AND repo = ?",
                (*to_delete, repo_path)
            )
            self._conn.commit()
        return len(to_delete)

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
