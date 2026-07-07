import json
import hmac
import hashlib
import importlib.util
import os
import re
import secrets
import shutil
import socket
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
DATA_FILE = DATA_DIR / "projects.json"
AI_SETTINGS_FILE = DATA_DIR / "ai-settings.json"
AUTH_FILE = DATA_DIR / "auth.json"
SESSION_COOKIE = "schedule_ai_session"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(60 * 60 * 24 * 30)))
SUPPORTED_AI_PROVIDERS = {"deepseek", "gemini", "openai"}
AI_PROVIDER_HOSTS = {"deepseek": "api.deepseek.com", "gemini": "generativelanguage.googleapis.com", "openai": "api.openai.com"}


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
        if self.admin_token:
            return bool(supplied and hmac.compare_digest(supplied, self.admin_token))
        return self.allow_local_admin and self.client_address[0] in {"127.0.0.1", "::1"}

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

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._send_json(200, {"ok": True, "storage": str(DATA_FILE.name), "publicReady": bool(self.admin_token), "auth": True, "ai": self.ai_store.public(), "codex": self.codex_agent.public()})
        if path == "/api/auth/me":
            user = self._current_user()
            return self._send_json(200, {"authenticated": bool(user), "user": user, "owner": self._client_id()})
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
        if path == "/api/projects":
            return self._send_json(200, {"projects": self.store.list(self._client_id())})
        if path == "/api/settings/ai":
            return self._send_json(200, self.ai_store.public())
        project_id = self._project_id()
        if project_id is not None:
            record = self.store.get(project_id, self._client_id())
            return self._send_json(200, record) if record else self._send_json(404, {"error": "project not found"})
        return super().do_GET()

    def do_PUT(self):
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
            return self._send_json(200, self.store.save(project_id, self._read_json(), self._client_id()))
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
        if not self.ai_limiter.allow(f"{self.client_address[0]}:{self._client_id()}"):
            return self._send_json(429, {"error": "AI 请求过于频繁，请稍后重试"})
        try:
            return self._send_json(200, call_ai_provider(config, self._read_json()))
        except (ValueError, json.JSONDecodeError) as error:
            return self._send_json(400, {"error": str(error)})
        except HTTPError as error:
            return self._send_json(502, {"error": f"模型服务返回 HTTP {error.code}"})
        except (URLError, TimeoutError, OSError):
            return self._send_json(502, {"error": "无法连接模型服务"})


def create_server(host="127.0.0.1", port=4173, static_root=None, data_file=None, ai_settings_file=None, auth_file=None, admin_token=None, allowed_origins=None, ai_rate_limit=None, codex_agent=None):
    configured_admin_token = os.environ.get("ADMIN_TOKEN", "") if admin_token is None else admin_token
    configured_origins = AppHandler.allowed_origins if allowed_origins is None else set(allowed_origins)
    configured_rate_limit = ai_rate_limit if ai_rate_limit is not None else os.environ.get("AI_RATE_LIMIT_PER_MINUTE", "30")
    configured_codex_agent = codex_agent or CodexAgent()
    class ConfiguredHandler(AppHandler):
        store = ProjectStore(Path(data_file) if data_file else DATA_FILE)
        ai_store = AiConfigStore(Path(ai_settings_file) if ai_settings_file else AI_SETTINGS_FILE)
        auth_store = AuthStore(Path(auth_file) if auth_file else AUTH_FILE)
        admin_token = configured_admin_token
        allow_local_admin = host in {"127.0.0.1", "::1", "localhost"}
        allowed_origins = configured_origins
        ai_limiter = RateLimiter(configured_rate_limit)
        codex_agent = configured_codex_agent

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=Path(static_root) if static_root else STATIC_ROOT, **kwargs)

    return ThreadingHTTPServer((host, port), ConfiguredHandler)


if __name__ == "__main__":
    create_server(host=os.environ.get("APP_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "4173"))).serve_forever()
