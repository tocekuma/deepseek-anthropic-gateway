# DeepSeek Anthropic Mapping Gateway

本地小代理，用来给 Claude Desktop 提供一个 Anthropic-compatible 入口，再把模型映射到 DeepSeek。

## 作用

- Claude Desktop 看到 `claude-opus-4-7` 和 `claude-sonnet-4-5`
- 代理把 `claude-opus-4-7` 改写成 `deepseek-v4-pro[1m]`
- 代理也接受 Claude Code 自动追加的 `claude-opus-4-7[1m]`
- 代理把 `claude-sonnet-4-5` 改写成 `deepseek-v4-flash`
- 代理强制把请求体里的 `effort` 设为 `max`
- 再转发到 DeepSeek 的 Anthropic 兼容接口

## 环境变量

- `GATEWAY_UPSTREAM_BASE_URL`：DeepSeek Anthropic endpoint，例如 `https://api.deepseek.com/anthropic`
- `GATEWAY_UPSTREAM_API_KEY`：DeepSeek API key
- `GATEWAY_LISTEN_HOST`：默认 `127.0.0.1`
- `GATEWAY_LISTEN_PORT`：默认 `8088`
- `GATEWAY_UPSTREAM_TIMEOUT_SECONDS`：默认 `30`
- `GATEWAY_FORCE_EFFORT`：默认 `max`
- `GATEWAY_MODEL_MAP_JSON`：可选，自定义模型映射 JSON
- `GATEWAY_LOG_FILE`：可选，默认 `~/Library/Logs/Claude-3p/deepseek-gateway.log`

## 启动

```bash
export GATEWAY_UPSTREAM_BASE_URL="https://api.deepseek.com/anthropic"
export GATEWAY_UPSTREAM_API_KEY="***"
python3 tools/deepseek-anthropic-gateway/server.py
```

先检查配置：

```bash
python3 tools/deepseek-anthropic-gateway/server.py --check-config
```

## 日志

gateway 会写 JSON Lines 格式的脱敏日志，默认位置：

```bash
tail -f "$HOME/Library/Logs/Claude-3p/deepseek-gateway.log"
```

每条请求会记录：

- `method` / `path`
- `client_model` / `upstream_model`
- `forced_effort`
- `status`
- `duration_ms`
- `error` / `upstream_error`

日志不会记录 API key，也不会记录用户 prompt 内容。

## Claude Desktop 侧配置思路

把 Claude Desktop 里 3P / gateway 的 base URL 指到本地代理：

```json
{
  "inferenceProvider": "gateway",
  "inferenceGatewayBaseUrl": "http://127.0.0.1:8088",
  "inferenceModels": [
    { "name": "claude-opus-4-7", "supports1m": true },
    { "name": "claude-sonnet-4-5" }
  ]
}
```

## 当前支持

- `GET /health`
- `GET /v1/models`
- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

## 限制

- 这是最小代理，只处理你当前需要的路径
- 未实现 SSE 流式转发的特殊边界测试
- 未做认证/ACL，默认只建议本机监听
