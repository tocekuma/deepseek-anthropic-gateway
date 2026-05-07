# DeepSeek Anthropic Gateway

Make Claude Desktop speak Claude, while DeepSeek does the actual work.

This is a tiny local gateway for Claude Desktop / Claude Code custom 3P setups. It exposes an Anthropic-compatible surface to the client, rewrites Claude-looking model names into DeepSeek model names, forces `effort=max`, and keeps a redacted request log so you can debug the chain without leaking prompts or API keys.

In short:

```text
Claude Desktop -> localhost gateway -> DeepSeek Anthropic-compatible API
```

## Why This Exists

Claude Desktop may validate model names more strictly than your upstream provider expects. If the client wants to see Claude-style model IDs, but your backend wants DeepSeek model IDs, direct configuration can get awkward fast.

This gateway sits in the middle and says:

| Claude-facing route | Upstream model |
| --- | --- |
| `claude-opus-4-7` | `deepseek-v4-pro[1m]` |
| `claude-opus-4-7[1m]` | `deepseek-v4-pro[1m]` |
| `anthropic/claude-opus-4-7` | `deepseek-v4-pro[1m]` |
| `anthropic/claude-opus-4-7[1m]` | `deepseek-v4-pro[1m]` |
| `opus-4.7` | `deepseek-v4-pro[1m]` |
| `opus-4.7[1m]` | `deepseek-v4-pro[1m]` |
| `claude-sonnet-4-5` | `deepseek-v4-flash` |
| `anthropic/claude-sonnet-4-5` | `deepseek-v4-flash` |
| `sonnet-4.5` | `deepseek-v4-flash` |
| `claude-haiku-4-5-20251001` | `deepseek-v4-flash` |

For model names not listed above, the gateway also applies family defaults:

| Client model contains | Upstream model |
| --- | --- |
| `opus` | `deepseek-v4-pro[1m]` |
| `sonnet` | `deepseek-v4-flash` |
| `haiku` | `deepseek-v4-flash` |

It also overwrites any incoming `effort` value with:

```json
{"effort":"max"}
```

Because if you asked for max, the client does not get a vote. Politely.

## Features

- Anthropic-compatible local endpoints for Claude Desktop / Claude Code
- Model discovery via `GET /v1/models`
- Model name rewriting before upstream forwarding
- Forced `effort=max`
- Redacted JSON Lines logs
- No prompt logging
- No API key logging
- Pure Python standard library implementation

## Quick Start

Set your upstream endpoint and DeepSeek API key:

```bash
export GATEWAY_UPSTREAM_BASE_URL="https://api.deepseek.com/anthropic"
export GATEWAY_UPSTREAM_API_KEY="YOUR_DEEPSEEK_API_KEY"
```

Check the config:

```bash
python3 server.py --check-config
```

Start the gateway:

```bash
python3 server.py
```

By default it listens on:

```text
http://127.0.0.1:8088
```

Health check:

```bash
curl http://127.0.0.1:8088/health
```

Expected:

```json
{"status":"ok"}
```

## Claude Desktop Config

Point your Claude Desktop 3P / gateway config at the local server:

```json
{
  "inferenceProvider": "gateway",
  "inferenceGatewayBaseUrl": "http://127.0.0.1:8088",
  "inferenceGatewayApiKey": "local-placeholder-key",
  "inferenceGatewayAuthScheme": "bearer",
  "inferenceModels": [
    {
      "name": "claude-opus-4-7",
      "supports1m": true
    },
    {
      "name": "claude-sonnet-4-5"
    },
    {
      "name": "claude-haiku-4-5-20251001"
    }
  ]
}
```

The gateway ignores the client-side placeholder key when forwarding upstream. It uses `GATEWAY_UPSTREAM_API_KEY` for DeepSeek.

## Environment Variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `GATEWAY_UPSTREAM_BASE_URL` | Yes | none | DeepSeek Anthropic-compatible base URL |
| `GATEWAY_UPSTREAM_API_KEY` | Yes | none | DeepSeek API key |
| `GATEWAY_LISTEN_HOST` | No | `127.0.0.1` | Local bind host |
| `GATEWAY_LISTEN_PORT` | No | `8088` | Local bind port |
| `GATEWAY_UPSTREAM_TIMEOUT_SECONDS` | No | `30` | Upstream timeout |
| `GATEWAY_FORCE_EFFORT` | No | `max` | Value written into request body |
| `GATEWAY_MODEL_MAP_JSON` | No | built-in map | Extra or overriding model map entries |
| `GATEWAY_LOG_FILE` | No | `~/Library/Logs/Claude-3p/deepseek-gateway.log` | Redacted gateway log path |

Example custom model map:

```bash
export GATEWAY_MODEL_MAP_JSON='{"my-claude-route":"deepseek-v4-flash"}'
```

## Logs

Tail the live gateway log:

```bash
tail -f "$HOME/Library/Logs/Claude-3p/deepseek-gateway.log"
```

Example request-end event:

```json
{"ts":"2026-05-06T04:55:20.123Z","event":"request_end","request_id":"...","method":"POST","path":"/v1/messages","status":200,"duration_ms":6123,"client_model":"claude-opus-4-7","upstream_model":"deepseek-v4-pro[1m]","forced_effort":"max"}
```

The log records:

- HTTP method and path
- Claude-facing model name
- DeepSeek upstream model name
- Forced effort value
- Response status
- Duration in milliseconds
- Error category and upstream error, when available

The log does not record:

- User prompts
- Message content
- API keys
- Authorization headers

## Supported Endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/health` | Local health check |
| `GET` | `/v1/models` | Returns Claude-facing model IDs |
| `POST` | `/v1/messages` | Rewrites model and forwards upstream |
| `POST` | `/v1/messages/count_tokens` | Rewrites model and forwards upstream |

## Troubleshooting

### Claude spins forever

Check whether the gateway is alive:

```bash
curl http://127.0.0.1:8088/health
```

Then watch both logs:

```bash
tail -f "$HOME/Library/Logs/Claude-3p/deepseek-gateway.log"
tail -f "$HOME/Library/Logs/Claude-3p/main.log"
```

### DeepSeek does not show any request

Look for a gateway error before blaming the upstream provider. A common local failure is Python TLS verification:

```text
CERTIFICATE_VERIFY_FAILED
```

If `curl https://api.deepseek.com` works but Python fails, your Python CA bundle may need to be installed or refreshed.

### Claude says it is Opus

Expected. The client-facing model route is Claude-like by design. The upstream model used by DeepSeek is visible in the gateway log as `upstream_model`.

## Security Notes

- Bind to `127.0.0.1` unless you know exactly why you need another host.
- Do not commit real API keys.
- Keep `GATEWAY_UPSTREAM_API_KEY` in your shell environment or a local ignored env file.
- The default logger is intentionally redacted.

## Tests

Run:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover:

- Model discovery
- Query-string handling for `/v1/models`
- Model rewriting
- Family defaults for `opus`, `sonnet`, and `haiku`
- `effort=max`
- Upstream authorization forwarding
- Unsupported model rejection
- Redacted logging

## Limitations

- This is a focused local gateway, not a general-purpose reverse proxy.
- It only handles the endpoints listed above.
- SSE streaming passthrough has not been deeply optimized yet.
- There is no built-in auth or ACL layer. Localhost is the intended boundary.

## License

No license has been selected yet. Treat this as all rights reserved until a license file is added.
