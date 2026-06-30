#!/usr/bin/env bash
# Post-commit git hook — re-indexes changed files and logs the decision to Scopenos.
# Install: cp scripts/post-commit.sh .git/hooks/post-commit && chmod +x .git/hooks/post-commit

set -euo pipefail

SCOPENOS_URL="${SCOPENOS_URL:-http://100.71.88.106:3004}"
# API key resolution order: env var → git config → empty (will 401)
SCOPENOS_API_KEY="${SCOPENOS_API_KEY:-$(git config --get scopenos.apikey 2>/dev/null || true)}"

CHANGED=$(git diff-tree --no-commit-id -r --name-only HEAD 2>/dev/null || true)

if [ -z "$CHANGED" ]; then
  exit 0
fi

REPO_ROOT=$(git rev-parse --show-toplevel)

# Derive project_id: prefer SCOPENOS_PROJECT env var, then git remote basename, then dirname.
if [ -n "${SCOPENOS_PROJECT:-}" ]; then
  PROJECT_ID="$SCOPENOS_PROJECT"
else
  REMOTE_URL=$(git remote get-url origin 2>/dev/null || true)
  if [ -n "$REMOTE_URL" ]; then
    # Strip trailing .git, take last path segment
    PROJECT_ID=$(echo "$REMOTE_URL" | sed 's/\.git$//' | sed 's|.*[/:]||')
  else
    PROJECT_ID=$(basename "$REPO_ROOT")
  fi
fi

# ── Re-index ────────────────────────────────────────────────────────────────────
# If the parser itself changed, all previously indexed files have stale metadata
# (e.g. new columns like start_line/return_type were added). In that case, re-index
# every source file instead of just the diff.
#
# Add paths to FULL_REINDEX_TRIGGERS to extend the list of files that trigger this.

FULL_REINDEX_TRIGGERS="src/call_graph/parser.py"
NEEDS_FULL_REINDEX=false

for _trigger in $FULL_REINDEX_TRIGGERS; do
  if echo "$CHANGED" | grep -qF "$_trigger"; then
    NEEDS_FULL_REINDEX=true
    echo "[scopenos] $( echo "$_trigger" | xargs basename ) changed — triggering full re-index"
    break
  fi
done

if [ "$NEEDS_FULL_REINDEX" = "true" ]; then
  SCOPENOS_URL="$SCOPENOS_URL" SCOPENOS_PROJECT_ID="$PROJECT_ID" REPO_ROOT="$REPO_ROOT" python3 - <<'PYEOF'
import glob, json, os, sys
from urllib.request import urlopen, Request as UReq

url       = os.environ.get("SCOPENOS_URL", "http://100.71.88.106:3004")
project   = os.environ.get("SCOPENOS_PROJECT_ID", "default")
root      = os.environ.get("REPO_ROOT", "")
src_files = glob.glob(f"{root}/src/**/*.py", recursive=True)

BATCH, total_fns = 10, 0
for i in range(0, len(src_files), BATCH):
    files = {}
    for fp in src_files[i:i + BATCH]:
        try:
            files[fp] = open(fp, encoding="utf-8", errors="replace").read()
        except Exception:
            pass
    if not files:
        continue
    payload = json.dumps({"project_root": root, "project_id": project, "files": files}).encode()
    req = UReq(f"{url}/api/index-bulk", data=payload,
               headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=60) as r:
            total_fns += json.loads(r.read()).get("functions_updated", 0)
    except Exception as e:
        print(f"[scopenos] batch failed: {e}", file=sys.stderr)

print(f"[scopenos] full re-index: {len(src_files)} files, {total_fns} functions updated")
PYEOF
else
  FILES_JSON=$(echo "$CHANGED" | while IFS= read -r f; do
    [ -n "$f" ] && echo "\"${REPO_ROOT}/${f}\""
  done | paste -sd ',' - | sed 's/^/[/' | sed 's/$/]/')

  INDEX_HTTP=$(curl --silent --max-time 30 -o /tmp/scopenos-index-resp.json -w "%{http_code}" \
    -X POST "${SCOPENOS_URL}/index" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${SCOPENOS_API_KEY}" \
    -d "{\"changed_files\": ${FILES_JSON}, \"project_root\": \"${REPO_ROOT}\", \"project_id\": \"${PROJECT_ID}\"}" \
    2>/dev/null || echo "000")

  FILE_COUNT=$(echo "$CHANGED" | wc -l | tr -d ' ')
  if [ "$INDEX_HTTP" = "200" ]; then
    echo "[scopenos] index_changes: ${FILE_COUNT} files (project: ${PROJECT_ID})"
  else
    echo "[scopenos] ⚠ index_changes failed: HTTP ${INDEX_HTTP} — index may be stale" >&2
    if [ -f /tmp/scopenos-index-resp.json ]; then
      cat /tmp/scopenos-index-resp.json >&2
      echo "" >&2
    fi
  fi
fi

# ── Contract check ──────────────────────────────────────────────────────────────
# Resolve function IDs for changed files then check against active contracts.
# Non-blocking: violations are printed as warnings but do not fail the commit.

CHANGED_SRC=$(echo "$CHANGED" | grep -E '\.(py|ts|tsx)$' || true)

if [ -n "$CHANGED_SRC" ]; then
  ABS_FILES_JSON=$(echo "$CHANGED_SRC" | while IFS= read -r f; do
    [ -n "$f" ] && echo "\"${REPO_ROOT}/${f}\""
  done | paste -sd ',' - | sed 's/^/[/' | sed 's/$/]/')

  # Get function IDs for changed files.
  FN_RESP=$(curl --silent --max-time 5 \
    -X POST "${SCOPENOS_URL}/api/functions" \
    -H "Content-Type: application/json" \
    -d "{\"files\": ${ABS_FILES_JSON}, \"project_id\": \"${PROJECT_ID}\"}" 2>/dev/null || echo '{}')

  FUNCTION_IDS=$(echo "$FN_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = d.get('function_ids', [])
print(json.dumps(ids))
" 2>/dev/null || echo '[]')

  # Check contracts.
  VIOLATIONS=$(curl --silent --max-time 15 \
    -X POST "${SCOPENOS_URL}/api/contracts/check" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\": \"${PROJECT_ID}\", \"function_ids\": ${FUNCTION_IDS}}" 2>/dev/null || echo '{"violations":[]}')

  VIOL_COUNT=$(echo "$VIOLATIONS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
viols = d.get('violations', [])
if viols:
    print(f'[scopenos] ⚠  {len(viols)} contract violation(s) detected:')
    for v in viols:
        pct = f\"{v['score']*100:.0f}%\" if v['violation_type'] == 'semantic' else 'structural'
        print(f'  [{v[\"violation_type\"]}] {v[\"function_id\"]} → {v.get(\"contract_title\",v[\"contract_id\"])} ({pct})')
else:
    print('[scopenos] contracts: ok (no violations)')
" 2>/dev/null || echo '')

  if [ -n "$VIOL_COUNT" ]; then
    echo "$VIOL_COUNT" >&2
  fi
fi

# ── Log decision ────────────────────────────────────────────────────────────────

SCOPENOS_PROJECT_ID="$PROJECT_ID" SCOPENOS_URL="$SCOPENOS_URL" REPO_ROOT="$REPO_ROOT" SCOPENOS_API_KEY="$SCOPENOS_API_KEY" python3 - <<'PYEOF'
import json, os, subprocess, sys
try:
    from urllib.request import urlopen, Request as UReq

    scopenos_url    = os.environ.get("SCOPENOS_URL", "http://100.71.88.106:3004")
    project_id  = os.environ.get("SCOPENOS_PROJECT_ID", "default")
    repo_root   = os.environ.get("REPO_ROOT", "")

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

    parts = [msg]
    if body:
        parts.append(body)
    parts.append(f"Changes:\n{diff_stat}")
    description = " — ".join(parts)

    # Resolve changed files → actual indexed function IDs via the Scopenos API.
    abs_files = [f"{repo_root}/{f}" for f in changed if f.endswith((".py", ".ts", ".tsx"))]
    linked = None
    if abs_files:
        try:
            fn_req = UReq(
                f"{scopenos_url}/api/functions",
                data=json.dumps({"files": abs_files, "project_id": project_id}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(fn_req, timeout=5) as r:
                fn_resp = json.loads(r.read())
            linked = fn_resp.get("function_ids") or None
        except Exception:
            linked = [f.replace("/", ".").removesuffix(".py") for f in changed
                      if f.endswith((".py", ".ts", ".tsx"))] or None

    payload = json.dumps({
        "type": type_,
        "description": description,
        "trigger": f"git:{hash_[:8]}",
        "linked_function_ids": linked,
        "project_id": project_id,
    }).encode()

    api_key = os.environ.get("SCOPENOS_API_KEY", "")
    req = UReq(
        f"{scopenos_url}/api/decisions",
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    from urllib.error import HTTPError
    try:
        with urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        print(f"[scopenos] decision logged ({type_}): {resp.get('decision_id', '')[:8]}")
    except HTTPError as e:
        print(f"[scopenos] ⚠ decision log failed: HTTP {e.code} — check SCOPENOS_API_KEY", file=sys.stderr)
except Exception as e:
    print(f"[scopenos] decision log skipped: {e}", file=sys.stderr)
PYEOF
