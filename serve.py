import json
import hmac
import hashlib
import importlib.util
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from http.cookies import SimpleCookie
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PROJECT_ROOT / "dist" if (PROJECT_ROOT / "dist").exists() else PROJECT_ROOT
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(PROJECT_ROOT / "data")))


def sqlite_file_from_environment():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url.startswith("sqlite:///"):
        return Path(database_url[len("sqlite:///"):])
    if database_url and not database_url.startswith("sqlite://"):
        raise ValueError("DATABASE_URL currently supports sqlite:/// paths only")
    return Path(os.environ.get("APP_DB_FILE") or (DATA_DIR / "app.db"))


DATA_FILE = DATA_DIR / "projects.json"
AI_SETTINGS_FILE = DATA_DIR / "ai-settings.json"
AUTH_FILE = DATA_DIR / "auth.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
DB_FILE = sqlite_file_from_environment()
SESSION_COOKIE = "schedule_ai_session"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30)))
PROJECT_LIMIT_PER_OWNER = int(os.environ.get("PROJECT_LIMIT_PER_OWNER", "20"))
AI_DAILY_LIMIT_PER_OWNER = int(os.environ.get("AI_DAILY_LIMIT_PER_OWNER", "20"))
SUPPORTED_AI_PROVIDERS = {"deepseek", "gemini", "openai"}
AI_PROVIDER_HOSTS = {"deepseek": "api.deepseek.com", "gemini": "generativelanguage.googleapis.com", "openai": "api.openai.com"}


def configured_admin_emails():
    return {value.strip().lower() for value in os.environ.get("ADMIN_EMAILS", "").split(",") if value.strip()}


def role_for_email(email, fallback="user"):
    return "admin" if str(email or "").strip().lower() in configured_admin_emails() else fallback


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def check_tcp_endpoint(host, port=443, timeout=.8):
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        return {"host": host, "dns": False, "tcp443": False, "addresses": [], "error": str(error)}
    addresses = []
    reachable = False
    for family, socktype, proto, _, sockaddr in records[:6]:
        address = str(sockaddr[0])
        if address not in addresses:
            addresses.append(address)
        connection = socket.socket(family, socktype, proto)
        connection.settimeout(timeout)
        try:
            connection.connect(sockaddr)
            reachable = True
            break
        except OSError:
            continue
        finally:
            connection.close()
    return {"host": host, "dns": bool(addresses), "tcp443": reachable, "addresses": addresses[:4]}


def _json_encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_decode(value, fallback):
    if value in (None, ""):
        return fallback
    try:
        parsed = json.loads(value)
        return parsed
    except (TypeError, json.JSONDecodeError):
        return fallback


class SQLiteDatabase:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.ready = False

    def _connect_raw(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def ensure_schema(self):
        with self.lock:
            if self.ready:
                return
            with self._connect_raw() as connection:
                connection.executescript("""
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS projects (
                  owner TEXT NOT NULL,
                  id TEXT NOT NULL,
                  name TEXT NOT NULL,
                  location TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  project_json TEXT NOT NULL,
                  tasks_json TEXT NOT NULL,
                  baselines_json TEXT NOT NULL,
                  custom_templates_json TEXT NOT NULL,
                  PRIMARY KEY (owner, id)
                );
                CREATE INDEX IF NOT EXISTS idx_projects_owner_updated
                  ON projects(owner, updated_at DESC);

                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  email TEXT NOT NULL UNIQUE,
                  name TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  expires_at REAL NOT NULL,
                  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS user_templates (
                  owner TEXT PRIMARY KEY,
                  templates_json TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_settings (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  api_key TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_usage (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  owner TEXT NOT NULL,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  success INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  error_type TEXT NOT NULL DEFAULT '',
                  duration_ms INTEGER NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ai_usage_owner_created
                  ON ai_usage(owner, created_at);
                CREATE INDEX IF NOT EXISTS idx_ai_usage_created
                  ON ai_usage(created_at);
                """)
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
                if "role" not in columns:
                    connection.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
                connection.commit()
            self.ready = True

    def connect(self):
        self.ensure_schema()
        return self._connect_raw()


class ProjectStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {"schemaVersion": 1, "projects": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("projects"), dict):
                raise ValueError("projects must be an object")
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            return {"schemaVersion": 1, "projects": {}}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def list(self, owner="local"):
        with self.lock:
            records = [item for item in self._read()["projects"].values() if item.get("owner", "local") == owner]
            summaries = [{
                "id": item["id"],
                "name": item.get("project", {}).get("projectName", "未命名项目"),
                "location": item.get("project", {}).get("location", ""),
                "updatedAt": item.get("updatedAt", ""),
                "createdAt": item.get("createdAt", ""),
                "taskCount": len(item.get("tasks", [])),
                "completionDate": item.get("tasks", [{}])[-1].get("endDate", "") if item.get("tasks") else "",
            } for item in records]
            return sorted(summaries, key=lambda item: item["updatedAt"], reverse=True)

    def get(self, project_id, owner="local"):
        with self.lock:
            record = self._read()["projects"].get(project_id)
            return record if record and record.get("owner", "local") == owner else None

    def count(self, owner="local"):
        with self.lock:
            return len([item for item in self._read()["projects"].values() if item.get("owner", "local") == owner])

    def save(self, project_id, payload, owner="local"):
        if not project_id or len(project_id) > 100:
            raise ValueError("invalid project id")
        project, tasks = payload.get("project"), payload.get("tasks")
        if not isinstance(project, dict) or not isinstance(tasks, list) or not project.get("projectName"):
            raise ValueError("project and tasks are required")
        with self.lock:
            data = self._read()
            previous = data["projects"].get(project_id, {})
            if previous and previous.get("owner", "local") != owner:
                raise ValueError("project id is already in use")
            record = {
                "id": project_id,
                "owner": owner,
                "createdAt": previous.get("createdAt", utc_now()),
                "updatedAt": utc_now(),
                "project": project,
                "tasks": tasks,
                "baselines": payload.get("baselines", []),
                "customTemplates": payload.get("customTemplates", []),
            }
            data["projects"][project_id] = record
            self._write(data)
            return record

    def delete(self, project_id, owner="local"):
        with self.lock:
            data = self._read()
            record = data["projects"].get(project_id)
            existed = bool(record and record.get("owner", "local") == owner)
            if existed:
                data["projects"].pop(project_id, None)
            if existed:
                self._write(data)
            return existed


class UserTemplateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {"schemaVersion": 1, "owners": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("owners"), dict):
                raise ValueError("owners must be an object")
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            return {"schemaVersion": 1, "owners": {}}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _clean_template(item, index=0):
        if not isinstance(item, dict):
            raise ValueError("templates must contain objects")
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError("template name is required")
        duration = item.get("duration", 1)
        try:
            duration = max(1, int(duration))
        except (TypeError, ValueError):
            raise ValueError("template duration must be a number")
        template_id = str(item.get("id") or f"CUSTOM-SERVER-{int(time.time() * 1000)}-{index + 1}").strip()
        cleaned = {**item, "id": template_id[:120], "name": name[:160], "duration": duration, "isCustom": True}
        cleaned["predecessorNames"] = [str(value).strip()[:160] for value in item.get("predecessorNames", []) if str(value).strip()][:20]
        cleaned["resourceDemand"] = [str(value).strip()[:120] for value in item.get("resourceDemand", []) if str(value).strip()][:40]
        cleaned["materialNodes"] = [str(value).strip()[:120] for value in item.get("materialNodes", []) if str(value).strip()][:40]
        cleaned["expansionDimensions"] = [str(value).strip()[:80] for value in item.get("expansionDimensions", []) if str(value).strip()][:10]
        if cleaned.get("relationType") not in {"FS", "SS", "FF", "SF"}:
            cleaned["relationType"] = "FS"
        try:
            cleaned["lag"] = int(cleaned.get("lag", 0))
        except (TypeError, ValueError):
            cleaned["lag"] = 0
        return cleaned

    def list(self, owner):
        with self.lock:
            owner_data = self._read()["owners"].get(owner, {})
            templates = owner_data.get("templates", [])
            return {"templates": templates if isinstance(templates, list) else [], "updatedAt": owner_data.get("updatedAt", "")}

    def replace(self, owner, templates):
        if not isinstance(templates, list):
            raise ValueError("templates must be a list")
        if len(templates) > 500:
            raise ValueError("最多保存 500 项自定义模板")
        cleaned = [self._clean_template(item, index) for index, item in enumerate(templates)]
        deduped = {}
        for item in cleaned:
            deduped[item["id"]] = item
        with self.lock:
            data = self._read()
            data["owners"][owner] = {"templates": list(deduped.values()), "updatedAt": utc_now()}
            self._write(data)
            return self.list(owner)


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {"schemaVersion": 1, "users": {}, "sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("users"), dict):
                raise ValueError("users must be an object")
            if not isinstance(data.get("sessions"), dict):
                data["sessions"] = {}
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            return {"schemaVersion": 1, "users": {}, "sessions": {}}

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _normalize_email(email):
        return str(email or "").strip().lower()

    @staticmethod
    def _public_user(user):
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or user["email"].split("@")[0],
            "role": role_for_email(user["email"], user.get("role", "user")),
            "createdAt": user.get("createdAt", ""),
        }

    @staticmethod
    def _hash_password(password):
        salt = secrets.token_hex(16)
        iterations = 220000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
        return f"pbkdf2_sha256${iterations}${salt}${digest}"

    @staticmethod
    def _verify_password(password, stored):
        try:
            algorithm, iterations, salt, expected = stored.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    def create_user(self, payload):
        email = self._normalize_email(payload.get("email"))
        password = str(payload.get("password", ""))
        name = str(payload.get("name", "")).strip()[:60] or email.split("@")[0]
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("请输入有效邮箱")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")
        with self.lock:
            data = self._read()
            if any(user.get("email") == email for user in data["users"].values()):
                raise ValueError("该邮箱已注册")
            user_id = f"u_{secrets.token_urlsafe(12)}"
            user = {
                "id": user_id,
                "email": email,
                "name": name,
                "passwordHash": self._hash_password(password),
                "role": role_for_email(email),
                "createdAt": utc_now(),
                "updatedAt": utc_now(),
            }
            data["users"][user_id] = user
            self._write(data)
            return self._public_user(user)

    def authenticate(self, email, password):
        email = self._normalize_email(email)
        with self.lock:
            data = self._read()
            for user in data["users"].values():
                if user.get("email") == email and self._verify_password(str(password or ""), user.get("passwordHash", "")):
                    return self._public_user(user)
        raise ValueError("邮箱或密码不正确")

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.lock:
            data = self._read()
            if user_id not in data["users"]:
                raise ValueError("用户不存在")
            data["sessions"][token] = {"userId": user_id, "createdAt": utc_now(), "expiresAt": time.time() + SESSION_TTL_SECONDS}
            self._write(data)
        return token

    def user_from_session(self, token):
        if not token:
            return None
        with self.lock:
            data = self._read()
            session = data["sessions"].get(token)
            if not session:
                return None
            if float(session.get("expiresAt", 0)) < time.time():
                data["sessions"].pop(token, None)
                self._write(data)
                return None
            user = data["users"].get(session.get("userId"))
            return self._public_user(user) if user else None

    def logout(self, token):
        if not token:
            return
        with self.lock:
            data = self._read()
            if token in data["sessions"]:
                data["sessions"].pop(token, None)
                self._write(data)


class RateLimiter:
    def __init__(self, limit=30, window_seconds=60):
        self.limit = max(1, int(limit))
        self.window_seconds = window_seconds
        self.lock = threading.Lock()
        self.events = {}

    def allow(self, key):
        now = time.time()
        with self.lock:
            recent = [stamp for stamp in self.events.get(key, []) if now - stamp < self.window_seconds]
            if len(recent) >= self.limit:
                self.events[key] = recent
                return False
            recent.append(now)
            self.events[key] = recent
            return True


class AiConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    def get(self):
        with self.lock:
            env_key = os.environ.get("AI_API_KEY", "").strip()
            if env_key:
                provider = os.environ.get("AI_PROVIDER", "deepseek").strip()
                model = os.environ.get("AI_MODEL", "deepseek-chat").strip()
                if provider in SUPPORTED_AI_PROVIDERS and model:
                    return {"provider": provider, "model": model, "apiKey": env_key, "source": "environment"}
            if not self.path.exists():
                return None
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return data if data.get("provider") in SUPPORTED_AI_PROVIDERS and data.get("apiKey") and data.get("model") else None
            except (json.JSONDecodeError, OSError):
                return None

    def public(self):
        data = self.get()
        if not data:
            return {"configured": False, "provider": "deepseek", "model": "deepseek-chat", "maskedKey": ""}
        key = data["apiKey"]
        return {"configured": True, "provider": data["provider"], "model": data["model"], "maskedKey": f"••••{key[-4:]}"}

    def save(self, payload):
        provider, model, api_key = payload.get("provider"), str(payload.get("model", "")).strip(), str(payload.get("apiKey", "")).strip()
        previous = self.get()
        if not api_key and previous and previous.get("provider") == provider:
            api_key = previous["apiKey"]
        if provider not in SUPPORTED_AI_PROVIDERS or not model or not api_key:
            raise ValueError("provider, model and apiKey are required")
        data = {"provider": provider, "model": model, "apiKey": api_key, "updatedAt": utc_now()}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        return self.public()

    def delete(self):
        with self.lock:
            if self.path.exists():
                self.path.unlink()


class DatabaseProjectStore:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    @staticmethod
    def _row_to_record(row):
        if not row:
            return None
        return {
            "id": row["id"],
            "owner": row["owner"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "project": _json_decode(row["project_json"], {}),
            "tasks": _json_decode(row["tasks_json"], []),
            "baselines": _json_decode(row["baselines_json"], []),
            "customTemplates": _json_decode(row["custom_templates_json"], []),
        }

    def list(self, owner="local"):
        with self.database.lock, self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects WHERE owner = ? ORDER BY updated_at DESC",
                (owner,),
            ).fetchall()
        summaries = []
        for row in rows:
            project = _json_decode(row["project_json"], {})
            tasks = _json_decode(row["tasks_json"], [])
            summaries.append({
                "id": row["id"],
                "name": project.get("projectName", row["name"] or "未命名项目"),
                "location": project.get("location", row["location"] or ""),
                "updatedAt": row["updated_at"],
                "createdAt": row["created_at"],
                "taskCount": len(tasks),
                "completionDate": tasks[-1].get("endDate", "") if tasks else "",
            })
        return summaries

    def get(self, project_id, owner="local"):
        with self.database.lock, self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE owner = ? AND id = ?",
                (owner, project_id),
            ).fetchone()
        return self._row_to_record(row)

    def count(self, owner="local"):
        with self.database.lock, self.database.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM projects WHERE owner = ?", (owner,)).fetchone()[0])

    def save(self, project_id, payload, owner="local"):
        if not project_id or len(project_id) > 100:
            raise ValueError("invalid project id")
        project, tasks = payload.get("project"), payload.get("tasks")
        if not isinstance(project, dict) or not isinstance(tasks, list) or not project.get("projectName"):
            raise ValueError("project and tasks are required")
        now = utc_now()
        with self.database.lock, self.database.connect() as connection:
            conflict = connection.execute(
                "SELECT 1 FROM projects WHERE id = ? AND owner <> ?",
                (project_id, owner),
            ).fetchone()
            if conflict:
                raise ValueError("project id is already in use")
            previous = connection.execute(
                "SELECT created_at FROM projects WHERE owner = ? AND id = ?",
                (owner, project_id),
            ).fetchone()
            created_at = previous["created_at"] if previous else now
            connection.execute(
                """
                INSERT INTO projects (
                  owner, id, name, location, created_at, updated_at,
                  project_json, tasks_json, baselines_json, custom_templates_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner, id) DO UPDATE SET
                  name = excluded.name,
                  location = excluded.location,
                  updated_at = excluded.updated_at,
                  project_json = excluded.project_json,
                  tasks_json = excluded.tasks_json,
                  baselines_json = excluded.baselines_json,
                  custom_templates_json = excluded.custom_templates_json
                """,
                (
                    owner,
                    project_id,
                    str(project.get("projectName", "未命名项目"))[:240],
                    str(project.get("location", ""))[:240],
                    created_at,
                    now,
                    _json_encode(project),
                    _json_encode(tasks),
                    _json_encode(payload.get("baselines", [])),
                    _json_encode(payload.get("customTemplates", [])),
                ),
            )
            connection.commit()
        return self.get(project_id, owner)

    def delete(self, project_id, owner="local"):
        with self.database.lock, self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE owner = ? AND id = ?",
                (owner, project_id),
            )
            connection.commit()
            return cursor.rowcount > 0


class DatabaseUserTemplateStore:
    _clean_template = staticmethod(UserTemplateStore._clean_template)

    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def list(self, owner):
        with self.database.lock, self.database.connect() as connection:
            row = connection.execute(
                "SELECT templates_json, updated_at FROM user_templates WHERE owner = ?",
                (owner,),
            ).fetchone()
        if not row:
            return {"templates": [], "updatedAt": ""}
        templates = _json_decode(row["templates_json"], [])
        return {"templates": templates if isinstance(templates, list) else [], "updatedAt": row["updated_at"]}

    def replace(self, owner, templates):
        if not isinstance(templates, list):
            raise ValueError("templates must be a list")
        if len(templates) > 500:
            raise ValueError("最多保存 500 项自定义模板")
        cleaned = [self._clean_template(item, index) for index, item in enumerate(templates)]
        deduped = {}
        for item in cleaned:
            deduped[item["id"]] = item
        now = utc_now()
        with self.database.lock, self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_templates(owner, templates_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(owner) DO UPDATE SET
                  templates_json = excluded.templates_json,
                  updated_at = excluded.updated_at
                """,
                (owner, _json_encode(list(deduped.values())), now),
            )
            connection.commit()
        return self.list(owner)


class DatabaseAuthStore:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    @staticmethod
    def _public_user(user):
        role = role_for_email(user.get("email"), user.get("role", "user"))
        return {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or user["email"].split("@")[0],
            "role": role,
            "createdAt": user.get("createdAt") or user.get("created_at") or "",
        }

    def create_user(self, payload):
        email = AuthStore._normalize_email(payload.get("email"))
        password = str(payload.get("password", ""))
        name = str(payload.get("name", "")).strip()[:60] or email.split("@")[0]
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("请输入有效邮箱")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")
        now = utc_now()
        user_id = f"u_{secrets.token_urlsafe(12)}"
        user = {
            "id": user_id,
            "email": email,
            "name": name,
            "password_hash": AuthStore._hash_password(password),
            "role": role_for_email(email),
            "created_at": now,
            "updated_at": now,
        }
        with self.database.lock, self.database.connect() as connection:
            if connection.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                raise ValueError("该邮箱已注册")
            connection.execute(
                "INSERT INTO users(id, email, name, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user["id"], user["email"], user["name"], user["password_hash"], user["role"], user["created_at"], user["updated_at"]),
            )
            connection.commit()
        return self._public_user(user)

    def authenticate(self, email, password):
        email = AuthStore._normalize_email(email)
        with self.database.lock, self.database.connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row and AuthStore._verify_password(str(password or ""), row["password_hash"]):
            return self._public_user(dict(row))
        raise ValueError("邮箱或密码不正确")

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.database.lock, self.database.connect() as connection:
            if not connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
                raise ValueError("用户不存在")
            connection.execute(
                "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, utc_now(), time.time() + SESSION_TTL_SECONDS),
            )
            connection.commit()
        return token

    def user_from_session(self, token):
        if not token:
            return None
        with self.database.lock, self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.email, users.name, users.role, users.created_at, sessions.expires_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ?
                """,
                (token,),
            ).fetchone()
            if not row:
                return None
            if float(row["expires_at"]) < time.time():
                connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
                connection.commit()
                return None
            return self._public_user(dict(row))

    def logout(self, token):
        if not token:
            return
        with self.database.lock, self.database.connect() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (token,))
            connection.commit()


class DatabaseAiConfigStore:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def get(self):
        env_key = os.environ.get("AI_API_KEY", "").strip()
        if env_key:
            provider = os.environ.get("AI_PROVIDER", "deepseek").strip()
            model = os.environ.get("AI_MODEL", "deepseek-chat").strip()
            if provider in SUPPORTED_AI_PROVIDERS and model:
                return {"provider": provider, "model": model, "apiKey": env_key, "source": "environment"}
        with self.database.lock, self.database.connect() as connection:
            row = connection.execute("SELECT provider, model, api_key FROM ai_settings WHERE id = 1").fetchone()
        if not row:
            return None
        if row["provider"] not in SUPPORTED_AI_PROVIDERS or not row["model"] or not row["api_key"]:
            return None
        return {"provider": row["provider"], "model": row["model"], "apiKey": row["api_key"], "source": "database"}

    def public(self):
        data = self.get()
        if not data:
            return {"configured": False, "provider": "deepseek", "model": "deepseek-chat", "maskedKey": ""}
        key = data["apiKey"]
        return {"configured": True, "provider": data["provider"], "model": data["model"], "maskedKey": f"••••{key[-4:]}"}

    def save(self, payload):
        provider = payload.get("provider")
        model = str(payload.get("model", "")).strip()
        api_key = str(payload.get("apiKey", "")).strip()
        previous = self.get()
        if not api_key and previous and previous.get("provider") == provider:
            api_key = previous["apiKey"]
        if provider not in SUPPORTED_AI_PROVIDERS or not model or not api_key:
            raise ValueError("provider, model and apiKey are required")
        now = utc_now()
        with self.database.lock, self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_settings(id, provider, model, api_key, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  provider = excluded.provider,
                  model = excluded.model,
                  api_key = excluded.api_key,
                  updated_at = excluded.updated_at
                """,
                (provider, model, api_key, now),
            )
            connection.commit()
        return self.public()

    def delete(self):
        with self.database.lock, self.database.connect() as connection:
            connection.execute("DELETE FROM ai_settings WHERE id = 1")
            connection.commit()


def migrate_json_files_to_sqlite(database, data_file=DATA_FILE, ai_settings_file=AI_SETTINGS_FILE, auth_file=AUTH_FILE, templates_file=TEMPLATES_FILE):
    """Best-effort one-way import from earlier JSON stores. Existing SQLite rows win."""
    database.ensure_schema()
    with database.lock, database.connect() as connection:
        if Path(data_file).exists():
            try:
                projects = json.loads(Path(data_file).read_text(encoding="utf-8")).get("projects", {})
            except (json.JSONDecodeError, OSError, AttributeError):
                projects = {}
            for project_id, record in projects.items():
                if not isinstance(record, dict):
                    continue
                project = record.get("project") if isinstance(record.get("project"), dict) else {}
                tasks = record.get("tasks") if isinstance(record.get("tasks"), list) else []
                created_at = record.get("createdAt") or utc_now()
                updated_at = record.get("updatedAt") or created_at
                owner = record.get("owner", "local")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO projects (
                      owner, id, name, location, created_at, updated_at,
                      project_json, tasks_json, baselines_json, custom_templates_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        owner,
                        str(project_id),
                        str(project.get("projectName", "未命名项目"))[:240],
                        str(project.get("location", ""))[:240],
                        created_at,
                        updated_at,
                        _json_encode(project),
                        _json_encode(tasks),
                        _json_encode(record.get("baselines", [])),
                        _json_encode(record.get("customTemplates", [])),
                    ),
                )

        if Path(auth_file).exists():
            try:
                auth_data = json.loads(Path(auth_file).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                auth_data = {}
            for user_id, user in (auth_data.get("users") or {}).items():
                if not isinstance(user, dict) or not user.get("email") or not user.get("passwordHash"):
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO users(id, email, name, password_hash, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.get("id") or user_id,
                        user.get("email"),
                        user.get("name") or str(user.get("email")).split("@")[0],
                        user.get("passwordHash"),
                        role_for_email(user.get("email"), user.get("role", "user")),
                        user.get("createdAt") or utc_now(),
                        user.get("updatedAt") or user.get("createdAt") or utc_now(),
                    ),
                )
            for token, session in (auth_data.get("sessions") or {}).items():
                if not isinstance(session, dict) or not session.get("userId"):
                    continue
                try:
                    connection.execute(
                        "INSERT OR IGNORE INTO sessions(token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                        (token, session.get("userId"), session.get("createdAt") or utc_now(), float(session.get("expiresAt", 0))),
                    )
                except sqlite3.IntegrityError:
                    continue

        if Path(templates_file).exists():
            try:
                owners = json.loads(Path(templates_file).read_text(encoding="utf-8")).get("owners", {})
            except (json.JSONDecodeError, OSError, AttributeError):
                owners = {}
            for owner, owner_data in owners.items():
                if not isinstance(owner_data, dict):
                    continue
                templates = owner_data.get("templates")
                if not isinstance(templates, list):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO user_templates(owner, templates_json, updated_at) VALUES (?, ?, ?)",
                    (owner, _json_encode(templates), owner_data.get("updatedAt") or utc_now()),
                )

        if Path(ai_settings_file).exists() and not connection.execute("SELECT 1 FROM ai_settings WHERE id = 1").fetchone():
            try:
                settings = json.loads(Path(ai_settings_file).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                settings = {}
            if settings.get("provider") in SUPPORTED_AI_PROVIDERS and settings.get("model") and settings.get("apiKey"):
                connection.execute(
                    "INSERT INTO ai_settings(id, provider, model, api_key, updated_at) VALUES (1, ?, ?, ?, ?)",
                    (settings["provider"], settings["model"], settings["apiKey"], settings.get("updatedAt") or utc_now()),
                )
        connection.commit()


class CodexAgent:
    """Optional local Codex SDK bridge. Disabled by default and never exposed without admin authorization."""

    def __init__(self, enabled=None, model=None, allow_write=None, runner=None):
        self.enabled = (os.environ.get("ENABLE_CODEX_AGENT", "0") == "1") if enabled is None else bool(enabled)
        self.model = (model or os.environ.get("CODEX_MODEL", "gpt-5.4")).strip()
        self.allow_write = (os.environ.get("CODEX_ALLOW_WRITE", "0") == "1") if allow_write is None else bool(allow_write)
        self.runner = runner
        self.lock = threading.Lock()

    def available(self):
        return bool(self.runner or importlib.util.find_spec("openai_codex") or self._codex_bin())

    def _codex_bin(self):
        return os.environ.get("CODEX_BIN", "").strip() or shutil.which("codex") or shutil.which("codex.cmd")

    def runtime(self):
        if self.runner:
            return "test-runner"
        if importlib.util.find_spec("openai_codex"):
            return "python-sdk"
        return "cli" if self._codex_bin() else "unavailable"

    def public(self):
        available = self.available()
        return {
            "enabled": self.enabled,
            "available": available,
            "ready": bool(self.enabled and available),
            "model": self.model,
            "sandbox": "workspace_write" if self.allow_write else "read_only",
            "adminOnly": True,
            "runtime": self.runtime(),
        }

    def run(self, payload):
        if not self.enabled:
            raise RuntimeError("Codex 智能体未启用；请设置 ENABLE_CODEX_AGENT=1")
        if not self.available():
            raise RuntimeError("Codex SDK 或 CLI 不可用；请安装 openai-codex 或 Codex CLI")
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt or len(prompt) > 30000:
            raise ValueError("prompt must contain 1 to 30000 characters")
        requested_write = payload.get("sandbox") == "workspace_write"
        if requested_write and not self.allow_write:
            raise ValueError("当前服务只允许 Codex 只读审查")
        sandbox_name = "workspace_write" if requested_write else "read_only"
        with self.lock:
            if self.runner:
                result = self.runner(prompt=prompt, model=self.model, sandbox=sandbox_name)
                return result if isinstance(result, dict) else {"finalResponse": str(result)}
            if importlib.util.find_spec("openai_codex"):
                from openai_codex import Codex, Sandbox
                sandbox = Sandbox.workspace_write if requested_write else Sandbox.read_only
                with Codex() as codex:
                    thread = codex.thread_start(model=self.model, sandbox=sandbox)
                    result = thread.run(prompt)
                    return {"finalResponse": result.final_response, "model": self.model, "sandbox": sandbox_name, "runtime": "python-sdk"}
            codex_bin = self._codex_bin()
            if not codex_bin:
                raise RuntimeError("Codex SDK 或 CLI 不可用")
            command = [codex_bin, "exec", "--ephemeral", "--sandbox", "workspace-write" if requested_write else "read-only", "-C", str(PROJECT_ROOT), "--model", self.model, prompt]
            if os.name == "nt" and codex_bin.lower().endswith((".cmd", ".bat")):
                command = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *command]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            try:
                stdout, stderr = process.communicate(timeout=max(30, int(os.environ.get("CODEX_TIMEOUT_SECONDS", "180"))))
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                else:
                    process.kill()
                process.communicate()
                raise RuntimeError("Codex 执行超时，进程已终止")
            if process.returncode:
                detail = (stderr or stdout).strip().splitlines()
                raise RuntimeError(detail[-1] if detail else "Codex CLI 执行失败")
            return {"finalResponse": stdout.strip(), "model": self.model, "sandbox": sandbox_name, "runtime": "cli"}


def parse_model_json(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("模型未返回可解析内容")
    candidates = [text.strip()]
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    if cleaned != candidates[0]:
        candidates.append(cleaned)
    starts = [position for position in (cleaned.find("{"), cleaned.find("[")) if position >= 0]
    if starts:
        start = min(starts)
        closing = "}" if cleaned[start] == "{" else "]"
        end = cleaned.rfind(closing)
        if end > start:
            candidates.append(cleaned[start:end + 1])
    for candidate in candidates:
        for version in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                parsed = json.loads(version)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except json.JSONDecodeError:
                continue
    raise ValueError("模型返回的 JSON 格式无效，自动修复失败")


def call_ai_provider(config, payload):
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 20:
        raise ValueError("messages must contain 1 to 20 items")
    cleaned = []
    for item in messages:
        role, content = item.get("role"), item.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str) or len(content) > 300000:
            raise ValueError("invalid message")
        cleaned.append({"role": role, "content": content})
    if config["provider"] == "deepseek":
        body = {"model": config["model"], "messages": cleaned, "temperature": .2, "response_format": {"type": "json_object"}}
        request = Request("https://api.deepseek.com/chat/completions", data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {config['apiKey']}"})
        response = json.loads(urlopen(request, timeout=60).read().decode("utf-8"))
        text = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    elif config["provider"] == "gemini":
        system = "\n".join(item["content"] for item in cleaned if item["role"] == "system")
        contents = [{"role": "model" if item["role"] == "assistant" else "user", "parts": [{"text": item["content"]}]} for item in cleaned if item["role"] != "system"]
        body = {"contents": contents, "systemInstruction": {"parts": [{"text": system}]}, "generationConfig": {"temperature": .2, "responseMimeType": "application/json"}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(config['model'], safe='')}:generateContent"
        request = Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": config["apiKey"]})
        response = json.loads(urlopen(request, timeout=60).read().decode("utf-8"))
        text = "".join(part.get("text", "") for part in response.get("candidates", [{}])[0].get("content", {}).get("parts", []))
    else:
        body = {"model": config["model"], "input": cleaned}
        request = Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {config['apiKey']}"})
        response = json.loads(urlopen(request, timeout=120).read().decode("utf-8"))
        text = response.get("output_text", "")
        if not text:
            text = "".join(
                content.get("text", "")
                for item in response.get("output", [])
                for content in item.get("content", [])
                if content.get("type") == "output_text"
            )
    return parse_model_json(text)


class AppHandler(SimpleHTTPRequestHandler):
    store = ProjectStore(DATA_FILE)
    ai_store = AiConfigStore(AI_SETTINGS_FILE)
    auth_store = AuthStore(AUTH_FILE)
    template_store = UserTemplateStore(TEMPLATES_FILE)
    storage_label = DATA_FILE.name
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    allow_local_admin = True
    allowed_origins = {value.strip() for value in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if value.strip()}
    ai_limiter = RateLimiter(os.environ.get("AI_RATE_LIMIT_PER_MINUTE", "30"))
    codex_agent = CodexAgent()

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT if directory is None else directory), **kwargs)

    def log_message(self, _format, *args):
        pass

    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Client-Id, X-Admin-Token")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def _current_user(self):
        return self.auth_store.user_from_session(self._session_token())

    def _cookie_secure(self):
        return os.environ.get("APP_SECURE_COOKIES", "0") == "1" or self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _session_cookie(self, token):
        parts = [f"{SESSION_COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={SESSION_TTL_SECONDS}"]
        if self._cookie_secure():
            parts.append("Secure")
        return "; ".join(parts)

    def _clear_session_cookie(self):
        parts = [f"{SESSION_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
        if self._cookie_secure():
            parts.append("Secure")
        return "; ".join(parts)

    def _client_id(self):
        user = self._current_user()
        if user:
            return f"user:{user['id']}"
        if self.allow_local_admin:
            return "local"
        value = self.headers.get("X-Client-Id", "").strip()
        if re.fullmatch(r"[A-Za-z0-9_-]{10,100}", value):
            return value
        fingerprint = f"{self.client_address[0]}:{self.headers.get('User-Agent', '')}".encode("utf-8")
        return f"guest-{hashlib.sha256(fingerprint).hexdigest()[:24]}"

    def _is_admin(self):
        supplied = self.headers.get("X-Admin-Token", "")
        token_ok = bool(self.admin_token and supplied and hmac.compare_digest(supplied, self.admin_token))
        user = self._current_user()
        role_ok = bool(user and user.get("role") == "admin")
        local_ok = self.allow_local_admin and self.client_address[0] in {"127.0.0.1", "::1"}
        return token_ok or role_ok or (local_ok and not self.admin_token)

    def _project_quota(self, owner):
        count = self.store.count(owner) if hasattr(self.store, "count") else len(self.store.list(owner))
        exempt = owner == "local" or self._is_admin()
        limit = 0 if exempt else max(1, int(getattr(self, "project_limit_per_owner", PROJECT_LIMIT_PER_OWNER)))
        return {"limit": limit, "used": count, "remaining": None if exempt else max(0, limit - count), "exempt": exempt}

    def _today_start(self):
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    def _ai_usage_count(self, owner):
        database = getattr(self.store, "database", None)
        if not database:
            return 0
        with database.lock, database.connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM ai_usage WHERE owner = ? AND created_at >= ?",
                (owner, self._today_start()),
            ).fetchone()[0])

    def _ai_quota(self, owner):
        exempt = owner == "local" or self._is_admin()
        used = self._ai_usage_count(owner)
        limit = 0 if exempt else max(1, int(getattr(self, "ai_daily_limit_per_owner", AI_DAILY_LIMIT_PER_OWNER)))
        return {"limit": limit, "used": used, "remaining": None if exempt else max(0, limit - used), "exempt": exempt, "window": "UTC_DAY"}

    def _record_ai_usage(self, owner, config, success, status, started_at, error_type=""):
        database = getattr(self.store, "database", None)
        if not database:
            return
        duration_ms = max(0, int((time.time() - started_at) * 1000))
        with database.lock, database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_usage(owner, provider, model, success, status, error_type, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (owner, config.get("provider", ""), config.get("model", ""), 1 if success else 0, status, str(error_type or "")[:80], duration_ms, utc_now()),
            )
            connection.commit()

    def _ai_usage_overview(self):
        database = getattr(self.store, "database", None)
        if not database:
            return {"todayTotal": 0, "todaySuccess": 0, "todayFailed": 0, "recent": []}
        with database.lock, database.connect() as connection:
            today = self._today_start()
            total, success = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(success), 0) FROM ai_usage WHERE created_at >= ?",
                (today,),
            ).fetchone()
            recent = connection.execute(
                "SELECT owner, provider, model, success, status, error_type, duration_ms, created_at FROM ai_usage ORDER BY created_at DESC LIMIT 5"
            ).fetchall()
        return {
            "todayTotal": int(total),
            "todaySuccess": int(success),
            "todayFailed": int(total) - int(success),
            "recent": [{"owner": row["owner"], "provider": row["provider"], "model": row["model"], "success": bool(row["success"]), "status": row["status"], "errorType": row["error_type"], "durationMs": row["duration_ms"], "createdAt": row["created_at"]} for row in recent],
        }

    def _send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 20 * 1024 * 1024:
            raise ValueError("invalid request body")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _project_id(self):
        path = urlparse(self.path).path
        prefix = "/api/projects/"
        return unquote(path[len(prefix):]) if path.startswith(prefix) else None

    def _admin_overview(self):
        database = getattr(self.store, "database", None)
        if database:
            with database.lock, database.connect() as connection:
                projects = connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
                users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                sessions = connection.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (time.time(),)).fetchone()[0]
                template_rows = connection.execute("SELECT templates_json FROM user_templates").fetchall()
                ai_configured = bool(connection.execute("SELECT 1 FROM ai_settings WHERE id = 1").fetchone() or os.environ.get("AI_API_KEY", "").strip())
                recent_rows = connection.execute("SELECT id, owner, name, updated_at FROM projects ORDER BY updated_at DESC LIMIT 5").fetchall()
            template_items = sum(len(_json_decode(row["templates_json"], [])) for row in template_rows)
            storage_path = Path(database.path)
            storage_exists = storage_path.exists()
            return {
                "generatedAt": utc_now(),
                "storage": {
                    "engine": "sqlite",
                    "label": self.storage_label,
                    "path": str(storage_path),
                    "exists": storage_exists,
                    "sizeBytes": storage_path.stat().st_size if storage_exists else 0,
                    "updatedAt": datetime.fromtimestamp(storage_path.stat().st_mtime, timezone.utc).isoformat() if storage_exists else "",
                },
                "counts": {
                    "users": users,
                    "projects": projects,
                    "activeSessions": sessions,
                    "templateOwners": len(template_rows),
                    "customTemplates": template_items,
                },
                "limits": {
                    "projectLimitPerOwner": max(1, int(getattr(self, "project_limit_per_owner", PROJECT_LIMIT_PER_OWNER))),
                    "aiDailyLimitPerOwner": max(1, int(getattr(self, "ai_daily_limit_per_owner", AI_DAILY_LIMIT_PER_OWNER))),
                },
                "aiUsage": self._ai_usage_overview(),
                "integrations": {
                    "aiConfigured": ai_configured,
                    "codexReady": self.codex_agent.public().get("ready", False),
                    "codexRuntime": self.codex_agent.public().get("runtime", "unavailable"),
                },
                "recentProjects": [{"id": row["id"], "owner": row["owner"], "name": row["name"], "updatedAt": row["updated_at"]} for row in recent_rows],
            }
        projects_data = self.store._read().get("projects", {}) if hasattr(self.store, "_read") else {}
        templates_data = self.template_store._read().get("owners", {}) if hasattr(self.template_store, "_read") else {}
        auth_data = self.auth_store._read() if hasattr(self.auth_store, "_read") else {"users": {}, "sessions": {}}
        storage_path = getattr(self.store, "path", DATA_FILE)
        storage_exists = Path(storage_path).exists()
        return {
            "generatedAt": utc_now(),
            "storage": {
                "engine": "json",
                "label": self.storage_label,
                "path": str(storage_path),
                "exists": storage_exists,
                "sizeBytes": Path(storage_path).stat().st_size if storage_exists else 0,
                "updatedAt": datetime.fromtimestamp(Path(storage_path).stat().st_mtime, timezone.utc).isoformat() if storage_exists else "",
            },
            "counts": {
                "users": len(auth_data.get("users", {})),
                "projects": len(projects_data),
                "activeSessions": len([s for s in auth_data.get("sessions", {}).values() if float(s.get("expiresAt", 0)) > time.time()]),
                "templateOwners": len(templates_data),
                "customTemplates": sum(len(owner.get("templates", [])) for owner in templates_data.values() if isinstance(owner, dict)),
            },
            "limits": {
                "projectLimitPerOwner": max(1, int(getattr(self, "project_limit_per_owner", PROJECT_LIMIT_PER_OWNER))),
                "aiDailyLimitPerOwner": max(1, int(getattr(self, "ai_daily_limit_per_owner", AI_DAILY_LIMIT_PER_OWNER))),
            },
            "aiUsage": self._ai_usage_overview(),
            "integrations": {
                "aiConfigured": self.ai_store.public().get("configured", False),
                "codexReady": self.codex_agent.public().get("ready", False),
                "codexRuntime": self.codex_agent.public().get("runtime", "unavailable"),
            },
            "recentProjects": sorted([{"id": item.get("id", ""), "owner": item.get("owner", ""), "name": item.get("project", {}).get("projectName", ""), "updatedAt": item.get("updatedAt", "")} for item in projects_data.values()], key=lambda item: item["updatedAt"], reverse=True)[:5],
        }

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._send_json(200, {"ok": True, "storage": self.storage_label, "publicReady": bool(self.admin_token), "auth": True, "ai": self.ai_store.public(), "codex": self.codex_agent.public()})
        if path == "/api/auth/me":
            user = self._current_user()
            owner = self._client_id()
            return self._send_json(200, {"authenticated": bool(user), "user": user, "owner": owner, "projectQuota": self._project_quota(owner), "aiQuota": self._ai_quota(owner)})
        if path == "/api/integrations":
            return self._send_json(200, {"ai": self.ai_store.public(), "codex": self.codex_agent.public()})
        if path == "/api/diagnostics/connectivity":
            if not self._is_admin():
                return self._send_json(403, {"error": "仅管理员可以运行网络诊断"})
            config = self.ai_store.get()
            hosts = ["api.openai.com"]
            if config:
                provider_host = AI_PROVIDER_HOSTS.get(config["provider"])
                if provider_host and provider_host not in hosts:
                    hosts.append(provider_host)
            checks = [check_tcp_endpoint(host) for host in hosts]
            return self._send_json(200, {"ok": all(item["tcp443"] for item in checks), "checkedAt": utc_now(), "checks": checks})
        if path == "/api/admin/overview":
            if not self._is_admin():
                return self._send_json(403, {"error": "仅管理员可以查看运营概览"})
            return self._send_json(200, self._admin_overview())
        if path == "/api/projects":
            return self._send_json(200, {"projects": self.store.list(self._client_id())})
        if path == "/api/templates":
            return self._send_json(200, self.template_store.list(self._client_id()))
        if path == "/api/settings/ai":
            return self._send_json(200, self.ai_store.public())
        project_id = self._project_id()
        if project_id is not None:
            record = self.store.get(project_id, self._client_id())
            return self._send_json(200, record) if record else self._send_json(404, {"error": "project not found"})
        return super().do_GET()

    def do_PUT(self):
        if urlparse(self.path).path == "/api/templates":
            try:
                payload = self._read_json()
                templates = payload if isinstance(payload, list) else payload.get("templates") if isinstance(payload, dict) else None
                return self._send_json(200, self.template_store.replace(self._client_id(), templates))
            except (ValueError, json.JSONDecodeError) as error:
                return self._send_json(400, {"error": str(error)})
        if urlparse(self.path).path == "/api/settings/ai":
            if not self._is_admin():
                return self._send_json(403, {"error": "仅管理员可以修改 AI 配置"})
            try:
                return self._send_json(200, self.ai_store.save(self._read_json()))
            except (ValueError, json.JSONDecodeError) as error:
                return self._send_json(400, {"error": str(error)})
        project_id = self._project_id()
        if project_id is None:
            return self._send_json(404, {"error": "not found"})
        try:
            owner = self._client_id()
            if not self.store.get(project_id, owner):
                quota = self._project_quota(owner)
                if not quota["exempt"] and quota["remaining"] == 0:
                    return self._send_json(409, {"error": f"项目数量已达到上限（{quota['used']}/{quota['limit']}）。请删除旧项目或联系管理员提高配额。", "projectQuota": quota})
            record = self.store.save(project_id, self._read_json(), owner)
            return self._send_json(200, {**record, "projectQuota": self._project_quota(owner)})
        except (ValueError, json.JSONDecodeError) as error:
            return self._send_json(400, {"error": str(error)})

    def do_DELETE(self):
        if urlparse(self.path).path == "/api/settings/ai":
            if not self._is_admin():
                return self._send_json(403, {"error": "仅管理员可以清除 AI 配置"})
            self.ai_store.delete()
            return self._send_json(200, {"deleted": True})
        project_id = self._project_id()
        if project_id is None:
            return self._send_json(404, {"error": "not found"})
        return self._send_json(200, {"deleted": True}) if self.store.delete(project_id, self._client_id()) else self._send_json(404, {"error": "project not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/auth/register":
            try:
                user = self.auth_store.create_user(self._read_json())
                token = self.auth_store.create_session(user["id"])
                return self._send_json(200, {"authenticated": True, "user": user}, {"Set-Cookie": self._session_cookie(token)})
            except (ValueError, json.JSONDecodeError) as error:
                return self._send_json(400, {"error": str(error)})
        if path == "/api/auth/login":
            try:
                payload = self._read_json()
                user = self.auth_store.authenticate(payload.get("email"), payload.get("password"))
                token = self.auth_store.create_session(user["id"])
                return self._send_json(200, {"authenticated": True, "user": user}, {"Set-Cookie": self._session_cookie(token)})
            except (ValueError, json.JSONDecodeError) as error:
                return self._send_json(401, {"error": str(error)})
        if path == "/api/auth/logout":
            self.auth_store.logout(self._session_token())
            return self._send_json(200, {"authenticated": False, "user": None}, {"Set-Cookie": self._clear_session_cookie()})
        if path == "/api/codex/run":
            if not self._is_admin():
                return self._send_json(403, {"error": "仅管理员可以调用 Codex 智能体"})
            try:
                return self._send_json(200, self.codex_agent.run(self._read_json()))
            except ValueError as error:
                return self._send_json(400, {"error": str(error)})
            except RuntimeError as error:
                return self._send_json(409, {"error": str(error)})
            except Exception:
                return self._send_json(502, {"error": "Codex 智能体执行失败"})
        if path != "/api/ai/chat":
            return self._send_json(404, {"error": "not found"})
        config = self.ai_store.get()
        if not config:
            return self._send_json(409, {"error": "AI 服务尚未配置"})
        owner = self._client_id()
        if not self.ai_limiter.allow(f"{self.client_address[0]}:{owner}"):
            return self._send_json(429, {"error": "AI 请求过于频繁，请稍后重试"})
        quota = self._ai_quota(owner)
        if not quota["exempt"] and quota["remaining"] == 0:
            return self._send_json(429, {"error": f"今日 AI 调用额度已用完（{quota['used']}/{quota['limit']}）。请明天再试或联系管理员。", "aiQuota": quota})
        started_at = time.time()
        try:
            result = call_ai_provider(config, self._read_json())
            self._record_ai_usage(owner, config, True, "ok", started_at)
            return self._send_json(200, {**result, "aiQuota": self._ai_quota(owner)})
        except (ValueError, json.JSONDecodeError) as error:
            self._record_ai_usage(owner, config, False, "bad_request", started_at, type(error).__name__)
            return self._send_json(400, {"error": str(error)})
        except HTTPError as error:
            self._record_ai_usage(owner, config, False, f"http_{error.code}", started_at, "HTTPError")
            return self._send_json(502, {"error": f"模型服务返回 HTTP {error.code}"})
        except (URLError, TimeoutError, OSError):
            self._record_ai_usage(owner, config, False, "network_error", started_at, "NetworkError")
            return self._send_json(502, {"error": "无法连接模型服务"})


def create_server(host="127.0.0.1", port=4173, static_root=None, data_file=None, ai_settings_file=None, auth_file=None, templates_file=None, database_file=None, use_sqlite=None, admin_token=None, allowed_origins=None, ai_rate_limit=None, project_limit_per_owner=None, ai_daily_limit_per_owner=None, codex_agent=None):
    configured_admin_token = os.environ.get("ADMIN_TOKEN", "") if admin_token is None else admin_token
    configured_origins = AppHandler.allowed_origins if allowed_origins is None else set(allowed_origins)
    configured_rate_limit = ai_rate_limit if ai_rate_limit is not None else os.environ.get("AI_RATE_LIMIT_PER_MINUTE", "30")
    configured_project_limit = project_limit_per_owner if project_limit_per_owner is not None else os.environ.get("PROJECT_LIMIT_PER_OWNER", str(PROJECT_LIMIT_PER_OWNER))
    configured_ai_daily_limit = ai_daily_limit_per_owner if ai_daily_limit_per_owner is not None else os.environ.get("AI_DAILY_LIMIT_PER_OWNER", str(AI_DAILY_LIMIT_PER_OWNER))
    configured_codex_agent = codex_agent or CodexAgent()
    legacy_file_mode = any(value is not None for value in (data_file, ai_settings_file, auth_file, templates_file))
    use_database = (not legacy_file_mode) if use_sqlite is None else bool(use_sqlite)
    database = SQLiteDatabase(Path(database_file) if database_file else DB_FILE) if use_database else None
    if database:
        migrate_json_files_to_sqlite(
            database,
            Path(data_file) if data_file else DATA_FILE,
            Path(ai_settings_file) if ai_settings_file else AI_SETTINGS_FILE,
            Path(auth_file) if auth_file else AUTH_FILE,
            Path(templates_file) if templates_file else TEMPLATES_FILE,
        )
    class ConfiguredHandler(AppHandler):
        store = DatabaseProjectStore(database) if database else ProjectStore(Path(data_file) if data_file else DATA_FILE)
        ai_store = DatabaseAiConfigStore(database) if database else AiConfigStore(Path(ai_settings_file) if ai_settings_file else AI_SETTINGS_FILE)
        auth_store = DatabaseAuthStore(database) if database else AuthStore(Path(auth_file) if auth_file else AUTH_FILE)
        template_store = DatabaseUserTemplateStore(database) if database else UserTemplateStore(Path(templates_file) if templates_file else TEMPLATES_FILE)
        storage_label = f"sqlite:{Path(database.path).name}" if database else str((Path(data_file) if data_file else DATA_FILE).name)
        admin_token = configured_admin_token
        allow_local_admin = host in {"127.0.0.1", "::1", "localhost"}
        allowed_origins = configured_origins
        ai_limiter = RateLimiter(configured_rate_limit)
        project_limit_per_owner = int(configured_project_limit)
        ai_daily_limit_per_owner = int(configured_ai_daily_limit)
        codex_agent = configured_codex_agent

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=Path(static_root) if static_root else STATIC_ROOT, **kwargs)

    return ThreadingHTTPServer((host, port), ConfiguredHandler)


if __name__ == "__main__":
    create_server(host=os.environ.get("APP_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "4173"))).serve_forever()
