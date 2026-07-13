import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from serve import CodexAgent, call_ai_provider, create_server, parse_model_json


class ProjectApiTest(unittest.TestCase):
    def test_model_json_repair(self):
        repaired = parse_model_json('```json\n{"summary":"ok","items":[1,2,],}\n```')
        self.assertEqual(repaired["summary"], "ok")
        self.assertEqual(repaired["items"], [1, 2])

    @patch("serve.urlopen")
    def test_openai_responses_api_request_and_output_parsing(self, mocked_urlopen):
        class FakeResponse:
            def read(self):
                return json.dumps({"output": [{"content": [{"type": "output_text", "text": '{"summary":"ok"}'}]}]}).encode("utf-8")
        mocked_urlopen.return_value = FakeResponse()
        result = call_ai_provider(
            {"provider": "openai", "model": "gpt-5.4-mini", "apiKey": "sk-test"},
            {"messages": [{"role": "system", "content": "只返回 JSON"}, {"role": "user", "content": "测试"}]},
        )
        self.assertEqual(result["summary"], "ok")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(json.loads(request.data)["model"], "gpt-5.4-mini")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "index.html").write_text("ok", encoding="utf-8")
        self.db_file = root / "app.db"
        self.server = create_server(port=0, static_root=root, database_file=self.db_file, use_sqlite=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request_raw(self, path, method="GET", payload=None, headers=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request_headers={"Content-Type": "application/json", **(headers or {})}
        request = Request(self.base + path, data=body, method=method, headers=request_headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8")), response.headers

    def request(self, path, method="GET", payload=None, headers=None):
        status, data, _ = self.request_raw(path, method, payload, headers)
        return status, data

    def test_project_crud_and_disk_persistence(self):
        payload = {
            "project": {"projectName": "接口测试项目", "location": "上海"},
            "tasks": [{"id": "A", "name": "任务A", "endDate": "2026-08-01"}],
            "baselines": [],
            "customTemplates": [{"id": "CUSTOM-1", "name": "企业工序"}],
        }
        status, saved = self.request("/api/projects/P-TEST", "PUT", payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved["project"]["projectName"], "接口测试项目")

        _, listing = self.request("/api/projects")
        self.assertEqual(listing["projects"][0]["taskCount"], 1)
        self.assertEqual(listing["projects"][0]["completionDate"], "2026-08-01")

        _, loaded = self.request("/api/projects/P-TEST")
        self.assertEqual(loaded["tasks"][0]["id"], "A")
        self.assertEqual(loaded["customTemplates"][0]["id"], "CUSTOM-1")
        self.assertTrue(self.db_file.exists())
        with sqlite3.connect(self.db_file) as db:
            count = db.execute("SELECT COUNT(*) FROM projects WHERE id = 'P-TEST'").fetchone()[0]
        self.assertEqual(count, 1)

        _, deleted = self.request("/api/projects/P-TEST", "DELETE")
        self.assertTrue(deleted["deleted"])
        with self.assertRaises(HTTPError) as missing:
            self.request("/api/projects/P-TEST")
        self.assertEqual(missing.exception.code, 404)

    def test_auth_register_login_logout_and_project_ownership(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        status, registered, headers = self.request_raw(
            "/api/auth/register",
            "POST",
            {"email": "owner@example.com", "password": "securepass1", "name": "项目经理"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(registered["authenticated"])
        self.assertEqual(registered["user"]["email"], "owner@example.com")
        cookie = headers["Set-Cookie"].split(";", 1)[0]

        _, me = self.request("/api/auth/me", headers={"Cookie": cookie})
        self.assertTrue(me["authenticated"])
        self.assertTrue(me["owner"].startswith("user:"))

        payload = {"project": {"projectName": "登录用户项目"}, "tasks": [], "baselines": []}
        self.request("/api/projects/P-AUTH", "PUT", payload, {"Cookie": cookie})
        _, own = self.request("/api/projects", headers={"Cookie": cookie})
        _, guest = self.request("/api/projects", headers={"X-Client-Id": "web-guest-private"})
        self.assertEqual([item["name"] for item in own["projects"]], ["登录用户项目"])
        self.assertEqual(guest["projects"], [])

        _, logged_out, logout_headers = self.request_raw("/api/auth/logout", "POST", headers={"Cookie": cookie})
        self.assertFalse(logged_out["authenticated"])
        self.assertIn("Max-Age=0", logout_headers["Set-Cookie"])

        with self.assertRaises(HTTPError) as failed_login:
            self.request("/api/auth/login", "POST", {"email": "owner@example.com", "password": "wrongpass"})
        self.assertEqual(failed_login.exception.code, 401)
        _, logged_in, login_headers = self.request_raw("/api/auth/login", "POST", {"email": "owner@example.com", "password": "securepass1"})
        self.assertTrue(logged_in["authenticated"])
        self.assertIn("schedule_ai_session=", login_headers["Set-Cookie"])

    def test_admin_default_login_and_phone_code_login(self):
        self.server.RequestHandlerClass.allow_local_admin = True
        status, admin, admin_headers = self.request_raw(
            "/api/auth/admin-login",
            "POST",
            {"email": "admin@example.com", "password": "177099"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin["user"]["role"], "admin")
        self.assertIn("schedule_ai_session=", admin_headers["Set-Cookie"])

        _, registered, headers = self.request_raw(
            "/api/auth/register",
            "POST",
            {"email": "phone@example.com", "password": "securepass1", "name": "手机用户"},
        )
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertTrue(registered["authenticated"])

        _, issued = self.request("/api/auth/phone-code", "POST", {"phone": "13800138000"})
        self.assertEqual(issued["phone"], "13800138000")
        self.assertRegex(issued["devCode"], r"^\d{6}$")

        _, bound = self.request(
            "/api/account/phone",
            "POST",
            {"phone": "13800138000", "code": issued["devCode"]},
            {"Cookie": cookie},
        )
        self.assertEqual(bound["user"]["phone"], "13800138000")

        _, second_code = self.request("/api/auth/phone-code", "POST", {"phone": "+86 13800138000"})
        _, phone_login, phone_headers = self.request_raw(
            "/api/auth/phone-login",
            "POST",
            {"phone": "13800138000", "code": second_code["devCode"]},
        )
        self.assertTrue(phone_login["authenticated"])
        self.assertEqual(phone_login["user"]["email"], "phone@example.com")
        self.assertIn("schedule_ai_session=", phone_headers["Set-Cookie"])

    def test_default_admin_password_is_local_only(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        with self.assertRaises(HTTPError) as blocked:
            self.request(
                "/api/auth/admin-login",
                "POST",
                {"email": "admin@example.com", "password": "177099"},
            )
        self.assertEqual(blocked.exception.code, 403)

    def test_phone_code_dev_mode_is_local_only(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        with self.assertRaises(HTTPError) as blocked:
            self.request("/api/auth/phone-code", "POST", {"phone": "13800138000"})
        self.assertEqual(blocked.exception.code, 403)

    def test_legacy_user_table_without_phone_column_migrates(self):
        legacy_db = Path(self.temp.name) / "legacy-no-phone.db"
        with sqlite3.connect(legacy_db) as db:
            db.execute("""
                CREATE TABLE users (
                  id TEXT PRIMARY KEY,
                  email TEXT NOT NULL UNIQUE,
                  name TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'user',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
            """)
            db.execute(
                "INSERT INTO users(id, email, name, password_hash, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("u_legacy", "legacy@example.com", "Legacy", "hash", "user", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
            )
            db.commit()
        server = create_server(port=0, static_root=Path(self.temp.name), database_file=legacy_db, use_sqlite=True)
        server.server_close()
        with sqlite3.connect(legacy_db) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
            indexes = {row[1] for row in db.execute("PRAGMA index_list(users)").fetchall()}
            phone = db.execute("SELECT phone FROM users WHERE id = 'u_legacy'").fetchone()[0]
        self.assertIn("phone", columns)
        self.assertIn("idx_users_phone_unique", indexes)
        self.assertEqual(phone, "")

    def test_change_password_requires_current_password_and_rotates_login_secret(self):
        _, registered, headers = self.request_raw(
            "/api/auth/register",
            "POST",
            {"email": "change@example.com", "password": "oldpass123", "name": "改密用户"},
        )
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertTrue(registered["authenticated"])
        with self.assertRaises(HTTPError) as wrong_current:
            self.request("/api/account/password", "POST", {"currentPassword": "badpass", "newPassword": "newpass123"}, {"Cookie": cookie})
        self.assertEqual(wrong_current.exception.code, 400)
        status, changed, changed_headers = self.request_raw("/api/account/password", "POST", {"currentPassword": "oldpass123", "newPassword": "newpass123"}, {"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(changed["authenticated"])
        self.assertIn("schedule_ai_session=", changed_headers["Set-Cookie"])
        with self.assertRaises(HTTPError) as old_login:
            self.request("/api/auth/login", "POST", {"email": "change@example.com", "password": "oldpass123"})
        self.assertEqual(old_login.exception.code, 401)
        _, new_login = self.request("/api/auth/login", "POST", {"email": "change@example.com", "password": "newpass123"})
        self.assertTrue(new_login["authenticated"])

    def test_login_failures_are_rate_limited(self):
        self.server.RequestHandlerClass.login_limiter = __import__("serve").FailedLoginLimiter(limit=2, window_seconds=60)
        self.request("/api/auth/register", "POST", {"email": "limit@example.com", "password": "securepass1", "name": "限制用户"})
        for _ in range(2):
            with self.assertRaises(HTTPError) as failed:
                self.request("/api/auth/login", "POST", {"email": "limit@example.com", "password": "wrongpass"})
            self.assertEqual(failed.exception.code, 401)
        with self.assertRaises(HTTPError) as limited:
            self.request("/api/auth/login", "POST", {"email": "limit@example.com", "password": "wrongpass"})
        self.assertEqual(limited.exception.code, 429)

    def test_rejects_invalid_payload(self):
        with self.assertRaises(HTTPError) as invalid:
            self.request("/api/projects/P-BAD", "PUT", {"tasks": []})
        self.assertEqual(invalid.exception.code, 400)

    def test_ai_config_is_masked_and_proxy_requires_configuration(self):
        _, empty = self.request("/api/settings/ai")
        self.assertFalse(empty["configured"])
        with self.assertRaises(HTTPError) as unavailable:
            self.request("/api/ai/chat", "POST", {"messages": [{"role": "user", "content": "test"}]})
        self.assertEqual(unavailable.exception.code, 409)

        _, configured = self.request("/api/settings/ai", "PUT", {"provider": "deepseek", "model": "deepseek-chat", "apiKey": "sk-test-secret"})
        self.assertTrue(configured["configured"])
        self.assertEqual(configured["maskedKey"], "••••cret")
        self.assertNotIn("apiKey", configured)

        _, public = self.request("/api/settings/ai")
        self.assertNotIn("apiKey", public)
        with sqlite3.connect(self.db_file) as db:
            stored = db.execute("SELECT api_key FROM ai_settings WHERE id = 1").fetchone()
        self.assertEqual(stored[0], "sk-test-secret")

        _, removed = self.request("/api/settings/ai", "DELETE")
        self.assertTrue(removed["deleted"])
        _, empty_again = self.request("/api/settings/ai")
        self.assertFalse(empty_again["configured"])

    def test_openai_provider_configuration_is_supported(self):
        _, configured = self.request("/api/settings/ai", "PUT", {"provider": "openai", "model": "gpt-5.4-mini", "apiKey": "sk-openai-secret"})
        self.assertTrue(configured["configured"])
        self.assertEqual(configured["provider"], "openai")
        self.assertEqual(configured["model"], "gpt-5.4-mini")
        self.assertNotIn("apiKey", configured)

    @patch("serve.check_tcp_endpoint")
    def test_connectivity_diagnostics_report_provider_endpoint_and_require_admin(self, mocked_check):
        mocked_check.side_effect = lambda host: {"host": host, "dns": True, "tcp443": host != "api.openai.com", "addresses": ["203.0.113.10"]}
        self.request("/api/settings/ai", "PUT", {"provider": "deepseek", "model": "deepseek-chat", "apiKey": "sk-test"})
        _, diagnostics = self.request("/api/diagnostics/connectivity")
        self.assertFalse(diagnostics["ok"])
        self.assertEqual([item["host"] for item in diagnostics["checks"]], ["api.openai.com", "api.deepseek.com"])
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        with self.assertRaises(HTTPError) as forbidden:
            self.request("/api/diagnostics/connectivity")
        self.assertEqual(forbidden.exception.code, 403)
        _, authorized = self.request("/api/diagnostics/connectivity", headers={"X-Admin-Token": "admin-secret"})
        self.assertIn("checks", authorized)

    def test_codex_bridge_is_admin_only_and_supports_read_only_runner(self):
        calls = []
        self.server.RequestHandlerClass.codex_agent = CodexAgent(
            enabled=True,
            allow_write=False,
            runner=lambda **kwargs: calls.append(kwargs) or {"finalResponse": "审查完成", "sandbox": kwargs["sandbox"]},
        )
        _, integrations = self.request("/api/integrations")
        self.assertTrue(integrations["codex"]["ready"])
        self.assertEqual(integrations["codex"]["sandbox"], "read_only")
        _, result = self.request("/api/codex/run", "POST", {"prompt": "只读审查当前计划"})
        self.assertEqual(result["finalResponse"], "审查完成")
        self.assertEqual(calls[0]["sandbox"], "read_only")
        with self.assertRaises(HTTPError) as write_rejected:
            self.request("/api/codex/run", "POST", {"prompt": "修改计划", "sandbox": "workspace_write"})
        self.assertEqual(write_rejected.exception.code, 400)
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        with self.assertRaises(HTTPError) as forbidden:
            self.request("/api/codex/run", "POST", {"prompt": "审查"})
        self.assertEqual(forbidden.exception.code, 403)
        _, authorized = self.request("/api/codex/run", "POST", {"prompt": "审查"}, {"X-Admin-Token": "admin-secret"})
        self.assertEqual(authorized["finalResponse"], "审查完成")

    def test_public_clients_cannot_read_each_others_projects(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        payload = {"project": {"projectName": "访客项目"}, "tasks": [], "baselines": []}
        client_a={"X-Client-Id":"web-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}
        client_b={"X-Client-Id":"web-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"}
        self.request("/api/projects/P-PRIVATE", "PUT", payload, client_a)
        _, own = self.request("/api/projects", headers=client_a)
        _, other = self.request("/api/projects", headers=client_b)
        self.assertEqual(len(own["projects"]), 1)
        self.assertEqual(other["projects"], [])
        with self.assertRaises(HTTPError) as hidden:
            self.request("/api/projects/P-PRIVATE", headers=client_b)
        self.assertEqual(hidden.exception.code, 404)

    def test_custom_templates_are_saved_per_user_or_guest_owner(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        client_a={"X-Client-Id":"web-template-a"}
        client_b={"X-Client-Id":"web-template-b"}
        template = {
            "id": "CUSTOM-TPL-1",
            "name": "企业样板工序",
            "phase": "样板阶段",
            "discipline": "土建",
            "duration": 3,
            "predecessorNames": ["施工准备"],
            "relationType": "SS",
            "lag": 2,
            "resourceDemand": ["木工班组"],
            "materialNodes": ["模板验收"],
            "expansionDimensions": ["楼栋"],
        }
        _, saved = self.request("/api/templates", "PUT", {"templates": [template]}, client_a)
        self.assertEqual(saved["templates"][0]["name"], "企业样板工序")
        self.assertTrue(saved["templates"][0]["isCustom"])
        self.assertEqual(saved["templates"][0]["relationType"], "SS")

        _, own = self.request("/api/templates", headers=client_a)
        _, other = self.request("/api/templates", headers=client_b)
        self.assertEqual(len(own["templates"]), 1)
        self.assertEqual(other["templates"], [])
        with sqlite3.connect(self.db_file) as db:
            count = db.execute("SELECT COUNT(*) FROM user_templates WHERE owner = ?", (client_a["X-Client-Id"],)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_public_ai_configuration_requires_admin_token(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        payload={"provider":"deepseek","model":"deepseek-chat","apiKey":"sk-private"}
        with self.assertRaises(HTTPError) as forbidden:
            self.request("/api/settings/ai", "PUT", payload)
        self.assertEqual(forbidden.exception.code, 403)
        _, configured=self.request("/api/settings/ai", "PUT", payload, {"X-Admin-Token":"admin-secret"})
        self.assertTrue(configured["configured"])

    def test_admin_overview_reports_database_counts_and_requires_admin(self):
        self.request("/api/auth/register", "POST", {"email": "ops@example.com", "password": "securepass1", "name": "运维"})
        self.request("/api/projects/P-OPS", "PUT", {"project": {"projectName": "运营统计项目"}, "tasks": []})
        self.request("/api/templates", "PUT", {"templates": [{"id": "OPS-TPL", "name": "统计模板", "duration": 2}]})
        self.server.RequestHandlerClass.allow_local_admin = True
        _, overview = self.request("/api/admin/overview")
        self.assertEqual(overview["storage"]["engine"], "sqlite")
        self.assertGreaterEqual(overview["counts"]["users"], 1)
        self.assertGreaterEqual(overview["counts"]["projects"], 1)
        self.assertGreaterEqual(overview["counts"]["customTemplates"], 1)
        self.assertTrue(overview["storage"]["exists"])
        self.assertEqual(overview["recentProjects"][0]["name"], "运营统计项目")
        self.assertEqual(overview["recentUsers"][0]["email"], "ops@example.com")
        self.assertEqual(overview["recentTemplates"][0]["count"], 1)

        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        with self.assertRaises(HTTPError) as forbidden:
            self.request("/api/admin/overview")
        self.assertEqual(forbidden.exception.code, 403)
        _, authorized = self.request("/api/admin/overview", headers={"X-Admin-Token": "admin-secret"})
        self.assertIn("counts", authorized)

    def test_project_quota_blocks_new_projects_but_allows_updates(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.project_limit_per_owner = 1
        client = {"X-Client-Id": "web-quota-user"}
        payload = {"project": {"projectName": "配额内项目"}, "tasks": [], "baselines": []}
        self.request("/api/projects/P-QUOTA-1", "PUT", payload, client)
        self.request("/api/projects/P-QUOTA-1", "PUT", {"project": {"projectName": "允许更新"}, "tasks": [], "baselines": []}, client)
        with self.assertRaises(HTTPError) as limited:
            self.request("/api/projects/P-QUOTA-2", "PUT", {"project": {"projectName": "超限项目"}, "tasks": [], "baselines": []}, client)
        self.assertEqual(limited.exception.code, 409)

    def test_admin_email_role_can_access_admin_overview(self):
        with patch.dict("os.environ", {"ADMIN_EMAILS": "boss@example.com"}):
            _, registered, headers = self.request_raw("/api/auth/register", "POST", {"email": "boss@example.com", "password": "securepass1", "name": "站点管理员"})
        self.assertEqual(registered["user"]["role"], "admin")
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        _, overview = self.request("/api/admin/overview", headers={"Cookie": cookie})
        self.assertIn("limits", overview)

    def test_readiness_check_requires_admin_and_reports_core_status(self):
        self.server.RequestHandlerClass.allow_local_admin = False
        self.server.RequestHandlerClass.admin_token = "admin-secret"
        with self.assertRaises(HTTPError) as forbidden:
            self.request("/api/readiness")
        self.assertEqual(forbidden.exception.code, 403)

        _, readiness = self.request("/api/readiness", headers={"X-Admin-Token": "admin-secret"})
        self.assertFalse(readiness["ready"])
        checks = {item["key"]: item for item in readiness["checks"]}
        self.assertEqual(checks["storageWritable"]["level"], "ok")
        self.assertEqual(checks["database"]["level"], "ok")
        self.assertEqual(checks["adminToken"]["level"], "ok")
        self.assertEqual(checks["adminPassword"]["level"], "error")
        self.assertEqual(checks["phoneCode"]["level"], "error")
        self.assertIn("warningCount", readiness)

    @patch("serve.call_ai_provider")
    def test_ai_daily_quota_records_usage_and_blocks_when_exhausted(self, mocked_ai):
        mocked_ai.return_value = {"summary": "ok"}
        self.server.RequestHandlerClass.ai_daily_limit_per_owner = 2
        self.request("/api/settings/ai", "PUT", {"provider": "openai", "model": "gpt-5.4-mini", "apiKey": "sk-test"})
        self.server.RequestHandlerClass.allow_local_admin = False
        client = {"X-Client-Id": "web-ai-quota"}
        payload = {"messages": [{"role": "user", "content": "test"}]}
        _, first = self.request("/api/ai/chat", "POST", payload, client)
        _, second = self.request("/api/ai/chat", "POST", payload, client)
        self.assertEqual(first["summary"], "ok")
        self.assertEqual(second["aiQuota"]["remaining"], 0)
        with self.assertRaises(HTTPError) as limited:
            self.request("/api/ai/chat", "POST", payload, client)
        self.assertEqual(limited.exception.code, 429)

        self.server.RequestHandlerClass.allow_local_admin = True
        self.server.RequestHandlerClass.admin_token = ""
        _, overview = self.request("/api/admin/overview")
        self.assertEqual(overview["aiUsage"]["todayTotal"], 2)
        self.assertEqual(overview["aiUsage"]["todaySuccess"], 2)

    def test_account_export_and_delete_remove_user_owned_data(self):
        _, registered, headers = self.request_raw(
            "/api/auth/register",
            "POST",
            {"email": "delete-me@example.com", "password": "securepass1", "name": "待删除用户"},
        )
        self.assertTrue(registered["authenticated"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        auth_headers = {"Cookie": cookie}
        self.request("/api/projects/P-DELETE-ME", "PUT", {"project": {"projectName": "待导出项目"}, "tasks": [], "baselines": []}, auth_headers)
        self.request("/api/templates", "PUT", {"templates": [{"id": "T-DELETE", "name": "待导出模板", "duration": 1}]}, auth_headers)

        _, exported = self.request("/api/account/export", headers=auth_headers)
        self.assertEqual(exported["user"]["email"], "delete-me@example.com")
        self.assertEqual(exported["projects"][0]["project"]["projectName"], "待导出项目")
        self.assertEqual(exported["templates"][0]["name"], "待导出模板")

        status, deleted, delete_headers = self.request_raw("/api/account", "DELETE", headers=auth_headers)
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(deleted["projects"], 1)
        self.assertIn("Max-Age=0", delete_headers["Set-Cookie"])
        with self.assertRaises(HTTPError) as after_delete:
            self.request("/api/account/export", headers=auth_headers)
        self.assertEqual(after_delete.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
