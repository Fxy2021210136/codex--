# Render + Neon PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留本机 SQLite 的同时，让 Render 部署通过 `DATABASE_URL` 使用 Neon PostgreSQL 持久保存全部业务数据。

**Architecture:** 继续使用 React 静态文件和 Python API 同容器的单体结构。在 `serve.py` 增加一个最小 PostgreSQL 连接适配器，使现有 Store 类不需要重写；SQLite 专属建表和旧 JSON 迁移保持原样，PostgreSQL 使用独立幂等建表语句。

**Tech Stack:** Python 3.12、stdlib `sqlite3`、`psycopg` 3、PostgreSQL 16、React/Vite、Docker、Render Blueprint、GitHub Actions。

## Global Constraints

- 本机未配置 PostgreSQL 时必须继续使用 `data/app.db`，现有 EXE 和 `scripts/start-local.ps1` 不改变。
- 只新增 `psycopg[binary]>=3.2,<4` 一个 Python 运行依赖；不引入 ORM、迁移框架或连接池。
- 配置 PostgreSQL 后连接或建表失败必须终止启动，不得静默回退 SQLite。
- 前端 API、项目 JSON、模板结构、Cookie 名称和登录交互保持不变。
- PostgreSQL 连接串只能来自环境变量，不得写入仓库、响应或日志。
- 旧 JSON 文件自动迁移只在 SQLite 模式运行。
- 当前单实例继续共用进程内 `RLock`；并发扩展到多个 Render 实例时再引入数据库级并发策略。

---

### Task 1: PostgreSQL 连接与 SQL 兼容适配

**Files:**
- Modify: `serve.py:1-223`
- Modify: `tests/test_server.py:1-35`

**Interfaces:**
- Consumes: `DATABASE_URL`、可选 `database_file`。
- Produces: `PostgresDatabase(url)`, `database_from_configuration(database_url=None, database_file=None)`, `database.engine`, `database.label`, `database.path`, `database.connect()`。

- [ ] **Step 1: 写出数据库选择和兼容行的失败测试**

在 `tests/test_server.py` 的导入中加入 `HybridRow`、`PostgresDatabase`、`SQLiteDatabase`、`database_from_configuration`，并加入：

```python
    def test_database_configuration_keeps_sqlite_and_selects_postgres(self):
        sqlite_database = database_from_configuration("", self.db_file)
        self.assertEqual(sqlite_database.engine, "sqlite")
        self.assertEqual(sqlite_database.path, self.db_file)

        postgres_database = database_from_configuration("postgresql://user:secret@db.example/app")
        self.assertIsInstance(postgres_database, PostgresDatabase)
        self.assertEqual(postgres_database.engine, "postgresql")
        self.assertEqual(postgres_database.label, "postgresql")
        self.assertNotIn("secret", repr(postgres_database))

    def test_hybrid_row_supports_index_name_and_unpacking(self):
        row = HybridRow(("count", "success"), (4, 3))
        self.assertEqual(row[0], 4)
        self.assertEqual(row["success"], 3)
        total, success = row
        self.assertEqual((total, success), (4, 3))
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m unittest tests.test_server.ProjectApiTest.test_database_configuration_keeps_sqlite_and_selects_postgres tests.test_server.ProjectApiTest.test_hybrid_row_supports_index_name_and_unpacking -v`

Expected: FAIL，提示 `HybridRow` 或 `database_from_configuration` 尚未定义。

- [ ] **Step 3: 在 `serve.py` 增加最小 PostgreSQL 适配**

保留现有 `SQLiteDatabase`，给它加入：

```python
    engine = "sqlite"

    @property
    def label(self):
        return f"sqlite:{self.path.name}"
```

在 `SQLiteDatabase` 后加入：

```python
class HybridRow:
    def __init__(self, names, values):
        self.names = tuple(names)
        self.values = tuple(values)
        self.by_name = dict(zip(self.names, self.values))

    def __getitem__(self, key):
        return self.values[key] if isinstance(key, int) else self.by_name[key]

    def __iter__(self):
        return iter(self.values)


def _postgres_row_factory(cursor):
    names = tuple(column.name for column in cursor.description)
    return lambda values: HybridRow(names, values)


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def commit(self):
        return self.connection.commit()

    def rollback(self):
        return self.connection.rollback()

    def close(self):
        return self.connection.close()

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.connection.__exit__(exc_type, exc, traceback)


POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS projects (
         owner TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
         location TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
         updated_at TEXT NOT NULL, project_json TEXT NOT NULL,
         tasks_json TEXT NOT NULL, baselines_json TEXT NOT NULL,
         custom_templates_json TEXT NOT NULL, PRIMARY KEY (owner, id))""",
    "CREATE INDEX IF NOT EXISTS idx_projects_owner_updated ON projects(owner, updated_at DESC)",
    """CREATE TABLE IF NOT EXISTS users (
         id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
         password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
         phone TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (
         token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
         created_at TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
    """CREATE TABLE IF NOT EXISTS user_templates (
         owner TEXT PRIMARY KEY, templates_json TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_settings (
         id INTEGER PRIMARY KEY CHECK (id = 1), provider TEXT NOT NULL,
         model TEXT NOT NULL, api_key TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_usage (
         id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
         owner TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
         success INTEGER NOT NULL, status TEXT NOT NULL, error_type TEXT NOT NULL DEFAULT '',
         duration_ms INTEGER NOT NULL, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_owner_created ON ai_usage(owner, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT NOT NULL DEFAULT ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique ON users(phone) WHERE phone <> ''",
)


class PostgresDatabase:
    engine = "postgresql"
    label = "postgresql"
    path = None

    def __init__(self, url):
        self.url = str(url)
        self.lock = threading.RLock()
        self.ready = False

    def __repr__(self):
        return "PostgresDatabase(<redacted>)"

    def _connect_raw(self):
        try:
            import psycopg
        except ImportError as error:
            raise RuntimeError("PostgreSQL 已配置，但未安装 psycopg；请安装 requirements.txt") from error
        return PostgresConnection(psycopg.connect(self.url, row_factory=_postgres_row_factory))

    def ensure_schema(self):
        with self.lock:
            if self.ready:
                return
            with self._connect_raw() as connection:
                for statement in POSTGRES_SCHEMA:
                    connection.execute(statement)
            self.ready = True

    def connect(self):
        self.ensure_schema()
        return self._connect_raw()


def database_from_configuration(database_url=None, database_file=None):
    url = os.environ.get("DATABASE_URL", "").strip() if database_url is None else str(database_url).strip()
    if url.startswith(("postgresql://", "postgres://")):
        return PostgresDatabase(url)
    if url.startswith("sqlite:///"):
        return SQLiteDatabase(Path(url[len("sqlite:///"):]))
    if url:
        raise ValueError("DATABASE_URL 仅支持 sqlite:///、postgresql:// 或 postgres://")
    return SQLiteDatabase(Path(database_file) if database_file else Path(os.environ.get("APP_DB_FILE") or (DATA_DIR / "app.db")))
```

删除 `sqlite_file_from_environment()` 和导入阶段调用它的 `DB_FILE` 常量，避免 PostgreSQL URL 在模块导入时被拒绝；SQLite 路径解析已经由 `database_from_configuration()` 完整接管。

- [ ] **Step 4: 运行定向测试和现有 SQLite 测试**

Run: `python -m unittest tests.test_server.ProjectApiTest.test_database_configuration_keeps_sqlite_and_selects_postgres tests.test_server.ProjectApiTest.test_hybrid_row_supports_index_name_and_unpacking -v`

Expected: 2 tests PASS。

Run: `python -m unittest tests.test_server -v`

Expected: 原有 24 tests 加新增 2 tests 全部 PASS。

- [ ] **Step 5: 提交数据库适配**

```powershell
git add serve.py tests/test_server.py
git commit -m "feat: add PostgreSQL database adapter"
```

---

### Task 2: 将服务、健康检查和运营概览接到可选数据库

**Files:**
- Modify: `serve.py:1510-1760`
- Modify: `serve.py:1932-1975`
- Modify: `tests/test_server.py:420-445`

**Interfaces:**
- Consumes: Task 1 的 `database_from_configuration()`、`database.engine`、`database.label`、`database.path`。
- Produces: `create_server(..., database_url=None)`；`/api/health.database = {engine, connected}`；PostgreSQL 可用的管理员概览和上线检查。

- [ ] **Step 1: 写出健康检查和显式数据库选择的失败测试**

在 SQLite readiness 测试中增加：

```python
        self.assertEqual(health["database"], {"engine": "sqlite", "connected": True})
```

新增无需真实连接的工厂接线测试：

```python
    @patch("serve.database_from_configuration")
    def test_create_server_uses_explicit_database_url(self, factory):
        database = SQLiteDatabase(self.db_file)
        factory.return_value = database
        server = create_server(port=0, static_root=Path(self.temp.name), database_url="postgresql://redacted")
        try:
            factory.assert_called_once_with("postgresql://redacted", None)
            self.assertIs(server.RequestHandlerClass.store.database, database)
        finally:
            server.server_close()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m unittest tests.test_server.ProjectApiTest.test_create_server_uses_explicit_database_url tests.test_server.ProjectApiTest.test_readiness_check_requires_admin_and_reports_core_status -v`

Expected: FAIL，提示 `database_url` 参数或 `health["database"]` 不存在。

- [ ] **Step 3: 修改 `create_server` 数据库选择**

签名加入 `database_url=None`，数据库初始化改为：

```python
    database = None
    if use_database:
        database = database_from_configuration(database_url, database_file)
        database.ensure_schema()
        if database.engine == "sqlite":
            migrate_json_files_to_sqlite(
                database,
                Path(data_file) if data_file else DATA_FILE,
                Path(ai_settings_file) if ai_settings_file else AI_SETTINGS_FILE,
                Path(auth_file) if auth_file else AUTH_FILE,
                Path(templates_file) if templates_file else TEMPLATES_FILE,
            )
```

`ConfiguredHandler.storage_label` 改为：

```python
        storage_label = database.label if database else str((Path(data_file) if data_file else DATA_FILE).name)
```

- [ ] **Step 4: 使运营概览和 readiness 不再假定数据库一定有文件路径**

在 `_admin_overview()` 的数据库分支中按引擎生成 storage：

```python
            if database.engine == "sqlite":
                storage_path = Path(database.path)
                storage_exists = storage_path.exists()
                storage = {
                    "engine": "sqlite",
                    "label": self.storage_label,
                    "path": str(storage_path),
                    "exists": storage_exists,
                    "sizeBytes": storage_path.stat().st_size if storage_exists else 0,
                    "updatedAt": datetime.fromtimestamp(storage_path.stat().st_mtime, timezone.utc).isoformat() if storage_exists else "",
                }
            else:
                storage = {"engine": "postgresql", "label": "postgresql", "path": "", "exists": True, "sizeBytes": 0, "updatedAt": ""}
```

返回值使用 `"storage": storage`。

`_readiness_overview()` 中将现有的 `storage_path`、`storage_parent` 和临时探针代码整体放入下面 `else`；PostgreSQL 不触碰 Render 文件系统：

```python
        if database and database.engine == "postgresql":
            add("storageWritable", "持久数据库", "ok", "PostgreSQL 负责持久化，不依赖 Render 临时文件系统。", True)
        else:
            storage_path = Path(database.path) if database else Path(getattr(self.store, "path", DATA_FILE))
            storage_parent = storage_path.parent
            try:
                storage_parent.mkdir(parents=True, exist_ok=True)
                probe = storage_parent / f".readiness-{secrets.token_hex(4)}.tmp"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                add("storageWritable", "数据目录可写", "ok", f"{storage_parent} 可写，项目和账号数据可持久保存。", True)
            except OSError as error:
                add("storageWritable", "数据目录可写", "error", f"{storage_parent} 不可写：{error}", True)
```

数据库检查统一为：

```python
        try:
            if database:
                with database.lock, database.connect() as connection:
                    connection.execute("SELECT COUNT(*) FROM projects").fetchone()
                add("database", "数据库连接", "ok", f"{database.label} 可连接，核心表结构已初始化。", True)
            else:
                add("database", "数据库连接", "warning", "当前使用 JSON 文件存储；多人长期使用建议切换数据库。", False)
        except Exception as error:
            add("database", "数据库连接", "error", f"数据库不可用：{error}", True)
```

`/api/health` 返回值加入：

```python
"database": {"engine": getattr(getattr(self.store, "database", None), "engine", "json"), "connected": True}
```

- [ ] **Step 5: 运行全部后端测试**

Run: `python -m unittest tests.test_server -v`

Expected: 全部 PASS，SQLite readiness 文案和运营统计保持通过。

- [ ] **Step 6: 提交服务接线**

```powershell
git add serve.py tests/test_server.py
git commit -m "feat: select persistent database by URL"
```

---

### Task 3: 真实 PostgreSQL 集成测试与 CI 门禁

**Files:**
- Create: `requirements.txt`
- Create: `tests/test_postgres.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 2 的 `create_server(database_url=...)`。
- Produces: `TEST_POSTGRES_URL` 驱动的真实 PostgreSQL API 测试；CI PostgreSQL 16 service。

- [ ] **Step 1: 添加 Python 运行依赖**

创建 `requirements.txt`：

```text
psycopg[binary]>=3.2,<4
```

- [ ] **Step 2: 写出真实 PostgreSQL 集成测试**

创建 `tests/test_postgres.py`：

```python
import json
import os
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from serve import PostgresDatabase, create_server


POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")


@unittest.skipUnless(POSTGRES_URL, "TEST_POSTGRES_URL is not configured")
class PostgresApiTest(unittest.TestCase):
    def setUp(self):
        database = PostgresDatabase(POSTGRES_URL)
        database.ensure_schema()
        with database.connect() as connection:
            connection.execute("TRUNCATE ai_usage, ai_settings, user_templates, sessions, projects, users RESTART IDENTITY CASCADE")
        self.server = create_server(port=0, static_root=Path(__file__).parent, database_url=POSTGRES_URL)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, method="GET", payload=None, headers=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(self.base + path, data=body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")), response.headers

    def test_account_project_template_and_restart_persist(self):
        registered, headers = self.request("/api/auth/register", "POST", {"email": "pg@example.com", "password": "securepass1", "name": "PG 用户"})
        self.assertTrue(registered["authenticated"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        auth = {"Cookie": cookie}
        self.request("/api/projects/P-PG", "PUT", {"project": {"projectName": "PostgreSQL 项目"}, "tasks": [], "baselines": []}, auth)
        self.request("/api/templates", "PUT", {"templates": [{"id": "PG-TPL", "name": "PG 模板", "duration": 2}]}, auth)

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = create_server(port=0, static_root=Path(__file__).parent, database_url=POSTGRES_URL)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

        projects, _ = self.request("/api/projects", headers=auth)
        templates, _ = self.request("/api/templates", headers=auth)
        self.assertEqual(projects["projects"][0]["name"], "PostgreSQL 项目")
        self.assertEqual(templates["templates"][0]["name"], "PG 模板")
        health, _ = self.request("/api/health")
        self.assertEqual(health["database"], {"engine": "postgresql", "connected": True})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 在无 PostgreSQL 的本机确认测试安全跳过**

Run: `python -m unittest tests.test_postgres -v`

Expected: 1 test skipped，原因是 `TEST_POSTGRES_URL is not configured`。

- [ ] **Step 4: 给 GitHub Actions 增加 PostgreSQL 16 service**

在 `test-and-build` job 增加：

```yaml
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: schedule
          POSTGRES_PASSWORD: schedule
          POSTGRES_DB: schedule_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U schedule -d schedule_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
```

在后端测试前加入：

```yaml
      - run: python -m pip install -r requirements.txt
      - run: python -m unittest tests.test_server -v
      - run: python -m unittest tests.test_postgres -v
        env:
          TEST_POSTGRES_URL: postgresql://schedule:schedule@127.0.0.1:5432/schedule_test
```

删除原来重复的单独 `python -m unittest tests.test_server -v` 步骤。

- [ ] **Step 5: 运行本机完整回归**

Run: `python -m unittest tests.test_server tests.test_postgres -v`

Expected: SQLite 测试全部 PASS，PostgreSQL 测试在本机无 URL 时 SKIP。

Run: `node --experimental-strip-types --experimental-specifier-resolution=node --test tests/*.test.ts`

Expected: 24 tests PASS。

- [ ] **Step 6: 提交集成测试**

```powershell
git add requirements.txt tests/test_postgres.py .github/workflows/ci.yml
git commit -m "test: verify PostgreSQL persistence in CI"
```

---

### Task 4: Docker、Render Blueprint 和用户部署说明

**Files:**
- Modify: `Dockerfile`
- Create: `render.yaml`
- Modify: `.env.production.example`
- Modify: `DEPLOYMENT.md`
- Modify: `PUBLIC_DEPLOYMENT_CHECKLIST.md`

**Interfaces:**
- Consumes: `requirements.txt`、Neon 提供的 `DATABASE_URL`。
- Produces: 可由 Render 从 GitHub 构建的免费 Web Service；逐项用户操作说明。

- [ ] **Step 1: 让 Docker 运行阶段安装 PostgreSQL 驱动**

在 runtime 阶段 `COPY serve.py` 前加入：

```dockerfile
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
```

- [ ] **Step 2: 创建最小 Render Blueprint**

创建 `render.yaml`：

```yaml
services:
  - type: web
    name: construction-schedule-ai
    runtime: docker
    plan: free
    healthCheckPath: /api/health
    envVars:
      - key: APP_HOST
        value: 0.0.0.0
      - key: APP_SECURE_COOKIES
        value: "1"
      - key: PHONE_CODE_DEV_MODE
        value: "0"
      - key: EMAIL_VERIFICATION_MODE
        value: off
      - key: DATABASE_URL
        sync: false
      - key: ADMIN_TOKEN
        generateValue: true
      - key: ADMIN_DEFAULT_PASSWORD
        sync: false
      - key: ADMIN_EMAILS
        sync: false
```

- [ ] **Step 3: 更新生产环境示例**

将 `.env.production.example` 的数据库段改为：

```env
# Local containers may use sqlite:////data/app.db.
# Render Free must use the Neon connection string because its filesystem is temporary.
DATABASE_URL=postgresql://user:password@host/database?sslmode=require
```

保留 `APP_DATA_DIR=/data`，用于本机/付费持久磁盘兼容。

- [ ] **Step 4: 在两份部署文档写出用户实际操作**

`DEPLOYMENT.md` 增加“Render Free + Neon Free”章节，明确：

```markdown
1. 在 Neon 使用 GitHub 登录并创建 Free 项目。
2. 在 Neon 的 Connect 页面复制 PostgreSQL 连接串，确认末尾包含 `sslmode=require`。
3. 在 Render 使用 GitHub 登录，选择 New > Blueprint，并授权 `Fxy2021210136/codex--`。
4. 设置 `DATABASE_URL`、`ADMIN_DEFAULT_PASSWORD` 和 `ADMIN_EMAILS`；`ADMIN_TOKEN` 由 Blueprint 自动生成。
5. 部署完成后打开 `https://<服务名>.onrender.com/api/health`，确认 `database.engine` 为 `postgresql`。
6. 注册测试账号、保存项目，再执行一次 Manual Deploy，确认数据仍存在。
```

`PUBLIC_DEPLOYMENT_CHECKLIST.md` 将免费长期试用方案更新为 Render + Neon，并保留“本机 + Tunnel”作为无需云账号的临时演示方案。

- [ ] **Step 5: 构建和检查部署文件**

Run: `docker build -t construction-schedule-ai:test .`

Expected: Docker 镜像成功构建，runtime 阶段成功安装 psycopg。

Run: `node node_modules/typescript/bin/tsc -b --force`

Expected: exit code 0。

Run: `node node_modules/vite/bin/vite.js build .`

Expected: `dist/` 构建成功。

Run: `git diff --check`

Expected: 无输出。

- [ ] **Step 6: 提交部署配置**

```powershell
git add Dockerfile render.yaml .env.production.example DEPLOYMENT.md PUBLIC_DEPLOYMENT_CHECKLIST.md
git commit -m "deploy: add free Render and Neon configuration"
```

---

### Task 5: 最终验证与发布准备

**Files:**
- Modify only if verification exposes a defect in files from Tasks 1-4.

**Interfaces:**
- Consumes: Tasks 1-4 的完整实现。
- Produces: 可推送分支、明确的 Neon/Render 用户操作清单。

- [ ] **Step 1: 运行完整测试与构建**

```powershell
python -m unittest tests.test_server tests.test_postgres -v
node --experimental-strip-types --experimental-specifier-resolution=node --test tests/*.test.ts
node node_modules\typescript\bin\tsc -b --force
node node_modules\vite\bin\vite.js build .
docker build -t construction-schedule-ai:test .
```

Expected: Python SQLite 全部 PASS、无本机 URL 时 PostgreSQL 1 项 SKIP、TypeScript 24 项 PASS、类型检查/前端构建/Docker 构建均成功。

- [ ] **Step 2: 检查秘密和差异**

Run: `rg -n "postgresql://[^:]+:[^@]+@|DATABASE_URL=.*@" . -g '!docs/superpowers/**' -g '!node_modules/**' -g '!dist/**'`

Expected: 只允许 `.env.production.example` 中的明显占位连接串，不出现真实主机、账号或密码。

Run: `git diff --check && git status --short`

Expected: 无空白错误；仅出现实施计划预期文件。

- [ ] **Step 3: 推送前确认**

Run: `git log -6 --oneline --decorate`

Expected: 设计提交以及 3-5 个范围清晰的实现提交位于当前分支顶部。
