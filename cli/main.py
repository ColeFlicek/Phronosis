"""Scopenos CLI — manage API keys and MCP configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx
import typer

from . import config as cfg

app = typer.Typer(
    help="Scopenos CLI — manage API keys and MCP configuration.",
    no_args_is_help=True,
)
auth_app = typer.Typer(help="Manage API keys.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


# ── auth init ─────────────────────────────────────────────────────────────────

@auth_app.command("init")
def auth_init(
    server: str = typer.Option(..., "--server", "-s", help="Scopenos server URL, e.g. http://host:3004"),
    email: str = typer.Option(..., "--email", "-e", prompt="Your email"),
    name: str = typer.Option("primary", "--name", "-n", help="Name for this key"),
    write_mcp: bool = typer.Option(True, "--mcp/--no-mcp", help="Write .mcp.json in current directory"),
) -> None:
    """First-time setup: create user + API key on a fresh server."""
    server = server.rstrip("/")
    try:
        resp = httpx.post(
            f"{server}/setup",
            json={"email": email, "name": name},
            timeout=10,
        )
    except httpx.ConnectError:
        typer.secho(f"Cannot connect to {server}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if resp.status_code == 409:
        typer.secho(
            "Server already has users. To add a key, use: scopenos auth rotate",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(1)
    if resp.status_code != 200:
        typer.secho(f"Error {resp.status_code}: {resp.text}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    data = resp.json()
    conf = cfg.load_config()
    conf.setdefault("server", {})["url"] = server
    conf.setdefault("auth", {})["api_key"] = data["key"]
    conf["auth"]["email"] = email
    cfg.save_config(conf)
    typer.secho(f"✓ Config saved: {cfg.CONFIG_FILE}", fg=typer.colors.GREEN)

    if write_mcp:
        mcp_path = cfg.write_mcp_json()
        typer.secho(f"✓ .mcp.json written: {mcp_path}", fg=typer.colors.GREEN)

    typer.secho("\nRestart Claude Code to pick up the new MCP config.", fg=typer.colors.YELLOW)


# ── auth rotate ───────────────────────────────────────────────────────────────

@auth_app.command("rotate")
def auth_rotate(
    name: str = typer.Option("rotated", "--name", "-n", help="Name for the new key"),
    keep_old: bool = typer.Option(False, "--keep-old", help="Issue new key without revoking the current one"),
    write_mcp: bool = typer.Option(True, "--mcp/--no-mcp", help="Update .mcp.json if present in cwd"),
) -> None:
    """Create a new API key (and revoke the current one by default)."""
    server = cfg.get_server_url()
    key = cfg.get_api_key()
    if not server or not key:
        typer.secho("No config found. Run: scopenos auth init --server <URL>", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        resp = httpx.post(
            f"{server}/api/auth/keys",
            json={"name": name, "revoke_current": not keep_old},
            headers={"X-API-Key": key},
            timeout=10,
        )
    except httpx.ConnectError:
        typer.secho(f"Cannot connect to {server}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if resp.status_code != 200:
        typer.secho(f"Error {resp.status_code}: {resp.text}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    data = resp.json()
    conf = cfg.load_config()
    conf.setdefault("auth", {})["api_key"] = data["key"]
    cfg.save_config(conf)
    typer.secho("✓ New key saved to config", fg=typer.colors.GREEN)

    if data.get("revoked_id"):
        typer.secho(f"✓ Revoked old key: {data['revoked_id']}", fg=typer.colors.GREEN)

    if write_mcp and Path(".mcp.json").exists():
        cfg.write_mcp_json()
        typer.secho("✓ .mcp.json updated", fg=typer.colors.GREEN)

    typer.secho("\nRestart Claude Code to pick up the new key.", fg=typer.colors.YELLOW)


# ── auth list ─────────────────────────────────────────────────────────────────

@auth_app.command("list")
def auth_list() -> None:
    """List your active API keys."""
    server = cfg.get_server_url()
    key = cfg.get_api_key()
    if not server or not key:
        typer.secho("No config found. Run: scopenos auth init --server <URL>", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        resp = httpx.get(f"{server}/api/auth/keys", headers={"X-API-Key": key}, timeout=10)
    except httpx.ConnectError:
        typer.secho(f"Cannot connect to {server}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if resp.status_code != 200:
        typer.secho(f"Error {resp.status_code}: {resp.text}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    keys = resp.json().get("keys", [])
    if not keys:
        typer.echo("No active keys.")
        return

    typer.echo(f"{'ID':<38}  {'NAME':<20}  {'CREATED':<20}  LAST USED")
    typer.echo("─" * 96)
    for k in keys:
        last = (k.get("last_used") or "never")[:19]
        typer.echo(f"{k['id']:<38}  {k['name']:<20}  {k['created_at'][:19]:<20}  {last}")


# ── auth revoke ───────────────────────────────────────────────────────────────

@auth_app.command("revoke")
def auth_revoke(
    key_id: str = typer.Argument(help="Key ID to revoke (from: scopenos auth list)"),
) -> None:
    """Revoke a specific API key by ID."""
    server = cfg.get_server_url()
    key = cfg.get_api_key()
    if not server or not key:
        typer.secho("No config found. Run: scopenos auth init --server <URL>", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        resp = httpx.delete(
            f"{server}/api/auth/keys/{key_id}",
            headers={"X-API-Key": key},
            timeout=10,
        )
    except httpx.ConnectError:
        typer.secho(f"Cannot connect to {server}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if resp.status_code == 404:
        typer.secho("Key not found or already revoked.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)
    if resp.status_code != 200:
        typer.secho(f"Error {resp.status_code}: {resp.text}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho(f"✓ Revoked: {key_id}", fg=typer.colors.GREEN)


# ── mcp-config ────────────────────────────────────────────────────────────────

@app.command("mcp-config")
def mcp_config(
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Directory to write .mcp.json (default: cwd)"
    ),
) -> None:
    """Write (or overwrite) .mcp.json from stored config."""
    try:
        mcp_path = cfg.write_mcp_json(directory)
        typer.secho(f"✓ Written: {mcp_path}", fg=typer.colors.GREEN)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
