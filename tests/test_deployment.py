from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
import tomllib
import unittest

from fastapi.testclient import TestClient

from sports_briefing import __version__
from sports_briefing.api import create_app


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory) / "missing.sqlite3", public_mode=True))
            self.responses = {}
            for path in ("/health", "/meta", "/timeline", "/timeline?hide_results=false",
                         "/briefings/arsenal", "/briefings/texans"):
                response = client.get(path)
                self.responses[path] = (response.status_code, response.json())

    def run_smoke(self) -> subprocess.CompletedProcess[str]:
        responses = deepcopy(self.responses)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status, body = responses[self.path]
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return subprocess.run(
                ["bash", str(ROOT / "deploy/smoke_check.sh"), f"http://127.0.0.1:{server.server_port}"],
                env={**os.environ, "PYTHONOPTIMIZE": "1"}, capture_output=True, text=True, timeout=15,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_smoke_accepts_actual_public_api_contract_with_optimization_enabled(self) -> None:
        result = self.run_smoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("both spoiler modes, briefings blocked", result.stdout)

    def test_smoke_rejects_empty_or_missing_entity_timeline(self) -> None:
        original = deepcopy(self.responses)
        for items in ([], [self.responses["/timeline"][1]["items"][0]]):
            with self.subTest(items=len(items)):
                self.responses = deepcopy(original)
                self.responses["/timeline"][1]["items"] = items
                result = self.run_smoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing demo entity", result.stderr)

    def test_smoke_rejects_wrong_provider_and_each_missing_demo_label(self) -> None:
        original = deepcopy(self.responses)
        for field in ("provider", "title", "summary", "attribution", "data_mode"):
            with self.subTest(field=field):
                self.responses = deepcopy(original)
                item = self.responses["/timeline"][1]["items"][0]
                if field in ("provider", "attribution"):
                    item["source"][field] = "unlabelled-provider"
                else:
                    item[field] = "unlabelled"
                self.assertNotEqual(self.run_smoke().returncode, 0)

    def test_smoke_rejects_wrong_default_mode_and_exposed_result(self) -> None:
        original = deepcopy(self.responses)
        for error in ("mode", "result"):
            with self.subTest(error=error):
                self.responses = deepcopy(original)
                body = self.responses["/timeline"][1]
                if error == "mode":
                    body["spoiler_mode"] = "show_results"
                else:
                    body["items"][0]["result"] = {"winner": "HOME_TEAM"}
                self.assertNotEqual(self.run_smoke().returncode, 0)

    def test_smoke_checks_revealed_timeline_and_both_restricted_endpoints(self) -> None:
        original = deepcopy(self.responses)
        for path in ("/timeline?hide_results=false", "/briefings/arsenal", "/briefings/texans"):
            with self.subTest(path=path):
                self.responses = deepcopy(original)
                if path.startswith("/timeline"):
                    self.responses[path][1]["spoiler_mode"] = "hide_results"
                else:
                    self.responses[path] = (200, {"provider": "restricted"})
                self.assertNotEqual(self.run_smoke().returncode, 0)

    def test_smoke_rejects_private_mode_even_with_optimization_enabled(self) -> None:
        self.responses["/meta"][1]["public_mode"] = False
        result = self.run_smoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("public mode is not enabled", result.stderr)


class VersionTests(unittest.TestCase):
    def test_package_metadata_meta_and_openapi_use_shared_version(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertNotIn("version", config["project"])
        self.assertIn("version", config["project"]["dynamic"])
        self.assertEqual(config["tool"]["setuptools"]["dynamic"]["version"]["attr"],
                         "sports_briefing.__version__")
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "missing.sqlite3", public_mode=True)
            client = TestClient(app)
            self.assertEqual(client.get("/meta").json()["version"], __version__)
            self.assertEqual(client.get("/openapi.json").json()["info"]["version"], __version__)
