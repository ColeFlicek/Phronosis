# Contract Enforcement — Bypass Vectors

Identified 2026-06-16. Fix priority order TBD.

## Structural enforcement gaps

### 1. Depth-1 call graph only
`_check_structural_for_function` fetches direct callees only. One wrapper layer defeats
the check entirely. A function calling `_helper()` which calls `raw_db_query()` is invisible.

**Fix:** Configurable traversal depth on structural checks, or BFS up to depth N.

### 2. `required_callee` is trivially satisfiable
"prohibited: `raw_db`; required: `validate`" is satisfied by calling a no-op `validate()`
alongside the violation. The checker sees both calls and clears it.

**Fix:** Semantic check on the required callee — verify it's doing real work, not a stub.

### 3. Name matching is last-segment only
`find_prohibited_callees` splits on `.` and matches the last name segment, lowercased.
Rename, wrap, or move the prohibited function to a new module — pattern stops matching.

**Fix:** Match against full qualified ID, not just last segment. Support glob patterns.

---

## Semantic enforcement gaps

### 4. Semantic input is signature+docstring, not body
`check_semantic` embeds `signature + docstring + summary` — never the function body.
Write a compliant-looking signature, put the violation in the implementation.

**Fix:** Include function body (truncated) in the semantic check input.

### 5. `check_project` is structural-only
MCP tool `check_contracts(project_id)` only runs `_check_structural`. The semantic path
only fires in `check_functions` (post-commit hook path). Full-project semantic scans
don't exist.

**Fix:** Add semantic sweep to `check_project` / expose a `check_project_full` tool.

---

## Enforcement trigger gaps

### 6. No write-time gate
Contracts are checked on-demand or via post-commit hook. No enforcement at index time.
An agent can commit violating code, skip the hook, and it sits undetected.

**Fix:** `index_changes` should optionally call `check_functions` on newly written nodes
and return violations in the indexing response. Agents see violations inline.

### 7. Agent doesn't see contracts before editing
Contracts live in the DB. Nothing surfaces them to the agent before it writes code.
`get_project_home` shows `active_contract_count` but not the natural language rules.
An agent that doesn't explicitly call `list_contracts` never knows what rules exist.

**Fix:** Surface active contract titles + natural language in `get_project_home` health
section. Agent sees rules at session start, before any edits.

### 8. Hook is optional
Post-commit hook is opt-in per repo. No hook = no enforcement. Agents can't install
or verify the hook themselves.

**Fix:** `index_project` response should warn if no post-commit hook is detected.

---

## Scoping gaps

### 9. `function_ids` pattern contracts have a coverage gap (new, 2026-06-16)
A contract scoped to `[subscribe, notify, registry]` won't catch violations in new
functions added to the pattern — because new function IDs aren't in the scoped list yet.

**Fix:** `function_ids` should support glob/prefix matching, not just exact IDs. Or
contracts can declare a `scope_prefix` (e.g. `myproject.EventBus.*`) that auto-covers
new methods added to the class.

### 10. `scope_exclusions` is broad and prefix-based
Any function in an excluded namespace bypasses all checks. Exclusion lists tend to grow
over time and become a wide-open door.

**Fix:** Require justification comment per exclusion. Flag exclusions that cover >N functions.

---

## Not yet addressed

- Draft contracts never auto-expire or prompt for approval
- Threshold is per-contract in DB; no audit trail if changed
