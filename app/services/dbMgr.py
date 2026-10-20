import sqlite3
import os
import json
import time
import uuid
import hashlib
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
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
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
        msg_id: Optional[str] = None
    ) -> str:
        now = time.time()
        record_id = msg_id or str(uuid.uuid4())
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO messages (
                    id, recipient, text, encoding, segments, sim_slot,
                    status, batch_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record_id, recipient, text, encoding, segments, sim_slot,
                status, batch_id, now, now
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
        delivered_at = now if status in ("delivered", "sent") else None
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE id = ?', (msg_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = 'SELECT * FROM messages'
        params: List[Any] = []
        conditions = []

        if status and status != "all":
            conditions.append('status = ?')
            params.append(status)

        if search:
            conditions.append('(recipient LIKE ? OR text LIKE ?)')
            params.extend([f"%{search}%", f"%{search}%"])

        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)

        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_metrics(self) -> Dict[str, Any]:
        """Calculates live gateway stats (today's sent, failed, queue depth, success rate)."""
        now = time.time()
        # Start of current day timestamp (midnight UTC/local approximation)
        start_of_day = now - (now % 86400)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Queue depth
            cursor.execute("SELECT COUNT(*) FROM messages WHERE status IN ('queued', 'sending')")
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

        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO api_keys (id, name, key_hash, prefix, scopes, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (key_id, name, key_hash, prefix, scopes_json, now))
            conn.commit()
        return key_id

    def verify_api_key(self, raw_key: str) -> Optional[Dict[str, Any]]:
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        now = time.time()
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, prefix, scopes, created_at, last_used_at, is_active FROM api_keys ORDER BY created_at DESC')
            keys = []
            for row in cursor.fetchall():
                d = dict(row)
                d["scopes"] = json.loads(d.get("scopes") or "[]")
                keys.append(d)
            return keys

    def revoke_api_key(self, key_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE api_keys SET is_active = 0 WHERE id = ?', (key_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_api_key(self, key_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
            conn.commit()
            return cursor.rowcount > 0

    def migrate_legacy_keys_json(self, keys_file_path: str):
        """Imports existing keys from legacy keys.json if table is currently empty."""
        if not os.path.exists(keys_file_path):
            return
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM api_keys')
                count = cursor.fetchone()[0]
                if count > 0:
                    return

                with open(keys_file_path, "r", encoding="utf-8") as kf:
                    data = json.load(kf)

                for hashed_key, info in data.items():
                    name = info.get("name", "Migrated Key")
                    scopes = json.dumps(info.get("scopes", ["sms:write", "sms:read"]))
                    created_at = info.get("created_at", time.time())
                    cursor.execute('''
                        INSERT OR IGNORE INTO api_keys (id, name, key_hash, prefix, scopes, created_at, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                    ''', (str(uuid.uuid4()), name, hashed_key, "osms_migrated...", scopes, created_at))
                conn.commit()
        except Exception as e:
            print(f"Notice: legacy keys migration skipped: {e}")
