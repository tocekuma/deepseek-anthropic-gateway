import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request
from urllib.error import HTTPError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gateway import GatewayConfig, create_handler


class UpstreamRecorder:
    def __init__(self):
        self.requests = []
        self.response_status = 200
        self.response_headers = {"Content-Type": "application/json"}
        self.response_body = b'{"ok":true}'


def start_server(handler_class):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.upstream = UpstreamRecorder()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = pathlib.Path(self.temp_dir.name) / "gateway.log"

        recorder = self.upstream

        class UpstreamHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                recorder.requests.append(
                    {
                        "method": "GET",
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": b"",
                    }
                )
                self.send_response(recorder.response_status)
                for key, value in recorder.response_headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(recorder.response_body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                recorder.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "headers": dict(self.headers.items()),
                        "body": body,
                    }
                )
                self.send_response(recorder.response_status)
                for key, value in recorder.response_headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(recorder.response_body)

            def log_message(self, *_args):
                return

        self.upstream_server = start_server(UpstreamHandler)
        upstream_base = f"http://127.0.0.1:{self.upstream_server.server_port}"

        config = GatewayConfig(
            upstream_base_url=upstream_base,
            listen_host="127.0.0.1",
            listen_port=0,
            api_key="secret-key",
            model_map={
                "claude-opus-4-7": "deepseek-v4-pro[1m]",
                "claude-opus-4-7[1m]": "deepseek-v4-pro[1m]",
                "anthropic/claude-opus-4-7": "deepseek-v4-pro[1m]",
                "anthropic/claude-opus-4-7[1m]": "deepseek-v4-pro[1m]",
                "opus-4.7": "deepseek-v4-pro[1m]",
                "opus-4.7[1m]": "deepseek-v4-pro[1m]",
                "claude-sonnet-4-5": "deepseek-v4-flash",
                "anthropic/claude-sonnet-4-5": "deepseek-v4-flash",
                "sonnet-4.5": "deepseek-v4-flash",
                "claude-haiku-4-5-20251001": "deepseek-v4-flash",
            },
            forced_effort="max",
            upstream_timeout_seconds=5,
            log_file=str(self.log_file),
        )
        self.gateway_server = start_server(create_handler(config))
        self.gateway_base = f"http://127.0.0.1:{self.gateway_server.server_port}"

    def tearDown(self):
        self.gateway_server.shutdown()
        self.upstream_server.shutdown()
        self.gateway_server.server_close()
        self.upstream_server.server_close()
        self.temp_dir.cleanup()

    def test_models_returns_claude_routes_for_desktop_picker(self):
        response = request.urlopen(f"{self.gateway_base}/v1/models", timeout=5)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.read().decode("utf-8"))
        model_ids = [item["id"] for item in payload["data"]]
        self.assertEqual(
            model_ids,
            [
                "claude-opus-4-7",
                "claude-opus-4-7[1m]",
                "anthropic/claude-opus-4-7",
                "anthropic/claude-opus-4-7[1m]",
                "opus-4.7",
                "opus-4.7[1m]",
                "claude-sonnet-4-5",
                "anthropic/claude-sonnet-4-5",
                "sonnet-4.5",
                "claude-haiku-4-5-20251001",
            ],
        )
        self.assertEqual(self.upstream.requests, [])

    def test_models_accepts_query_string_from_desktop_discovery(self):
        response = request.urlopen(f"{self.gateway_base}/v1/models?source=desktop", timeout=5)

        self.assertEqual(response.status, 200)
        payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["object"], "list")

    def test_messages_rewrites_route_model_and_forwards_authorization(self):
        body = {
            "model": "claude-sonnet-4-5",
            "max_tokens": 16,
            "effort": "low",
            "messages": [{"role": "user", "content": "ping"}],
        }
        req = request.Request(
            f"{self.gateway_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer desktop-token",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        response = request.urlopen(req, timeout=5)

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.read().decode("utf-8")), {"ok": True})
        self.assertEqual(len(self.upstream.requests), 1)
        forwarded = self.upstream.requests[0]
        forwarded_headers = {key.lower(): value for key, value in forwarded["headers"].items()}
        self.assertEqual(forwarded["path"], "/v1/messages")
        self.assertEqual(forwarded_headers["authorization"], "Bearer secret-key")
        self.assertEqual(forwarded_headers["x-api-key"], "secret-key")
        self.assertEqual(forwarded_headers["anthropic-version"], "2023-06-01")
        forwarded_payload = json.loads(forwarded["body"].decode("utf-8"))
        self.assertEqual(forwarded_payload["model"], "deepseek-v4-flash")
        self.assertEqual(forwarded_payload["effort"], "max")

    def test_messages_writes_redacted_model_mapping_log(self):
        body = {
            "model": "claude-sonnet-4-5",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "do not log this prompt"}],
        }
        req = request.Request(
            f"{self.gateway_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        request.urlopen(req, timeout=5).read()

        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["method"], "POST")
        self.assertEqual(event["path"], "/v1/messages")
        self.assertEqual(event["status"], 200)
        self.assertEqual(event["client_model"], "claude-sonnet-4-5")
        self.assertEqual(event["upstream_model"], "deepseek-v4-flash")
        self.assertEqual(event["forced_effort"], "max")
        self.assertIn("duration_ms", event)
        log_text = self.log_file.read_text(encoding="utf-8")
        self.assertNotIn("secret-key", log_text)
        self.assertNotIn("do not log this prompt", log_text)

    def test_count_tokens_rewrites_model(self):
        body = {"model": "claude-opus-4-7[1m]", "messages": []}
        req = request.Request(
            f"{self.gateway_base}/v1/messages/count_tokens",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        request.urlopen(req, timeout=5).read()

        forwarded_payload = json.loads(self.upstream.requests[0]["body"].decode("utf-8"))
        self.assertEqual(forwarded_payload["model"], "deepseek-v4-pro[1m]")

    def test_short_sonnet_alias_rewrites_to_flash(self):
        body = {"model": "sonnet-4.5", "messages": []}
        req = request.Request(
            f"{self.gateway_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        request.urlopen(req, timeout=5).read()

        forwarded_payload = json.loads(self.upstream.requests[0]["body"].decode("utf-8"))
        self.assertEqual(forwarded_payload["model"], "deepseek-v4-flash")

    def test_unknown_sonnet_or_haiku_routes_default_to_flash(self):
        for model_name in ("claude-sonnet-4-5-20251001", "claude-haiku-4-5-20251001"):
            body = {"model": model_name, "messages": []}
            req = request.Request(
                f"{self.gateway_base}/v1/messages",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            request.urlopen(req, timeout=5).read()

        forwarded_payloads = [
            json.loads(item["body"].decode("utf-8")) for item in self.upstream.requests[-2:]
        ]
        self.assertEqual(
            [item["model"] for item in forwarded_payloads],
            ["deepseek-v4-flash", "deepseek-v4-flash"],
        )

    def test_unknown_opus_routes_default_to_pro(self):
        body = {"model": "claude-opus-4-7-20251001", "messages": []}
        req = request.Request(
            f"{self.gateway_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        request.urlopen(req, timeout=5).read()

        forwarded_payload = json.loads(self.upstream.requests[-1]["body"].decode("utf-8"))
        self.assertEqual(forwarded_payload["model"], "deepseek-v4-pro[1m]")

    def test_unknown_model_returns_400_before_upstream(self):
        body = {"model": "deepseek-v4-pro", "messages": []}
        req = request.Request(
            f"{self.gateway_base}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as exc:
            request.urlopen(req, timeout=5)

        self.assertEqual(exc.exception.code, 400)
        self.assertIn("Unsupported model route", exc.exception.read().decode("utf-8"))
        self.assertEqual(self.upstream.requests, [])


if __name__ == "__main__":
    unittest.main()
