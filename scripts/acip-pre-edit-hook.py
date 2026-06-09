#!/usr/bin/env python3
"""
PreToolUse hook — ACIP workflow enforcement.

Fires on: Bash (grep), Read (source files), Edit (source files)

Bash/Read: nudge toward ACIP tools instead of file exploration.
Edit: check project home for risk signals on the file being edited.
      If the file contains chokepoints or risk-surface functions,
      print a specific warning and the three pre-edit checks to run.
      Silent if no risk signals — only loud when it matters.

Always exits 0 (non-blocking). Never fails a tool call.
"""
import json
import os
import re
import sys
import urllib.request

ACIP_URL = os.environ.get("ACIP_URL", "http://100.71.88.106:3004")
TIMEOUT = 3  # seconds — fast fail, never slow down the agent


def _project_id() -> str:
    """Resolve project ID from env, git remote, or repo dirname."""
    pid = os.environ.get("ACIP_PROJECT", "")
    if pid:
        return pid
    try:
        import subprocess
        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL, timeout=2
        ).decode().strip()
        return re.sub(r"\.git$", "", remote).split("/")[-1].split(":")[-1]
    except Exception:
        pass
    try:
        import subprocess
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=2
        ).decode().strip()
        return os.path.basename(root)
    except Exception:
        return ""


def _get_project_home(project_id: str) -> dict:
    """Fetch the ACIP project home snapshot; returns empty dict on any error."""
    try:
        safe = urllib.request.quote(project_id, safe="")
        url = f"{ACIP_URL}/api/project-home/{safe}"
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _file_to_module(file_path: str) -> str:
    """Convert src/call_graph/storage.py -> src.call_graph.storage"""
    p = file_path
    for ext in (".py", ".ts", ".tsx"):
        if p.endswith(ext):
            p = p[: -len(ext)]
    return p.replace("/", ".").lstrip(".")


try:
    data = json.loads(sys.stdin.read())
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {})

    # ── Bash: nudge on grep against source files ──────────────────────────
    if tool == "Bash":
        cmd = inp.get("command", "")
        if (
            re.search(r"\bgrep\b", cmd)
            and re.search(r"\.(py|ts|tsx)", cmd)
            and not re.search(r"\b(git|pytest|rtk|ruff|mypy|test)\b", cmd)
        ):
            print(
                "[ACIP] grep on source — MCP is faster and cross-file:\n"
                "  get_callers(fn) · get_callees(fn) · query_similar_functions(snippet)"
            )

    # ── Read: nudge on source file reads ─────────────────────────────────
    elif tool == "Read":
        path = inp.get("file_path", "")
        if re.search(r"\.(py|ts|tsx)$", path) and "/scripts/" not in path:
            print(
                "[ACIP] Reading source — if exploring structure, MCP is faster:\n"
                "  get_impact_radius(fn) · get_decision_history(fn) · get_callers(fn)"
            )

    # ── Edit: risk-signal check before modifying source ───────────────────
    elif tool == "Edit":
        path = inp.get("file_path", "")
        if not re.search(r"\.(py|ts|tsx)$", path):
            sys.exit(0)

        module = _file_to_module(path)
        project_id = _project_id()
        if not project_id:
            sys.exit(0)

        home = _get_project_home(project_id)
        if not home:
            # ACIP unreachable — silent pass, never block
            sys.exit(0)

        warnings = []

        for cp in home.get("chokepoints", []):
            fid = cp.get("id", "")
            if module and (module in fid or fid.startswith(module)):
                warnings.append(
                    f"  CHOKEPOINT  {'.'.join(fid.split('.')[-2:])}  "
                    f"({cp['caller_count']} callers — signature changes break everything depending on it)"
                )

        for rs in home.get("risk_surface", []):
            fid = rs.get("id", "")
            if module and (module in fid or fid.startswith(module)):
                warnings.append(
                    f"  RISK SURFACE  {'.'.join(fid.split('.')[-2:])}  "
                    f"({rs['churn']} patches · {rs['caller_count']} callers — high-churn AND high-impact)"
                )

        if warnings:
            print(f"[ACIP] High-risk edit in {os.path.basename(path)}:")
            for w in warnings:
                print(w)
            print("  Before editing, run:")
            print("  1. get_impact_radius(fn, depth=2)        — what breaks?")
            print("  2. get_decision_history(fn)              — why was this designed this way?")
            print("  3. query_similar_functions(snippet)      — what is the existing pattern?")
        else:
            fn_hint = module.split(".")[-1] if module else "fn"
            print(
                f"[ACIP] Pre-edit: get_impact_radius({fn_hint}) · "
                f"get_decision_history({fn_hint}) · "
                f"query_similar_functions(snippet)"
            )

except Exception:
    pass  # Never block Claude on hook error

sys.exit(0)
