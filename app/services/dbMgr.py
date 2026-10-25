import sqlite3
import os
import json
import time
import uuid
import hashlib
import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List

class DatabaseManager:
    _instance = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    @classmethod
    def get_instance(cls, db_dir: Optional[str] = None):
        if cls._instance is None:
            if not db_dir:
                from services.pathMgr import get_user_data_dir
                db_dir = str(get_user_data_dir("opensms") / "config")
            db_path = os.path.join(db_dir, "opensms.db")
            cls._instance = cls(db_path)
        return cls._instance

    @classmethod
    def set_db_path(cls, db_path: str):
        cls._instance = cls(db_path)
        return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def _conn(self):
        """Open a connection, commit on success / roll back on error, ALWAYS close it.
        (sqlite3's own context manager only commits; it leaves the file descriptor open.)"""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            cursor = conn.cursor()
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    recipient TEXT NOT NULL,
                    text TEXT NOT NULL,
                    encoding TEXT DEFAULT 'GSM-7',
                    segments INTEGER DEFAULT 1,
                    sim_slot INTEGER DEFAULT -1,
                    status TEXT DEFAULT 'queued',
                    carrier_error TEXT DEFAULT NULL,
                    batch_id TEXT DEFAULT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    delivered_at REAL DEFAULT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_batch ON messages(batch_id)')

            # API Keys table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_hash TEXT UNIQUE NOT NULL,
                    prefix TEXT NOT NULL,
                    scopes TEXT DEFAULT '["sms:write", "sms:read"]',
                    created_at REAL NOT NULL,
                    last_used_at REAL DEFAULT NULL,
                    is_active INTEGER DEFAULT 1
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_keys_hash ON api_keys(key_hash)')

            # Webhooks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS webhooks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    events TEXT DEFAULT '["sms.delivered", "sms.failed"]',
                    secret TEXT DEFAULT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at REAL NOT NULL
                )
            ''')
            conn.commit()
        self._migrate()

    # --- Schema migrations (PRAGMA user_version) ---
    # v0: schema created by releases <= 0.4.0 (or a brand-new file)
    # v1: idempotency table (additive only: no existing table or row is modified)
    # v2: per-part SMS receipts (message_parts) + messages.provider / messages.parts_expected
    SCHEMA_VERSION = 2
    IDEMPOTENCY_TTL_SECONDS = 24 * 3600
    IDEMPOTENCY_STALE_IN_PROGRESS_SECONDS = 15 * 60

    def _migrate(self):
        with self._conn() as conn:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema v{current} is newer than this app supports (v{self.SCHEMA_VERSION}). "
                    "Refusing to open it to avoid data loss; update the app.")
            if current < 1:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS idempotency (
                        key_id TEXT NOT NULL,
                        idem_key TEXT NOT NULL,
                        request_hash TEXT NOT NULL,
                        state TEXT NOT NULL,              -- 'in_progress' | 'done'
                        response TEXT DEFAULT NULL,       -- JSON of the original response
                        created_at REAL NOT NULL,
                        PRIMARY KEY (key_id, idem_key)
                    )
                ''')
                conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency(created_at)")
            if current < 2:
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
                if "provider" not in cols:
                    conn.execute("ALTER TABLE messages ADD COLUMN provider TEXT DEFAULT NULL")
                if "parts_expected" not in cols:
                    conn.execute("ALTER TABLE messages ADD COLUMN parts_expected INTEGER DEFAULT NULL")
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS message_parts (
                        msg_id TEXT NOT NULL,
                        part INTEGER NOT NULL,
                        sent_ok INTEGER DEFAULT NULL,       -- NULL unknown, 1 radio accepted, 0 failed
                        sent_error TEXT DEFAULT NULL,
                        delivery TEXT DEFAULT NULL,         -- NULL, 'delivered', 'pending', 'failed'
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (msg_id, part)
                    )
                ''')
            if current < self.SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {int(self.SCHEMA_VERSION)}")

    def get_schema_version(self) -> int:
        with self._conn() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    # --- Idempotency ---
    def idem_begin(self, key_id: str, idem_key: str, request_hash: str):
        """
        Atomically claim an idempotency key.
        Returns (state, stored_response):
          ("new", None)          caller owns the key and must call idem_complete/idem_release
          ("replay", dict)       identical request already completed: return stored_response
          ("in_progress", None)  identical request still running
          ("conflict", None)     same key reused with a different request body
        """
        now = time.time()
        with self._conn() as conn:
            conn.execute("DELETE FROM idempotency WHERE created_at < ?", (now - self.IDEMPOTENCY_TTL_SECONDS,))
            cur = conn.execute(
                "INSERT OR IGNORE INTO idempotency (key_id, idem_key, request_hash, state, created_at) "
                "VALUES (?, ?, ?, 'in_progress', ?)", (key_id, idem_key, request_hash, now))
            if cur.rowcount == 1:
                return "new", None
            row = conn.execute(
                "SELECT request_hash, state, response, created_at FROM idempotency WHERE key_id = ? AND idem_key = ?",
                (key_id, idem_key)).fetchone()
            if row is None:  # deleted between statements; treat as new on retry by caller
                return "in_progress", None
            if row["request_hash"] != request_hash:
                return "conflict", None
            if row["state"] == "done":
                return "replay", json.loads(row["response"])
            if now - row["created_at"] > self.IDEMPOTENCY_STALE_IN_PROGRESS_SECONDS:
                # owner crashed long ago: allow a retry to take the key over
                conn.execute("UPDATE idempotency SET created_at = ? WHERE key_id = ? AND idem_key = ?",
                             (now, key_id, idem_key))
                return "new", None
            return "in_progress", None

    def idem_complete(self, key_id: str, idem_key: str, response: Dict[str, Any]):
        with self._conn() as conn:
            conn.execute("UPDATE idempotency SET state = 'done', response = ? WHERE key_id = ? AND idem_key = ?",
                         (json.dumps(response), key_id, idem_key))

    def idem_release(self, key_id: str, idem_key: str):
        """Forget a claim after a failed attempt so the client may retry with the same key."""
        with self._conn() as conn:
            conn.execute("DELETE FROM idempotency WHERE key_id = ? AND idem_key = ? AND state = 'in_progress'",
                         (key_id, idem_key))

    # --- Messages Operations ---

    def create_message(
        self,
        recipient: str,
        text: str,
        encoding: str = "GSM-7",
        segments: int = 1,
        sim_slot: int = -1,
        status: str = "queued",
        batch_id: Optional[str] = None,
        msg_id: Optional[str] = None,
        provider: Optional[str] = None
    ) -> str:
        now = time.time()
        record_id = msg_id or str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute('''
                INSERT INTO messages (
                    id, recipient, text, encoding, segments, sim_slot,
                    status, batch_id, created_at, updated_at, provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record_id, recipient, text, encoding, segments, sim_slot,
                status, batch_id, now, now, provider
            ))
            conn.commit()
        return record_id

    def update_message_status(
        self,
        msg_id: str,
        status: str,
        carrier_error: Optional[str] = None
    ) -> bool:
        now = time.time()
        delivered_at = now if status == "delivered" else None
        with self._conn() as conn:
            cursor = conn.cursor()
            if delivered_at:
                cursor.execute('''
                    UPDATE messages
                    SET status = ?, carrier_error = ?, updated_at = ?, delivered_at = ?
                    WHERE id = ?
                ''', (status, carrier_error, now, delivered_at, msg_id))
            else:
                cursor.execute('''
                    UPDATE messages
                    SET status = ?, carrier_error = ?, updated_at = ?
                    WHERE id = ?
                ''', (status, carrier_error, now, msg_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_message(self, msg_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE id = ?', (msg_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Per-part receipts & lifecycle ---
    def record_parts(self, msg_id: str, expected: int):
        """Fix the number of SMS parts for a message and make sure a row exists for each."""
        now = time.time()
        with self._conn() as conn:
            conn.execute("UPDATE messages SET parts_expected = ? WHERE id = ?", (expected, msg_id))
            for part in range(expected):
                conn.execute("INSERT OR IGNORE INTO message_parts (msg_id, part, updated_at) VALUES (?, ?, ?)",
                             (msg_id, part, now))

    def update_part(self, msg_id: str, part: int, sent_ok: Optional[bool] = None,
                    sent_error: Optional[str] = None, delivery: Optional[str] = None):
        """Upsert a receipt for one part (receipts may arrive before record_parts or out of order)."""
        now = time.time()
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO message_parts (msg_id, part, updated_at) VALUES (?, ?, ?)",
                         (msg_id, part, now))
            if sent_ok is not None:
                conn.execute("UPDATE message_parts SET sent_ok = ?, sent_error = ?, updated_at = ? WHERE msg_id = ? AND part = ?",
                             (1 if sent_ok else 0, sent_error, now, msg_id, part))
            if delivery is not None:
                conn.execute("UPDATE message_parts SET delivery = ?, updated_at = ? WHERE msg_id = ? AND part = ?",
                             (delivery, now, msg_id, part))

    def get_parts(self, msg_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT part, sent_ok, sent_error, delivery, updated_at FROM message_parts "
                                "WHERE msg_id = ? ORDER BY part", (msg_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_status_row(self, msg_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute("SELECT id, status, parts_expected, provider, carrier_error FROM messages WHERE id = ?",
                             (msg_id,)).fetchone()
            return dict(r) if r else None

    def list_by_status(self, statuses: List[str], limit: int = 5000) -> List[Dict[str, Any]]:
        marks = ",".join("?" for _ in statuses)
        with self._conn() as conn:
            rows = conn.execute(f"SELECT * FROM messages WHERE status IN ({marks}) ORDER BY created_at LIMIT ?",
                                list(statuses) + [limit]).fetchall()
            return [dict(r) for r in rows]

    FINISHED_STATUSES = ("sent", "delivered", "failed", "unknown")

    def purge_messages(self, older_than_ts: Optional[float] = None) -> int:
        """
        Delete finished messages (and their per-part receipts), optionally only those created before
        `older_than_ts`. Messages still in flight (queued / submitted / sending) are NEVER deleted.
        Returns the number of messages removed.
        """
        marks = ",".join("?" for _ in self.FINISHED_STATUSES)
        where = f"status IN ({marks})"
        params: List[Any] = list(self.FINISHED_STATUSES)
        if older_than_ts is not None:
            where += " AND created_at < ?"
            params.append(older_than_ts)
        with self._conn() as conn:
            ids = [r[0] for r in conn.execute(f"SELECT id FROM messages WHERE {where}", params).fetchall()]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                m = ",".join("?" for _ in chunk)
                conn.execute(f"DELETE FROM message_parts WHERE msg_id IN ({m})", chunk)
                conn.execute(f"DELETE FROM messages WHERE id IN ({m})", chunk)
            return len(ids)

    def storage_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            active_keys = conn.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1").fetchone()[0]
            schema = conn.execute("PRAGMA user_version").fetchone()[0]
        try:
            size = os.path.getsize(self.db_path)
        except OSError:
            size = None
        return {"messages": messages, "active_keys": active_keys, "schema": schema, "size_bytes": size}

    def expire_submitted(self, older_than_ts: float, error: str) -> int:
        """Messages handed to the radio layer with no 'sent' receipt after a long time -> 'unknown'."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE messages SET status = 'unknown', carrier_error = ?, updated_at = ? "
                "WHERE status = 'submitted' AND provider = 'android' AND updated_at < ?",
                (error, now, older_than_ts))
            return cur.rowcount

    @staticmethod
    def _message_filters(status: Optional[str], search: Optional[str]):
        params: List[Any] = []
        conditions = []
        if status and status != "all":
            conditions.append('status = ?')
            params.append(status)
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(recipient LIKE ? ESCAPE '\\' OR text LIKE ? ESCAPE '\\')")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        return where, params

    def get_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        where, params = self._message_filters(status, search)
        query = 'SELECT * FROM messages' + where + ' ORDER BY created_at DESC, id LIMIT ? OFFSET ?'
        with self._conn() as conn:
            return [dict(row) for row in conn.execute(query, params + [limit, offset]).fetchall()]

    def count_messages(self, status: Optional[str] = None, search: Optional[str] = None) -> int:
        where, params = self._message_filters(status, search)
        with self._conn() as conn:
            return conn.execute('SELECT COUNT(*) FROM messages' + where, params).fetchone()[0]

    def get_metrics(self) -> Dict[str, Any]:
        """Calculates live gateway stats (today's sent, failed, queue depth, success rate)."""
        # Start of the current *local* day
        local_now = datetime.datetime.now().astimezone()
        start_of_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        with self._conn() as conn:
            cursor = conn.cursor()
            # Queue depth
            cursor.execute("SELECT COUNT(*) FROM messages WHERE status IN ('queued', 'sending', 'submitted')")
            queue_depth = cursor.fetchone()[0]

            # Sent today
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE status IN ('sent', 'delivered') AND created_at >= ?",
                (start_of_day,)
            )
            sent_today = cursor.fetchone()[0]

            # Failed today
            cursor.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'failed' AND created_at >= ?",
                (start_of_day,)
            )
            failed_today = cursor.fetchone()[0]

            # All-time total
            cursor.execute("SELECT COUNT(*) FROM messages WHERE status IN ('sent', 'delivered')")
            total_sent = cursor.fetchone()[0]

            total_today = sent_today + failed_today
            success_rate = (sent_today / total_today * 100.0) if total_today > 0 else 100.0

            return {
                "queue_depth": queue_depth,
                "sent_today": sent_today,
                "failed_today": failed_today,
                "total_sent": total_sent,
                "success_rate": round(success_rate, 1)
            }

    # --- API Keys Operations ---

    def add_api_key(self, raw_key: str, name: str = "Default Key", scopes: Optional[List[str]] = None) -> str:
        key_id = str(uuid.uuid4())
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        prefix = raw_key[:10] + "..." if len(raw_key) > 10 else raw_key
        scopes_json = json.dumps(scopes or ["sms:write", "sms:read"])
        now = time.time()

        with self._conn() as conn:
            conn.execute('''
                INSERT INTO api_keys (id, name, key_hash, prefix, scopes, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (key_id, name, key_hash, prefix, scopes_json, now))
            conn.commit()
        return key_id

    def verify_api_key(self, raw_key: str) -> Optional[Dict[str, Any]]:
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now = time.time()
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1', (key_hash,))
            row = cursor.fetchone()
            if row:
                key_dict = dict(row)
                key_dict["scopes"] = json.loads(key_dict.get("scopes") or "[]")
                # Update last used
                cursor.execute('UPDATE api_keys SET last_used_at = ? WHERE id = ?', (now, key_dict["id"]))
                conn.commit()
                return key_dict
        return None

    def list_api_keys(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, prefix, scopes, created_at, last_used_at, is_active FROM api_keys ORDER BY created_at DESC')
            keys = []
            for row in cursor.fetchall():
                d = dict(row)
                d["scopes"] = json.loads(d.get("scopes") or "[]")
                keys.append(d)
            return keys

    def revoke_api_key(self, key_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE api_keys SET is_active = 0 WHERE id = ?', (key_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_api_key(self, key_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                'SELECT id, name, prefix, scopes, created_at, last_used_at, is_active FROM api_keys WHERE id = ?',
                (key_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            d["scopes"] = json.loads(d.get("scopes") or "[]")
            return d

    def count_active_keys(self) -> int:
        with self._conn() as conn:
            return conn.execute('SELECT COUNT(*) FROM api_keys WHERE is_active = 1').fetchone()[0]

    def migrate_legacy_keys_json(self, keys_file_path: str):
        """
        One-time import of the legacy keys.json into SQLite (SQLite is the single source of truth).
        Every hash not already present is imported, then the file is renamed to keys.json.migrated
        so it can never act as a second, un-revocable key store (audit issue SEC-02).
        """
        if not os.path.exists(keys_file_path):
            return
        try:
            with open(keys_file_path, "r", encoding="utf-8") as kf:
                data = json.load(kf)
            if not isinstance(data, dict):
                raise ValueError("keys.json is not an object")
            with self._conn() as conn:
                for hashed_key, info in data.items():
                    info = info if isinstance(info, dict) else {}
                    name = info.get("name", "Migrated Key")
                    scopes = json.dumps(info.get("scopes") or ["sms:write", "sms:read"])
                    created_at = info.get("created_at", time.time())
                    conn.execute('''
                        INSERT OR IGNORE INTO api_keys (id, name, key_hash, prefix, scopes, created_at, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                    ''', (str(uuid.uuid4()), name, hashed_key, "osms_migrated...", scopes, created_at))
            os.replace(keys_file_path, keys_file_path + ".migrated")
        except Exception as e:
            print(f"Notice: legacy keys migration skipped: {e}")
