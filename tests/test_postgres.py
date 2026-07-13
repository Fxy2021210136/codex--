import json
import os
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from serve import PostgresDatabase, create_server


POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "")


@unittest.skipUnless(POSTGRES_URL, "TEST_POSTGRES_URL is not configured")
class PostgresApiTest(unittest.TestCase):
    def setUp(self):
        database = PostgresDatabase(POSTGRES_URL)
        database.ensure_schema()
        with database.connect() as connection:
            connection.execute(
                "TRUNCATE ai_usage, ai_settings, user_templates, sessions, projects, users "
                "RESTART IDENTITY CASCADE"
            )
        self.server = create_server(
            port=0, static_root=Path(__file__).parent, database_url=POSTGRES_URL
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, method="GET", payload=None, headers=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            self.base + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")), response.headers

    def test_account_project_template_and_restart_persist(self):
        registered, headers = self.request(
            "/api/auth/register",
            "POST",
            {"email": "pg@example.com", "password": "securepass1", "name": "PG 用户"},
        )
        self.assertTrue(registered["authenticated"])
        registered_cookie = headers["Set-Cookie"].split(";", 1)[0]
        logged_in, headers = self.request(
            "/api/auth/login",
            "POST",
            {"email": "pg@example.com", "password": "securepass1"},
        )
        self.assertTrue(logged_in["authenticated"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertNotEqual(cookie, registered_cookie)
        auth = {"Cookie": cookie}
        self.request(
            "/api/projects/P-PG",
            "PUT",
            {
                "project": {"projectName": "PostgreSQL 项目"},
                "tasks": [],
                "baselines": [],
            },
            auth,
        )
        updated, _ = self.request(
            "/api/projects/P-PG",
            "PUT",
            {
                "project": {"projectName": "PostgreSQL 更新项目"},
                "tasks": [{"id": "PG-1", "name": "更新工序"}],
                "baselines": [],
            },
            auth,
        )
        self.assertEqual(updated["project"]["projectName"], "PostgreSQL 更新项目")
        self.request(
            "/api/templates",
            "PUT",
            {"templates": [{"id": "PG-TPL", "name": "PG 模板", "duration": 2}]},
            auth,
        )

        _, second_headers = self.request(
            "/api/auth/register",
            "POST",
            {"email": "pg-second@example.com", "password": "securepass2", "name": "第二用户"},
        )
        second_auth = {"Cookie": second_headers["Set-Cookie"].split(";", 1)[0]}
        second_projects, _ = self.request("/api/projects", headers=second_auth)
        self.assertEqual(second_projects["projects"], [])
        with self.assertRaises(HTTPError) as hidden:
            self.request("/api/projects/P-PG", headers=second_auth)
        self.assertEqual(hidden.exception.code, 404)

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = create_server(
            port=0, static_root=Path(__file__).parent, database_url=POSTGRES_URL
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

        projects, _ = self.request("/api/projects", headers=auth)
        templates, _ = self.request("/api/templates", headers=auth)
        self.assertEqual(projects["projects"][0]["name"], "PostgreSQL 更新项目")
        project, _ = self.request("/api/projects/P-PG", headers=auth)
        self.assertEqual(project["tasks"][0]["name"], "更新工序")
        self.assertEqual(templates["templates"][0]["name"], "PG 模板")
        health, _ = self.request("/api/health")
        self.assertEqual(
            health["database"], {"engine": "postgresql", "connected": True}
        )


if __name__ == "__main__":
    unittest.main()
