#!/usr/bin/env bash
# Post-commit git hook — re-indexes changed files and logs the decision to ACIP.
# Install: cp scripts/post-commit.sh .git/hooks/post-commit && chmod +x .git/hooks/post-commit

set -euo pipefail

ACIP_URL="${ACIP_URL:-http://localhost:3004}"

CHANGED=$(git diff-tree --no-commit-id -r --name-only HEAD 2>/dev/null || true)

if [ -z "$CHANGED" ]; then
  exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel)

# ── Re-index changed files ──────────────────────────────────────────────────────

FILES_JSON=$(echo "$CHANGED" | while IFS= read -r f; do
  [ -n "$f" ] && echo "\"${REPO_ROOT}/${f}\""
done | paste -sd ',' - | sed 's/^/[/' | sed 's/$/]/')

curl --silent --show-error --max-time 30 \
  -X POST "${ACIP_URL}/index" \
  -H "Content-Type: application/json" \
  -d "{\"changed_files\": ${FILES_JSON}, \"project_root\": \"${REPO_ROOT}\"}" \
  > /dev/null

echo "[acip] index_changes triggered for $(echo "$CHANGED" | wc -l | tr -d ' ') files"

# ── Log decision ────────────────────────────────────────────────────────────────

python3 - <<'PYEOF'
import json, os, subprocess, sys
try:
    from urllib.request import urlopen, Request as UReq

    acip_url = os.environ.get("ACIP_URL", "http://localhost:3004")

    msg   = subprocess.check_output(["git", "log", "-1", "--format=%s"]).decode().strip()
    body  = subprocess.check_output(["git", "log", "-1", "--format=%b"]).decode().strip()
    hash_ = subprocess.check_output(["git", "log", "-1", "--format=%H"]).decode().strip()
    changed = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"]
    ).decode().strip().splitlines()
    diff_stat = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "-r", "--stat", "HEAD"]
    ).decode().strip()

    low = msg.lower()
    if low.startswith(("fix", "bug", "patch", "hotfix", "revert")):
        type_ = "Patch"
    elif low.startswith(("add", "feat", "impl", "build", "create", "new", "support")):
        type_ = "Implementation"
    elif low.startswith(("refactor", "redesign", "move", "extract", "restructure", "rename", "clean")):
        type_ = "Design"
    elif low.startswith(("arch",)):
        type_ = "Architectural"
    else:
        type_ = "Patch"

    # Build description: commit message + body + diff stat so get_decision_history
    # answers "what changed" without requiring a separate git show.
    parts = [msg]
    if body:
        parts.append(body)
    parts.append(f"Changes:\n{diff_stat}")
    description = " — ".join(parts)

    # Resolve changed files → actual indexed function IDs via the ACIP API.
    # Falls back to module-path approximation if the server can't be reached.
    repo_root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip()
    abs_files = [f"{repo_root}/{f}" for f in changed if f.endswith((".py", ".ts", ".tsx"))]
    linked = None
    if abs_files:
        try:
            fn_req = UReq(
                f"{acip_url}/api/functions",
                data=json.dumps({"files": abs_files}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(fn_req, timeout=5) as r:
                fn_resp = json.loads(r.read())
            linked = fn_resp.get("function_ids") or None
        except Exception:
            # Server unreachable — fall back to module paths so the decision
            # is still logged, just without per-function granularity.
            linked = [f.replace("/", ".").removesuffix(".py") for f in changed
                      if f.endswith((".py", ".ts", ".tsx"))] or None

    payload = json.dumps({
        "type": type_,
        "description": description,
        "trigger": f"git:{hash_[:8]}",
        "linked_function_ids": linked,
    }).encode()

    req = UReq(
        f"{acip_url}/api/decisions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    print(f"[acip] decision logged ({type_}): {resp.get('decision_id', '')[:8]}")
except Exception as e:
    print(f"[acip] decision log skipped: {e}", file=sys.stderr)
PYEOF
