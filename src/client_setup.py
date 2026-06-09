"""
ACIP client setup — generates the self-contained Python script that configures
a user's machine and project to work with ACIP.

Called by the setup_acip_client MCP tool. The returned script writes all
required files (hook, settings.json merge, CLAUDE.md, memory files, git hook)
and requires no manual steps beyond running it.
"""
from __future__ import annotations

import os

# ── Template: Claude Code pre-edit hook ───────────────────────────────────────
# Installed to ~/.claude/hooks/acip-suggest.py
_HOOK_SCRIPT = r'''#!/usr/bin/env python3
"""ACIP PreToolUse hook — risk checks on Edit, nudges on Bash/Read."""
import json, os, re, sys, urllib.request

ACIP_URL = os.environ.get("ACIP_URL", "{acip_url}")
TIMEOUT = 3

def _project_id():
    pid = os.environ.get("ACIP_PROJECT", "")
    if pid: return pid
    try:
        import subprocess
        remote = subprocess.check_output(["git","remote","get-url","origin"],
            stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        return re.sub(r"\.git$","",remote).split("/")[-1].split(":")[-1]
    except Exception: pass
    try:
        import subprocess
        root = subprocess.check_output(["git","rev-parse","--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        return os.path.basename(root)
    except Exception: return ""

def _project_home(pid):
    try:
        url = f"{ACIP_URL}/api/project-home/{urllib.request.quote(pid,safe='')}"
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception: return {}

def _module(path):
    p = path
    for ext in (".py",".ts",".tsx"):
        if p.endswith(ext): p = p[:-len(ext)]
    return p.replace("/",".").lstrip(".")

try:
    data = json.loads(sys.stdin.read())
    tool = data.get("tool_name","")
    inp  = data.get("tool_input",{})

    if tool == "Bash":
        cmd = inp.get("command","")
        if (re.search(r"\bgrep\b",cmd) and re.search(r"\.(py|ts|tsx)",cmd)
                and not re.search(r"\b(git|pytest|rtk|ruff|mypy|test)\b",cmd)):
            print("[ACIP] grep on source — MCP is faster:\n"
                  "  get_callers(fn) · get_callees(fn) · query_similar_functions(snippet)")

    elif tool == "Read":
        path = inp.get("file_path","")
        if re.search(r"\.(py|ts|tsx)$",path) and "/scripts/" not in path:
            print("[ACIP] Reading source — if exploring structure, MCP is faster:\n"
                  "  get_impact_radius(fn) · get_decision_history(fn) · get_callers(fn)")

    elif tool == "Edit":
        path = inp.get("file_path","")
        if not re.search(r"\.(py|ts|tsx)$",path): sys.exit(0)
        mod = _module(path)
        pid = _project_id()
        if not pid: sys.exit(0)
        home = _project_home(pid)
        if not home: sys.exit(0)
        warnings = []
        for cp in home.get("chokepoints",[]):
            fid = cp.get("id","")
            if mod and (mod in fid or fid.startswith(mod)):
                warnings.append(f"  CHOKEPOINT  {'.'.join(fid.split('.')[-2:])}  ({cp['caller_count']} callers)")
        for rs in home.get("risk_surface",[]):
            fid = rs.get("id","")
            if mod and (mod in fid or fid.startswith(mod)):
                warnings.append(f"  RISK SURFACE  {'.'.join(fid.split('.')[-2:])}  ({rs['churn']} patches · {rs['caller_count']} callers)")
        if warnings:
            print(f"[ACIP] High-risk edit in {os.path.basename(path)}:")
            for w in warnings: print(w)
            print("  1. get_impact_radius(fn, depth=2)     — what breaks?")
            print("  2. get_decision_history(fn)           — why was this designed this way?")
            print("  3. query_similar_functions(snippet)   — what is the existing pattern?")
        else:
            fn = mod.split(".")[-1] if mod else "fn"
            print(f"[ACIP] Pre-edit: get_impact_radius({fn}) · get_decision_history({fn}) · query_similar_functions(snippet)")
except Exception: pass
sys.exit(0)
'''

# ── Template: project CLAUDE.md ───────────────────────────────────────────────
# Written to <project_root>/CLAUDE.md (appended if file exists)
_CLIENT_CLAUDE_MD = """\
# ACIP Workflow

This project is indexed in ACIP at `{acip_url}` (project: `{project_id}`).
Follow this three-tier retrieval ladder every session.

## Session start — build the map first

**Tier 1** (one call, ~500 tokens, full architectural picture):
```
get_project_home("{project_id}")
```
Returns subsystems, wiring, chokepoints, entry points, risk surface, contracts,
recent decisions. This replaces reading files to understand architecture.

**Tier 2** (targeted queries for the specific task):
```
query_similar_functions("<feature>", top_k=8)
get_impact_radius("<function>", depth=2)
get_decision_history("<function>")
```

**Tier 3** (file reads — precision only):
```
Read(file)   # only for exact implementation of the function you are about to modify
```

## Pre-edit gate (before every Edit on an existing function)

1. `get_impact_radius(fn, depth=2)` — what breaks?
2. `get_decision_history(fn)` — why was this designed this way?
3. `query_similar_functions(what_you_are_about_to_write)` — existing pattern?

In multi-agent contexts: step 2 also reveals whether a concurrent agent
recently modified this function. Run it even on functions you wrote yourself.

## After edits

```
index_changes(["file.py"], {{"file.py": "<content>"}})
```

## Session end

```
log_decision(type, description, trigger, linked_function_ids)
```

Log immediately after significant decisions — not only at session end.
Concurrent agents read this before touching the same code.
"""

# ── Template: memory feedback file ───────────────────────────────────────────
# Written to ~/.claude/projects/<project>/memory/feedback_acip_workflow.md
_MEMORY_FEEDBACK = """\
---
name: feedback-acip-workflow
description: "ACIP workflow rules for {project_id}: three-tier retrieval, pre-edit gate, immediate decision logging."
metadata:
  type: feedback
---

Use the three-tier retrieval ladder on every session for project `{project_id}`:
1. get_project_home("{project_id}") — architectural map before any implementation
2. query_similar_functions / get_impact_radius / get_decision_history — specific function context
3. Read() — only for exact implementation of what you're about to modify

Pre-edit gate before every Edit: impact radius → decision history → structural consistency check.

log_decision() immediately after significant choices (not just at session end).
Concurrent agents read it before touching the same code.

**Why:** file reads for architectural understanding waste tokens and miss cross-file context.
ACIP queries are more information-dense. [[feedback-acip-comprehension]]
"""

_MEMORY_INDEX = """\
# ACIP Memory Index

- [ACIP workflow](feedback_acip_workflow.md) — three-tier retrieval, pre-edit gate, immediate decision logging
"""

# ── Setup script generator ─────────────────────────────────────────────────────

def generate_setup_script(
    project_root: str,
    acip_url: str,
    project_id: str,
    claude_home: str,
    install_git_hook: bool,
    post_commit_content: str,
) -> str:
    """
    Generate a self-contained Python script that configures a machine and project
    to work with ACIP. The caller executes this script via Bash.
    """
    hook_content = _HOOK_SCRIPT.replace("{acip_url}", acip_url)
    claude_md = _CLIENT_CLAUDE_MD.replace("{acip_url}", acip_url).replace("{project_id}", project_id)
    mem_feedback = _MEMORY_FEEDBACK.replace("{project_id}", project_id)

    # Memory dir path: ~/.claude/projects/<project-root-with-slashes-as-dashes>/memory
    mem_path_key = project_root.replace("/", "-").lstrip("-")

    settings_hook_entry = {
        "matcher": "Edit",
        "hooks": [{"type": "command", "command": f"python3 {claude_home}/hooks/acip-suggest.py"}]
    }
    bash_hook_entry = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": f"python3 {claude_home}/hooks/acip-suggest.py"}]
    }
    read_hook_entry = {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": f"python3 {claude_home}/hooks/acip-suggest.py"}]
    }

    import json as _json
    settings_entries = _json.dumps(
        [bash_hook_entry, read_hook_entry, settings_hook_entry], indent=4
    )

    git_hook_block = ""
    if install_git_hook:
        escaped = post_commit_content.replace("\\", "\\\\").replace("'", "\\'")
        git_hook_block = f"""
# ── Git post-commit hook ──────────────────────────────────────────
git_hooks_dir = pathlib.Path("{project_root}") / ".git" / "hooks"
if git_hooks_dir.exists():
    post_commit = git_hooks_dir / "post-commit"
    post_commit.write_text({repr(post_commit_content)})
    post_commit.chmod(post_commit.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    results.append(f"  git hook     {{post_commit}}")
else:
    results.append("  git hook     SKIPPED (no .git/hooks found)")
"""

    script = f'''#!/usr/bin/env python3
"""ACIP client setup — generated by setup_acip_client().  Run once per machine/project."""
import json, os, pathlib, re, stat, sys

PROJECT_ROOT = "{project_root}"
ACIP_URL     = "{acip_url}"
PROJECT_ID   = "{project_id}"
CLAUDE_HOME  = "{claude_home}"
MEM_KEY      = "{mem_path_key}"

results = []

# ── Pre-edit hook ──────────────────────────────────────────────────
hooks_dir = pathlib.Path(CLAUDE_HOME) / "hooks"
hooks_dir.mkdir(parents=True, exist_ok=True)
hook_path = hooks_dir / "acip-suggest.py"
hook_path.write_text({repr(hook_content)})
hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
results.append(f"  hook         {{hook_path}}")

# ── settings.json — merge hook entries ────────────────────────────
settings_path = pathlib.Path(CLAUDE_HOME) / "settings.json"
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {{}}
new_hooks = {settings_entries}

existing_hooks = settings.setdefault("hooks", {{}}).setdefault("PreToolUse", [])
existing_matchers = {{h["matcher"] for h in existing_hooks}}
for entry in new_hooks:
    if entry["matcher"] not in existing_matchers:
        existing_hooks.append(entry)
settings_path.write_text(json.dumps(settings, indent=2))
results.append(f"  settings     {{settings_path}}")

# ── Project CLAUDE.md ──────────────────────────────────────────────
claude_md_path = pathlib.Path(PROJECT_ROOT) / "CLAUDE.md"
acip_section = {repr(claude_md)}
if claude_md_path.exists():
    existing = claude_md_path.read_text()
    if "# ACIP Workflow" not in existing:
        claude_md_path.write_text(existing.rstrip() + "\\n\\n" + acip_section)
        results.append(f"  CLAUDE.md    {{claude_md_path}} (ACIP section appended)")
    else:
        results.append(f"  CLAUDE.md    {{claude_md_path}} (already has ACIP section, skipped)")
else:
    claude_md_path.write_text(acip_section)
    results.append(f"  CLAUDE.md    {{claude_md_path}} (created)")

# ── Memory files ───────────────────────────────────────────────────
mem_dir = pathlib.Path(CLAUDE_HOME) / "projects" / MEM_KEY / "memory"
mem_dir.mkdir(parents=True, exist_ok=True)
(mem_dir / "feedback_acip_workflow.md").write_text({repr(mem_feedback)})
mem_index = mem_dir / "MEMORY.md"
if not mem_index.exists():
    mem_index.write_text({repr(_MEMORY_INDEX)})
results.append(f"  memory       {{mem_dir}}")

{git_hook_block}

# ── Done ───────────────────────────────────────────────────────────
print("\\nACIP setup complete for project:", PROJECT_ID)
print("Server:", ACIP_URL)
print("\\nFiles written:")
for r in results: print(r)
print("\\nNext: restart Claude Code to activate the hooks.")
print("Then run: index_project(\\"" + PROJECT_ROOT + "\\") to index the codebase.")
'''
    return script


def _default_claude_home() -> str:
    return os.path.expanduser("~/.claude")
