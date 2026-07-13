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
        cookie = headers["Set-Cookie"].split(";", 1)[0]
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
        self.request(
            "/api/templates",
            "PUT",
            {"templates": [{"id": "PG-TPL", "name": "PG 模板", "duration": 2}]},
            auth,
        )

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
        self.assertEqual(projects["projects"][0]["name"], "PostgreSQL 项目")
        self.assertEqual(templates["templates"][0]["name"], "PG 模板")
        health, _ = self.request("/api/health")
        self.assertEqual(
            health["database"], {"engine": "postgresql", "connected": True}
        )


if __name__ == "__main__":
    unittest.main()
