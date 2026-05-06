#!/usr/bin/env python3
import argparse
import json
import sys

from gateway import GatewayConfig, run_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local Anthropic-compatible model mapping gateway for DeepSeek."
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment configuration and exit without starting the server.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = GatewayConfig.from_env()
    except (ValueError, json.JSONDecodeError) as exc:  # type: ignore[name-defined]
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print("Configuration OK")
        print(f"Listen: http://{config.listen_host}:{config.listen_port}")
        print(f"Upstream: {config.upstream_base_url}")
        print(f"Forced effort: {config.forced_effort}")
        print("Routes:")
        for route, upstream in config.model_map.items():
            print(f"  {route} -> {upstream}")
        return 0

    run_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
