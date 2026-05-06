import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MODEL_MAP = {
    "claude-opus-4-7": "deepseek-v4-pro[1m]",
    "claude-opus-4-7[1m]": "deepseek-v4-pro[1m]",
    "anthropic/claude-opus-4-7": "deepseek-v4-pro[1m]",
    "anthropic/claude-opus-4-7[1m]": "deepseek-v4-pro[1m]",
    "opus-4.7": "deepseek-v4-pro[1m]",
    "opus-4.7[1m]": "deepseek-v4-pro[1m]",
    "claude-sonnet-4-5": "deepseek-v4-flash",
    "anthropic/claude-sonnet-4-5": "deepseek-v4-flash",
    "sonnet-4.5": "deepseek-v4-flash",
}

DEFAULT_LOG_FILE = Path.home() / "Library/Logs/Claude-3p/deepseek-gateway.log"
_LOG_LOCK = threading.Lock()


@dataclass
class GatewayConfig:
    upstream_base_url: str
    listen_host: str = "127.0.0.1"
    listen_port: int = 8088
    api_key: str | None = None
    log_file: str | None = str(DEFAULT_LOG_FILE)
    model_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODEL_MAP))
    forced_effort: str = "max"
    upstream_timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        upstream_base_url = os.environ.get("GATEWAY_UPSTREAM_BASE_URL")
        if not upstream_base_url:
            raise ValueError("GATEWAY_UPSTREAM_BASE_URL is required")

        api_key = os.environ.get("GATEWAY_UPSTREAM_API_KEY")
        if not api_key:
            raise ValueError("GATEWAY_UPSTREAM_API_KEY is required")

        listen_host = os.environ.get("GATEWAY_LISTEN_HOST", "127.0.0.1")
        listen_port = int(os.environ.get("GATEWAY_LISTEN_PORT", "8088"))
        timeout = int(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "30"))
        forced_effort = os.environ.get("GATEWAY_FORCE_EFFORT", "max")
        log_file = os.environ.get("GATEWAY_LOG_FILE") or str(DEFAULT_LOG_FILE)
        model_map_raw = os.environ.get("GATEWAY_MODEL_MAP_JSON")
        model_map = dict(DEFAULT_MODEL_MAP)
        if model_map_raw:
            model_map.update(json.loads(model_map_raw))

        return cls(
            upstream_base_url=upstream_base_url.rstrip("/"),
            listen_host=listen_host,
            listen_port=listen_port,
            api_key=api_key,
            log_file=log_file,
            model_map=model_map,
            forced_effort=forced_effort,
            upstream_timeout_seconds=timeout,
        )


def create_handler(config: GatewayConfig):
    class GatewayHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            request_id = uuid.uuid4().hex
            path = urlsplit(self.path).path
            query = urlsplit(self.path).query
            started = time.perf_counter()
            status = 404
            self._log_event(
                event="request_start",
                request_id=request_id,
                method="GET",
                path=path,
                query=query,
            )
            if path == "/health":
                status = 200
                self._send_json(200, {"status": "ok"})
            elif path == "/v1/models":
                status = 200
                self._send_json(200, _models_payload(config.model_map))
            else:
                self._send_json(404, {"error": "not_found"})
            self._log_event(
                event="request_end",
                request_id=request_id,
                method="GET",
                path=path,
                query=query,
                status=status,
                duration_ms=_elapsed_ms(started),
            )

        def do_POST(self):
            request_id = uuid.uuid4().hex
            path = urlsplit(self.path).path
            started = time.perf_counter()
            if path not in ("/v1/messages", "/v1/messages/count_tokens"):
                self._log_event(
                    event="request_end",
                    request_id=request_id,
                    method="POST",
                    path=path,
                    status=404,
                    duration_ms=_elapsed_ms(started),
                    error="not_found",
                )
                self._send_json(404, {"error": "not_found"})
                return

            payload = _read_json(self)
            client_model = payload.get("model")
            upstream_model = config.model_map.get(client_model)
            if upstream_model is None:
                self._log_event(
                    event="request_end",
                    request_id=request_id,
                    method="POST",
                    path=path,
                    status=400,
                    duration_ms=_elapsed_ms(started),
                    client_model=client_model,
                    error="unsupported_model",
                )
                self._send_json(400, {"error": f"Unsupported model route: {client_model}"})
                return

            payload["model"] = upstream_model
            if config.forced_effort:
                payload["effort"] = config.forced_effort
            upstream_url = f"{config.upstream_base_url}{path}"
            body = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                "Authorization": f"Bearer {config.api_key}",
                "x-api-key": config.api_key or "",
            }
            if self.headers.get("anthropic-beta"):
                headers["anthropic-beta"] = self.headers["anthropic-beta"]

            upstream_request = Request(upstream_url, data=body, headers=headers, method="POST")
            self._log_event(
                event="request_start",
                request_id=request_id,
                method="POST",
                path=path,
                client_model=client_model,
                upstream_model=upstream_model,
                forced_effort=config.forced_effort,
            )

            try:
                with urlopen(upstream_request, timeout=config.upstream_timeout_seconds) as response:
                    response_body = response.read()
                    self.send_response(response.status)
                    for key, value in response.headers.items():
                        if key.lower() == "transfer-encoding":
                            continue
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(response_body)
                    self._log_event(
                        event="request_end",
                        request_id=request_id,
                        method="POST",
                        path=path,
                        status=response.status,
                        duration_ms=_elapsed_ms(started),
                        client_model=client_model,
                        upstream_model=upstream_model,
                        forced_effort=config.forced_effort,
                    )
            except HTTPError as exc:
                self._relay_error(exc)
                self._log_event(
                    event="request_end",
                    request_id=request_id,
                    method="POST",
                    path=path,
                    status=exc.code,
                    duration_ms=_elapsed_ms(started),
                    client_model=client_model,
                    upstream_model=upstream_model,
                    forced_effort=config.forced_effort,
                    error="http_error",
                    upstream_error=exc.reason,
                )
            except URLError as exc:
                self._send_json(502, {"error": f"upstream_unreachable: {exc.reason}"})
                self._log_event(
                    event="request_end",
                    request_id=request_id,
                    method="POST",
                    path=path,
                    status=502,
                    duration_ms=_elapsed_ms(started),
                    client_model=client_model,
                    upstream_model=upstream_model,
                    forced_effort=config.forced_effort,
                    error="upstream_unreachable",
                    upstream_error=str(exc.reason),
                )

        def log_message(self, *_args: Any) -> None:
            return

        def _log_event(self, **fields: Any) -> None:
            _append_log(config.log_file, fields)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _relay_error(self, exc: HTTPError) -> None:
            body = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json")
            self.send_response(exc.code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return GatewayHandler


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _append_log(log_file: str | None, fields: dict[str, Any]) -> None:
    if not log_file:
        return

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
    path = Path(log_file).expanduser()

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
    except OSError:
        return


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _models_payload(model_map: dict[str, str]) -> dict[str, Any]:
    data = []
    for model_name in model_map:
        data.append(
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": "deepseek",
            }
        )
    return {"object": "list", "data": data}


def run_server(config: GatewayConfig) -> None:
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), create_handler(config))
    print(
        f"DeepSeek Anthropic mapping gateway listening on http://{config.listen_host}:{config.listen_port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
