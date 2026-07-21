import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    properties TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_project_type ON nodes(project_id, type);

CREATE TABLE IF NOT EXISTS edges (
    source_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_id, relation_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
"""


def _try_load_vec_extension(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def connect(db_path: Path | str, embedding_dim: int = 1536) -> sqlite3.Connection:
    """Open a LabKAG graph SQLite connection: WAL mode, schema ensured,
    sqlite-vec loaded and evidence_vec created only if the extension is
    available. Never raises for a missing/unloadable sqlite-vec -- callers
    check vec_available(conn) and degrade to keyword-only search."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    if _try_load_vec_extension(conn):
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS evidence_vec USING "
            f"vec0(evidence_id TEXT PRIMARY KEY, embedding FLOAT[{embedding_dim}])"
        )
    return conn


def vec_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM evidence_vec LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False
