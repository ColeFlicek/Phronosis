"""Read/write ~/.config/scopenos/config.toml and generate .mcp.json files."""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import tomli_w

CONFIG_DIR = Path(os.environ.get("SCOPENOS_CONFIG_DIR", Path.home() / ".config" / "scopenos"))
CONFIG_FILE = CONFIG_DIR / "config.toml"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with CONFIG_FILE.open("rb") as f:
        return tomllib.load(f)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("wb") as f:
        tomli_w.dump(config, f)
    CONFIG_FILE.chmod(0o600)


def get_server_url() -> str:
    return load_config().get("server", {}).get("url", "")


def get_api_key() -> str:
    return load_config().get("auth", {}).get("api_key", "")


def write_mcp_json(directory: Path | None = None) -> Path:
    """Write .mcp.json for the given directory (default: cwd) from stored config."""
    config = load_config()
    server_url = config.get("server", {}).get("url", "")
    api_key = config.get("auth", {}).get("api_key", "")
    if not server_url or not api_key:
        raise RuntimeError("No config found. Run: scopenos auth init --server <URL>")

    out_dir = Path(directory) if directory else Path.cwd()
    mcp_path = out_dir / ".mcp.json"
    payload = {
        "mcpServers": {
            "scopenos": {
                "type": "http",
                "url": server_url,
                "headers": {"X-API-Key": api_key},
            }
        }
    }
    mcp_path.write_text(json.dumps(payload, indent=2) + "\n")
    return mcp_path
